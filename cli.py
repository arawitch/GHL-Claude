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

from ghl.client import GHLClient, GHLError, GHLScopeError
from ghl import segments, sending, reactivation, weekly, rollout


def scoped(fn, fmt=lambda v: f"{v:,}"):
    """Render a value from a scoped endpoint, or say why it is missing.

    A private integration token can be issued with contact access but without
    the locations, workflows or emails scopes. Those reads 401 while every
    contact-driven command keeps working, so `info` reports what it can rather
    than failing whole.
    """
    try:
        return fmt(fn())
    except GHLScopeError:
        return "unavailable (token lacks this scope)"


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
    try:
        loc = client.location()
        print(f"location : {loc.get('name')}  ({loc.get('id')})")
        print(f"timezone : {loc.get('timezone')}")
    except GHLScopeError:
        print(f"location : {client.location_id}")
        print("timezone : unavailable (token lacks the locations scope)")
    print(f"contacts : {client.count_contacts():,}")
    print(f"mailable : {client.count_contacts(segments.all_of(segments.MAILABLE)):,}"
          "   (has email, global DND off, email DND off)")
    print(f"sendable : {client.count_contacts(sending.safe_send()):,}"
          "   (mailable, minus suppression tags)")
    print(f"tags     : {scoped(lambda: len(client.tags()))}")
    print(f"fields   : {scoped(lambda: len(client.custom_fields()))} custom fields")
    print(f"workflows: {scoped(lambda: len(client.workflows()))}")


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
                       ("safe_send", "minus suppression tags")]:
        print(f"  {label:<32}{a[key]:>8,}  {100 * a[key] / total:>5.1f}%")
    print("-" * 58)
    # engaged and validated are two independent narrowings of safe_send, not
    # further steps below it. Listing them in one column made the funnel look
    # cumulative, which understates the safe list by an order of magnitude.
    print("  narrowings of the safe list:")
    for key, label in [("engaged", "+ has engagement tag"),
                       ("validated", "+ confirmed deliverable")]:
        note = ""
        if key == "validated" and not a[key]:
            note = "  <- no validEmail data in this location"
        print(f"  {label:<32}{a[key]:>8,}  {100 * a[key] / total:>5.1f}%{note}")
    print("=" * 58)
    hidden = a["mailable"] - a["safe_send"]
    print(f"  suppression removes {hidden:,} that a plain --mailable segment "
          f"would have included\n")
    print("SUPPRESSED CONTACTS BY TAG")
    print("-" * 58)
    for tag, n in sending.suppression_breakdown(client):
        if n:
            print(f"  {n:>7,}  {tag}")


def cmd_sendlist(client: GHLClient, args) -> int | None:
    if args.tier == "validated" and not sending.validation_data_available(client):
        # Refuse rather than export an empty file. A zero-row send list reads as
        # "nobody qualified" when the truth is that the field it filters on has
        # no data, and the two call for opposite responses.
        print("error: --tier validated filters on validEmail, and no contact in this\n"
              "       location has validEmail == true, so the tier matches nothing.\n"
              "       GHL sets validEmail only after it has sent to an address; that\n"
              "       history is absent here. Use --tier engaged, or --tier safe.",
              file=sys.stderr)
        return 1
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
    if not sending.validation_data_available(client):
        print()
        print("  note: 'already recorded bad' comes from validEmail, which is not")
        print("        populated in this location. A near-zero figure here means GHL")
        print("        has no delivery history to answer with, not that the candidate")
        print("        list is clean -- expect the verifier to find bad addresses.")
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


def cmd_weekly(client: GHLClient, args) -> int | None:
    rows = weekly.plan(client, args.event, reminders=args.reminders)
    print(f"SEND PLAN for event {args.event!r}")
    print("=" * 58)
    print(f"  {'slot':<22}{'track':<8}{'recipients':>12}")
    print("-" * 58)
    failed = False
    for slot, track, n, err in rows:
        label = {"A": "A reg", "B": "B unreg", "-": "post"}[track]
        if n >= 0:
            print(f"  {slot:<22}{label:<8}{n:>12,}")
        else:
            failed = True
            print(f"  {slot:<22}{label:<8}{'FAILED':>12}   {err}")
    print("-" * 58)
    if failed:
        print("  a slot failed to count and would be skipped by an export; fix that")
        print("  before relying on this plan\n")
        return 1
    if not args.out_dir:
        print("  pass --out-dir to export one CSV per slot")
        return

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    seen: dict[str, str] = {}
    for slot, track, n, _err in rows:
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
        return args.func(GHLClient(), args) or 0
    except GHLError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
