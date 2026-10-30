# Lead scoring — high ticket ($4k+) vs low ticket ($99/mo)

Routes every person in both GoHighLevel sub-accounts to a high-ticket or a
low-ticket offer, from survey answers, engagement tags, purchase history and
the phone's area code. Read-only: nothing here writes to GHL.

Run in order, from this directory. Each step writes its intermediate to the
current directory, so run it somewhere scratch, not in the repo.

```bash
python3 dump.py SMS        # ~3 min: contacts + opportunities -> contacts_SMS.jsonl, opps_SMS.jsonl
python3 dump.py EMAIL      # ~3 min, in parallel is fine
python3 pipes.py           # pipeline + stage names   -> pipes_{SMS,EMAIL}.json
python3 cf.py              # custom field definitions -> cf_{SMS,EMAIL}.json
python3 build.py           # dedupe to people.pkl, classify buyers and disqualified leads
python3 features.py        # leakage-screened features -> feats.pkl, prints the lift table
python3 score.py           # apply both scores, print routing and in-sample validation
python3 holdout.py         # out-of-sample check: fit on half the buyers, score the other half
python3 emit.py            # write the CSVs to /mnt/project-files/lead-scoring/
```

Needs `GHL_SMS_API_KEY` / `GHL_SMS_LOCATION_ID` and `GHL_EMAIL_API_KEY` /
`GHL_EMAIL_LOCATION_ID`.

## Design notes

People are deduped by lowercased email, then phone — 94.8% of contacts exist in
both sub-accounts, so anything contact-level double-counts.

`features.py` screens out every signal that is a *consequence* of buying
(`uoo vsl: won`, `customer`, product and membership tags, bot-support answers,
refund questions, "which rep sold you your bot"). It also drops recency,
time-in-CRM and appointment history: $4k+ buyers are mostly pre-2026
main-account history, so those three are calendar artifacts, not signals.

The high-ticket weights are `round(10 * log2(lift))` clipped to ±30, measured
against *engaged non-buyers* (booked, showed, or disqualified and never paid) —
not against the whole list, which would just rank "is in the CRM at all".
`holdout.py` is the honest check: weights from a random half of the buyers,
scored on the half the model never saw. Top band runs 40x base rate, monotone
across seven bands.

The Signal Pilot score is **not** fitted. The account holds no sub-$2k purchase
to train on (935 of 941 recorded purchase values are $1,000+), so it ranks on
the engagement markers this data does measure plus an affordability floor from
the survey capital answer. Recalibrate it once real $99/mo sales exist.

`areacodes.py` holds approximate ACS-era median household income for the metro
each of 290 area codes principally serves. The figures are directional, not
census-exact, and a mobile number only says where it was issued. Measured effect
is small (±4 points of ~100) and the real pattern is regional rather than
income-driven — Phoenix out-converts Silicon Valley. Use it as a tiebreaker.
