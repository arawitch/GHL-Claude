#!/usr/bin/env python3
"""Create or update Week 1 webinar email templates in GoHighLevel.

Creating a template takes two calls: POST /emails/builder makes a shell (the
html passed there is discarded), then PATCH /emails/builder/{id} stores the
body under editorContent. editorType is required on the PATCH or it 422s.

Run with --apply to write. Without it, nothing is created and the HTML is
written to ./week1-preview/ so the copy can be read before it reaches GHL.
--apply is idempotent: it matches existing templates by name (or old_key, for
ones that have been renamed) and PATCHes them in place rather than duplicating.

--------------------------------------------------------------------------
Why the Track A copy reads the way it does
--------------------------------------------------------------------------
The first draft of these emails was abstract -- "the market pays you for
discipline", "the best trade you'll ever make never happens" -- and clicked at
0.07-0.13%. Their seven highest-clicking webinar invites were pulled from the
send archive and share a skeleton that the first draft had none of:

  1. "Hey {{contact.first_name}}," -- never "Hi".
  2. The problem is stated as an observable market condition, not a maxim.
     "One headline comes out... SPY rips."  Not "the market rewards patience."
  3. A recognition list in second person, one fragment per line:
     "You wait too long. / You enter too early. / You chase the move."
  4. "Sound familiar?" -- an explicit question, early.
  5. A bulleted "I'll walk you through:" list of what the session covers.
  6. TWO calls to action: an inline text link mid-body, then a P.S. carrying a
     second one. Every top performer has the P.S.; the first draft had none.
  7. The time is in the subject line: "Tomorrow at 2:", "Will you be joining
     at 2?", "Going live in 15 mins".

Worth stating plainly, because it cuts against a warning made earlier: these
winners contain **no performance figures at all**. The "5 trades. 5 wins."
subject lines belong to daily recap sends to a ~3,100 list, not to the webinar
invites that carry the 11-23% campaign click rates. So the format that works
for this audience can be copied without importing the earnings-claim problem
flagged against slides 21-22 -- there is no trade-off to make here.
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


def html(body: str, cta: str | None = None, fallback: bool = False,
         ps: str | None = None) -> str:
    """Assemble one email.

    Order matters and is taken from their top performers: body, sign-off, name,
    P.S., CTA, fallback. An earlier version appended the name after the whole
    block, which left "Dan" orphaned below the "if that button doesn't work"
    line -- signing the disclaimer rather than the email.
    """
    parts = [f'<div style="{CSS}">', body, SIGN]
    if ps:
        parts.append(P % f"<strong>P.S.</strong> {ps}")
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

# One fragment per line, as in the originals. <p> with no margin between them
# reads as the staccato block their top performers use.
TIGHT = 'style="margin:0;"'


def lines(*rows: str) -> str:
    """A recognition list: short second-person fragments, tightly stacked."""
    return "".join(f"<p {TIGHT}>{r}</p>" for r in rows)


def bullets(*rows: str) -> str:
    return "<ul>" + "".join(f"<li>{r}</li>" for r in rows) + "</ul>"


def inline(text: str) -> str:
    """Mid-body text CTA. Every top performer has one of these above the P.S."""
    return P % f'<a href="{ONE_CLICK}">{text}</a>'


EMAILS: list[dict] = [
    # ---------------- Track A: not registered ----------------
    # A1 and A2 have already sent. Left here for the record; --apply will
    # update them in place, which is harmless but changes nothing that shipped.
    dict(key="W1-A1-Mon-NotReg", subject="The best trade you'll ever make never happens",
         preview="Why we look for reasons not to trade",
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
         ]), cta=ONE_CLICK, fallback=True)),

    dict(key="W1-A2-Tue-NotReg", subject="I learned this lesson the hard way",
         preview="The trade that changed how I think about being right",
         audience="current email list  MINUS  7/30 register, verified bad, buyer tags",
         body=html("".join([
             P % "Hi {{contact.first_name}},",
             P % "Years ago, long before University of Options became what it is today, I made a mistake that completely changed the way I think about trading.",
             P % "I found myself on the wrong side of the market.",
             P % "Instead of accepting that the market wasn&rsquo;t doing what I expected, I spent too much time trying to make the trade work.",
             P % "Looking back, the biggest mistake wasn&rsquo;t the losing trade. It was believing I had to prove I was right.",
             P % "The market doesn&rsquo;t care about your opinion. Your job isn&rsquo;t to predict what should happen. It&rsquo;s to recognize when the odds are in your favour and have the discipline to do nothing when they aren&rsquo;t.",
             P % "Today our team passes on the overwhelming majority of setups we look at. Not because we don&rsquo;t like trading &mdash; because every dollar you don&rsquo;t lose is a dollar you don&rsquo;t have to earn back.",
             P % "This Thursday I&rsquo;ll show you exactly how we decide when a trade deserves our attention and, more importantly, when it doesn&rsquo;t.",
         ]), cta=ONE_CLICK, fallback=True)),

    # ---- A3 onward: rebuilt on the structure of the top-clicking invites ----

    # Modelled on "Tomorrow at 2: How to trade these headline driven markets"
    # (6,818 recipients) -- their best-clicking Wednesday send. Same skeleton,
    # fresh specifics, because the original body has already run twice.
    dict(key="W1-A3-Wed-NotReg",
         subject="Tomorrow at 2: what we check before any trade",
         preview="The four questions that decide whether a setup is worth taking",
         audience="current email list  MINUS  7/30 register, verified bad, buyer tags",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "Most traders don&rsquo;t lose money because they picked the wrong stock.",
             P % "They lose it because they had no rule for what to do next.",
             lines(
                 "You see a setup you like... but you&rsquo;re not sure it&rsquo;s the right time.",
                 "You wait for confirmation... and the move leaves without you.",
                 "You get into the next one... and it reverses an hour later.",
                 "You take the loss...",
                 "...and then the trade finally does what you thought it would.",
             ),
             P % "Sound familiar?",
             P % "That&rsquo;s not a stock-picking problem. That&rsquo;s a decision problem.",
             P % "And it doesn&rsquo;t get fixed by a better indicator or a faster alert. It gets fixed by having a process that tells you, <em>before</em> you enter, what has to be true for a trade to be worth taking &mdash; and what makes it a pass.",
             P % "That&rsquo;s what tomorrow&rsquo;s training is about.",
             P % "I&rsquo;m going live at <strong>2 PM Pacific</strong> and I&rsquo;ll walk you through:",
             bullets(
                 "What we check before any trade gets our capital",
                 "Why we pass on the overwhelming majority of setups we look at",
                 "How to tell a setup that&rsquo;s early from one that&rsquo;s simply wrong",
                 "What to do on the days when nothing qualifies",
             ),
             inline("Register for tomorrow&rsquo;s webinar here"),
             P % "See you there,",
         ]),
             ps="The traders having the hardest time right now are usually the "
                "ones deciding trade by trade. Tomorrow I&rsquo;ll show you the "
                "roadmap we use instead. Grab your seat below:",
             cta=ONE_CLICK, fallback=True)),

    # Modelled on "I'm givng you the blueprint to consistent trading today" /
    # "We're live today at 2 PM Pacific" -- the same body sent to 6,782 and
    # 7,187. Note the P.S. plus a second, capitalised CTA in the original.
    dict(key="W1-A4-Thu8am-NotReg",
         subject="We're live today at 2 PM Pacific",
         preview="What I'm breaking down this afternoon",
         audience="current email list  MINUS  7/30 register, verified bad, buyer tags",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "We&rsquo;re going live today at 2 PM Pacific.",
             P % "During this training I&rsquo;m going to walk you through how we decide what&rsquo;s worth trading &mdash; and, just as importantly, what isn&rsquo;t.",
             P % "Because consistency doesn&rsquo;t come from finding more opportunities.",
             lines(
                 "It comes from having rules for what you&rsquo;ll take.",
                 "It comes from having rules for how much you&rsquo;ll risk.",
                 "And it comes from recognizing when the best decision is to stay on the sidelines.",
             ),
             P % "That&rsquo;s what I&rsquo;ll be breaking down today.",
             P % "I&rsquo;ll show you what we look at inside University of Options before a single dollar goes into a trade, how we evaluate a setup, and why a structured process helps traders make clearer decisions instead of second-guessing every candle.",
             P % "If you&rsquo;ve been struggling to find consistency, or to feel confident in the decisions you&rsquo;re making, I hope you&rsquo;ll join me.",
             inline("Register for today&rsquo;s webinar here"),
             P % "I&rsquo;ll see you today at 2 Pacific,",
         ]),
             ps="You don&rsquo;t have to catch every move to become a better "
                "trader. You need a process that helps you recognize the right "
                "opportunities and skip the wrong ones. Save your spot here:",
             cta=ONE_CLICK, fallback=True)),

    # Modelled on "Will you be joining at 2?" / "Will you be joining me?" --
    # their single best-clicking webinar email, and the shortest. Four short
    # paragraphs, one plain text link, no P.S., no bullets. Left short on
    # purpose: the brevity is the thing that works.
    dict(key="W1-A5-ThuNoon-NotReg", old_key="W1-A5-Thu1pm-NotReg",
         subject="Will you be joining at 2?",
         preview="A quick reminder about this afternoon",
         audience="current email list  MINUS  7/30 register, verified bad, buyer tags",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "Just a quick reminder that my options training is happening this afternoon at 2 PM Pacific.",
             P % "If you&rsquo;ve been trading this market and feeling like you&rsquo;re constantly second-guessing your entries, your exits, and whether a setup is even worth taking... you&rsquo;re not alone.",
             P % "That&rsquo;s exactly what we&rsquo;re going to talk about today.",
             P % "I&rsquo;ll walk through how we&rsquo;re looking at the market right now, what we&rsquo;re being careful with, and how a more structured approach helps you stop making decisions out of fear, frustration, or FOMO.",
             inline("You can register here"),
             P % "See you soon,",
         ]), cta=ONE_CLICK, fallback=True)),

    # New slot. Modelled on "Going live in 15 mins" (6,780) and "going live in
    # 15" -- five lines, one link. Their sequence always has three Thursday
    # sends; ours had two.
    dict(key="W1-A6-Thu145-NotReg",
         subject="Going live in 15 mins",
         preview="Last chance to grab a seat",
         audience="current email list  MINUS  7/30 register, verified bad, buyer tags",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "My free options training is starting in 15 minutes.",
             P % "If you want to see how we decide what&rsquo;s worth trading in this market &mdash; and what we skip &mdash; now&rsquo;s the time to grab your spot.",
             inline("Save your seat here"),
             P % "I&rsquo;ll see you inside,",
         ]), cta=ONE_CLICK, fallback=True)),

    # ---------------- Track B: registered ----------------
    # No registration CTA anywhere in this one: they are already registered and
    # WebinarJam is sending them their unique join link.
    dict(key="W1-B1-WedAM-Registered", subject="One thing to think about before tomorrow",
         preview="A question worth sitting with before we meet",
         audience="7/30 register  MINUS  verified bad",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "Looking forward to seeing you tomorrow.",
             P % "Before we meet, I want you to think about one question.",
             P % "<strong>How many trades have you taken simply because you wanted to be in a trade?</strong>",
             P % "Be honest about it. Almost every trader has a number here, and for most people it&rsquo;s higher than they&rsquo;d like.",
             P % "Tomorrow I&rsquo;ll show you why our first objective each morning isn&rsquo;t finding a trade. It&rsquo;s finding a reason not to take one.",
             P % "I think you&rsquo;ll see the market a little differently afterward.",
             P % "See you tomorrow at 2 PM Pacific,",
         ]),
             ps="Your join link is in the confirmation email from WebinarJam. "
                "It&rsquo;s unique to you, so keep hold of it.")),

    # ---------------- Track C: attended ----------------
    dict(key="W1-C1-ThuPM-Attended", subject="Thanks for joining me today",
         preview="The one idea I hope stuck",
         audience="7/30 attended",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "Thank you for spending part of your afternoon with me.",
             P % "If there&rsquo;s one idea I hope stuck with you, it&rsquo;s this.",
             P % "<strong>The market pays you for discipline. Not activity.</strong>",
             P % "Everything we do at University of Options is built around that.",
             P % "If you&rsquo;re ready to stop guessing and start following a repeatable roadmap, I&rsquo;d love to help.",
             P % f'<a href="{SALES_LINK}">Learn more about Options Navigator and the Spread Trade Bot</a>',
             P % "I appreciate you being there today,",
         ]),
             ps=f'If you&rsquo;d rather talk it through with someone first, you '
                f'can <a href="{BOOK_CALL}">schedule a call with our team</a>.')),

    dict(key="W1-C2-Fri-Attended", subject="A quick follow up on yesterday",
         preview="The part most traders underestimate",
         audience="7/30 attended",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "The hardest part of becoming a better trader usually isn&rsquo;t learning another strategy.",
             P % "It&rsquo;s building the discipline to follow one consistently.",
             P % "That&rsquo;s the part most people underestimate, and it&rsquo;s exactly what we help our members with every day &mdash; the rules, the review, and having someone to check your thinking against.",
             P % f'If you&rsquo;re ready for the next step, <a href="{SALES_LINK}">you can see everything that&rsquo;s included here</a>.',
             P % "I hope to see you inside,",
         ]))),

    # ---------------- Track D: registered, did not attend ----------------
    # Subject is logistics, not sentiment: their replay sends that clicked best
    # were "The replay is ready" and "Missed the kickoff? Watch the replay".
    dict(key="W1-D1-ThuPM-NoShow", subject="The replay is ready",
         preview="Sorry we missed you — here's the recording",
         audience="7/30 absent  MINUS  7/30 attended",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "Sorry we missed you today.",
             P % "One sentence from this afternoon&rsquo;s training has been stuck in my head since.",
             P % "<strong>The market pays you for discipline. Not activity.</strong>",
             P % f'If you have time this evening or tomorrow morning, I really hope you&rsquo;ll <a href="{REPLAY_LINK}">watch the replay</a>.',
             P % "It&rsquo;s about an hour, and the part on deciding what to skip is worth it on its own.",
             P % "Enjoy it,",
         ]),
             ps=f'Once you&rsquo;ve watched, if you&rsquo;d like help applying '
                f'that roadmap to your own trading, <a href="{SALES_LINK}">you '
                f'can learn more here</a>.')),

    dict(key="W1-D2-Fri-NoShow", subject="Taking the replay down tonight",
         preview="Last chance to watch Thursday's training",
         audience="7/30 absent  MINUS  7/30 attended, 7/30 replay",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "Quick note before we take the replay down tonight.",
             P % "If you only remember one thing from this week&rsquo;s training, let it be this.",
             P % "<strong>The best trade you&rsquo;ll ever make is often the one you never take.</strong>",
             P % "That single shift has saved me more money than any indicator ever has.",
             P % f'<a href="{REPLAY_LINK}">You can still watch the replay here</a>.',
             P % "I hope you enjoy it,",
         ]))),

    # ---------------- Weekend: the offer deadline ----------------
    dict(key="W1-E1-Sat-Deadline", subject="This closes tomorrow night",
         preview="About the pricing we opened on Thursday",
         audience="7/30 attended + 7/30 absent  MINUS  buyer tags, verified bad",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "Quick note about something I mentioned on Thursday.",
             P % "The pricing we opened up during the training closes <strong>tomorrow at midnight</strong>. After that it goes back to standard.",
             P % "I&rsquo;m not going to pretend that&rsquo;s a reason to join. If the approach doesn&rsquo;t fit how you want to trade, a deadline shouldn&rsquo;t change your mind.",
             P % "But if you&rsquo;ve been sitting on the fence &mdash; if the part about skipping most setups landed, and you&rsquo;d rather have a roadmap than another strategy &mdash; this is the window.",
             P % f'<a href="{SALES_LINK}">Here&rsquo;s everything that&rsquo;s included</a>.',
         ]),
             ps=f'Still deciding? <a href="{BOOK_CALL}">Book a call</a> and '
                f'we&rsquo;ll talk it through honestly.')),

    dict(key="W1-E2-Sun-Deadline", subject="Closes at midnight",
         preview="Last note on Thursday's pricing",
         audience="7/30 attended + 7/30 absent  MINUS  buyer tags, verified bad",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "Last note on this, then I&rsquo;ll leave you alone about it.",
             P % "The pricing from Thursday&rsquo;s training closes tonight at midnight.",
             P % "Here&rsquo;s the honest version: what we teach isn&rsquo;t a shortcut. It&rsquo;s a process, and following it takes more patience than most people expect. That&rsquo;s exactly why it works.",
             P % "If that&rsquo;s the kind of trading you want to build, we&rsquo;d like to help you build it.",
             P % f'<a href="{SALES_LINK}">Join before midnight</a>',
         ]),
             ps="Either way, I&rsquo;ll see you Thursday. We do this every week.")),
]


def patch(client: GHLClient, tid: str, item: dict) -> None:
    client.request("PATCH", f"/emails/builder/{tid}", json={
        "locationId": client.location_id,
        "templateId": tid,
        "name": item["key"],
        "updatedBy": "api",
        "editorType": "html",
        "editorContent": item["body"],
        "previewText": item.get("preview", item["subject"]),
        "importProvider": None,
    })


def create(client: GHLClient, item: dict) -> str:
    made = client.request("POST", "/emails/builder", json={
        "locationId": client.location_id,
        "type": "html",
        "title": item["key"],
        "name": item["key"],
    })
    tid = made["id"]
    # The html sent above is discarded; the body only lands via PATCH.
    patch(client, tid, item)
    return tid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="create/update them in GHL")
    args = ap.parse_args()

    if not args.apply:
        out = Path("week1-preview")
        out.mkdir(exist_ok=True)
        print(f"{'template':<26}{'subject':<46}audience")
        print("-" * 118)
        for e in EMAILS:
            (out / f"{e['key']}.html").write_text(e["body"], encoding="utf-8")
            print(f"{e['key']:<26}{e['subject'][:44]:<46}{e['audience']}")
        print(f"\n{len(EMAILS)} templates written to {out}/ -- re-run with --apply to update in GHL")
        return 0

    client = GHLClient()
    existing = {t.get("name"): t["id"] for t in client.email_templates(limit=100)}

    for e in EMAILS:
        tid = existing.get(e["key"]) or existing.get(e.get("old_key", ""))
        try:
            if tid:
                patch(client, tid, e)
                verb = "updated"
            else:
                tid = create(client, e)
                verb = "created"
            print(f"  {verb} {e['key']:<26} {tid}")
        except GHLError as exc:
            print(f"  FAILED  {e['key']:<26} {str(exc)[:120]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
