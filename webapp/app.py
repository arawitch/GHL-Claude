"""A private page where a closer types a buyer's name and gets the evidence pack.

One password, one search box. Type a name (or an email, or a phone number),
pick the right person from the matches, and the app builds the same PDF that
`cli.py dispute-evidence` builds and hands it back as a download.

Run it:

    DISPUTE_PASSWORD=somethinglong \\
    GHL_SMS_API_KEY=... GHL_SMS_LOCATION_ID=... \\
    GHL_EMAIL_API_KEY=... GHL_EMAIL_LOCATION_ID=... \\
    python3 webapp/app.py

It listens on $PORT (default 5000). There is no user database and nothing is
stored: packs are written to a temporary directory and deleted on restart.

A pack takes a minute or so to build, because it reads both sub-accounts, so
the build runs in a background thread and the page polls until it is ready.
"""

from __future__ import annotations

import os
import secrets
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import (Flask, abort, jsonify, redirect, request, send_file,
                   session, url_for)

from ghl import dispute
from ghl.client import GHLClient

PASSWORD = os.environ.get("DISPUTE_PASSWORD", "")
OUT_DIR = Path(tempfile.gettempdir()) / "dispute-packs"
OUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

# job id -> {"state", "error", "path", "name", "started"}
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def accounts() -> list[tuple[str, GHLClient]]:
    out = []
    for label, token_var, loc_var in (
            ("SMS", "GHL_SMS_API_KEY", "GHL_SMS_LOCATION_ID"),
            ("main/EMAIL", "GHL_EMAIL_API_KEY", "GHL_EMAIL_LOCATION_ID")):
        token, loc = os.environ.get(token_var), os.environ.get(loc_var)
        if token and loc:
            out.append((label, GHLClient(token=token, location_id=loc)))
    return out


def logged_in() -> bool:
    return bool(session.get("ok"))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

STYLE = """
:root { color-scheme: light dark;
  --bg:#ffffff; --fg:#1a1a1a; --muted:#666; --line:#dcdcdc; --accent:#1f5f3f;
  --card:#fafafa; }
@media (prefers-color-scheme: dark) { :root {
  --bg:#16181c; --fg:#ececec; --muted:#9aa0a6; --line:#33373d; --accent:#6fd39b;
  --card:#1d2025; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.5
  ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
.wrap { max-width:720px; margin:0 auto; padding:40px 16px 80px; }
h1 { font-size:22px; margin:0 0 4px; letter-spacing:-0.01em; }
p.sub { color:var(--muted); margin:0 0 28px; font-size:14px; }
form.row { display:flex; gap:8px; flex-wrap:wrap; }
input[type=text], input[type=password] { flex:1 1 240px; padding:11px 13px;
  border:1px solid var(--line); border-radius:8px; background:var(--card);
  color:var(--fg); font-size:16px; }
button { padding:11px 18px; border:0; border-radius:8px; background:var(--accent);
  color:#fff; font-size:15px; font-weight:600; cursor:pointer; }
@media (prefers-color-scheme: dark) { button { color:#10251a; } }
button:disabled { opacity:.5; cursor:default; }
.hit { border:1px solid var(--line); border-radius:10px; padding:14px 16px;
  margin:10px 0; background:var(--card); display:flex; gap:12px;
  align-items:center; justify-content:space-between; flex-wrap:wrap; }
.hit .who { font-weight:600; }
.hit .meta { color:var(--muted); font-size:13px; margin-top:2px;
  word-break:break-all; }
.note { color:var(--muted); font-size:13px; margin-top:28px;
  border-top:1px solid var(--line); padding-top:14px; }
.err { color:#b3261e; font-size:14px; }
@media (prefers-color-scheme: dark) { .err { color:#ff8a80; } }
a { color:var(--accent); }
"""


def page(body: str, title: str = "Dispute evidence") -> str:
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{title}</title><style>{STYLE}</style></head>"
            f"<body><div class=wrap>{body}</div></body></html>")


def esc(value: object) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


@app.get("/")
def home():
    if not logged_in():
        return redirect(url_for("login"))
    return page(
        "<h1>Dispute evidence</h1>"
        "<p class=sub>Type the buyer's name, email or phone number. "
        "Building a pack takes about a minute.</p>"
        "<form class=row method=get action='/search'>"
        "<input type=text name=q placeholder='e.g. Bryan Stahl' autofocus "
        "autocomplete=off required>"
        "<button type=submit>Search</button></form>"
        "<p class=note>The pack covers the order, what the buyer had to agree "
        "to at checkout, the published terms, every call and message, and a "
        "capture of the checkout page. Submit it as-is to the processor.</p>")


@app.route("/login", methods=["GET", "POST"])
def login():
    if not PASSWORD:
        return page("<h1>Not configured</h1><p class=err>Set DISPUTE_PASSWORD "
                    "in the environment before using this page.</p>"), 500
    error = ""
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", ""), PASSWORD):
            session["ok"] = True
            session.permanent = False
            return redirect(url_for("home"))
        time.sleep(1.0)
        error = "<p class=err>Wrong password.</p>"
    return page("<h1>Dispute evidence</h1>"
                "<p class=sub>Enter the shared password.</p>"
                f"{error}"
                "<form class=row method=post>"
                "<input type=password name=password autofocus required>"
                "<button type=submit>Enter</button></form>")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/search")
def search():
    if not logged_in():
        return redirect(url_for("login"))
    query = (request.args.get("q") or "").strip()
    if not query:
        return redirect(url_for("home"))

    seen, hits = set(), []
    for label, client in accounts():
        for row in dispute.search(client, query):
            key = (row["email"] or "").lower() or row["phone"] or row["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            row["account"] = label
            hits.append(row)

    parts = [f"<h1>Matches for &ldquo;{esc(query)}&rdquo;</h1>"]
    if not hits:
        parts.append("<p class=sub>Nobody matched. Try a surname on its own, "
                     "or the email address.</p>")
    for row in hits:
        meta = " &middot; ".join(filter(None, [esc(row["email"]), esc(row["phone"]),
                                               "added " + esc(row["created"][:10])]))
        parts.append(
            "<div class=hit><div>"
            f"<div class=who>{esc(row['name']) or '(no name)'}</div>"
            f"<div class=meta>{meta}</div></div>"
            "<form method=post action='/build'>"
            f"<input type=hidden name=email value='{esc(row['email'])}'>"
            f"<input type=hidden name=phone value='{esc(row['phone'])}'>"
            f"<input type=hidden name=name value='{esc(row['name'])}'>"
            f"<select name=checkout>{checkout_options()}</select> "
            "<button type=submit>Build pack</button></form></div>")
    parts.append("<p class=note><a href='/'>New search</a></p>")
    return page("".join(parts))


def checkout_options() -> str:
    """The checkout pages, so a pack can carry the right exhibit even when the
    order record is unreadable and the page cannot be detected."""
    out = ["<option value=''>Checkout: detect from the order</option>"]
    for path in dispute.CHECKOUT_ACCEPTANCE:
        if path != path.lower():          # the /PRESALE duplicate
            continue
        out.append(f"<option value='{esc(path)}'>{esc(path)}</option>")
    return "".join(out)


def build_job(job_id: str, email: str, phone: str, name: str,
              checkout: str = "") -> None:
    try:
        packs = [dispute.gather(client, email=email, phone=phone, label=label,
                                pages=6)
                 for label, client in accounts()]
        facts = dispute.transaction_summary(packs)
        exhibit = ""
        for pack in packs:
            for order in (pack.get("orders") or {}).get("orders", []):
                exhibit = exhibit or dispute.exhibit_for(order.get("bought_on", ""))
        if not exhibit and checkout:
            exhibit = dispute.exhibit_for(
                "https://go.universityofoptions.com" + checkout)
        if checkout and not any(
                (p.get("orders") or {}).get("orders") for p in packs):
            facts.setdefault("Checkout page (selected)",
                             "https://go.universityofoptions.com" + checkout)
        slug = "".join(ch if ch.isalnum() else "-" for ch in (name or email or "buyer"))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out = OUT_DIR / f"{slug.strip('-').lower()}-{stamp}-{job_id[:6]}.pdf"
        accepted = dispute.CHECKOUT_ACCEPTANCE.get(checkout, "") if checkout else ""
        dispute.render_pdf(packs, str(out), facts or None, exhibit=exhibit,
                           acceptance=accepted)
        with JOBS_LOCK:
            JOBS[job_id].update(state="done", path=str(out),
                                found=any(p.get("found") for p in packs))
    except Exception as exc:                          # surfaced on the page
        with JOBS_LOCK:
            JOBS[job_id].update(state="error", error=str(exc)[:400])


@app.post("/build")
def build():
    if not logged_in():
        return redirect(url_for("login"))
    email = (request.form.get("email") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    name = (request.form.get("name") or "").strip()
    if not email and not phone:
        return redirect(url_for("home"))
    job_id = secrets.token_urlsafe(12)
    with JOBS_LOCK:
        JOBS[job_id] = {"state": "running", "name": name, "started": time.time()}
    checkout = (request.form.get("checkout") or "").strip()
    if checkout and checkout not in dispute.CHECKOUT_ACCEPTANCE:
        checkout = ""
    threading.Thread(target=build_job,
                     args=(job_id, email, phone, name, checkout),
                     daemon=True).start()
    return redirect(url_for("status_page", job_id=job_id))


@app.get("/pack/<job_id>")
def status_page(job_id: str):
    if not logged_in():
        return redirect(url_for("login"))
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        abort(404)
    return page(
        f"<h1>{esc(job['name']) or 'Evidence pack'}</h1>"
        "<p class=sub id=state>Reading both GoHighLevel accounts&hellip; this "
        "takes about a minute.</p>"
        "<p id=action></p>"
        "<p class=note><a href='/'>New search</a></p>"
        "<script>"
        f"const id={job_id!r};"
        "async function tick(){"
        " const r=await fetch('/pack/'+id+'/status');const j=await r.json();"
        " if(j.state==='done'){"
        "  document.getElementById('state').textContent = j.found ?"
        "   'Ready.' : 'Built, but no CRM record matched \\u2014 check the spelling.';"
        "  document.getElementById('action').innerHTML ="
        "   \"<a href='/pack/\"+id+\"/download'>Download the PDF</a>\"; return; }"
        " if(j.state==='error'){"
        "  document.getElementById('state').className='err';"
        "  document.getElementById('state').textContent='Failed: '+j.error; return; }"
        " setTimeout(tick,2000); }"
        "tick();</script>")


@app.get("/pack/<job_id>/status")
def status(job_id: str):
    if not logged_in():
        abort(403)
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        abort(404)
    return jsonify({k: job.get(k) for k in ("state", "error", "found")})


@app.get("/pack/<job_id>/download")
def download(job_id: str):
    if not logged_in():
        return redirect(url_for("login"))
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or job.get("state") != "done":
        abort(404)
    path = Path(job["path"])
    if not path.exists():
        abort(404)
    return send_file(path, as_attachment=True, download_name=path.name,
                     mimetype="application/pdf")


if __name__ == "__main__":
    if not PASSWORD:
        print("DISPUTE_PASSWORD is not set; the page will refuse to log anyone in.",
              file=sys.stderr)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
