#!/usr/bin/env python3
"""Replay-click follow-up campaign: five emails and five SMS.

Audience: contacts tagged `clicked 7/31 replay` (81 in the main location, and
the same 81 mirrored into the SMS sub-account). Deadline: Sunday midnight.

--------------------------------------------------------------------------
What is and is not built here
--------------------------------------------------------------------------
Email templates are created in GoHighLevel. **SMS templates cannot be** -- the
API exposes no snippet or SMS-template endpoint (`/snippets`, `/templates`,
`/sms/templates` all 404), so the SMS bodies below have to be pasted into the
workflow steps by hand. They are kept here anyway so both channels stay in one
place and cannot drift apart.

The workflow itself also has to be built in the UI: workflow create/update is
not in the public API at all. The two exit conditions the campaign needs are
listed in EXIT_CONDITIONS below.

--------------------------------------------------------------------------
Subject selection
--------------------------------------------------------------------------
Each day came with several options. The one chosen is the one closest to the
shape that measured best in this account's archive: subjects that state
logistics or a deadline outperformed persuasive ones, with "The replay is
ready" at 39.3% open and "Starting in one hour" at 37.0% against 18-24% for
benefit-led subjects. So the two deadline days take the flattest wording
available, and the alternates are kept for A/B testing rather than discarded.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ghl.client import GHLClient, GHLError

# A GHL trigger link. It resolves to the tracked destination at send time, and
# works as an href value as well as bare text.
CTA = "{{trigger_link.l5C7oQ9aKzxO8oti1sfr}}"

EXIT_CONDITIONS = [
    "Remove from workflow when the contact purchases (goal event / 'purchased' tag).",
    "Remove from workflow when an appointment is booked, and add them to the "
    "appointment follow-up instead -- otherwise a booked call keeps receiving "
    "deadline pressure.",
    "Remove anyone who unsubscribes or replies STOP (SMS opt-out is automatic, "
    "email is not).",
]

CSS = ("font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;"
       "font-size:16px;line-height:1.6;color:#222;max-width:600px;margin:0 auto;padding:24px;")
P = "<p>%s</p>"
SIGN = "<p>Dan</p>"


def html(body: str, ps: str | None = None, label: str = "Review The Program") -> str:
    parts = [f'<div style="{CSS}">', body, SIGN]
    if ps:
        parts.append(P % f"<strong>P.S.</strong> {ps}")
    parts.append(
        f'<p style="margin:28px 0;"><a href="{CTA}" '
        'style="background:#16a34a;color:#fff;padding:15px 30px;font-weight:600;'
        f'border-radius:6px;text-decoration:none;display:inline-block;">{label}</a></p>')
    parts.append("</div>")
    return "\n".join(parts)


def link(text: str) -> str:
    return P % f'<a href="{CTA}">{text}</a>'


def tight(*rows: str) -> str:
    return "".join(f'<p style="margin:0;">{r}</p>' for r in rows)


EMAILS: list[dict] = [
    dict(key="RC1-Thu-SawYouWatched",
         send="Thursday",
         subject="Saw you checked out the replay",
         alternates=["We extended the offer", "Did you get a chance to watch?",
                     "A quick follow-up"],
         preview="If you had a chance to watch the training, I wanted to make sure "
                 "you knew the promotion was extended.",
         sms="Dan here. I saw you checked out the replay from this week's training. "
             "I also wanted to let you know that we extended the current UOO promotion "
             f"through Sunday. You can review everything or book a call here: {CTA}\n"
             "Reply STOP to opt out.",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "I saw you checked out the replay from this week&rsquo;s training.",
             P % "Hopefully you had a chance to spend some time with it.",
             P % "If you did, you saw that our approach to trading isn&rsquo;t built around constantly searching for more opportunities.",
             P % "It&rsquo;s built around having a clear process for deciding which trades are actually worth taking.",
             P % "I also wanted to make sure you knew that we decided to extend the current University of Options promotion through <strong>Sunday at midnight</strong>.",
             P % "You can use the page below to review everything included, enroll directly, or book a call with our team if you still have questions.",
             link("Review the program or book a call here"),
             P % "If it feels like the right fit, we&rsquo;d love to have you.",
         ]),
             ps="If you checked out the replay but haven&rsquo;t had time to finish "
                "it yet, that&rsquo;s completely fine. The page above will give you a "
                "full breakdown of the program and a place to speak with our team.")),

    dict(key="RC2-Fri-RulesArentEnough",
         send="Friday",
         subject="Knowing the rules isn't enough",
         alternates=["The checklist is the easy part", "This is where traders get stuck",
                     "You need more than a strategy"],
         preview="Knowing what to do and consistently doing it are two completely "
                 "different things.",
         sms="Knowing the trading rules and consistently following them are two "
             "different things. UOO is built around structure, coaching and "
             f"accountability, not just another strategy. The extended offer ends Sunday: {CTA}\n"
             "Reply STOP to opt out.",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "If you had a chance to watch the replay, you heard me talk about the questions we ask before putting capital at risk.",
             P % "But knowing the questions is only the beginning.",
             P % "Most traders already know they shouldn&rsquo;t chase trades.",
             tight(
                 "They know they need risk management.",
                 "They know they shouldn&rsquo;t force setups.",
                 "They know they shouldn&rsquo;t suddenly increase their position size after one good day.",
             ),
             P % "The hard part is consistently following those rules when money and emotion are involved.",
             P % "That&rsquo;s why University of Options isn&rsquo;t built around one indicator or one strategy.",
             P % "It&rsquo;s built around structure.",
             P % "Inside Options Navigator, you get daily live trading, education, charting tools, weekly coaching, trade ideas, tracking resources, and a community focused on following a repeatable process.",
             P % "The current promotion has been extended through <strong>Sunday at midnight</strong>.",
             link("Review everything included or book a call here"),
         ]),
             ps="You don&rsquo;t need to have everything figured out before joining. "
                "If you&rsquo;re unsure whether the program fits your experience "
                "level, book a call and let us help you work through it.")),

    dict(key="RC3-Sat-ExpensiveMistakes",
         send="Saturday",
         subject="Learn from my expensive mistakes",
         alternates=["You could figure this out alone", "The long way or the shorter way",
                     "This took me years to learn"],
         preview="You can learn trading on your own, but there is a real cost to "
                 "figuring everything out through trial and error.",
         sms="Trading can be learned through years of trial and error, but those "
             "lessons can get expensive. If you're considering UOO, the extended "
             f"promotion ends tomorrow. Review everything or book a call here: {CTA}\n"
             "Reply STOP to opt out.",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "There&rsquo;s something from the training that I think is worth repeating.",
             P % "<strong>It&rsquo;s better to learn from someone else&rsquo;s expensive mistakes than to make every one of them yourself.</strong>",
             P % "Could you learn trading on your own?",
             P % "Absolutely.",
             P % "But there&rsquo;s a cost to trial and error.",
             tight(
                 "Bad trades cost money.",
                 "Confusing strategies cost time.",
                 "Emotional decisions can cost confidence.",
             ),
             P % "It took me years to develop the process we now teach inside University of Options.",
             P % "The goal isn&rsquo;t to remove the work. The goal is to give you a clearer path.",
             tight(
                 "Instead of wondering which charts to use, you can use ours.",
                 "Instead of guessing whether a setup is worth taking, you can watch us make those decisions live.",
                 "Instead of wondering how much risk to take or when to scale, you can build a structured plan.",
             ),
             P % "<strong>Tomorrow is the final day</strong> of the extended promotion.",
             link("See everything included, enroll, or book a call here"),
         ]),
             ps="Don&rsquo;t join because trading sounds exciting today. Join because "
                "you&rsquo;re ready to approach it with more discipline and structure "
                "tomorrow.")),

    dict(key="RC4-SunAM-EndsTonight",
         send="Sunday morning",
         subject="Extended pricing ends tonight",
         alternates=["Today is the final day", "Before midnight tonight",
                     "Last day to join at this price", "A decision for you to make"],
         preview="We extended the promotion through the weekend, but it ends tonight "
                 "at midnight.",
         sms="Quick reminder from Dan. We extended the UOO promotion through the "
             "weekend, but it ends tonight at midnight. You can review the program, "
             f"enroll or book a call here: {CTA}\nReply STOP to opt out.",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "Just a quick reminder.",
             P % "We extended the current University of Options promotion through the weekend.",
             P % "That extension ends <strong>tonight at midnight</strong>.",
             P % "If you checked out the replay and have been thinking about joining us, today&rsquo;s the day to make a decision.",
             P % "That doesn&rsquo;t mean everyone should join.",
             P % "But if you&rsquo;re serious about trading and what you&rsquo;ve been missing is a roadmap, structure, tools, and experienced traders to learn from, that&rsquo;s exactly what University of Options was designed to provide.",
             link("Review everything included here"),
             P % "If you&rsquo;re ready, you can enroll directly. If you still have questions, scroll down and schedule a call with our team.",
             P % "Don&rsquo;t let an unanswered question make the decision for you.",
         ]),
             ps=f'The extended pricing expires at midnight tonight. You can '
                f'<a href="{CTA}">review the program, enroll, or book a call here</a>.')),

    dict(key="RC5-SunPM-Midnight",
         send="Sunday evening",
         subject="Ends at midnight",
         alternates=["A few hours left", "Final reminder", "Last call",
                     "Before I sign off"],
         preview="Just making sure the extended deadline doesn't slip through the cracks.",
         sms="Final heads up. The extended UOO promotion ends at midnight tonight. "
             f"If you're ready, you can enroll or book a call here: {CTA}\n"
             "Reply STOP to opt out.",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "I&rsquo;ll keep this short.",
             P % "The extended University of Options promotion ends at <strong>midnight tonight</strong>.",
             P % "If you checked out the replay, reviewed the program, and decided you&rsquo;re ready to take the next step, you can join us here:",
             link("Enroll or book a call"),
             P % "Still have a question? You can also use that page to book a call with our team.",
             P % "That&rsquo;s it. Hope to see you inside.",
         ]), label="Join Before Midnight")),
]


def segments(text: str) -> tuple[int, int]:
    """(characters, SMS segments). GSM-7 splits at 160, then 153 per part."""
    n = len(text)
    return n, 1 if n <= 160 else -(-n // 153)


def patch(client: GHLClient, tid: str, item: dict) -> None:
    client.request("PATCH", f"/emails/builder/{tid}", json={
        "locationId": client.location_id, "templateId": tid,
        "name": item["key"], "updatedBy": "api", "editorType": "html",
        "editorContent": item["body"], "previewText": item["preview"],
        "importProvider": None,
    })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sms-location", action="store_true",
                    help="build in the TEXT sub-account, which is where this "
                         "campaign sends from")
    args = ap.parse_args()

    if not args.apply:
        out = Path("followup-preview")
        out.mkdir(exist_ok=True)
        print(f"{'template':<26}{'send':<18}{'chars':>6}{'segs':>6}  subject")
        print("-" * 100)
        for e in EMAILS:
            (out / f"{e['key']}.html").write_text(e["body"], encoding="utf-8")
            n, seg = segments(e["sms"])
            print(f"{e['key']:<26}{e['send']:<18}{n:>6}{seg:>6}  {e['subject']}")
        print(f"\n{len(EMAILS)} written to {out}/ -- re-run with --apply")
        print("\nchars/segs are for the SMS body, which the API cannot create.")
        return 0

    if args.sms_location:
        token, location = os.environ.get("GHL_SMS_API_KEY"), os.environ.get("GHL_SMS_LOCATION_ID")
        if not token or not location:
            print("GHL_SMS_API_KEY and GHL_SMS_LOCATION_ID must be set", file=sys.stderr)
            return 1
        client = GHLClient(token=token, location_id=location)
    else:
        client = GHLClient()
    try:
        existing = {t.get("name"): t["id"] for t in client.email_templates(limit=100)}
    except GHLError as exc:
        if "not authorized for this scope" in str(exc):
            # The TEXT sub-account token ships with contacts scope only. The
            # campaign sends from that location, so the templates have to live
            # there -- but they cannot be written until the scope is widened.
            print("This token cannot read or write email templates.\n"
                  "Add these scopes to the private integration token for this\n"
                  "location, then re-run:\n"
                  "    emails/builder.readonly\n"
                  "    emails/builder.write\n"
                  "    links.readonly        (to verify the trigger link)",
                  file=sys.stderr)
            return 1
        raise
    for e in EMAILS:
        try:
            tid = existing.get(e["key"])
            if not tid:
                tid = client.request("POST", "/emails/builder", json={
                    "locationId": client.location_id, "type": "html",
                    "title": e["key"], "name": e["key"]})["id"]
                verb = "created"
            else:
                verb = "updated"
            patch(client, tid, e)
            print(f"  {verb} {e['key']:<26} {tid}")
        except GHLError as exc:
            print(f"  FAILED {e['key']}: {str(exc)[:110]}", file=sys.stderr)
    print("\n  SMS bodies are not created -- no API endpoint. Paste them into the")
    print("  workflow steps from the paste sheet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
