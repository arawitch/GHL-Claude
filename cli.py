#!/usr/bin/env python3
"""Command line access to the GoHighLevel location.

Every command in this file is read-only. Nothing here sends an email,
edits a contact, or enrolls anyone in a workflow.

    python3 cli.py info
    python3 cli.py tags --search newsletter
    python3 cli.py workflows --status published
    python3 cli.py schedules
    python3 cli.py count --tag "weekly newsletter subscriber" --mailable
    python3 cli.py export --tag "weekly newsletter subscriber" --mailable --out lists/newsletter.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from ghl.client import GHLClient, GHLError
from ghl import segments, sending, reactivation, weekly, rollout, clicks, sync as syncmod
from ghl.webinarjam import WebinarJamClient, WebinarJamError


def build_filters(args) -> list[dict]:
    parts = []
    if args.tag:
        parts.append(segments.any_tag(args.tag) if len(args.tag) > 1
                     else segments.has_tag(args.tag[0]))
    if args.added_after or args.added_before:
        parts.append(segments.added_between(args.added_after or "1970-01-01",
                                            args.added_before or "2100-01-01"))
    if args.mailable:
        return segments.mailable(*parts) if parts else segments.all_of(segments.MAILABLE)
    return segments.all_of(*parts) if parts else []


def cmd_info(client: GHLClient, args) -> None:
    loc = client.location()
    print(f"location : {loc.get('name')}  ({loc.get('id')})")
    print(f"timezone : {loc.get('timezone')}")
    print(f"contacts : {client.count_contacts():,}")
    print(f"mailable : {client.count_contacts(segments.all_of(segments.MAILABLE)):,}"
          "   (has email, global DND off, email DND off)")
    print(f"sendable : {client.count_contacts(sending.safe_send()):,}"
          "   (mailable, minus suppression tags)")
    print(f"tags     : {len(client.tags()):,}")
    print(f"fields   : {len(client.custom_fields()):,} custom fields")
    print(f"workflows: {len(client.workflows()):,}")


def cmd_tags(client: GHLClient, args) -> None:
    tags = client.tags()
    if args.search:
        needle = args.search.lower()
        tags = [t for t in tags if needle in t.get("name", "").lower()]
    for tag in sorted(tags, key=lambda t: t.get("name", "")):
        print(tag.get("name"))
    print(f"\n{len(tags)} tag(s)", file=sys.stderr)


def cmd_workflows(client: GHLClient, args) -> None:
    flows = client.workflows()
    if args.status:
        flows = [w for w in flows if w.get("status") == args.status]
    if args.search:
        needle = args.search.lower()
        flows = [w for w in flows if needle in w.get("name", "").lower()]
    for wf in sorted(flows, key=lambda w: w.get("name", "")):
        print(f"{wf.get('status','?'):<10} {wf.get('name')}")
    print(f"\n{len(flows)} workflow(s)", file=sys.stderr)


def cmd_schedules(client: GHLClient, args) -> None:
    for s in client.email_schedules():
        print(f"{str(s.get('status','?')):<12} {str(s.get('name'))[:48]:<50} {s.get('subject','')}")


def cmd_audit(client: GHLClient, args) -> None:
    a = sending.audit(client)
    total = a["total"]
    print("SEND LIST FUNNEL")
    print("=" * 58)
    for key, label in [("total", "all contacts"),
                       ("mailable", "has email, DND off"),
                       ("safe_send", "minus suppression tags"),
                       ("validated", "+ confirmed deliverable"),
                       ("engaged", "+ has engagement tag")]:
        print(f"  {label:<32}{a[key]:>8,}  {100 * a[key] / total:>5.1f}%")
    print("=" * 58)
    hidden = a["mailable"] - a["safe_send"]
    print(f"  suppression removes {hidden:,} that a plain --mailable segment "
          f"would have included\n")
    print("SUPPRESSED CONTACTS BY TAG")
    print("-" * 58)
    for tag, n in sending.suppression_breakdown(client):
        if n:
            print(f"  {n:>7,}  {tag}")


def cmd_sendlist(client: GHLClient, args) -> None:
    tier = {"safe": sending.safe_send, "engaged": sending.engaged,
            "validated": sending.validated}[args.tier]
    extra = [segments.has_tag(t) for t in (args.tag or [])]
    filters = tier(*extra)
    total = client.count_contacts(filters)
    if not args.out:
        print(f"{total:,} contact(s) in the '{args.tier}' send list")
        return
    print(f"{total:,} contact(s); exporting to {args.out} ...", file=sys.stderr)
    written = segments.export_csv(client, filters, args.out, max_records=args.limit)
    print(f"wrote {written:,} row(s) to {args.out}")


def cmd_reactivation(client: GHLClient, args) -> None:
    s = reactivation.summary(client)
    print("REACTIVATION COHORTS")
    print("=" * 60)
    print(f"  never upload (consent withdrawn)     {s['never_upload']:>7,}")
    print(f"  verification candidates              {s['verify_candidates']:>7,}")
    print(f"    already recorded bad               {s['confirmed_bad']:>7,}")
    print(f"    worth paying to verify             {s['worth_verifying']:>7,}")
    print()
    if not args.out_dir:
        print("  pass --out-dir to export the lists")
        return

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    verify_path = out / "verify-candidates.csv"
    exclude_path = out / "NEVER-UPLOAD.csv"

    print("  collecting opted-out addresses ...", file=sys.stderr)
    suppressed = reactivation.suppressed_addresses(client)

    # Duplicate contact records mean an address can pass verify_candidates()
    # on one record while another record for the same person carries the
    # opt-out. Filter by address, not by contact.
    written = dropped = 0
    with verify_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=segments.EXPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for contact in client.search_contacts(filters=reactivation.worth_verifying()):
            email = (contact.get("email") or "").strip().lower()
            if not email or email in suppressed:
                dropped += 1
                continue
            row = {k: contact.get(k, "") for k in segments.EXPORT_COLUMNS}
            row["tags_REFERENCE_DO_NOT_IMPORT"] = " / ".join(contact.get("tags") or [])
            writer.writerow(row)
            written += 1

    print(f"  wrote {written:,} rows to {verify_path}")
    if dropped:
        print(f"    ({dropped:,} dropped: a duplicate record for the same address opted out)")
    n = segments.export_csv(client, reactivation.never_upload(), exclude_path)
    print(f"  wrote {n:,} rows to {exclude_path}")
    print()
    print("  Upload verify-candidates.csv to the verification service.")
    print("  NEVER-UPLOAD.csv is a suppression reference for your own checking:")
    print("  those contacts withdrew consent, so a 'valid' verdict on them is")
    print("  irrelevant and acting on it would be an opt-out violation.")


def cmd_weekly(client: GHLClient, args) -> None:
    rows = weekly.plan(client, args.event, reminders=args.reminders)
    print(f"SEND PLAN for event {args.event!r}")
    print("=" * 58)
    print(f"  {'slot':<22}{'track':<8}{'recipients':>12}")
    print("-" * 58)
    for slot, track, n in rows:
        label = {"A": "A reg", "B": "B unreg", "-": "post"}[track]
        print(f"  {slot:<22}{label:<8}{n:>12,}" if n >= 0
              else f"  {slot:<22}{label:<8}{'tag missing':>12}")
    print("-" * 58)
    if not args.out_dir:
        print("  pass --out-dir to export one CSV per slot")
        return

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    seen: dict[str, str] = {}
    for slot, track, n in rows:
        if n <= 0:
            continue
        builder = dict((s, b) for s, _, b in weekly.slots_for(args.reminders))[slot]
        filters = builder(args.event)
        key = repr(filters)
        # Several slots share an audience; export once and say so rather than
        # writing byte-identical files under different names.
        if key in seen:
            print(f"  {slot:<22} same audience as {seen[key]}")
            continue
        seen[key] = slot
        written = segments.export_csv(client, filters, out / f"{slot}.csv")
        print(f"  wrote {written:>7,} to {slot}.csv")


def cmd_rollout(client: GHLClient, args) -> None:
    core_n = client.count_contacts(rollout.core())
    rec_n = client.count_contacts(rollout.recovered())
    total = core_n + rec_n
    steps = rollout.schedule(args.start, total, args.growth)

    print("VOLUME RAMP")
    print("=" * 58)
    print(f"  proven core (engaged)      {core_n:>8,}")
    print(f"  recovered (never reached)  {rec_n:>8,}")
    print(f"  full pool                  {total:>8,}")
    print("-" * 58)
    for i, v in enumerate(steps):
        mark = "  <- this step" if i == args.step else ""
        print(f"  step {i:<2} {v:>8,}{mark}")
    print("-" * 58)
    if args.step >= len(steps):
        print(f"  step {args.step} is past the end; the ramp finishes at step {len(steps)-1}")
        return

    if not args.out:
        print("  pass --out to export this step's recipients")
        return

    exclude = set()
    if args.exclude_file:
        with open(args.exclude_file, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                e = (row.get("email") or "").strip().lower()
                if e:
                    exclude.add(e)
        print(f"  excluding {len(exclude):,} addresses from {args.exclude_file}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=segments.EXPORT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for contact in rollout.step_list(client, steps[args.step], exclude):
            row = {k: contact.get(k, "") for k in segments.EXPORT_COLUMNS}
            row["tags_REFERENCE_DO_NOT_IMPORT"] = " / ".join(contact.get("tags") or [])
            w.writerow(row)
            written += 1
    print(f"  wrote {written:,} recipients to {out}")


def _relevant_schedules(wj, webinar_id, window_days):
    """Schedules within +/- window_days of now.

    Covers both directions on purpose: an upcoming session needs its
    registrations mirrored so Track B can exclude them, and a session that has
    just run needs its attendance and replay data pulled in.
    """
    from datetime import datetime, timedelta
    now = datetime.now()
    out = []
    for s in wj.schedules(webinar_id):
        try:
            when = datetime.strptime(str(s.get("date", "")), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if abs((when - now).total_seconds()) <= window_days * 86400:
            out.append((s.get("schedule"), when))
    return sorted(out, key=lambda x: x[1])


def cmd_sync_webinar(client: GHLClient, args) -> None:
    wj = WebinarJamClient()

    if args.auto:
        found = _relevant_schedules(wj, args.webinar_id, args.window_days)
        if not found:
            print(f"no session within {args.window_days} days of now - nothing to sync")
            return
        print(f"auto: {len(found)} session(s) within {args.window_days} days\n")
        for sched, when in found:
            args.schedule_id = sched
            args.prefix = None
            _sync_one(client, wj, args)
            print()
        return

    if not args.schedule_id:
        print(f"schedules for webinar {args.webinar_id}:")
        for s in wj.schedules(args.webinar_id):
            print(f"  schedule={s.get('schedule')}  {s.get('date')}  {s.get('comment','')}")
        print("\n  pass --schedule-id to sync one session, or --auto")
        return

    _sync_one(client, wj, args)


def _sync_one(client: GHLClient, wj, args) -> None:

    # Attendance roles are meaningless until the session has run: WebinarJam
    # reports attended_live as "No" for everyone beforehand.
    from datetime import datetime
    sched_date = None
    for s in wj.schedules(args.webinar_id):
        if str(s.get("schedule")) == str(args.schedule_id):
            sched_date = str(s.get("date", ""))
    event_finished = True
    if sched_date:
        try:
            event_finished = datetime.strptime(sched_date, "%Y-%m-%d %H:%M") < datetime.now()
        except ValueError:
            pass

    prefix = args.prefix
    if not prefix:
        for s in wj.schedules(args.webinar_id):
            if str(s.get("schedule")) == str(args.schedule_id):
                d = str(s.get("date", ""))[:10].split("-")
                if len(d) == 3:
                    prefix = f"{int(d[1])}/{int(d[2])}"
        if not prefix:
            print("could not derive a tag prefix; pass --prefix", file=sys.stderr)
            return

    mode = "APPLYING" if args.apply else "DRY RUN - nothing will be written"
    print(f"webinar {args.webinar_id} schedule {args.schedule_id} -> tag prefix {prefix!r}")
    print(f"{mode}\n")

    if not event_finished:
        print(f"  session runs {sched_date} - not finished yet, so only the")
        print("  registration tag is applied (attendance is not knowable yet)\n")

    import os
    secondary = None
    if os.environ.get("GHL_SMS_API_KEY") and os.environ.get("GHL_SMS_LOCATION_ID"):
        secondary = GHLClient(token=os.environ["GHL_SMS_API_KEY"],
                              location_id=os.environ["GHL_SMS_LOCATION_ID"])
        print(f"  also tagging in SMS location {secondary.location_id}\n")

    rep = syncmod.sync(wj, client, args.webinar_id, args.schedule_id, prefix,
                       stayed_minutes=args.stayed_minutes, apply=args.apply,
                       event_finished=event_finished, secondary=secondary)

    print(f"  registrants in WebinarJam   {rep.registrants:>7,}")
    print(f"  matched to a GHL contact    {rep.matched:>7,}")
    print(f"  no GHL contact found        {len(rep.unmatched):>7,}")
    if rep.tags_applied or rep.already_tagged:
        print(f"\n  {'tag':<28}{'to apply':>10}{'already':>10}")
        print("  " + "-" * 48)
        for tag in sorted(set(rep.tags_applied) | set(rep.already_tagged)):
            print(f"  {tag:<28}{rep.tags_applied.get(tag,0):>10,}{rep.already_tagged.get(tag,0):>10,}")
    if rep.unmatched:
        print(f"\n  unmatched addresses (first 10):")
        for e in rep.unmatched[:10]:
            print(f"    {e}")
    if rep.errors:
        print(f"\n  {len(rep.errors)} error(s):")
        for e in rep.errors[:5]:
            print(f"    {e}")

    if args.apply:
        print("\n  RECONCILIATION (GHL tag counts vs this session)")
        print("  " + "-" * 48)
        for tag, expected, actual in syncmod.reconcile(client, prefix, rep):
            flag = "" if actual >= expected else "   <-- SHORTFALL"
            print(f"  {tag:<28}{expected:>8,} expected{actual:>8,} in GHL{flag}")
    else:
        print("\n  re-run with --apply to write these tags")


def cmd_register(client: GHLClient, args) -> None:
    """Register people who clicked a one-click link but never landed in WebinarJam.

    GHL records the click; WebinarJam records the registration. A click with no
    matching registration means the link resolved for the tracker but the
    registration itself did not complete -- a mail gateway rewriting the URL, a
    scanner following it, or a client mangling the query string.
    """
    wj = WebinarJamClient()

    emails = list(args.email or [])
    if args.file:
        with open(args.file, newline="", encoding="utf-8-sig") as fh:
            head = fh.readline()
            fh.seek(0)
            if "," in head or "@" not in head:      # looks like a CSV with a header
                for row in csv.DictReader(fh):
                    for k, v in row.items():
                        if k and "email" in k.lower() and v and "@" in v:
                            emails.append(v.strip())
                            break
            else:                                    # one address per line
                emails += [l.strip() for l in fh if "@" in l]

    emails = list(dict.fromkeys(e.strip().lower() for e in emails if e.strip()))
    if not emails:
        print("no email addresses given; use --email or --file", file=sys.stderr)
        return

    already = {(r.get("email") or "").strip().lower()
               for r in wj.registrants(args.webinar_id, args.schedule_id)}
    todo = [e for e in emails if e not in already]

    print(f"  {len(emails):,} address(es) given")
    print(f"  {len(emails) - len(todo):,} already registered in WebinarJam")
    print(f"  {len(todo):,} to register\n")
    if not todo:
        return
    if not args.apply:
        for e in todo[:20]:
            print(f"    {e}")
        print("\n  re-run with --apply to register them")
        return

    ok = failed = nocontact = 0
    for email in todo:
        found = list(client.search_contacts(
            filters=[{"field": "email", "operator": "eq", "value": email}], max_records=1))
        if not found:
            print(f"    skip (no GHL contact): {email}")
            nocontact += 1
            continue
        ct = found[0]
        try:
            wj.register(args.webinar_id, args.schedule_id, email,
                        ct.get("firstName") or "", ct.get("lastName") or "")
            ok += 1
            print(f"    registered: {email}")
        except WebinarJamError as exc:
            failed += 1
            print(f"    FAILED {email}: {str(exc)[:120]}")
    print(f"\n  {ok:,} registered, {failed:,} failed, {nocontact:,} skipped")
    print("  WebinarJam sends each of them the confirmation and join link.")


def cmd_clicks(client: GHLClient, args) -> None:
    """Who clicked a GHL email this week, and whether they made it to WebinarJam.

    Clicks are only reachable per contact, three API hops deep -- see
    ghl/clicks.py for why, and for why a click is attributed to a specific send
    rather than to the contact.
    """
    sends = clicks.recent_sends(client, days=args.days)
    if not sends:
        print(f"no completed sends in the last {args.days} days")
        return

    print(f"SENDS in the last {args.days} days\n")
    print(f"  {'send':<28}{'scheduled':<17}{'delivered':>10}  {'tracking':<9}"
          f"{'reg link':<10}click means")
    print("  " + "-" * 92)
    for s in sends:
        means = ("register" if s.asks_registration and not s.ambiguous_click
                 else "AMBIGUOUS" if s.asks_registration else "-")
        print(f"  {s.name[:27]:<28}{s.scheduled.strftime('%a %m-%d %H:%MZ'):<17}"
              f"{s.recipients:>10,}  {'on' if s.tracking else 'OFF':<9}"
              f"{'yes' if s.asks_registration else 'no':<10}{means}")
    dark = [s for s in sends if not s.tracking and s.asks_registration]
    if dark:
        print("\n  NOTE: click tracking was off on "
              f"{', '.join(s.name for s in dark)}.")
        print("  Clicks there are unrecorded and cannot appear below. Untracked")
        print("  links are also unrewritten, so those one-clicks reached")
        print("  WebinarJam directly -- absence of data is not absence of clicks.")

    print(f"\nscanning clickers ...", file=sys.stderr)
    found = clicks.scan(client, sends, args.since, args.until,
                        progress=lambda n, f: print(f"  {n} candidates, {f} clickers",
                                                    end="\r", file=sys.stderr))
    intent, unclear, other = clicks.split_by_intent(found, sends)
    print(f"\n{len(found):,} clicker(s): {len(intent):,} definite registration "
          f"intent, {len(unclear):,} ambiguous, {len(other):,} on sends with no "
          f"register link\n")

    registered: set[str] = set()
    if args.webinar_id and args.schedule_id:
        wj = WebinarJamClient()
        registered = {(r.get("email") or "").strip().lower()
                      for r in wj.registrants(args.webinar_id, args.schedule_id)}

    missing = [c for c in intent if c.email and c.email not in registered]
    print(f"  {'email':<38}{'in WJ':<7}{'tagged':<8}sends clicked")
    print("  " + "-" * 96)
    tag = f"{args.prefix} register" if args.prefix else None
    for c in sorted(intent, key=lambda x: x.email):
        in_wj = "yes" if c.email in registered else "NO"
        tagged = "-"
        if tag:
            tagged = "yes" if tag in (c.tags or []) else "NO"
        print(f"  {c.email[:37]:<38}{in_wj:<7}{tagged:<8}{'; '.join(c.register_sends)[:44]}")

    if unclear:
        missing_unclear = [c for c in unclear if c.email and c.email not in registered]
        print(f"\n  AMBIGUOUS -- clicked a send that had a register link AND "
              f"something else\n  clickable. The API exposes no per-link data, so "
              f"these cannot be resolved.\n  {len(missing_unclear):,} of "
              f"{len(unclear):,} are not in WebinarJam. Decide, do not assume:")
        for c in sorted(unclear, key=lambda x: x.email):
            mark = "not in WJ" if c.email not in registered else "in WJ"
            print(f"    {c.email[:37]:<38}{mark:<11}{'; '.join(c.register_sends)[:34]}")

    if other:
        print(f"\n  clicked only a send with no register link "
              f"(NOT registration intent, left alone):")
        for c in sorted(other, key=lambda x: x.email):
            print(f"    {c.email[:37]:<38}{'; '.join(c.register_sends)[:44]}")

    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["email", "firstName", "lastName", "phone", "contactId",
                        "in_webinarjam", "clicked_sends"])
            for c in sorted(intent, key=lambda x: x.email):
                w.writerow([c.email, c.first, c.last, c.phone, c.contact_id,
                            "yes" if c.email in registered else "no",
                            "; ".join(c.register_sends)])
        print(f"\n  wrote {len(intent):,} row(s) to {args.out}")

    if registered:
        print(f"\n  {len(missing):,} clicked a register link but are not in WebinarJam.")
        if missing:
            print("  Register them with:")
            print(f"    python3 cli.py register --webinar-id {args.webinar_id} "
                  f"--schedule-id {args.schedule_id} --file {args.out or 'clicks.csv'} --apply")


def cmd_count(client: GHLClient, args) -> None:
    print(f"{client.count_contacts(build_filters(args)):,} contact(s) match")


def cmd_export(client: GHLClient, args) -> None:
    filters = build_filters(args)
    total = client.count_contacts(filters)
    print(f"{total:,} contact(s) match; exporting to {args.out} ...", file=sys.stderr)
    written = segments.export_csv(client, filters, args.out, max_records=args.limit)
    print(f"wrote {written:,} row(s) to {args.out}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_filter_args(p):
        p.add_argument("--tag", action="append", help="tag to match (repeat for OR)")
        p.add_argument("--added-after", help="ISO date, e.g. 2026-01-01")
        p.add_argument("--added-before", help="ISO date")
        p.add_argument("--mailable", action="store_true",
                       help="restrict to contacts with an email and DND off")

    sub.add_parser("info").set_defaults(func=cmd_info)

    p = sub.add_parser("tags"); p.add_argument("--search"); p.set_defaults(func=cmd_tags)

    p = sub.add_parser("workflows")
    p.add_argument("--status", choices=["published", "draft"])
    p.add_argument("--search")
    p.set_defaults(func=cmd_workflows)

    sub.add_parser("schedules").set_defaults(func=cmd_schedules)

    sub.add_parser("audit").set_defaults(func=cmd_audit)

    p = sub.add_parser("weekly")
    p.add_argument("--event", required=True,
                   help="event tag prefix, e.g. \"7/24\" for '7/24 register'")
    p.add_argument("--out-dir", help="directory to write one CSV per send slot")
    p.add_argument("--reminders", choices=["webinarjam", "ghl"], default="webinarjam",
                   help="who sends registrant reminders. Default assumes WebinarJam "
                        "handles 48h/24h/1h/15min, so GHL skips them.")
    p.set_defaults(func=cmd_weekly)

    p = sub.add_parser("rollout")
    p.add_argument("--step", type=int, default=0, help="which step to export")
    p.add_argument("--start", type=int, default=6795, help="current proven send volume")
    p.add_argument("--growth", type=float, default=rollout.DEFAULT_GROWTH)
    p.add_argument("--exclude-file", help="CSV of addresses to skip (verifier bad verdicts)")
    p.add_argument("--out", help="CSV path for this step's recipients")
    p.set_defaults(func=cmd_rollout)

    p = sub.add_parser("sync-webinar")
    p.add_argument("--webinar-id", type=int, required=True)
    p.add_argument("--schedule-id", type=int, help="omit to list available schedules")
    p.add_argument("--auto", action="store_true",
                   help="sync every session within --window-days of now; no weekly edits needed")
    p.add_argument("--window-days", type=int, default=7)
    p.add_argument("--prefix", help="tag prefix, e.g. \"7/30\"; derived from the schedule date if omitted")
    p.add_argument("--stayed-minutes", type=int, default=0,
                   help="also tag '<prefix> stayed' for anyone whose live watch time reached this")
    p.add_argument("--apply", action="store_true", help="write tags (default is a dry run)")
    p.set_defaults(func=cmd_sync_webinar)

    p = sub.add_parser("register")
    p.add_argument("--webinar-id", type=int, required=True)
    p.add_argument("--schedule-id", type=int, required=True, help="global schedule id, e.g. 107")
    p.add_argument("--email", action="append", help="address to register (repeatable)")
    p.add_argument("--file", help="CSV or newline list of addresses")
    p.add_argument("--apply", action="store_true", help="register them (default is a dry run)")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("clicks", help="who clicked a GHL email, and whether "
                                      "they reached WebinarJam")
    p.add_argument("--days", type=int, default=7, help="how far back to look for sends")
    p.add_argument("--since", default="2026-07-27", help="ISO date, start of the contact window")
    p.add_argument("--until", default="2100-01-01", help="ISO date, end of the contact window")
    p.add_argument("--webinar-id", type=int, help="cross-reference WebinarJam registrants")
    p.add_argument("--schedule-id", type=int, help="global schedule id, e.g. 107")
    p.add_argument("--prefix", help="event tag prefix, e.g. \"7/30\", to check tagging")
    p.add_argument("--out", help="CSV of register-intent clickers, for `register --file`")
    p.set_defaults(func=cmd_clicks)

    p = sub.add_parser("reactivation")
    p.add_argument("--out-dir", help="directory to write the two CSV lists into")
    p.set_defaults(func=cmd_reactivation)

    p = sub.add_parser("sendlist")
    p.add_argument("--tier", choices=["safe", "engaged", "validated"], default="engaged",
                   help="safe = minus suppression tags; engaged = also has an "
                        "engagement tag (default); validated = also confirmed deliverable")
    p.add_argument("--tag", action="append", help="additionally require this tag")
    p.add_argument("--out", help="CSV output path; omit to just print the count")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_sendlist)

    p = sub.add_parser("count"); add_filter_args(p); p.set_defaults(func=cmd_count)

    p = sub.add_parser("export")
    add_filter_args(p)
    p.add_argument("--out", required=True, help="CSV output path")
    p.add_argument("--limit", type=int, help="stop after N records")
    p.set_defaults(func=cmd_export)

    args = parser.parse_args()
    try:
        args.func(GHLClient(), args)
    except GHLError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
