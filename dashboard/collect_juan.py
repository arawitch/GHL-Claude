"""Collect Juan's call-list progress, one JSON document for the dashboard.

Juan does not tag pickups or bookings, so the only honest measure of his work
is the call log: TYPE_CALL messages whose userId is his. This reads every
contact on each of his call lists, counts his dials against them, and reports
how much of each list is still untouched.

    <outdir>/juan/status.json

Usage:  python3 dashboard/collect_juan.py [outdir]
Needs:  GHL_SMS_API_KEY, GHL_SMS_LOCATION_ID
"""
import os, sys, json, datetime, pathlib, collections

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ghl.client import GHLClient

JUAN_USER_ID = 'xxcp9j8UStACv8KfYRjj'

# The bot-fed queue first; the dated tags are the lists built by hand in
# October and are kept so the panel shows what is still unworked in them.
LISTS = [
    ('ai juan call list', 'Bot queue (live)'),
    ('10/26 juan webinar + newsletter', '10/26 webinar + newsletter'),
    ('10/26 juan new leads', '10/26 new leads'),
    ('10/26 juan finish 10-19 list', '10/26 finish 10/19'),
    ('10/19 juan call list', '10/19 original'),
]

# Why a lead is in the bot queue. Written by "Conversation AI - Juan follow up".
REASONS = [
    ('ai juan - qualified no booking', 'Qualified, never booked'),
    ('ai juan - no trial started', 'Sent the link, never started'),
]

# A dial under 20 seconds is a ring-out or a hang-up, not a conversation.
CONNECT_SECONDS = 20

outdir = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else 'dashout')
cl = GHLClient(os.environ['GHL_SMS_API_KEY'], os.environ['GHL_SMS_LOCATION_ID'])
LOC = os.environ['GHL_SMS_LOCATION_ID']


def tagged(tag):
    out, page = [], 1
    while True:
        r = cl.post('/contacts/search', {'locationId': LOC, 'pageLimit': 100,
            'page': page, 'filters': [{'field': 'tags', 'operator': 'eq', 'value': tag}]})
        cs = r.get('contacts', [])
        out += cs
        if len(cs) < 100:
            return out
        page += 1


def juan_calls(contact_id):
    """Every call Juan placed to this contact: (date, duration seconds)."""
    calls = []
    try:
        cv = cl.get('/conversations/search', contactId=contact_id).get('conversations', [])
    except Exception:
        return calls
    for conv in cv:
        try:
            box = cl.request('GET', '/conversations/%s/messages' % conv['id'],
                             params={'limit': 100}).get('messages', {})
        except Exception:
            continue
        for m in box.get('messages', []) or []:
            if m.get('messageType') != 'TYPE_CALL':
                continue
            if m.get('userId') != JUAN_USER_ID:
                continue
            dur = ((m.get('meta') or {}).get('call') or {}).get('duration') or 0
            calls.append(((m.get('dateAdded') or '')[:10], int(dur)))
    return calls


def live_appointments(contact_id):
    try:
        evs = cl.get('/contacts/%s/appointments' % contact_id).get('events', []) or []
    except Exception:
        return []
    return [e for e in evs
            if (e.get('appointmentStatus') or '').lower() not in ('cancelled', 'invalid')]


seen = set()
lists_out = []
by_day = collections.Counter()
totals = collections.Counter()
reason_counts = collections.Counter()
queue_rows = []

for tag, label in LISTS:
    people = tagged(tag)
    row = collections.Counter()
    row['size'] = len(people)
    for c in people:
        cid = c['id']
        tags = set(t.lower() for t in (c.get('tags') or []))
        calls = juan_calls(cid)
        dialled = bool(calls)
        connected = any(d >= CONNECT_SECONDS for _, d in calls)
        row['dials'] += len(calls)
        row['dialled'] += 1 if dialled else 0
        row['connected'] += 1 if connected else 0
        appts = live_appointments(cid)
        booked = bool(appts)
        row['booked'] += 1 if booked else 0
        # A person on two lists is counted once in the totals and once per list.
        if cid not in seen:
            seen.add(cid)
            totals['people'] += 1
            totals['dials'] += len(calls)
            totals['dialled'] += 1 if dialled else 0
            totals['connected'] += 1 if connected else 0
            totals['booked'] += 1 if booked else 0
            for day, _ in calls:
                by_day[day] += 1
        if tag == 'ai juan call list':
            for rtag, rlabel in REASONS:
                if rtag in tags:
                    reason_counts[rlabel] += 1
            queue_rows.append({
                'name': ((c.get('firstName') or '') + ' ' + (c.get('lastName') or '')).strip()
                        or c.get('email') or cid,
                'dials': len(calls),
                'last_dial': max([d for d, _ in calls], default=None),
                'best_seconds': max([s for _, s in calls], default=0),
                'booked': booked,
                'reason': next((rl for rt, rl in REASONS if rt in tags), ''),
            })
    row['to_call'] = row['size'] - row['dialled']
    lists_out.append({'tag': tag, 'label': label, **row})
    print(label, dict(row), file=sys.stderr)

cut = (datetime.date.today() - datetime.timedelta(days=20)).isoformat()
(outdir / 'juan').mkdir(parents=True, exist_ok=True)
(outdir / 'juan' / 'status.json').write_text(json.dumps({
    'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    'connect_seconds': CONNECT_SECONDS,
    'lists': lists_out,
    'totals': dict(totals),
    'reasons': [{'label': l, 'count': reason_counts.get(l, 0)} for _, l in REASONS],
    'dials_by_day': [{'day': d, 'dials': n} for d, n in sorted(by_day.items()) if d >= cut],
    'queue': sorted(queue_rows, key=lambda r: (r['dials'], r['last_dial'] or '')),
}, indent=1))
print('wrote juan/status.json', file=sys.stderr)
