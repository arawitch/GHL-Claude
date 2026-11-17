"""Collect bootcamp registration and engagement counts for the dashboard.

The bootcamp funnel is still being built, and its tag names are being decided
in the planning thread, so this does not hardcode a list. It reads every tag
whose name starts with "bootcamp" and counts the contacts carrying it. A tag
that does not exist yet simply does not appear, and the panel fills in on its
own the day the funnel starts writing tags.

BOTH sub-accounts are read, because the bootcamp work is split across them:
the invite sends and their `bootcamp invited` tag live in the main/EMAIL
account, while the nurture workflows and their registration tags live in SMS.
Reading only SMS showed 0 invited against 11,102 actually invited.

The two accounts hold mostly the SAME people (about 94.8% overlap), so the two
counts for a tag are NOT added together - that would double count. Each row
takes the LARGER of the two and records both, so a tag written in one account
reads correctly and a tag written in both does not inflate.

    <outdir>/bootcamp/status.json

Usage:  python3 dashboard/collect_bootcamp.py [outdir]
Needs:  GHL_SMS_API_KEY, GHL_SMS_LOCATION_ID,
        GHL_EMAIL_API_KEY, GHL_EMAIL_LOCATION_ID
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

# (label, client, location id). SMS first so it wins ties in the listing.
ACCOUNTS = [
    ('sms', GHLClient(os.environ['GHL_SMS_API_KEY'],
                      os.environ['GHL_SMS_LOCATION_ID']),
     os.environ['GHL_SMS_LOCATION_ID']),
    ('email', GHLClient(os.environ['GHL_EMAIL_API_KEY'],
                        os.environ['GHL_EMAIL_LOCATION_ID']),
     os.environ['GHL_EMAIL_LOCATION_ID']),
]


def count_in(cl, loc, tag):
    r = cl.post('/contacts/search', {'locationId': loc, 'pageLimit': 1,
        'filters': [{'field': 'tags', 'operator': 'eq', 'value': tag}]})
    return int(r.get('total') or 0)


def counts(tag):
    """Per-account counts for a tag, plus the larger of them."""
    per = {}
    for name, cl, loc in ACCOUNTS:
        try:
            per[name] = count_in(cl, loc, tag)
        except Exception as e:          # one account down must not blank the tab
            print('%s: %s count failed: %s' % (name, tag, e), file=sys.stderr)
            per[name] = 0
    return per, max(per.values() or [0])


def count(tag):
    return counts(tag)[1]


def rank(name):
    for i, word in enumerate(ORDER):
        if word in name:
            return (i, name)
    return (len(ORDER), name)


def label(name):
    s = re.sub(r'^bootcamp[\s-]*', '', name).strip() or name
    return s[:1].upper() + s[1:]


tags = []
for name, cl, loc in ACCOUNTS:
    try:
        for t in cl.get('/locations/%s/tags' % loc).get('tags', []):
            if t['name'] not in tags:
                tags.append(t['name'])
    except Exception as e:
        print('%s: tag list failed: %s' % (name, e), file=sys.stderr)
mine = sorted([t for t in tags if t.lower().startswith(PREFIX)], key=rank)

funnel, days = [], []
for t in mine:
    per, c = counts(t)
    key = re.sub(r'[^a-z0-9]+', '_', t.lower()).strip('_')
    row = {'key': key, 'tag': t, 'label': label(t), 'count': c, 'by_account': per}
    # "bootcamp day 2 attended" style tags become the attendance table.
    m = re.search(r'day\s*(\d+)', t.lower())
    if m and 'attend' in t.lower():
        days.append({'day_no': int(m.group(1)), 'label': 'Day ' + m.group(1),
                     'attended': c, 'stayed': 0, 'by_account': per})
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
inv = next((r['count'] for r in funnel if 'invited' in r['tag'].lower()), 0)
tiles = []
if inv:
    tiles.append({'label': 'Invited', 'value': inv,
                  'note': 'sent an invite to the Nov 30 bootcamp'})
tiles.append({'label': 'Registered', 'value': reg,
              'note': ('%.1f%% of those invited' % (100.0 * reg / inv)) if inv
                      else 'carrying a bootcamp registration tag'})
if days:
    tiles.append({'label': 'Attended day 1', 'value': days[0]['attended'], 'note': ''})
    tiles.append({'label': 'Still there on the last day',
                  'value': days[-1]['attended'], 'note': days[-1]['label']})

note = ('' if mine else
        'Nothing in GoHighLevel carries a bootcamp tag yet. This panel counts '
        'every tag whose name starts with "bootcamp", so it fills in by itself '
        'the moment the registration workflow starts writing them.')

counted_as = ('Counts cover both sub-accounts. The same people exist in both, '
              'so each tag shows the larger of the two counts, not their sum.')

(outdir / 'bootcamp').mkdir(parents=True, exist_ok=True)
(outdir / 'bootcamp' / 'status.json').write_text(json.dumps({
    'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    'note': note,
    'counted_as': counted_as,
    'tiles': tiles,
    'funnel': funnel,
    'days': days,
}, indent=1))
print('bootcamp tags found across both accounts: %d' % len(mine), file=sys.stderr)
