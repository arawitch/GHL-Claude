"""Collect bootcamp registration and engagement counts for the dashboard.

Tag names for the funnel are still being decided, so nothing is hardcoded:
this reads every tag in the SMS sub-account whose name starts with
"bootcamp" and counts the people carrying it, which means a tag invented
later wires itself up the day it starts being written.

Two things it does NOT do naively, both because they produced numbers that
contradicted each other on the same screen:

  * It counts PEOPLE, not contact records, across both sub-accounts. The SMS
    account alone showed 106 registrations where there are really 128 people,
    and the warm-up panel beside it (which always deduped) said 128.
  * It separates the tags left over from the January 2026 bootcamp from the
    Nov 30 funnel. Mixed into one table, `bootcamp` at 123 reads like a
    bigger registration count than `bootcamp registered` at 106.

    <outdir>/bootcamp/status.json

Usage:  python3 dashboard/collect_bootcamp.py [outdir]
Needs:  GHL_SMS_API_KEY, GHL_SMS_LOCATION_ID, and GHL_EMAIL_API_KEY /
        GHL_EMAIL_LOCATION_ID to count the second account.
"""
import os
import sys
import re
import json
import datetime
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ghl.client import GHLClient  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from people import tagged  # noqa: E402

PREFIX = 'bootcamp'
REGISTERED = 'bootcamp registered'

# The order these steps happen in. Anything matching none of them is listed
# after, alphabetically, so a tag invented later still shows up.
ORDER = ['invite', 'interested', 'registered', 'confirmed', 'reminded',
         'attended', 'day', 'stayed', 'replay', 'applied', 'booked']

# Tags from the January 2026 bootcamp that share the "bootcamp" prefix.
# Checked 2026-11-23 against the Nov 30 registrations: `bootcamp` overlaps it
# by 0 of 123, `bootcamp opt in` by 5 of 348 and `bootcamp- new post` by 0 of
# 4, so these are a different cohort, not a stage of this funnel. If a tag
# here ever starts overlapping the registrations, it has been reused and
# belongs back in the live funnel.
LEGACY = {'bootcamp', 'bootcamp opt in', 'bootcamp- new post',
          'bootcamp- new comment'}


def rank(name):
    for i, word in enumerate(ORDER):
        if word in name:
            return (i, name)
    return (len(ORDER), name)


def label(name):
    s = re.sub(r'^bootcamp[\s-]*', '', name).strip() or name
    return s[:1].upper() + s[1:]


def main():
    outdir = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else 'dashout')
    sms = GHLClient(os.environ['GHL_SMS_API_KEY'], os.environ['GHL_SMS_LOCATION_ID'])
    clients = [('sms', sms)]
    if os.environ.get('GHL_EMAIL_API_KEY') and os.environ.get('GHL_EMAIL_LOCATION_ID'):
        clients.append(('email', GHLClient(os.environ['GHL_EMAIL_API_KEY'],
                                           os.environ['GHL_EMAIL_LOCATION_ID'])))

    names = [t['name'] for t in
             sms.get('/locations/%s/tags' % sms.location_id).get('tags', [])]
    mine = sorted([t for t in names if t.lower().startswith(PREFIX)], key=rank)

    funnel, legacy, days, incomplete = [], [], [], []
    for tag in mine:
        people, partial = tagged(clients, tag)
        incomplete.extend(partial)
        count = len(people)
        key = re.sub(r'[^a-z0-9]+', '_', tag.lower()).strip('_')
        row = {'key': key, 'tag': tag, 'label': label(tag), 'count': count}

        if tag.lower() in LEGACY:
            legacy.append(row)
            continue
        # "bootcamp day 2 attended" style tags become the attendance table.
        m = re.search(r'day\s*(\d+)', tag.lower())
        if m and ('attend' in tag.lower() or 'joined' in tag.lower()):
            days.append({'day_no': int(m.group(1)), 'label': 'Day ' + m.group(1),
                         'attended': count, 'stayed': 0})
        else:
            funnel.append(row)

    # Pair each day's "stayed" tag with its attendance row where one exists.
    for tag in mine:
        m = re.search(r'day\s*(\d+)', tag.lower())
        if m and ('stayed' in tag.lower() or 'full' in tag.lower()):
            people, partial = tagged(clients, tag)
            incomplete.extend(partial)
            for d in days:
                if d['day_no'] == int(m.group(1)):
                    d['stayed'] = len(people)
    days.sort(key=lambda d: d['day_no'])

    reg = next((r['count'] for r in funnel
                if r['tag'].lower() == REGISTERED), 0)
    tiles = [{'label': 'Registered', 'value': reg,
              'note': 'people, deduplicated across both accounts'}]
    if days:
        tiles.append({'label': 'Attended day 1', 'value': days[0]['attended'],
                      'note': ''})
        tiles.append({'label': 'Still there on the last day',
                      'value': days[-1]['attended'], 'note': days[-1]['label']})

    note = ('' if mine else
            'Nothing in GoHighLevel carries a bootcamp tag yet. This panel counts '
            'every tag whose name starts with "bootcamp", so it fills in by itself '
            'the moment the registration workflow starts writing them.')
    if incomplete:
        note = (note + ' ' if note else '') + \
            'One sub-account could not be read on this pull, so these counts ' \
            'may be low: ' + '; '.join(sorted(set(incomplete)))

    (outdir / 'bootcamp').mkdir(parents=True, exist_ok=True)
    (outdir / 'bootcamp' / 'status.json').write_text(json.dumps({
        'updated_at': datetime.datetime.now(datetime.timezone.utc)
                      .isoformat(timespec='seconds'),
        'note': note,
        'tiles': tiles,
        'funnel': funnel,
        'legacy': legacy,
        'days': days,
    }, indent=1))
    print('bootcamp tags found: %d (%d legacy)' % (len(mine), len(legacy)),
          file=sys.stderr)


if __name__ == '__main__':
    main()
