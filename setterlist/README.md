# Setter call list

Builds a ranked list of leads for a setter to call, out of both GoHighLevel
sub-accounts. First built 2026-10-19 for Juan.

Run in order, from a directory where the JSONL dumps can live:

    python3 dump.py      # every contact in both accounts -> contacts_{sms,email}.jsonl
    python3 conv2.py     # conversations (reply/call recency) -> conv_{sms,email}.jsonl
    python3 opp3.py      # email-account opportunities (cursor paging past page 68)
    python3 events.py    # every calendar appointment -> events.json
    python3 build.py     # exclusions + scoring -> eligible.json
    python3 finalize.py  # cross-account dedupe, pick 250 -> juan-call-list.csv
    python3 guard.py     # re-check each pick against GHL's own appointment record
    python3 tag.py       # write the call-list tag in the SMS sub-account
    python3 xl.py        # formatted spreadsheet

`rules.py` holds the vocabulary the whole thing turns on: which tags and
pipeline stages mean a person already owns a product, which mean do-not-call,
and how a dated tag like "10/1 attended" is read. Those lists are the part to
edit when the tag vocabulary in GHL changes.

Exclusions, in the order they are applied: no dialable number, do-not-call,
already owns options bot / options navigator / futures, an appointment still
to come, disqualified, then anyone with no new-lead or engagement signal at
all. Scoring favours a fresh lead date, an inbound reply, webinar attendance,
clicks and an open opportunity in an early stage; see the second sheet of the
spreadsheet for the weights in plain language.

Reads are harmless. `tag.py` is the only script that writes to GHL.
