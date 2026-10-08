#!/usr/bin/env python3
"""Create the six 8/6 replay-chase emails in GoHighLevel.

--------------------------------------------------------------------------
What these are modelled on
--------------------------------------------------------------------------
Open and click rates were measured directly, because GoHighLevel exposes no
statistics endpoint: a sample of 260 contacts was walked and each message's
status (`delivered` / `opened` / `clicked`) read from
/conversations/messages/email/{id}. Every subject below n>=26 observations.

    The replay is ready                        39.3% open
    Starting in one hour                       37.0%
    Missed the kickoff? Watch the replay       37.0%
    Going live in 15 mins                      32.1%
    Last call before we start tomorrow         29.6%
    Will you be joining me?                    29.0%
    ...
    starting at 2 pacific                      23.5%
    Starting in 15 minutes: Options Spread Bot 18.8%

The two best-opening emails in the archive are both **replay** emails, which is
the format being written here.

**Click rates are not usable at this sample size** and are deliberately not
ranked on. At n~28 a single click is 3.6%, so the spread between a "3.7%"
subject and a "0.0%" one is one message. Open rates at n~30 carry roughly a
+/-9pp margin, enough to separate the top cluster (29-39%) from the bottom
(18-24%) but not to order subjects within it. So these six copy the *shape* of
the winning cluster rather than treating rank 1 as better than rank 5.

That shape:

  1. The subject is logistics or a deadline, never a benefit claim. "The replay
     is ready" beats every persuasive subject in the archive. Lowercase does no
     harm -- "going live in 15" scored 29.0%.
  2. Preview text is a *different* sentence that continues the subject, never a
     restatement of it.
  3. Body opens "Hey {{contact.first_name}}," then states in one sentence what
     happened, and in one more that the recording exists.
  4. Scarcity is a fact, not a threat: "we normally only run these a few times
     each year."
  5. Two CTAs -- an inline text link mid-body, then a P.S. carrying a second.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ghl.client import GHLClient, GHLError

REPLAY = "{{REPLAY_LINK}}"        # replace with the WebinarJam replay URL
SALES = "https://go.universityofoptions.com/buy"

CSS = ("font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;"
       "font-size:16px;line-height:1.6;color:#222;max-width:600px;margin:0 auto;padding:24px;")
P = "<p>%s</p>"
SIGN = "<p>Dan</p>"


def html(body: str, ps: str | None = None, cta: str = REPLAY,
         label: str = "Watch The Replay") -> str:
    parts = [f'<div style="{CSS}">', body, SIGN]
    if ps:
        parts.append(P % f"<strong>P.S.</strong> {ps}")
    parts.append(
        f'<p style="margin:28px 0;"><a href="{cta}" '
        'style="background:#16a34a;color:#fff;padding:15px 30px;font-weight:600;'
        f'border-radius:6px;text-decoration:none;display:inline-block;">{label}</a></p>')
    parts.append("</div>")
    return "\n".join(parts)


def link(text: str, href: str = REPLAY) -> str:
    return P % f'<a href="{href}">{text}</a>'


def tight(*rows: str) -> str:
    return "".join(f'<p style="margin:0;">{r}</p>' for r in rows)


EMAILS: list[dict] = [
    # Their single best-opening subject in the archive, reused as-is. There is
    # no cleverness to add here -- it won because it is plain.
    dict(key="R1-Wed-ReplayReady",
         subject="The replay is ready",
         preview="If you couldn't make it Thursday, the recording is up",
         send="Wednesday 4:00 PM PT",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "Last Thursday I ran a free training on how we decide what&rsquo;s actually worth trading &mdash; and, just as importantly, what isn&rsquo;t.",
             P % "If you weren&rsquo;t able to join us live, the recording is now available.",
             P % "In it I walk through what we check before any trade gets our capital, why we pass on the overwhelming majority of setups we look at, and how to tell a setup that&rsquo;s early from one that&rsquo;s simply wrong.",
             P % "It runs about an hour. The part on what to do when nothing qualifies is worth it on its own.",
             link("You can watch the replay here"),
         ]),
             ps="We only run these a few times a quarter, and the recording "
                "comes down Sunday night.")),

    # Modelled on "Missed the kickoff? Watch the replay" (37.0%). Question in
    # the subject, answer in the preview.
    dict(key="R2-Thu-MissedIt",
         subject="Missed Thursday? Watch the replay",
         preview="About an hour, and you can skip to the part you need",
         send="Thursday 8:00 AM PT",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "A lot of people told me they wanted to be on Thursday&rsquo;s training and couldn&rsquo;t make 2 PM work.",
             P % "The recording is up, so the time no longer matters.",
             P % "Here&rsquo;s what&rsquo;s in it:",
             tight(
                 "&mdash; What we check before any trade gets our capital",
                 "&mdash; Why we skip most of the setups we look at",
                 "&mdash; How to tell an early setup from a wrong one",
                 "&mdash; What to do on the days when nothing qualifies",
             ),
             P % "",
             link("Watch the recording here"),
         ]),
             ps="If you only have ten minutes, start at the section on "
                "passing on trades. That&rsquo;s the part people message me about.")),

    # Modelled on "Last call before we start tomorrow" (29.6%) -- a deadline
    # stated flatly. Lowercase subject, which scored the same as capitalised.
    dict(key="R3-Fri-ComingDown",
         subject="we're taking the replay down Sunday",
         preview="Two more days, then it goes back in the vault",
         send="Friday 8:00 AM PT",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "Quick heads up: Thursday&rsquo;s training comes down <strong>Sunday night</strong>.",
             P % "If you have been meaning to watch it and haven&rsquo;t yet, this weekend is the window.",
             P % "It&rsquo;s the clearest explanation I&rsquo;ve given of how we decide what to trade &mdash; not which stock to pick, but what has to be true before any trade is worth taking.",
             link("Watch it before Sunday"),
         ]),
             ps="We normally only run these a few times a quarter. When it "
                "comes down, it comes down.")),

    # Content angle rather than logistics -- one idea, no pitch. Gives the
    # weekend send a reason to exist beyond repeating the deadline.
    dict(key="R4-Sat-OneIdea",
         subject="the part everyone messages me about",
         preview="One idea from Thursday, in about sixty seconds",
         send="Saturday 9:00 AM PT",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "Every time I run this training, the same section is what people write in about afterward.",
             P % "It&rsquo;s the bit where I explain that we start each morning looking for reasons <em>not</em> to trade.",
             P % "That sounds backwards. Most traders open their platform asking what they should get into today.",
             P % "But consistency doesn&rsquo;t come from finding more opportunities. It comes from having rules for which ones deserve your capital &mdash; and the discipline to sit out when none of them do.",
             P % "That single shift has saved me more money than any indicator ever has.",
             link("That section starts about halfway through the replay"),
         ]),
             ps="The recording comes down tomorrow night.")),

    # Modelled on "Last call before we start tomorrow" (29.6%).
    dict(key="R5-Sun-LastCall",
         subject="Last call before the replay comes down",
         preview="Tonight is the end of it",
         send="Sunday 9:00 AM PT",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "Thursday&rsquo;s training comes down <strong>tonight</strong>.",
             P % "If it&rsquo;s been sitting in your inbox all week, this is the last morning to do anything about it.",
             P % "An hour, and you&rsquo;ll have a clear picture of how we evaluate a trade before we take it.",
             link("Watch it before tonight"),
         ]),
             ps=f'If you&rsquo;ve already watched and want to know what working '
                f'with us looks like, <a href="{SALES}">everything is here</a>.')),

    # Modelled on "Starting in one hour" (37.0%) -- their strongest pure-urgency
    # subject. Five lines, one link, nothing else.
    dict(key="R6-Sun-FinalHours",
         subject="coming down in a few hours",
         preview="Last chance on Thursday's recording",
         send="Sunday 6:00 PM PT",
         body=html("".join([
             P % "Hey {{contact.first_name}},",
             P % "Thursday&rsquo;s recording comes down tonight.",
             P % "If you want it, now is the time.",
             link("Watch the replay"),
             P % "See you at the next one,",
         ]))),
]


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
    args = ap.parse_args()

    if not args.apply:
        out = Path("replay-preview")
        out.mkdir(exist_ok=True)
        print(f"{'template':<24}{'send':<24}subject")
        print("-" * 96)
        for e in EMAILS:
            (out / f"{e['key']}.html").write_text(e["body"], encoding="utf-8")
            print(f"{e['key']:<24}{e['send']:<24}{e['subject']}")
        print(f"\n{len(EMAILS)} written to {out}/ -- re-run with --apply")
        return 0

    client = GHLClient()
    existing = {t.get("name"): t["id"] for t in client.email_templates(limit=100)}
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
            print(f"  {verb} {e['key']:<24} {tid}")
        except GHLError as exc:
            print(f"  FAILED {e['key']}: {str(exc)[:110]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
