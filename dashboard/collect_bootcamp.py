"""Collect bootcamp registration and engagement counts for the dashboard.

The bootcamp funnel is still being built, and its tag names are being decided
in the planning thread, so this does not hardcode a list. It reads every tag
in the SMS sub-account whose name starts with "bootcamp" and counts the
contacts carrying it. A tag that does not exist yet simply does not appear,
and the panel fills in on its own the day the funnel starts writing tags.

    <outdir>/bootcamp/status.json

Usage:  python3 dashboard/collect_bootcamp.py [outdir]
Needs:  GHL_SMS_API_KEY, GHL_SMS_LOCATION_ID
"""
import os, sys, json, re, datetime, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ghl.client import GHLClient

PREFIX = 'bootcamp'
# The order these steps happen in. Anything matching none of them is listed
# after, alphabetically, so a tag invented later still shows up.
ORDER = ['invite', 'interested', 'registered', 'confirmed', 'reminded',
         'attended', 'day', 'stayed', 'replay', 'applied', 'booked']

outdir = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else 'dashout')
cl = GHLClient(os.environ['GHL_SMS_API_KEY'], os.environ['GHL_SMS_LOCATION_ID'])
LOC = os.environ['GHL_SMS_LOCATION_ID']


def count(tag):
    r = cl.post('/contacts/search', {'locationId': LOC, 'pageLimit': 1,
        'filters': [{'field': 'tags', 'operator': 'eq', 'value': tag}]})
    return int(r.get('total') or 0)


def rank(name):
    for i, word in enumerate(ORDER):
        if word in name:
            return (i, name)
    return (len(ORDER), name)


def label(name):
    s = re.sub(r'^bootcamp[\s-]*', '', name).strip() or name
    return s[:1].upper() + s[1:]


tags = [t['name'] for t in cl.get('/locations/%s/tags' % LOC).get('tags', [])]
mine = sorted([t for t in tags if t.lower().startswith(PREFIX)], key=rank)

funnel, days = [], []
for t in mine:
    c = count(t)
    key = re.sub(r'[^a-z0-9]+', '_', t.lower()).strip('_')
    row = {'key': key, 'tag': t, 'label': label(t), 'count': c}
    # "bootcamp day 2 attended" style tags become the attendance table.
    m = re.search(r'day\s*(\d+)', t.lower())
    if m and 'attend' in t.lower():
        days.append({'day_no': int(m.group(1)), 'label': 'Day ' + m.group(1),
                     'attended': c, 'stayed': 0})
    else:
        funnel.append(row)

# Pair each day's "stayed" tag with its attendance row where one exists.
for t in mine:
    m = re.search(r'day\s*(\d+)', t.lower())
    if m and ('stayed' in t.lower() or 'full' in t.lower()):
        for d in days:
            if d['day_no'] == int(m.group(1)):
                d['stayed'] = count(t)
days.sort(key=lambda d: d['day_no'])

reg = next((r['count'] for r in funnel if 'registered' in r['tag'].lower()), 0)
tiles = [{'label': 'Registered', 'value': reg, 'note': 'carrying a bootcamp registration tag'}]
if days:
    tiles.append({'label': 'Attended day 1', 'value': days[0]['attended'], 'note': ''})
    tiles.append({'label': 'Still there on the last day',
                  'value': days[-1]['attended'], 'note': days[-1]['label']})

note = ('' if mine else
        'Nothing in GoHighLevel carries a bootcamp tag yet. This panel counts '
        'every tag whose name starts with "bootcamp", so it fills in by itself '
        'the moment the registration workflow starts writing them.')

(outdir / 'bootcamp').mkdir(parents=True, exist_ok=True)
(outdir / 'bootcamp' / 'status.json').write_text(json.dumps({
    'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    'note': note,
    'tiles': tiles,
    'funnel': funnel,
    'days': days,
}, indent=1))
print('bootcamp tags found: %d' % len(mine), file=sys.stderr)
