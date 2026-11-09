# Vendored from arawitch/trading-bot-safe-analysis extracted/dashboard/a1720_proofofuse.py.
# Do not edit here: change it there and copy it again, so the box tool and this page agree.
#!/usr/bin/env python3
"""#A1720-proofofuse -- Spreads Bot "proof of use" for chargeback evidence. READ-ONLY.

What it answers, for one buyer (keyed on email; name as a fallback):
  * did they get a Spreads Bot account, and when was it created
  * when did they last sign in, and from what IP address
  * every IP address the server has tied to them, with the date and what they did there
    (accepted the live-trading authorization, approved a signal, enabled a strategy, ...)
  * how often those IPs used the app (sessions = distinct days seen in the web logs)
  * last activity
  * trades the bot placed or copied for them, with dates and counts (no dollar figures)

It changes NOTHING. The database is opened with SQLite's read-only URI (mode=ro), it never
SELECTs a password, token, or broker secret column, and web logs are only read.

Two halves in one stdlib-only file, so the same file works on the bot box and in Replit:

  1. COLLECT (on the bot box, where the data is):
       python a1720_proofofuse.py --db /opt/optionspreads/data/trading.db \
           --email buyer@example.com [--name "Jane Doe"] [--logs]
     prints a readable summary, then one JSON block between BEGIN/END markers.

  2. USE (in the dispute-evidence app):
       import a1720_proofofuse as pou
       result = pou.from_json(pasted_text)            # or pou.collect(db_path, email=...)
       pou.ip_matches(result, ["203.0.113.7"])        # GHL opt-in IPs -> matches
       for block in pou.pdf_blocks(result, ghl_ips=[...]):
           heading, rows, widths, note = block["heading"], block["rows"], block["widths"], block["note"]
           # render with dispute.py's own table() helper

What the server does NOT keep (said plainly in every result, under "limits"):
  * There is no login history table. users.last_login holds only the most recent sign-in time
    and is overwritten each time. Earlier sign-in IPs exist only in the web logs, which rotate
    (nginx ~14 days, gunicorn ~5 weeks). Older ones are gone.
  * There is no phone number on a Spreads Bot account, so a phone cannot be matched.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

VERSION = "a1720-4"
JSON_BEGIN = "----- BEGIN A1720 PROOF OF USE JSON -----"
JSON_END = "----- END A1720 PROOF OF USE JSON -----"

DEFAULT_LOG_GLOBS = (
    "/var/log/nginx/access.log*",
    "/opt/optionspreads/logs/gunicorn-access.log*",
)

# Only these users columns are ever read. Anything with token/secret/password is never touched.
USER_COLS = ("id", "email", "name", "created_at", "last_login", "phase", "paper_start",
             "live_approved_at", "broker", "snaptrade_broker", "snaptrade_connected_at",
             "bot_enabled", "is_active_sub", "disclosure_accepted_at", "disclosure_version",
             "risk_ack_at", "risk_ack_ip", "tp_consent_at", "tp_consent_ip",
             "household_disclosure_ip", "hotpicks_enabled")

# Every users column ending in _at is a dated record on the member's settings. These are the
# ones with plain-English labels; any other *_at column the live table carries is shown too,
# labelled from its name. Columns already reported elsewhere, or written by our own background
# checks rather than by the member, are skipped. A column whose name suggests a secret is never
# read, whatever its suffix.
SETTINGS_TS_LABELS = {
    "disclosure_accepted_at": "Accepted the Live Trading Authorization & Risk Disclosure (settings record)",
    "snaptrade_connected_at": "Linked a brokerage account",
    "paper_start": "Started paper trading",
    "live_approved_at": "Approved for live trading",
    "condor_consent_at": "Iron condor consent (settings record)",
    "hotpicks_consent_at": "Hot Picks consent (settings record)",
    "signals_consent_at": "Signal Pilot consent (settings record)",
    "household_disclosure_at": "Accepted the household account disclosure",
    "must_change_password_at": "Was asked to set a new password",
}
SETTINGS_TS_SKIP = {"created_at", "last_login", "risk_ack_at", "tp_consent_at", "broker_checked_at",
                    "broker_last_ok_at", "trial_ends", "schwab_token_expires", "disabled_at"}
SECRETISH = re.compile(r"token|secret|password_hash|passw|hash|key", re.I)

# (table, time column, ip column, user-agent column, label, extra columns to describe it)
IP_EVENT_TABLES = (
    ("disclosure_acceptances", "accepted_at", "ip_address", "user_agent",
     "Accepted the Live Trading Authorization & Risk Disclosure", ("version",)),
    ("signal_acceptances", "accepted_at", "ip", "user_agent",
     "Signal Pilot: agreed / approved a trade signal", ("action", "signal_id", "version")),
    ("condor_acceptances", "accepted_at", "ip", "user_agent",
     "Iron condor strategy consent", ("action", "version")),
    ("hotpicks_acceptances", "accepted_at", "ip_address", "user_agent",
     "Hot Picks strategy consent", ("action", "version")),
)

# Anything that could identify a different person sharing the IP is kept out of the output.
LOG_LINE = re.compile(
    r'^(?P<ip>[0-9a-fA-F:.]+) \S+ \S+ \[(?P<ts>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" '
    r'(?P<status>\d{3}) ')


# ----------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------
def _connect_ro(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)
    con = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(db_path), uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con


def _cols_ordered(con, table: str) -> list:
    return [r[1] for r in con.execute("PRAGMA table_info(%s)" % table)]


def _tables(con) -> set:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _cols(con, table: str) -> set:
    return {r[1] for r in con.execute("PRAGMA table_info(%s)" % table)}


def _parse_dt(value):
    """Best-effort parse of what SQLite holds (naive UTC strings, ISO with offset, dates)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip().replace("T", " ")
    s = re.sub(r"Z$", "+00:00", s)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _fmt(d) -> str:
    if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.strip()):
        return d.strip()                              # a date (e.g. a trade day) has no time
    d = _parse_dt(d)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if d else ""


def _iso(d) -> str:
    d = _parse_dt(d)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds") if d else ""


def _norm_name(s) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


# ----------------------------------------------------------------------------------------------
# finding the account
# ----------------------------------------------------------------------------------------------
def find_user(con, email: str = "", name: str = ""):
    """Return (status, user_row_or_None, candidates, matched_on).
    status: 'found' | 'not_found' | 'ambiguous'. Email wins; name is only a fallback, and a
    name that matches more than one account is reported as ambiguous rather than guessed."""
    ucols = _cols(con, "users")
    sel = ", ".join(c for c in USER_COLS if c in ucols)
    email = (email or "").strip().lower()
    if email:
        rows = con.execute("SELECT %s FROM users WHERE lower(trim(email)) = ?" % sel,
                           (email,)).fetchall()
        if len(rows) == 1:
            return "found", rows[0], [], "email"
    nm = _norm_name(name)
    if nm:
        rows = [r for r in con.execute("SELECT %s FROM users" % sel).fetchall()
                if _norm_name(r["name"]) == nm]
        if len(rows) == 1:
            return "found", rows[0], [], "name (exact)"
        if len(rows) > 1:
            return "ambiguous", None, rows, "name (exact)"
        parts = nm.split(" ")
        if len(parts) >= 2:
            rows = [r for r in con.execute("SELECT %s FROM users" % sel).fetchall()
                    if all(p in _norm_name(r["name"]) for p in (parts[0], parts[-1]))]
            if rows:
                # A partial name match is never treated as the buyer on its own.
                return "ambiguous", None, rows, "name (first + last appear)"
    return "not_found", None, [], ""


# ----------------------------------------------------------------------------------------------
# web logs
# ----------------------------------------------------------------------------------------------
def _open_log(path):
    return gzip.open(path, "rt", errors="replace") if path.endswith(".gz") else \
        open(path, "r", errors="replace")


def _log_ts(raw: str):
    try:
        return datetime.strptime(raw, "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        return None


_MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
                                        "Sep", "Oct", "Nov", "Dec"), 1)}


def _fast_ts(raw: str, cache: dict):
    """'09/Nov/2026:20:49:41 +0000' -> 'YYYY-MM-DD HH:MM:SS' in UTC, cheaply (the date part is
    cached; an offset other than +0000 falls back to a full parse)."""
    if raw.endswith(" +0000") and len(raw) == 26:
        d = cache.get(raw[:11])
        if d is None:
            try:
                d = "%s-%02d-%s" % (raw[7:11], _MONTHS[raw[3:6]], raw[0:2])
            except KeyError:
                return None
            cache[raw[:11]] = d
        return d + " " + raw[12:20]
    t = _log_ts(raw)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if t else None


def scan_logs(paths, ips: set, last_login=None, window_s: int = 5, progress=None):
    """One pass over the web access logs.
    Returns (per_ip, last_login_ip, logs_read). per_ip only covers IPs already tied to this
    member by the database (we never attribute a stranger's IP from logs alone). The last
    sign-in IP is found by matching users.last_login to a successful POST /login (302) within
    `window_s` seconds; if two different IPs signed in inside that window it is left blank.
    Fast path: a line is only fully parsed when its IP is wanted or it is a POST /login."""
    per_ip = {ip: {"requests": 0, "days": set(), "first": None, "last": None, "logins": 0}
              for ip in ips}
    ll = _parse_dt(last_login)
    login_hits = []
    logs_read = []
    cache = {}
    for i, path in enumerate(paths, 1):
        if progress:
            progress("  reading log %d/%d %s ..." % (i, len(paths), path))
        try:
            fh = _open_log(path)
        except OSError as e:
            logs_read.append({"path": path, "lines": 0, "error": str(e)[:120]})
            continue
        n = 0
        first_raw = last_raw = None
        try:
            with fh:
                for line in fh:
                    sp = line.find(" ")
                    if sp <= 0:
                        continue
                    lb = line.find("[", sp)
                    rb = line.find("]", lb)
                    if lb < 0 or rb < 0:
                        continue
                    n += 1
                    raw = line[lb + 1:rb]
                    if first_raw is None:
                        first_raw = raw
                    last_raw = raw
                    ip = line[:sp]
                    s = per_ip.get(ip)
                    maybe_login = '"POST /login' in line
                    if s is None and not (maybe_login and ll is not None):
                        continue
                    m = LOG_LINE.match(line)
                    if not m:
                        continue
                    ts = _fast_ts(raw, cache)
                    if ts is None:
                        continue
                    is_login = (m.group("method") == "POST" and m.group("path").split("?")[0] == "/login"
                                and m.group("status") == "302")
                    if ll is not None and is_login:
                        t = _parse_dt(ts)
                        if t is not None and abs((t - ll).total_seconds()) <= window_s:
                            login_hits.append(ip)
                    if s is None:
                        continue
                    s["requests"] += 1
                    s["days"].add(ts[:10])
                    s["first"] = ts if s["first"] is None or ts < s["first"] else s["first"]
                    s["last"] = ts if s["last"] is None or ts > s["last"] else s["last"]
                    if is_login:
                        s["logins"] += 1
        except (OSError, EOFError) as e:
            logs_read.append({"path": path, "lines": n, "error": str(e)[:120]})
            continue
        logs_read.append({"path": path, "lines": n,
                          "from": _iso(_fast_ts(first_raw, cache)) if first_raw else "",
                          "to": _iso(_fast_ts(last_raw, cache)) if last_raw else ""})
    last_ip = login_hits[0] if login_hits and len(set(login_hits)) == 1 else ""
    return per_ip, last_ip, logs_read


# ----------------------------------------------------------------------------------------------
# collect (runs where the database is)
# ----------------------------------------------------------------------------------------------
def collect(db_path: str, email: str = "", name: str = "", phone: str = "",
            log_paths=None, progress=None) -> dict:
    """Gather the proof-of-use facts for one buyer. Read-only. log_paths=None skips web logs."""
    now = datetime.now(timezone.utc)
    out = {"version": VERSION, "source": "Spreads Bot server (TripleTrader)",
           "compiled_at": _iso(now), "query": {"email": email, "name": name, "phone": phone},
           "status": "not_found", "matched_on": "", "candidates": [], "account": {},
           "ip_events": [], "ip_usage": [], "sessions": {}, "visits": [], "history_since": "",
           "settings_dates": [], "settings_changes": [],
           "trades": {}, "activity": {},
           "limits": []}
    if phone:
        out["limits"].append("Spreads Bot accounts do not store a phone number, so the phone "
                             "was not used to match.")
    con = _connect_ro(db_path)
    try:
        tabs = _tables(con)
        status, u, cands, how = find_user(con, email, name)
        out["status"], out["matched_on"] = status, how
        if status == "ambiguous":
            out["candidates"] = [{"user_id": c["id"], "name": c["name"] or "",
                                  "email": c["email"], "created": _iso(c["created_at"])}
                                 for c in cands[:10]]
        if status != "found":
            return out
        uid = u["id"]
        keys = u.keys()
        g = lambda k: u[k] if k in keys else None
        out["account"] = {
            "user_id": uid, "email": g("email"), "name": g("name") or "",
            "created_at": _iso(g("created_at")), "last_login": _iso(g("last_login")),
            "phase": g("phase") or "", "paper_start": _iso(g("paper_start")),
            "live_approved_at": _iso(g("live_approved_at")),
            "broker": g("snaptrade_broker") or g("broker") or "",
            "broker_connected_at": _iso(g("snaptrade_connected_at")),
            "bot_enabled": bool(g("bot_enabled")) if g("bot_enabled") is not None else None,
            "subscription_active": bool(g("is_active_sub")) if g("is_active_sub") is not None else None,
        }

        # --- every IP the database ties to this member ---------------------------------------
        ev = []
        for tbl, tcol, ipcol, uacol, label, extra in IP_EVENT_TABLES:
            if tbl not in tabs:
                continue
            tc = _cols(con, tbl)
            if not {"user_id", tcol}.issubset(tc):
                continue
            want = [c for c in (tcol, ipcol, uacol) + tuple(extra) if c in tc]
            for r in con.execute("SELECT %s FROM %s WHERE user_id = ? ORDER BY %s"
                                 % (", ".join(want), tbl, tcol), (uid,)):
                d = dict(zip(want, r))
                detail = ", ".join("%s %s" % (k, d[k]) for k in extra if d.get(k) not in (None, ""))
                ev.append({"at": _iso(d.get(tcol)), "ip": (d.get(ipcol) or "").strip(),
                           "user_agent": (d.get(uacol) or "")[:200], "event": label,
                           "detail": detail, "source": tbl})
        for col_at, col_ip, label in (("risk_ack_at", "risk_ack_ip", "Acknowledged a custom stop-loss risk"),
                                      ("tp_consent_at", "tp_consent_ip", "Accepted a non-default take-profit mode")):
            if g(col_at) or g(col_ip):
                ev.append({"at": _iso(g(col_at)), "ip": (g(col_ip) or "").strip(), "user_agent": "",
                           "event": label, "detail": "", "source": "users"})
        if g("household_disclosure_ip"):
            ev.append({"at": "", "ip": g("household_disclosure_ip").strip(), "user_agent": "",
                       "event": "Accepted the household account disclosure", "detail": "",
                       "source": "users"})
        ev.sort(key=lambda e: e["at"] or "9999")
        out["ip_events"] = ev

        # --- dated records on the member's settings (users.*_at), with their IP if one exists --
        ucols = [c for c in _cols_ordered(con, "users") if not SECRETISH.search(c)]
        ts_cols = [c for c in ucols if (c.endswith("_at") or c in SETTINGS_TS_LABELS)
                   and c not in SETTINGS_TS_SKIP]
        sd = []
        if ts_cols:
            ip_for = {c: c[:-3] + "_ip" for c in ts_cols if c.endswith("_at") and c[:-3] + "_ip" in ucols}
            want = ts_cols + sorted(set(ip_for.values()))
            row = con.execute("SELECT %s FROM users WHERE id = ?" % ", ".join('"%s"' % c for c in want),
                              (uid,)).fetchone()
            vals = dict(zip(want, row))
            for c in ts_cols:
                if not vals.get(c):
                    continue
                label = SETTINGS_TS_LABELS.get(c) or (c[:-3] if c.endswith("_at") else c).replace("_", " ").capitalize()
                sd.append({"field": c, "label": label, "at": _iso(vals[c]),
                           "ip": (vals.get(ip_for.get(c, "")) or "").strip() if c in ip_for else ""})
            sd.sort(key=lambda x: x["at"] or "9999")
        out["settings_dates"] = sd
        for x in sd:
            if x["ip"] and not any(e["ip"] == x["ip"] and e["at"][:16] == x["at"][:16] for e in ev):
                ev.append({"at": x["at"], "ip": x["ip"], "user_agent": "", "event": x["label"],
                           "detail": "", "source": "users"})
        ev.sort(key=lambda e: e["at"] or "9999")

        # --- trades (counts and dates only, never dollars) -----------------------------------
        if "trades" in tabs:
            tc = _cols(con, "trades")
            sel = ["date", "time", "contracts", "status"] + [c for c in ("source", "is_paper", "is_preflight")
                                                            if c in tc]
            rows = [dict(zip(sel, r)) for r in con.execute(
                "SELECT %s FROM trades WHERE user_id = ? ORDER BY date, time" % ", ".join(sel), (uid,))]
            rows = [r for r in rows if not r.get("is_preflight")]
            by_kind = Counter()
            by_month = defaultdict(lambda: Counter())
            days = set()
            contracts = 0
            for r in rows:
                src = (r.get("source") or "").lower()
                kind = "Signal Pilot (member-approved)" if src == "signalpilot" else \
                    ("Paper (simulated)" if r.get("is_paper") else "Spreads Bot (placed at broker)")
                by_kind[kind] += 1
                mon = str(r["date"])[:7]
                by_month[mon][kind] += 1
                days.add(str(r["date"]))
                contracts += int(r.get("contracts") or 0)
            out["trades"] = {
                "count": len(rows), "contracts": contracts, "trading_days": len(days),
                "first": str(rows[0]["date"]) if rows else "", "last": str(rows[-1]["date"]) if rows else "",
                "by_kind": dict(by_kind),
                "by_month": [{"month": m, **dict(c)} for m, c in sorted(by_month.items())],
                "dates": sorted(days),
            }

        # --- other activity ------------------------------------------------------------------
        act = {}
        if "member_audit" in tabs:
            r = con.execute("SELECT COUNT(*), MIN(changed_at), MAX(changed_at) FROM member_audit "
                            "WHERE user_id = ?", (uid,)).fetchone()
            act["settings_changes"] = {"count": r[0], "first": _iso(r[1]), "last": _iso(r[2])}
            out["settings_changes"] = [
                {"at": _iso(x[0]), "field": x[1], "old": "" if x[2] is None else str(x[2])[:60],
                 "new": "" if x[3] is None else str(x[3])[:60]}
                for x in con.execute("SELECT changed_at, field, old_value, new_value FROM member_audit "
                                     "WHERE user_id = ? ORDER BY changed_at", (uid,))
                if not SECRETISH.search(x[1] or "")][:500]
        if "member_survey_submissions" in tabs:
            r = con.execute("SELECT COUNT(*), MAX(submitted_at) FROM member_survey_submissions "
                            "WHERE user_id = ?", (uid,)).fetchone()
            act["daily_check_ins"] = {"count": r[0], "last": _iso(r[1])}
        if "member_notices" in tabs and "seen_at" in _cols(con, "member_notices"):
            r = con.execute("SELECT COUNT(*), MAX(seen_at) FROM member_notices WHERE user_id = ? "
                            "AND seen_at IS NOT NULL", (uid,)).fetchone()
            act["notices_read"] = {"count": r[0], "last": _iso(r[1])}
        out["activity"] = act

        # --- #A1721-loginlog history, when the box carries it ---------------------------------
        if "login_events" in tabs:
            first = con.execute("SELECT MIN(at) FROM login_events").fetchone()[0]
            if "member_visits" in tabs:
                fv = con.execute("SELECT MIN(first_seen) FROM member_visits").fetchone()[0]
                first = min(x for x in (first, fv) if x) if (first or fv) else None
            out["history_since"] = _iso(first)
            for r in con.execute("SELECT at, ip, user_agent, via FROM login_events WHERE user_id = ? "
                                 "ORDER BY at", (uid,)):
                ev.append({"at": _iso(r[0]), "ip": (r[1] or "").strip(), "user_agent": (r[2] or "")[:200],
                           "event": "Signed in to the Spreads Bot" if (r[3] or "login") == "login"
                           else "Signed in to the Spreads Bot (%s)" % r[3],
                           "detail": "", "source": "login_events"})
            ev.sort(key=lambda e: e["at"] or "9999")
        if "member_visits" in tabs:
            out["visits"] = [{"day": r[0], "ip": r[1], "first_seen": _iso(r[2]), "last_seen": _iso(r[3]),
                              "hits": r[4]} for r in con.execute(
                "SELECT day, ip, first_seen, last_seen, hits FROM member_visits WHERE user_id = ? "
                "ORDER BY day, ip", (uid,))]
    finally:
        con.close()

    # --- web logs: last sign-in IP and how often the member's IPs used the app ---------------
    ips = {e["ip"] for e in out["ip_events"] if e["ip"]}
    if log_paths:
        per_ip, last_ip, logs_read = scan_logs(log_paths, set(ips), out["account"]["last_login"],
                                               progress=progress)
        if last_ip and last_ip not in ips:
            # Re-scan only to count usage for the newly learned sign-in IP.
            if progress:
                progress("  last sign-in came from a new IP; counting its visits ...")
            extra, _, _ = scan_logs(log_paths, {last_ip}, progress=progress)
            per_ip.update(extra)
        out["account"]["last_login_ip"] = last_ip
        usage = []
        all_days = set()
        for ip, s in per_ip.items():
            if not s["requests"]:
                continue
            all_days |= s["days"]
            usage.append({"ip": ip, "requests": s["requests"], "days_seen": len(s["days"]),
                          "first_seen": _iso(s["first"]), "last_seen": _iso(s["last"]),
                          "sign_ins": s["logins"]})
        usage.sort(key=lambda x: x["first_seen"])
        out["ip_usage"] = usage
        out["sessions"] = {"distinct_days_seen": len(all_days),
                           "days": sorted(all_days),
                           "log_window": _log_window(logs_read),
                           "logs_read": logs_read}
        if not last_ip and out["account"]["last_login"]:
            out["limits"].append("The last sign-in was not found in the web logs (it may be older "
                                 "than the logs reach), so its IP is unknown.")
    else:
        out["account"]["last_login_ip"] = ""
        out["limits"].append("Web logs were not read, so per-visit IPs and session counts are "
                             "not included.")

    # --- last activity across everything we have ---------------------------------------------
    stamps = [out["account"]["last_login"]] + [e["at"] for e in out["ip_events"]] + \
             [u["last_seen"] for u in out["ip_usage"]] + [v["last_seen"] for v in out["visits"]]
    a = out["activity"]
    for k in ("settings_changes", "daily_check_ins", "notices_read"):
        if a.get(k):
            stamps.append(a[k].get("last", ""))
    if out["trades"].get("last"):
        stamps.append(out["trades"]["last"])
    stamps = [s for s in stamps if s]
    out["activity"]["last_activity"] = max(stamps, key=lambda s: _parse_dt(s) or now) if stamps else ""

    if out["history_since"]:
        out["limits"].append("Every sign-in and every day of use, with its IP, has been recorded since "
                             "%s. Before that the server kept only the most recent sign-in time, and "
                             "earlier IPs exist only in the web logs, which roll over after a few weeks."
                             % _fmt(out["history_since"]))
    else:
        out["limits"].append("The server keeps only the most recent sign-in time per account, not a "
                             "history of every sign-in. Earlier sign-ins and their IPs exist only in "
                             "the web logs, which roll over after a few weeks.")
    return out


def _log_window(logs_read):
    fr = [l["from"] for l in logs_read if l.get("from")]
    to = [l["to"] for l in logs_read if l.get("to")]
    return {"from": min(fr) if fr else "", "to": max(to) if to else ""}


# ----------------------------------------------------------------------------------------------
# use (in the dispute-evidence app)
# ----------------------------------------------------------------------------------------------
def from_json(text: str) -> dict:
    """Parse the JSON the box command printed. Accepts the whole pasted terminal output."""
    if JSON_BEGIN in text:
        text = text.split(JSON_BEGIN, 1)[1].split(JSON_END, 1)[0]
    data = json.loads(text.strip())
    if not str(data.get("version", "")).startswith("a1720"):
        raise ValueError("not an #A1720 proof-of-use result")
    return data


def visits_by_ip(result: dict) -> list:
    """member_visits rows folded per IP: days used, first and last seen."""
    agg = {}
    for v in result.get("visits", []) or []:
        a = agg.setdefault(v["ip"], {"ip": v["ip"], "days": set(), "first_seen": v["first_seen"],
                                     "last_seen": v["last_seen"]})
        a["days"].add(v["day"])
        a["first_seen"] = min(a["first_seen"], v["first_seen"])
        a["last_seen"] = max(a["last_seen"], v["last_seen"])
    out = [{**a, "days": len(a["days"])} for a in agg.values()]
    return sorted(out, key=lambda a: a["first_seen"])


def ip_matches(result: dict, ghl_ips) -> list:
    """IPs that appear in BOTH the CRM opt-in/form records and the Spreads Bot records."""
    want = {(ip or "").strip() for ip in (ghl_ips or []) if (ip or "").strip()}
    hits = []
    seen = set()
    for e in result.get("ip_events", []):
        if e["ip"] in want:
            hits.append({"ip": e["ip"], "where": e["event"], "at": e["at"]})
            seen.add(e["ip"])
    ll = result.get("account", {}).get("last_login_ip", "")
    if ll in want:
        hits.append({"ip": ll, "where": "Signed in to the Spreads Bot",
                     "at": result["account"].get("last_login", "")})
    for v in visits_by_ip(result):
        if v["ip"] in want and v["ip"] not in seen and v["ip"] != ll:
            hits.append({"ip": v["ip"], "where": "Used the Spreads Bot site (%d days)" % v["days"],
                         "at": v["last_seen"]})
            seen.add(v["ip"])
    for u in result.get("ip_usage", []):
        if u["ip"] in want and u["ip"] not in seen and u["ip"] != ll:
            hits.append({"ip": u["ip"], "where": "Used the Spreads Bot app (%d days)" % u["days_seen"],
                         "at": u["last_seen"]})
    return hits


def summary_text(result: dict) -> str:
    """Plain-English summary, for the terminal or a PDF paragraph."""
    s = result.get("status")
    q = result.get("query", {})
    if s == "not_found":
        return ("No Spreads Bot account was found for %s." %
                (" / ".join(x for x in (q.get("email"), q.get("name")) if x) or "this buyer"))
    if s == "ambiguous":
        return ("No account matches that email. The name matches %d accounts, so none was "
                "chosen: %s" % (len(result["candidates"]), "; ".join(
                    "%s <%s>" % (c["name"], c["email"]) for c in result["candidates"])))
    a, t = result["account"], result.get("trades", {})
    lines = ["Spreads Bot account found (matched on %s): %s <%s>."
             % (result["matched_on"], a["name"] or "(no name)", a["email"]),
             "Account created %s; last sign-in %s%s." % (
                 _fmt(a["created_at"]) or "unknown", _fmt(a["last_login"]) or "never recorded",
                 (" from IP " + a["last_login_ip"]) if a.get("last_login_ip") else "")]
    if a.get("broker_connected_at") or a.get("broker"):
        when = _fmt(a["broker_connected_at"])
        lines.append("Connected a %s brokerage account%s." % (a.get("broker") or "brokerage",
                                                              (" on " + when) if when else ""))
    lines.append("%d dated actions tied to %d distinct IP address(es)." % (
        len(result["ip_events"]), len({e["ip"] for e in result["ip_events"] if e["ip"]})))
    if result.get("visits"):
        days = {v["day"] for v in result["visits"]}
        lines.append("Used the site on %d distinct days (%s to %s)." % (len(days), min(days), max(days)))
    if result.get("sessions"):
        w = result["sessions"]["log_window"]
        lines.append("Seen using the app on %d distinct days in the web logs (%s to %s)." % (
            result["sessions"]["distinct_days_seen"], w["from"][:10], w["to"][:10]))
    if t.get("count"):
        lines.append("%d trades (%d contracts) on %d trading days, %s to %s." % (
            t["count"], t["contracts"], t["trading_days"], t["first"], t["last"]))
    else:
        lines.append("No trades recorded for this account.")
    if result["activity"].get("last_activity"):
        lines.append("Last activity: %s." % _fmt(result["activity"]["last_activity"]))
    return " ".join(lines)


def pdf_blocks(result: dict, ghl_ips=None) -> list:
    """Section blocks for dispute.py's render_pdf. Each block:
    {"heading": str, "note": str, "rows": [[header...], [cells...]...] or [], "widths": [inches]}"""
    blocks = [{"heading": "Proof of use: Spreads Bot (TripleTrader)", "note": summary_text(result),
               "rows": [], "widths": []}]
    if result.get("status") != "found":
        return blocks
    a = result["account"]
    blocks.append({"heading": "Spreads Bot account", "note": "", "widths": [2.2, 4.3], "rows": [
        ["Field", "Value"],
        ["Account email", a["email"]], ["Name on account", a["name"]],
        ["Account created", _fmt(a["created_at"])],
        ["Most recent sign-in", _fmt(a["last_login"])],
        ["Most recent sign-in IP", a.get("last_login_ip") or "not in the web logs"],
        ["Brokerage connected", ("%s, %s" % (a.get("broker") or "yes", _fmt(a["broker_connected_at"])))
         if a.get("broker_connected_at") else (a.get("broker") or "no")],
        ["Approved for live trading", _fmt(a["live_approved_at"]) or "no"],
        ["Last activity", _fmt(result["activity"].get("last_activity"))],
    ]})
    hits = ip_matches(result, ghl_ips) if ghl_ips else []
    if hits:
        # Only a MATCH goes in. "No match" is not evidence of anything (IPs change) and does
        # not belong in a pack handed to a card processor; the closer sees it via ip_matches().
        blocks.append({
            "heading": "IP address match: CRM opt-in vs Spreads Bot",
            "note": "The IP address the cardholder opted in from also used the Spreads Bot account.",
            "widths": [1.6, 3.2, 1.7],
            "rows": [["IP address", "Seen on the Spreads Bot", "When"]] +
                    [[h["ip"], h["where"], _fmt(h["at"])] for h in hits]})
    if result["ip_events"]:
        blocks.append({"heading": "Dated actions and the IP they came from", "note": "",
                       "widths": [1.3, 1.1, 2.4, 1.7],
                       "rows": [["When", "IP address", "What the account holder did", "Browser"]] +
                       [[_fmt(e["at"]), e["ip"] or "not captured",
                         e["event"] + ((" (" + e["detail"] + ")") if e["detail"] else ""),
                         e["user_agent"][:90]] for e in result["ip_events"]]})
    vb = visits_by_ip(result)
    if vb:
        blocks.append({"heading": "Days the account used the site, by IP address",
                       "note": "Recorded by the site each day a signed-in session was active.",
                       "widths": [1.9, 1.0, 1.8, 1.8],
                       "rows": [["IP address", "Days used", "First seen", "Last seen"]] +
                       [[v["ip"], str(v["days"]), _fmt(v["first_seen"]), _fmt(v["last_seen"])] for v in vb]})
    if result.get("ip_usage"):
        w = result["sessions"]["log_window"]
        blocks.append({"heading": "App usage from those IP addresses (web server logs)",
                       "note": "Web logs on hand cover %s to %s. A session here is a distinct day "
                               "the IP used the app." % (w["from"][:10], w["to"][:10]),
                       "widths": [1.5, 0.9, 0.9, 0.8, 1.2, 1.2],
                       "rows": [["IP address", "Requests", "Days seen", "Sign-ins", "First seen", "Last seen"]] +
                       [[u["ip"], str(u["requests"]), str(u["days_seen"]), str(u["sign_ins"]),
                         _fmt(u["first_seen"]), _fmt(u["last_seen"])] for u in result["ip_usage"]]})
    t = result.get("trades") or {}
    if t.get("count"):
        kinds = sorted(t["by_kind"])
        blocks.append({"heading": "Trades placed or copied by the bot for this account",
                       "note": "%d trades, %d contracts, on %d trading days from %s to %s." % (
                           t["count"], t["contracts"], t["trading_days"], t["first"], t["last"]),
                       "widths": [1.2] + [5.3 / max(1, len(kinds))] * len(kinds),
                       "rows": [["Month"] + kinds] +
                       [[m["month"]] + [str(m.get(k, 0)) for k in kinds] for m in t["by_month"]]})
    if result.get("settings_dates"):
        blocks.append({"heading": "Timestamped records on the account's settings", "note": "",
                       "widths": [3.4, 1.6, 1.5],
                       "rows": [["Record", "When", "IP address"]] +
                       [[x["label"], _fmt(x["at"]), x["ip"] or ""] for x in result["settings_dates"]]})
    if result.get("settings_changes"):
        blocks.append({"heading": "Bot settings the account holder changed",
                       "note": "Each change to the account's bot settings, as recorded by the server.",
                       "widths": [1.5, 2.0, 1.5, 1.5],
                       "rows": [["When", "Setting", "From", "To"]] +
                       [[_fmt(x["at"]), x["field"].replace("_", " "), x["old"], x["new"]]
                        for x in result["settings_changes"]]})
    act = result.get("activity", {})
    rows = [["Activity", "Count", "Most recent"]]
    for k, label in (("settings_changes", "Bot settings changed"),
                     ("daily_check_ins", "Daily check-ins submitted"),
                     ("notices_read", "Account notices read")):
        if act.get(k) and act[k].get("count"):
            rows.append([label, str(act[k]["count"]), _fmt(act[k].get("last"))])
    if len(rows) > 1:
        blocks.append({"heading": "Other account activity", "note": "", "widths": [2.6, 1.0, 2.9],
                       "rows": rows})
    if result.get("limits"):
        blocks.append({"heading": "What these records cover", "note": " ".join(result["limits"]),
                       "rows": [], "widths": []})
    return blocks


# ----------------------------------------------------------------------------------------------
# command line
# ----------------------------------------------------------------------------------------------
def _expand_logs(globs_):
    paths = []
    for g in globs_:
        paths.extend(sorted(glob.glob(g)))
    return paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="#A1720 Spreads Bot proof of use (read-only)")
    ap.add_argument("--db", default="/opt/optionspreads/data/trading.db")
    ap.add_argument("--email", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--phone", default="")
    ap.add_argument("--logs", action="store_true",
                    help="also read the nginx and gunicorn access logs (needs sudo)")
    ap.add_argument("--log-glob", action="append", default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if not (a.email or a.name):
        ap.error("give --email (and optionally --name)")
    paths = _expand_logs(a.log_glob or DEFAULT_LOG_GLOBS) if (a.logs or a.log_glob) else None
    res = collect(a.db, email=a.email, name=a.name, phone=a.phone, log_paths=paths,
                  progress=lambda m: print(m, file=sys.stderr, flush=True))
    print("#A1720 proof of use  db=%s  status=%s" % (a.db, res["status"]))
    print(summary_text(res))
    for e in res["ip_events"]:
        print("  %-20s %-40s %s" % (_fmt(e["at"]), e["ip"] or "-", e["event"]))
    for u in res["ip_usage"]:
        print("  ip %-40s %5d req %3d days %2d sign-ins  %s .. %s" % (
            u["ip"], u["requests"], u["days_seen"], u["sign_ins"], u["first_seen"][:10], u["last_seen"][:10]))
    if res.get("sessions"):
        for l in res["sessions"]["logs_read"]:
            print("  log %s lines=%s %s" % (l["path"], l["lines"], l.get("error", "")))
    print(JSON_BEGIN)
    print(json.dumps(res, separators=(",", ":")))
    print(JSON_END)
    return 0


def _selftest() -> int:
    import tempfile
    d = tempfile.mkdtemp(prefix="a1720_")
    db = os.path.join(d, "t.db")
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, password_hash TEXT, name TEXT,
      created_at DATETIME, last_login DATETIME, phase TEXT, paper_start DATETIME,
      live_approved_at DATETIME, broker TEXT, broker_token TEXT, bot_enabled BOOLEAN,
      is_active_sub BOOLEAN, snaptrade_broker TEXT, snaptrade_connected_at DATETIME,
      snaptrade_user_secret TEXT, risk_ack_at DATETIME, risk_ack_ip TEXT, tp_consent_at TEXT,
      tp_consent_ip TEXT, household_disclosure_ip TEXT, condor_consent_at TEXT, condor_consent_ip TEXT,
      broker_checked_at TEXT, token_refreshed_at TEXT, futures_beta_at TEXT);
    CREATE TABLE disclosure_acceptances (id INTEGER PRIMARY KEY, user_id INTEGER, accepted_at DATETIME,
      version TEXT, ip_address TEXT, user_agent TEXT);
    CREATE TABLE signal_acceptances (id INTEGER PRIMARY KEY, user_id INTEGER, signal_id INTEGER,
      action TEXT, accepted_at TEXT, ip TEXT, user_agent TEXT, version TEXT, detail TEXT);
    CREATE TABLE trades (id INTEGER PRIMARY KEY, user_id INTEGER, date DATE, time DATETIME,
      contracts INTEGER, status TEXT, pnl FLOAT, is_paper BOOLEAN, is_preflight INTEGER, source TEXT);
    CREATE TABLE member_audit (id INTEGER PRIMARY KEY, user_id INTEGER, field TEXT, old_value TEXT,
      new_value TEXT, changed_at TEXT);
    CREATE TABLE login_events (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      at TEXT NOT NULL, ip TEXT, user_agent TEXT, via TEXT);
    CREATE TABLE member_visits (user_id INTEGER NOT NULL, day TEXT NOT NULL, ip TEXT NOT NULL,
      first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, hits INTEGER NOT NULL DEFAULT 1,
      user_agent TEXT, PRIMARY KEY (user_id, day, ip));
    """)
    c.executemany("INSERT INTO login_events (user_id, at, ip, user_agent, via) VALUES (?,?,?,?,?)", [
        (7, "2026-11-01 13:00:00", "203.0.113.7", "Mozilla/5.0 (Macintosh)", "login"),
        (8, "2026-10-30 13:00:00", "192.0.2.77", "x", "login")])
    c.executemany("INSERT INTO member_visits VALUES (?,?,?,?,?,?,?)", [
        (7, "2026-11-01", "203.0.113.7", "2026-11-01 13:00:00", "2026-11-01 15:00:00", 4, "M"),
        (7, "2026-11-02", "192.0.2.50", "2026-11-02 09:00:00", "2026-11-02 09:30:00", 2, "M"),
        (7, "2026-11-03", "192.0.2.50", "2026-11-03 09:00:00", "2026-11-03 09:10:00", 1, "M"),
        (8, "2026-11-03", "192.0.2.77", "2026-11-03 09:00:00", "2026-11-03 09:10:00", 1, "M")])
    c.execute("INSERT INTO users VALUES (7,'Jane@Example.com','HASH','Jane Doe','2026-09-01 14:00:00',"
              "'2026-11-05 13:30:02.123456','live','2026-09-01 14:05:00','2026-09-10 15:00:00','snaptrade',"
              "'TOKEN',1,1,'SCHWAB','2026-09-02 16:00:00','SECRET','2026-09-12 12:00:00','198.51.100.4',"
              "NULL,NULL,NULL,'2026-09-08 21:01:24','97.136.49.197','2026-11-09 01:00:00',"
              "'2026-11-01 00:00:00','2026-10-20 12:00:00')")
    c.execute("INSERT INTO users (id,email,name) VALUES (8,'a@x.com','John Smith'),(9,'b@x.com','John Smith')")
    c.execute("INSERT INTO disclosure_acceptances VALUES (1,7,'2026-09-10 14:59:00','2026-07-live-v1',"
              "'203.0.113.7','Mozilla/5.0 (Macintosh)')")
    c.execute("INSERT INTO signal_acceptances VALUES (1,7,55,'approve','2026-10-01T15:00:00+00:00',"
              "'203.0.113.7','Mozilla','1','x')")
    c.executemany("INSERT INTO trades (user_id,date,time,contracts,status,pnl,is_paper,is_preflight,source)"
                  " VALUES (?,?,?,?,?,?,?,?,?)", [
                      (7, "2026-09-03", "2026-09-03 14:00", 1, "closed", 0.4, 1, 0, None),
                      (7, "2026-09-15", "2026-09-15 14:00", 2, "closed", -1.0, 0, 0, None),
                      (7, "2026-10-01", "2026-10-01 15:01", 2, "closed", 0.2, 0, 0, "signalpilot"),
                      (7, "2026-10-02", "2026-10-02 15:01", 2, "open", None, 0, 1, None),
                      (8, "2026-10-02", "2026-10-02 15:01", 9, "closed", 1, 0, 0, None)])
    c.execute("INSERT INTO member_audit VALUES (1,7,'max_trades_day','1','2','2026-09-20 10:00:00')")
    c.commit()
    c.close()
    before = open(db, "rb").read()
    log = os.path.join(d, "access.log")
    with open(log, "w") as f:
        f.write('203.0.113.7 - - [05/Nov/2026:13:30:01 +0000] "GET /login HTTP/1.1" 200 10 "-" "M"\n')
        f.write('203.0.113.7 - - [05/Nov/2026:13:30:03 +0000] "POST /login HTTP/1.1" 302 10 "-" "M"\n')
        f.write('203.0.113.7 - - [06/Nov/2026:13:30:03 +0000] "GET /dashboard HTTP/1.1" 200 10 "-" "M"\n')
        f.write('192.0.2.99 - - [05/Nov/2026:13:40:00 +0000] "POST /login HTTP/1.1" 302 10 "-" "M"\n')
        f.write('garbage line\n')
    with gzip.open(log + ".2.gz", "wt") as f:
        f.write('203.0.113.7 - - [28/Oct/2026:09:00:00 +0000] "GET /performance HTTP/1.1" 200 10 "-" "M"\n')

    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    r = collect(db, email="  jane@EXAMPLE.com ", phone="555", log_paths=[log, log + ".2.gz"])
    blob = json.dumps(r)
    check(r["status"] == "found" and r["matched_on"] == "email", "email match")
    check("HASH" not in blob and "TOKEN" not in blob and "SECRET" not in blob, "no secrets in output")
    check(r["account"]["last_login_ip"] == "203.0.113.7", "last sign-in IP from log")
    check({e["ip"] for e in r["ip_events"]} == {"203.0.113.7", "198.51.100.4", "97.136.49.197"}, "ip events")
    check(sum(1 for e in r["ip_events"] if e["source"] == "login_events") == 1, "own sign-ins only")
    sdf = {x["field"]: x for x in r["settings_dates"]}
    check(sdf.get("condor_consent_at", {}).get("ip") == "97.136.49.197", "settings date with its IP")
    check("snaptrade_connected_at" in sdf and "live_approved_at" in sdf and "paper_start" in sdf,
          "labelled settings dates")
    check(sdf.get("futures_beta_at", {}).get("label") == "Futures beta", "unknown *_at column shown, named")
    check("token_refreshed_at" not in sdf and "broker_checked_at" not in sdf and "created_at" not in sdf,
          "secret-ish, system and duplicate columns skipped")
    check(any(e["ip"] == "97.136.49.197" for e in r["ip_events"]), "settings IP joins the IP list")
    check(r["settings_changes"] == [{"at": "2026-09-20T10:00:00+00:00", "field": "max_trades_day",
                                     "old": "1", "new": "2"}], "settings change listed")
    hb = [b["heading"] for b in pdf_blocks(r)]
    check("Timestamped records on the account's settings" in hb and
          "Bot settings the account holder changed" in hb, "pdf has settings blocks")
    check(r["history_since"].startswith("2026-10-30"), "history_since = earliest row on the box")
    check(len(r["visits"]) == 3 and {v["ip"] for v in r["visits"]} == {"203.0.113.7", "192.0.2.50"},
          "own visits only")
    vb = {v["ip"]: v for v in visits_by_ip(r)}
    check(vb["192.0.2.50"]["days"] == 2, "visits folded per IP")
    check(ip_matches(r, ["192.0.2.50"])[0]["where"].startswith("Used the Spreads Bot site"),
          "a visit IP matches")
    check(any("recorded since" in l for l in r["limits"]), "limit names the history start")
    check("Used the site on 3 distinct days" in summary_text(r), "summary counts visit days")
    check(r["trades"]["count"] == 3 and r["trades"]["contracts"] == 5, "trades exclude preflight + other users")
    check(r["trades"]["by_kind"] == {"Paper (simulated)": 1, "Spreads Bot (placed at broker)": 1,
                                     "Signal Pilot (member-approved)": 1}, "trade kinds")
    check("pnl" not in blob, "no pnl in output")
    u = {x["ip"]: x for x in r["ip_usage"]}
    check(u["203.0.113.7"]["days_seen"] == 3 and u["203.0.113.7"]["sign_ins"] == 1, "usage counts")
    check("192.0.2.99" not in u, "stranger IP not attributed")
    check(r["sessions"]["distinct_days_seen"] == 3, "sessions")
    check(r["activity"]["settings_changes"]["count"] == 1, "settings changes")
    check(r["activity"]["last_activity"].startswith("2026-11-06"), "last activity")
    check(any("phone" in l for l in r["limits"]), "phone limit stated")
    check(ip_matches(r, ["203.0.113.7", "10.0.0.1"])[0]["ip"] == "203.0.113.7", "ip match")
    check(ip_matches(r, ["10.0.0.1"]) == [], "no false ip match")
    r2 = from_json("noise\n" + JSON_BEGIN + "\n" + json.dumps(r) + "\n" + JSON_END + "\nmore")
    check(r2 == r, "json round trip")
    check(len(pdf_blocks(r, ghl_ips=["203.0.113.7"])) >= 6, "pdf blocks")
    check(not any(b["heading"].startswith("IP address match") for b in pdf_blocks(r, ghl_ips=["10.0.0.1"])),
          "no IP match block when nothing matches")
    n = collect(db, email="nobody@x.com")
    check(n["status"] == "not_found" and "No Spreads Bot account" in summary_text(n), "not found")
    amb = collect(db, name="john smith")
    check(amb["status"] == "ambiguous" and len(amb["candidates"]) == 2, "ambiguous name")
    byname = collect(db, email="wrong@x.com", name="Jane  Doe")
    check(byname["status"] == "found" and byname["matched_on"] == "name (exact)", "name fallback")
    part = collect(db, name="Jane Q Doe")
    check(part["status"] == "ambiguous", "partial name never auto-picked")
    check(open(db, "rb").read() == before, "database unchanged")
    old = os.path.join(d, "old.db")
    shutil.copy(db, old)
    oc = sqlite3.connect(old)
    oc.execute("DROP TABLE login_events")
    oc.execute("DROP TABLE member_visits")
    oc.commit()
    oc.close()
    ro = collect(old, email="jane@example.com")
    check(ro["visits"] == [] and ro["history_since"] == "" and
          any("only the most recent sign-in" in l for l in ro["limits"]), "a box without #A1721 still works")
    try:
        con = _connect_ro(db)
        con.execute("UPDATE users SET name='x'")
        fails.append("read-only open allowed a write")
    except sqlite3.OperationalError:
        pass
    for f in fails:
        print("FAIL", f)
    print("selftest %s (%d failures)" % ("PASS" if not fails else "FAILED", len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
