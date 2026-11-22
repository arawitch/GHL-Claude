"""Copy the `bootcamp registered` tag from the SMS account into the EMAIL one.

Registrations land in whichever account the person came through: the text
invite tags them in SMS, the registration page in EMAIL. Anything that emails
registrants has to be sent from the EMAIL account, so the tag has to exist
there too. Matches on email first, then on the last 10 digits of the phone,
because the two accounts often hold different addresses for one person.

Usage:  python3 bootcamp/sync_registrants.py [--go]
"""
import os, re, sys, csv, time, pathlib, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ghl.client import GHLClient

TAG = 'bootcamp registered'
OUT = '/mnt/project-files/bootcamp/bootcamp-registrants-%s.csv'


def digits(p):
    d = re.sub(r'\D', '', p or '')
    return d[-10:] if len(d) >= 10 else ''


def main():
    go = '--go' in sys.argv
    sms = GHLClient(os.environ['GHL_SMS_API_KEY'], os.environ['GHL_SMS_LOCATION_ID'])
    em = GHLClient(os.environ['GHL_EMAIL_API_KEY'], 'IyorbIIbJLsMLaqy8j1P')

    want = list(sms.search_contacts(
        filters=[{'field': 'tags', 'operator': 'eq', 'value': TAG}]))
    have = list(em.search_contacts(
        filters=[{'field': 'tags', 'operator': 'eq', 'value': TAG}]))
    print('SMS registrants %d, already tagged in EMAIL %d' % (len(want), len(have)))

    tagged_emails = {(c.get('email') or '').lower() for c in have if c.get('email')}
    tagged_phones = {digits(c.get('phone')) for c in have if digits(c.get('phone'))}

    todo, missing = [], []
    for c in want:
        e = (c.get('email') or '').strip().lower()
        p = digits(c.get('phone'))
        if (e and e in tagged_emails) or (p and p in tagged_phones):
            continue
        match = None
        for field, value in (('email', e), ('phone', c.get('phone'))):
            if not value:
                continue
            try:
                r = em.request('POST', '/contacts/search', json={
                    'locationId': em.location_id, 'pageLimit': 1,
                    'filters': [{'field': field, 'operator': 'eq', 'value': value}]})
                match = (r.get('contacts') or [None])[0]
            except Exception:
                match = None
            if match:
                break
        (todo if match else missing).append((c, match))

    print('to tag in EMAIL %d, no match found %d' % (len(todo), len(missing)))
    for c, _ in missing:
        print('   unmatched: %s %s' % (c.get('email'), c.get('phone')))
    if not go:
        print('DRY RUN - add --go to tag.')
        return

    ok = err = 0
    for _, m in todo:
        try:
            em.request('POST', '/contacts/%s/tags' % m['id'], json={'tags': [TAG]})
            ok += 1
            time.sleep(0.12)
        except Exception:
            err += 1
    print('tagged %d, errors %d' % (ok, err))

    stamp = datetime.date.today().isoformat()
    rows = {}
    for c in want + have:
        key = (c.get('email') or '').lower() or digits(c.get('phone')) or c['id']
        rows.setdefault(key, c)
    path = OUT % stamp
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['email', 'phone', 'first_name', 'last_name'])
        for c in sorted(rows.values(), key=lambda x: (x.get('email') or '')):
            w.writerow([c.get('email', ''), c.get('phone', ''),
                        c.get('firstName', ''), c.get('lastName', '')])
    print('wrote %s (%d unique)' % (path, len(rows)))


if __name__ == '__main__':
    main()
