#!/usr/bin/env python3
"""Render selected templates into one page for pasting into the classic builder.

The classic builder is a rich-text editor, so hyperlinks and bold survive a
copy-paste from a rendered browser page but not from plain text. This writes
each email exactly as it should look, with the one-click link live and the
emphasis applied, plus the subject and preview text to fill in beside it.

Bodies come from build_week1_templates.EMAILS rather than being retyped here, so
the classic-builder copy cannot drift from what the code builder is sending --
which is the whole point when the two are being compared.

    python3 make_paste_sheet.py --key W1-A4-Thu8am-NotReg --key W1-A5-ThuNoon-NotReg
    python3 make_paste_sheet.py --thursday --out paste-sheet.html
"""

from __future__ import annotations

import argparse
import html as htmlmod
from pathlib import Path

from build_week1_templates import EMAILS, ONE_CLICK, FALLBACK
from build_replay_emails import EMAILS as REPLAY_EMAILS

EMAILS = EMAILS + REPLAY_EMAILS
SEND_TIMES_EXTRA = {e["key"]: e["send"] for e in REPLAY_EMAILS}

THURSDAY = ["W1-A4-Thu8am-NotReg", "W1-A5-ThuNoon-NotReg", "W1-A6-Thu145-NotReg"]
REPLAY = ["R1-Wed-ReplayReady", "R2-Thu-MissedIt", "R3-Fri-ComingDown",
          "R4-Sat-OneIdea", "R5-Sun-LastCall", "R6-Sun-FinalHours"]

SEND_TIMES = {
    "W1-A4-Thu8am-NotReg": "Thursday 8:00 AM PT",
    "W1-A5-ThuNoon-NotReg": "Thursday 12:30 PM PT",
    "W1-A6-Thu145-NotReg": "Thursday 1:45 PM PT",
}

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Paste sheet &mdash; Thursday webinar emails</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
         line-height: 1.55; color: #1a1a1a; max-width: 820px;
         margin: 0 auto; padding: 32px 20px 80px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: #666; font-size: 14px; margin: 0 0 28px; }}
  .how {{ background: #f6f8fa; border: 1px solid #d8dee4; border-radius: 8px;
          padding: 14px 18px; font-size: 14px; margin: 0 0 34px; }}
  .how ol {{ margin: 8px 0 0; padding-left: 22px; }}
  .card {{ border: 1px solid #d8dee4; border-radius: 10px; margin: 0 0 34px;
           overflow: hidden; }}
  .head {{ background: #f6f8fa; border-bottom: 1px solid #d8dee4;
           padding: 14px 18px; font-size: 14px; }}
  .head .when {{ font-weight: 600; color: #0a5; text-transform: uppercase;
                 letter-spacing: .04em; font-size: 12px; }}
  .field {{ margin-top: 8px; }}
  .field b {{ display: inline-block; min-width: 96px; color: #555;
              font-weight: 600; }}
  .val {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          background: #fff; border: 1px solid #d8dee4; border-radius: 4px;
          padding: 2px 7px; font-size: 13px; }}
  .bodywrap {{ padding: 6px 18px 18px; }}
  .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .06em;
            color: #888; margin: 14px 0 2px; }}
  .urls {{ font-size: 13px; }}
  .urls code {{ display: block; background: #f6f8fa; border: 1px solid #d8dee4;
                border-radius: 6px; padding: 10px 12px; margin: 6px 0 14px;
                word-break: break-all; font-size: 12px; }}
</style>

<h1>Thursday webinar emails &mdash; paste sheet</h1>
<p class="sub">Rendered from the same source as the code-builder templates, so
the two versions cannot drift apart.</p>

<div class="how">
  <strong>To paste into the classic builder:</strong>
  <ol>
    <li>Select the email body below &mdash; from &ldquo;Hey&rdquo; down to the
        last grey line &mdash; and copy it.</li>
    <li>Paste into a text block in the classic builder. Links and bold carry
        over; the merge fields stay as literal text.</li>
    <li>Copy the subject and preview text from the header into their own fields.</li>
    <li><strong>Turn tracking off</strong> before scheduling, or the one-click
        link gets rewritten and mangled.</li>
    <li>Re-pull the audience so the {registered} people already registered drop out.</li>
  </ol>
</div>

{cards}

<div class="urls">
  <p class="label">one-click url &mdash; text link and button</p>
  <code>{one_click}</code>
  <p class="label">fallback url &mdash; small grey line only</p>
  <code>{fallback}</code>
  <p class="label">button</p>
  <code>background #16a34a &middot; white text &middot; 15px 30px padding &middot; 6px radius</code>
</div>
"""

CARD = """<div class="card">
  <div class="head">
    <div class="when">{when}</div>
    <div class="field"><b>Subject</b> <span class="val">{subject}</span></div>
    <div class="field"><b>Preview</b> <span class="val">{preview}</span></div>
  </div>
  <div class="bodywrap">{body}</div>
</div>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", action="append", help="template key (repeatable)")
    ap.add_argument("--thursday", action="store_true", help="the three Thursday sends")
    ap.add_argument("--replay", action="store_true", help="the six replay-chase sends")
    ap.add_argument("--registered", type=int, default=51,
                    help="how many are already registered, for the reminder")
    ap.add_argument("--out", default="paste-sheet.html")
    args = ap.parse_args()

    keys = list(args.key or [])
    if args.replay:
        keys = REPLAY
    elif args.thursday or not keys:
        keys = THURSDAY
    by_key = {e["key"]: e for e in EMAILS}

    missing = [k for k in keys if k not in by_key]
    if missing:
        raise SystemExit(f"unknown key(s): {', '.join(missing)}")

    cards = []
    for k in keys:
        e = by_key[k]
        cards.append(CARD.format(
            when={**SEND_TIMES, **SEND_TIMES_EXTRA}.get(k, k),
            subject=htmlmod.escape(e["subject"]),
            preview=htmlmod.escape(e.get("preview", "")),
            body=e["body"],
        ))

    Path(args.out).write_text(PAGE.format(
        cards="\n".join(cards),
        one_click=htmlmod.escape(ONE_CLICK),
        fallback=htmlmod.escape(FALLBACK),
        registered=args.registered,
    ), encoding="utf-8")
    print(f"wrote {args.out} ({len(keys)} email(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
