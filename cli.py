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
import sys

from ghl.client import GHLClient, GHLError
from ghl import segments, sending


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
          "   (has email, not DND)")
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
