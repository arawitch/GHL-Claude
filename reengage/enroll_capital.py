"""Enrol the next N people from the $5k+ capital list into the SMS qualifier.

Adds the `ai qualifying v2` tag, which is the qualifier workflow's trigger.
Everything else - business-hours gate, 15-per-15-minutes drip, opt-out and
complaint exits - is handled inside the workflow, so this script only decides
WHO and HOW MANY.

Resumable: a cursor file records how far down the list we have read, so each
run picks up where the last one stopped. Every contact is re-checked live
against GHL before being tagged, because the source CSV's reachability flags
are a snapshot and people acquire suppressions between runs.

The exclusion check runs against BOTH sub-accounts. The two accounts are
mirrors of one list but their tag sets are not identical, and ownership is
sometimes recorded in only one of them: on 2026-11-05 sixty-two people were
flagged as owners in the main/EMAIL account with no such tag in SMS. The
workflow's own guard can only see SMS tags, so the cross-account check has to
happen here, at enrolment, matched on lowercased email.

Usage:  python3 reengage/enroll_capital.py <count> [--go]
Needs:  GHL_SMS_API_KEY, GHL_SMS_LOCATION_ID,
        GHL_EMAIL_API_KEY, GHL_EMAIL_LOCATION_ID
"""
import sys, os, csv, json, time, pathlib, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ghl.client import GHLClient

TAG = 'ai qualifying v2'
LIST = '/mnt/project-files/reengagement/capital-5k-plus-clean-2026-11-04.csv'
CURSOR = '/mnt/project-files/reengagement/enroll-progress.json'
LOG = '/mnt/project-files/reengagement/enroll-log.csv'

# Anyone carrying one of these must never be pitched the high-ticket call:
# they already own it, are a current member, asked to cancel or refund, or
# have been suppressed. See the audience-gap notes - "does not include" with
# several tags in one GHL condition is OR-ish, so the check lives here.
#
# Deliberately NOT in this set: the Options Navigator ownership tags
# `options member`, `options navigator purchased`, `options nav new purchase`
# and `options nav 4k new purchase`. Audry's call on 2026-11-05: a Navigator
# owner should only be pulled out if they own the spreads bot TOO. Since
# every spreads-bot tag below already excludes outright (her 2026-11-02
# rule), "owns both" is covered by the bot half alone and needs no extra
# condition. A Navigator owner who does not own the bot stays in the
# campaign on purpose - the automated side is the thing being sold to them.
EXCL = {t.strip() for t in """do not contact|never send|ai exclude|complainer|ai complaint
new bot user|new bot|bot installed|options bot presale|options auto trader
options navigator purchased|options nav new purchase|options nav 4k new purchase
futures 4k new purchase|futures new purchase|new options purchase|new combo purchase
oh purchase|june oh purchase|bootcamp purchase|njc workshop purchase|purchased workshop
purchased tv bundle|automated forex bots|booked automated forex bots
grandfathered - active subscription|current masters member|flight path member
prop bootcamp member|marketmentor|market mentor|foundingmembermarketmentor
gold member|fs member|futures oh vtf access|futures vtf access|options vtf access
am options cancel|am options cancel request|cancelled masters program
uoo vsl: cancelled|marketmentorappremoval""".replace('\n', '|').split('|') if t.strip()}


def excluded_emails_in_email_account():
    """Lowercased emails carrying any exclusion tag in the main/EMAIL account.

    One search per tag, because GHL's contact search ORs several tags in a
    single filter and there is no "has any of these tags" that also returns
    which one matched. Roughly forty short calls, a few seconds in total.
    """
    cl = GHLClient(os.environ['GHL_EMAIL_API_KEY'],
                   os.environ['GHL_EMAIL_LOCATION_ID'])
    loc = os.environ['GHL_EMAIL_LOCATION_ID']
    out = set()
    for tag in sorted(EXCL):
        page = 1
        while True:
            r = cl.request('POST', '/contacts/search', json={
                'locationId': loc, 'page': page, 'pageLimit': 100,
                'filters': [{'field': 'tags', 'operator': 'eq', 'value': tag}]})
            cs = r.get('contacts', []) or []
            for c in cs:
                e = (c.get('email') or '').strip().lower()
                if e:
                    out.add(e)
            if len(cs) < 100:
                break
            page += 1
    return out


def main():
    want = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0
    go = '--go' in sys.argv
    if want <= 0:
        sys.exit('usage: enroll_capital.py <count> [--go]')

    cl = GHLClient(os.environ['GHL_SMS_API_KEY'], os.environ['GHL_SMS_LOCATION_ID'])
    rows = list(csv.DictReader(open(LIST)))
    start = 0
    if os.path.exists(CURSOR):
        start = json.load(open(CURSOR)).get('next_index', 0)
    if start >= len(rows):
        print('list exhausted: %d of %d already read' % (start, len(rows)))
        return

    other = excluded_emails_in_email_account()
    print('exclusion tags in the main account cover %d emails' % len(other))

    stats = {'tagged': 0, 'already': 0, 'excluded': 0, 'excl_other': 0,
             'dnd': 0, 'nophone': 0, 'missing': 0, 'error': 0}
    done, i = [], start
    while i < len(rows) and stats['tagged'] < want:
        r = rows[i]
        i += 1
        cid = r['sms_contact_id']
        try:
            c = cl.get('/contacts/%s' % cid).get('contact') or {}
        except Exception as e:
            stats['error'] += 1
            continue
        if not c.get('id'):
            stats['missing'] += 1
            continue
        tags = [t for t in (c.get('tags') or [])]
        low = {t.lower() for t in tags}
        if TAG in low:
            stats['already'] += 1
            continue
        if low & EXCL:
            stats['excluded'] += 1
            continue
        if (c.get('email') or '').strip().lower() in other:
            stats['excl_other'] += 1
            continue
        if not c.get('phone'):
            stats['nophone'] += 1
            continue
        # The SMS opt-out lives in a sub-field; top-level `dnd` misses it.
        sms = (c.get('dndSettings') or {}).get('SMS') or {}
        if c.get('dnd') or sms.get('status') in ('permanent', 'active'):
            stats['dnd'] += 1
            continue
        if not go:
            stats['tagged'] += 1
            done.append((cid, c.get('email'), r['capital_band']))
            continue
        try:
            cl.request('PUT', '/contacts/%s' % cid, json={'tags': tags + [TAG]})
            stats['tagged'] += 1
            done.append((cid, c.get('email'), r['capital_band']))
            time.sleep(0.15)
        except Exception:
            stats['error'] += 1

    print('read rows %d..%d of %d' % (start, i, len(rows)))
    for k in ('tagged', 'already', 'excluded', 'excl_other', 'dnd', 'nophone',
              'missing', 'error'):
        print('  %-9s %d' % (k, stats[k]))

    if not go:
        print('DRY RUN - nothing written. Add --go to enrol.')
        return

    json.dump({'next_index': i, 'updated_at': datetime.datetime.now(
        datetime.timezone.utc).isoformat(timespec='seconds')}, open(CURSOR, 'w'), indent=1)
    new = not os.path.exists(LOG)
    with open(LOG, 'a', newline='') as f:
        w = csv.writer(f)
        if new:
            w.writerow(['enrolled_at', 'sms_contact_id', 'email', 'capital_band'])
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
        for cid, email, band in done:
            w.writerow([stamp, cid, email, band])
    print('cursor now at %d; %d rows left in the list' % (i, len(rows) - i))


if __name__ == '__main__':
    main()
