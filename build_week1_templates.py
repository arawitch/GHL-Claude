#!/usr/bin/env python3
"""Create Week 1 webinar email templates in GoHighLevel.

Creating a template takes two calls: POST /emails/builder makes a shell (the
html passed there is discarded), then PATCH /emails/builder/{id} stores the
body under editorContent. editorType is required on the PATCH or it 422s.

Run with --apply to write. Without it, nothing is created and the HTML is
written to ./week1-preview/ so the copy can be read before it reaches GHL.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ghl.client import GHLClient, GHLError

# Phone parameters are deliberately absent. GoHighLevel stores phone in E.164
# ("+15612297055"), while WebinarJam wants the country code and number in
# separate fields -- and a raw "+" in a query string decodes as a space. The
# tested registration worked without them.
ONE_CLICK = (
    "https://event.webinarjam.com/gyywz/register/088v6bgy/1click"
    "?first_name={{contact.first_name}}"
    "&last_name={{contact.last_name}}"
    "&email={{contact.email}}"
    "&timezone=GMT-7"
    "&schedule_id=1"
)
FALLBACK = "https://event.webinarjam.com/gyywz/register/088v6bgy"

SALES_LINK = "https://go.universityofoptions.com/buy"
BOOK_CALL = "{{BOOK_CALL_LINK}}"      # replace: booking calendar URL
REPLAY_LINK = "{{REPLAY_LINK}}"       # replace: WebinarJam replay URL

CSS = (
    "font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;"
    "font-size:16px;line-height:1.6;color:#222;max-width:600px;margin:0 auto;padding:24px;"
)


def html(body: str, cta: str | None = None, fallback: bool = False) -> str:
    parts = [f'<div style="{CSS}">', body]
    if cta:
        parts.append(
            f'<p style="margin:28px 0;"><a href="{cta}" '
            'style="background:#16a34a;color:#fff;padding:15px 30px;font-weight:600;'
            'border-radius:6px;text-decoration:none;display:inline-block;">'
            'Reserve My Seat</a></p>'
        )
    if fallback:
        parts.append(
            f'<p style="font-size:14px;color:#666;">If that button doesn\'t work, '
            f'<a href="{FALLBACK}">register here instead</a>.</p>'
        )
    parts.append("</div>")
    return "\n".join(parts)


P = "<p>%s</p>"
SIGN = "<p>Dan</p>"

EMAILS: list[dict] = [
    # ---------------- Track A: not registered ----------------
    dict(key="W1-A1-Mon-NotReg", subject="The best trade you'll ever make never happens",
         audience="current email list  MINUS  7/30 register, verified bad, buyer tags",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "Most traders start their day asking one question.",
             P % "<strong>&ldquo;What should I trade today?&rdquo;</strong>",
             P % "Ironically, that&rsquo;s the wrong question.",
             P % "Every morning before our team ever considers placing a trade, we&rsquo;re actually looking for reasons <em>not</em> to trade.",
             P % "That probably sounds backwards.",
             P % "But over the years I&rsquo;ve learned that consistency doesn&rsquo;t come from finding more opportunities. It comes from having the discipline to ignore the ones that don&rsquo;t deserve your capital.",
             P % "The market gives us dozens of charts to look at every day. Most never become trades. And that&rsquo;s by design.",
             P % "This Thursday at 2 PM Pacific, I&rsquo;m hosting a free live training where I&rsquo;ll show you why we skip roughly 95% of the setups we evaluate and the roadmap we use to decide when a trade is actually worth taking.",
             P % "If you&rsquo;ve ever felt like you&rsquo;re constantly chasing the market or wondering if you&rsquo;re forcing trades, I think you&rsquo;ll get a lot out of this session.",
         ]), cta=ONE_CLICK, fallback=True) + SIGN),

    dict(key="W1-A2-Tue-NotReg", subject="I learned this lesson the hard way",
         audience="current email list  MINUS  7/30 register, verified bad, buyer tags",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "Years ago, long before University of Options became what it is today, I made a mistake that completely changed the way I think about trading.",
             P % "I found myself on the wrong side of the market.",
             P % "Instead of accepting that the market wasn&rsquo;t doing what I expected, I spent too much time trying to make the trade work.",
             P % "Looking back, the biggest mistake wasn&rsquo;t the losing trade. It was believing I had to prove I was right.",
             P % "The market doesn&rsquo;t care about your opinion. Your job isn&rsquo;t to predict what should happen. It&rsquo;s to recognise when the odds are in your favour and have the discipline to do nothing when they aren&rsquo;t.",
             P % "Today our team passes on the overwhelming majority of setups we look at. Not because we don&rsquo;t like trading &mdash; because every dollar you don&rsquo;t lose is a dollar you don&rsquo;t have to earn back.",
             P % "This Thursday I&rsquo;ll show you exactly how we decide when a trade deserves our attention and, more importantly, when it doesn&rsquo;t.",
         ]), cta=ONE_CLICK, fallback=True) + SIGN),

    dict(key="W1-A3-Wed-NotReg", subject="The market pays you for discipline",
         audience="current email list  MINUS  7/30 register, verified bad, buyer tags",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "One of the biggest misconceptions in trading is that productive traders are always busy.",
             P % "The reality is almost the opposite.",
             P % "Professional traders spend far more time waiting than trading. They are patient. They are selective. They are willing to sit on their hands until everything lines up.",
             P % "The market doesn&rsquo;t reward activity. It rewards discipline.",
             P % "Some of the best trading days you&rsquo;ll ever have are the days you decide not to trade at all.",
             P % "Tomorrow I&rsquo;m going to walk through the exact roadmap we use before risking a dollar in the market. You&rsquo;ll see why we ignore most setups and what has to line up before we ever click Buy or Sell.",
         ]), cta=ONE_CLICK, fallback=True) + SIGN),

    dict(key="W1-A4-Thu8am-NotReg", subject="Today's the day",
         audience="current email list  MINUS  7/30 register, verified bad, buyer tags",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "Today&rsquo;s the day. We go live at 2 PM Pacific.",
             P % "Bring a notebook.",
             P % "I&rsquo;m going to show you the exact framework we use before risking a dollar in the market, and why saying no is often the most profitable decision a trader can make.",
             P % "If you haven&rsquo;t reserved your seat yet, there&rsquo;s still time.",
         ]), cta=ONE_CLICK, fallback=True) + SIGN),

    dict(key="W1-A5-Thu1pm-NotReg", subject="We start in one hour",
         audience="current email list  MINUS  7/30 register, verified bad, buyer tags",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "We&rsquo;re going live in one hour.",
             P % "If you&rsquo;ve been thinking about joining us, I&rsquo;d love to have you there. This training could change the way you think about trading.",
             P % "There&rsquo;s still time to grab your seat.",
         ]), cta=ONE_CLICK, fallback=True) + SIGN),

    # ---------------- Track B: registered ----------------
    dict(key="W1-B1-WedAM-Registered", subject="One thing to think about before tomorrow",
         audience="7/30 register  MINUS  verified bad",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "Looking forward to seeing you tomorrow.",
             P % "Before we meet, I want you to think about one question.",
             P % "<strong>How many trades have you taken simply because you wanted to be in a trade?</strong>",
             P % "It&rsquo;s something almost every trader struggles with.",
             P % "Tomorrow I&rsquo;ll show you why our first objective each morning isn&rsquo;t finding a trade. It&rsquo;s finding a reason not to trade.",
             P % "I think you&rsquo;ll see the market a little differently afterward.",
             P % "See you tomorrow at 2 PM Pacific.",
         ])) + SIGN),

    # ---------------- Track C: attended ----------------
    dict(key="W1-C1-ThuPM-Attended", subject="Thanks for joining me today",
         audience="7/30 attended",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "Thank you for spending part of your afternoon with me.",
             P % "If there&rsquo;s one idea I hope sticks with you, it&rsquo;s this.",
             P % "<strong>The market pays you for discipline. Not activity.</strong>",
             P % "Everything we do at University of Options is built around that philosophy.",
             P % "If you&rsquo;re ready to stop guessing and start following a repeatable roadmap, I&rsquo;d love to help.",
             P % f'<a href="{SALES_LINK}">Learn more about Options Navigator and the Spread Trade Bot</a>',
             P % "I appreciate you being there today.",
             P % f'<span style="font-size:14px;color:#666;">P.S. If you&rsquo;d rather talk through your goals first, you can <a href="{BOOK_CALL}">schedule a call with our team</a>.</span>',
         ])) + SIGN),

    dict(key="W1-C2-Fri-Attended", subject="One last thought",
         audience="7/30 attended",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "The hardest part about becoming a better trader usually isn&rsquo;t learning another strategy.",
             P % "It&rsquo;s building the discipline to follow one consistently.",
             P % "That&rsquo;s exactly what we try to help our members do every day.",
             P % f'If you&rsquo;re ready for the next step, <a href="{SALES_LINK}">you can learn more here</a>.',
             P % "I hope to see you inside.",
         ])) + SIGN),

    # ---------------- Track D: registered, did not attend ----------------
    dict(key="W1-D1-ThuPM-NoShow", subject="Sorry we missed you",
         audience="7/30 absent  MINUS  7/30 attended",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "Sorry we missed you today.",
             P % "One sentence from today&rsquo;s training has been stuck in my head.",
             P % "<strong>The market pays you for discipline. Not activity.</strong>",
             P % "That idea changes everything.",
             P % f'If you have some time this evening or tomorrow morning, I really hope you&rsquo;ll <a href="{REPLAY_LINK}">watch the replay</a>.',
             P % f'After you&rsquo;ve watched it, if you&rsquo;d like help applying that roadmap to your own trading, <a href="{SALES_LINK}">you can learn more here</a>.',
             P % "Enjoy the replay.",
         ])) + SIGN),

    dict(key="W1-D2-Fri-NoShow", subject="Last chance to watch",
         audience="7/30 absent  MINUS  7/30 attended, 7/30 replay",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "Just a quick reminder before we take the replay down.",
             P % "If you only remember one thing from this week&rsquo;s training, let it be this.",
             P % "<strong>The best trade you&rsquo;ll ever make is often the one you never take.</strong>",
             P % "That single mindset shift has saved me far more money than any indicator ever has.",
             P % f'<a href="{REPLAY_LINK}">You can still watch the replay here</a>.',
             P % "I hope you enjoy it.",
         ])) + SIGN),

    # ---------------- Weekend: the offer deadline ----------------
    dict(key="W1-E1-Sat-Deadline", subject="This closes tomorrow night",
         audience="7/30 attended + 7/30 absent  MINUS  buyer tags, verified bad",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "Quick note about something I mentioned on Thursday.",
             P % "The pricing we opened up during the training closes <strong>tomorrow at midnight</strong>. After that it goes back to standard.",
             P % "I&rsquo;m not going to pretend that&rsquo;s a reason to join. If the approach doesn&rsquo;t fit how you want to trade, a deadline shouldn&rsquo;t change your mind.",
             P % "But if you&rsquo;ve been sitting on the fence &mdash; if the part about skipping 95% of setups landed, and you&rsquo;d like a roadmap rather than a strategy &mdash; this is the window.",
             P % f'<a href="{SALES_LINK}">Here&rsquo;s everything that&rsquo;s included</a>.',
             P % f'<span style="font-size:14px;color:#666;">Still deciding? <a href="{BOOK_CALL}">Book a call</a> and we&rsquo;ll talk it through honestly.</span>',
         ])) + SIGN),

    dict(key="W1-E2-Sun-Deadline", subject="Closes at midnight",
         audience="7/30 attended + 7/30 absent  MINUS  buyer tags, verified bad",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "Last note on this, then I&rsquo;ll leave you alone about it.",
             P % "The pricing from Thursday&rsquo;s training closes tonight at midnight.",
             P % "Here&rsquo;s the honest version: what we teach isn&rsquo;t a shortcut. It&rsquo;s a process, and following it takes more patience than most people expect. That&rsquo;s exactly why it works.",
             P % "If that&rsquo;s the kind of trading you want to build, we&rsquo;d like to help you build it.",
             P % f'<a href="{SALES_LINK}">Join before midnight</a>',
             P % "Either way, I&rsquo;ll see you Thursday. We do this every week.",
         ])) + SIGN),
]


def create(client: GHLClient, item: dict) -> str:
    made = client.request("POST", "/emails/builder", json={
        "locationId": client.location_id,
        "type": "html",
        "title": item["key"],
        "name": item["key"],
    })
    tid = made["id"]
    # The html sent above is discarded; the body only lands via PATCH.
    client.request("PATCH", f"/emails/builder/{tid}", json={
        "locationId": client.location_id,
        "templateId": tid,
        "name": item["key"],
        "updatedBy": "api",
        "editorType": "html",
        "editorContent": item["body"],
        "previewText": item["subject"],
        "importProvider": None,
    })
    return tid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="create them in GHL")
    args = ap.parse_args()

    if not args.apply:
        out = Path("week1-preview")
        out.mkdir(exist_ok=True)
        print(f"{'template':<26}{'subject':<46}audience")
        print("-" * 118)
        for e in EMAILS:
            (out / f"{e['key']}.html").write_text(e["body"], encoding="utf-8")
            print(f"{e['key']:<26}{e['subject'][:44]:<46}{e['audience']}")
        print(f"\n{len(EMAILS)} templates written to {out}/ -- re-run with --apply to create in GHL")
        return 0

    client = GHLClient()
    for e in EMAILS:
        try:
            tid = create(client, e)
            print(f"  created {e['key']:<26} {tid}")
        except GHLError as exc:
            print(f"  FAILED  {e['key']:<26} {str(exc)[:120]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
