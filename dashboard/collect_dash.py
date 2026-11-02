"""Collect Conversation AI qualifier results, one JSON document per day.

Reads the SMS sub-account, finds every contact ever tagged `ai qualifying v2`,
attributes each one to the day their opener went out, then counts outcomes from
tags. Writes JSON files ready to be loaded into the dashboard artifact's store:

    <outdir>/days/<YYYY-MM-DD>.json
    <outdir>/meta/status.json

Usage:  python3 dashboard/collect_dash.py [outdir]
Needs:  GHL_SMS_API_KEY, GHL_SMS_LOCATION_ID
"""
import os, sys, json, collections, datetime, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ghl.client import GHLClient

OPENER = 'are you still trading'
TAG = 'ai qualifying v2'
COLS = ['sent', 'delivered', 'replied', 'qualified', 'booked',
        'signal_pilot', 'wants_link', 'opted_out']

def fetch_messages(conv_id, cap=600):
    """Every message in a conversation, oldest first.

    `/conversations/{id}/messages` returns only the newest page (20 by default,
    100 at most), so a long thread hides its opener and the daily counts come
    out unstable. Page back with `lastMessageId` until the API says there is no
    more.
    """
    out, last = [], None
    while len(out) < cap:
        params = {'limit': 100}
        if last:
            params['lastMessageId'] = last
        box = cl.request('GET', '/conversations/%s/messages' % conv_id,
                         params=params).get('messages', {})
        batch = box.get('messages', []) or []
        out += batch
        if not box.get('nextPage') or not batch:
            break
        last = batch[-1]['id']
    return out


def booked_since(contact_id, since):
    """True when the contact holds an appointment starting after `since`."""
    try:
        evs = cl.get('/contacts/%s/appointments' % contact_id).get('events', []) or []
    except Exception:
        return False
    cut = str(since)[:10]
    for e in evs:
        if (e.get('appointmentStatus') or '').lower() in ('cancelled', 'noshow'):
            continue
        if str(e.get('startTime') or '')[:10] >= cut:
            return True
    return False


outdir = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else 'dashout')
cl = GHLClient(os.environ['GHL_SMS_API_KEY'], os.environ['GHL_SMS_LOCATION_ID'])
LOC = os.environ['GHL_SMS_LOCATION_ID']

contacts, page = [], 1
while True:
    r = cl.post('/contacts/search', {'locationId': LOC, 'pageLimit': 100, 'page': page,
        'filters': [{'field': 'tags', 'operator': 'eq', 'value': TAG}]})
    cs = r.get('contacts', [])
    contacts += cs
    if len(cs) < 100:
        break
    page += 1
print('enrolled contacts: %d' % len(contacts), file=sys.stderr)

days = collections.defaultdict(collections.Counter)
for c in contacts:
    tags = set(t.lower() for t in (c.get('tags') or []))
    cv = cl.get('/conversations/search', contactId=c['id']).get('conversations', [])
    if not cv:
        continue
    # A contact can hold more than one conversation and their order is not
    # stable, so merge every one of them rather than trusting the first.
    ms = []
    for conv in cv:
        ms += fetch_messages(conv['id'])
    ms = sorted(ms, key=lambda x: x.get('dateAdded') or '')
    op = [m for m in ms if OPENER in (m.get('body') or '').lower()]
    if not op:
        continue
    o = op[-1]
    d = days[(o.get('dateAdded') or '')[:10]]
    d['sent'] += 1
    if o.get('status') == 'delivered':
        d['delivered'] += 1
    if any(m.get('direction') == 'inbound' and (m.get('dateAdded') or '') > o['dateAdded'] for m in ms):
        d['replied'] += 1
    if 'ai high ticket' in tags:
        d['qualified'] += 1
    if 'ai booked high ticket' in tags or booked_since(c['id'], o['dateAdded']):
        # The bot tags its own bookings, but a rep who plugs the lead into
        # their calendar by hand does not, so also count a real appointment
        # that starts after the opener went out.
        d['booked'] += 1
    if 'ai signal pilot fit' in tags:
        d['signal_pilot'] += 1
    if 'ai wants signal pilot link' in tags:
        d['wants_link'] += 1
    sms = (c.get('dndSettings') or {}).get('SMS') or {}
    if 'do not contact' in tags or sms.get('status') in ('permanent', 'active'):
        d['opted_out'] += 1

(outdir / 'days').mkdir(parents=True, exist_ok=True)
(outdir / 'meta').mkdir(parents=True, exist_ok=True)
for day in sorted(days):
    doc = {'day': day}
    doc.update({k: days[day][k] for k in COLS})
    (outdir / 'days' / ('%s.json' % day)).write_text(json.dumps(doc, indent=1))
    print(day, doc)

(outdir / 'meta' / 'status.json').write_text(json.dumps({
    'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    'enrolled_total': len(contacts),
    'days': sorted(days),
}, indent=1))
print('wrote %d day files to %s' % (len(days), outdir))
