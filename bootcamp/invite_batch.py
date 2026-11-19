"""Tag the next N people from the bootcamp list so the invite texts go out.

Adds `bootcamp invited` and `bootcamp sms invited`. The first is what the
PROP reply handler filters on; the second is the invite drip's trigger, and
it has to be a NEW tag because 11,102 people already carry `bootcamp invited`
from the email send and GHL will not fire a tag-added trigger for a tag the
contact already has.

PACING LIVES HERE. This GHL account's workflow builder has no Drip Mode
setting (checked Settings, the Contact-tag trigger panel and the Advanced
builder), so the only throttle we control is how fast contacts get tagged.
The workflow's time window (11am-7pm Eastern, every day) decides WHEN a text
may go out; this script decides how fast they enter, in bursts of BURST with
GAP seconds between them.

Resumable: a cursor file records how far down the ranked list we have read.

Screening, all live reads, never the CSV snapshot:
  * suppression tags, `dnd`, and the SMS opt-out sub-field
  * already invited or already registered
  * a booked or confirmed call, and a two-way SMS exchange in the last 14
    days - reusing reengage/active_sales_screen.py, so an invite never lands
    on a lead a closer is mid-deal with

Usage:  python3 bootcamp/invite_batch.py <count> [--go]
Needs:  GHL_SMS_API_KEY, GHL_SMS_LOCATION_ID
"""
import sys, os, csv, json, time, pathlib, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ghl.client import GHLClient
from reengage.active_sales_screen import is_rep_working_them

TAGS = ['bootcamp invited', 'bootcamp sms invited']
TRIGGER = 'bootcamp sms invited'
LIST = '/mnt/project-files/bootcamp/bootcamp-sms-list-2026-11-17.csv'
CURSOR = '/mnt/project-files/bootcamp/invite-progress.json'
LOG = '/mnt/project-files/bootcamp/invite-log.csv'

SUPPRESS = {'do not contact', 'never send', 'ai exclude', 'complainer',
            'ai complaint', 'do not text'}

BURST = 20       # tag this many, then wait
GAP = 900        # seconds between bursts -> ~80/hour, ~640 over an 8h window


def messages_for(cl, contact_id):
    try:
        conv = cl.request('GET', '/conversations/search',
                          params={'locationId': cl.location_id,
                                  'contactId': contact_id})
    except Exception:
        return []
    out = []
    for cv in conv.get('conversations', []) or []:
        try:
            payload = cl.request('GET', '/conversations/%s/messages' % cv['id'],
                                 params={'limit': 50})
        except Exception:
            continue
        msgs = payload.get('messages', {})
        msgs = msgs.get('messages', msgs) if isinstance(msgs, dict) else msgs
        out.extend(msgs or [])
    return out


def save_cursor(i):
    json.dump({'next_index': i, 'updated_at': datetime.datetime.now(
        datetime.timezone.utc).isoformat(timespec='seconds')},
        open(CURSOR, 'w'), indent=1)


def save_log(rows):
    if not rows:
        return
    new = not os.path.exists(LOG)
    with open(LOG, 'a', newline='') as f:
        w = csv.writer(f)
        if new:
            w.writerow(['invited_at', 'sms_contact_id', 'email', 'rank', 'why'])
        stamp = datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec='seconds')
        for cid, email, rank, why in rows:
            w.writerow([stamp, cid, email, rank, why])


def main():
    want = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0
    go = '--go' in sys.argv
    if want <= 0:
        sys.exit('usage: invite_batch.py <count> [--go]')

    cl = GHLClient(os.environ['GHL_SMS_API_KEY'], os.environ['GHL_SMS_LOCATION_ID'])
    rows = list(csv.DictReader(open(LIST)))
    start = json.load(open(CURSOR)).get('next_index', 0) if os.path.exists(CURSOR) else 0
    if start >= len(rows):
        print('list exhausted: %d of %d already read' % (start, len(rows)))
        return

    stats = dict.fromkeys(('tagged', 'already', 'registered', 'suppressed',
                           'dnd', 'nophone', 'rep_working', 'missing', 'error'), 0)
    done, pending, i = [], [], start
    while i < len(rows) and stats['tagged'] < want:
        r = rows[i]
        i += 1
        cid = r['sms_contact_id']
        try:
            c = cl.get('/contacts/%s' % cid).get('contact') or {}
        except Exception:
            stats['error'] += 1
            continue
        if not c.get('id'):
            stats['missing'] += 1
            continue
        tags = list(c.get('tags') or [])
        low = {t.strip().lower() for t in tags}
        if TRIGGER in low:
            stats['already'] += 1
            continue
        if any(t.startswith('bootcamp regist') for t in low):
            stats['registered'] += 1
            continue
        if low & SUPPRESS:
            stats['suppressed'] += 1
            continue
        if not c.get('phone'):
            stats['nophone'] += 1
            continue
        sms = (c.get('dndSettings') or {}).get('SMS') or {}
        if c.get('dnd') or sms.get('status') in ('permanent', 'active'):
            stats['dnd'] += 1
            continue
        reason = is_rep_working_them(c, messages_for(cl, cid))
        if reason:
            stats['rep_working'] += 1
            continue
        if not go:
            stats['tagged'] += 1
            done.append((cid, c.get('email'), r['rank'], r['why']))
            continue
        try:
            cl.request('POST', '/contacts/%s/tags' % cid, json={'tags': TAGS})
            stats['tagged'] += 1
            done.append((cid, c.get('email'), r['rank'], r['why']))
            pending.append((cid, c.get('email'), r['rank'], r['why']))
            time.sleep(0.15)
        except Exception:
            stats['error'] += 1
            continue
        if len(pending) >= BURST:
            save_log(pending)
            save_cursor(i)
            pending = []
            if stats['tagged'] < want and i < len(rows):
                print('  %d tagged, sleeping %ds' % (stats['tagged'], GAP),
                      flush=True)
                time.sleep(GAP)

    print('read rows %d..%d of %d' % (start, i, len(rows)))
    for k in ('tagged', 'already', 'registered', 'suppressed', 'dnd',
              'nophone', 'rep_working', 'missing', 'error'):
        print('  %-11s %d' % (k, stats[k]))

    if not go:
        print('DRY RUN - nothing written. Add --go to send.')
        return

    save_log(pending)
    save_cursor(i)
    print('cursor now at %d; %d rows left' % (i, len(rows) - i))


if __name__ == '__main__':
    main()
