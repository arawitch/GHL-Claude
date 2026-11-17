"""Build the SMS invite list for the Nov 30 prop firm bootcamp.

Who can be texted, ranked by how likely they are to show up, capped at what
the send window can actually deliver.

Eligibility is checked in BOTH sub-accounts. The SMS account decides whether a
text can be sent at all (its DND state is independent of the main account's),
and the main/EMAIL account is where ownership and suppression tags are
sometimes recorded alone - on 2026-11-05, 62 people were flagged as owners in
the main account with no such tag in SMS.

Ranking, strongest first:
  +6  attended a past live webinar          strongest show-up signal there is
  +4  weekly newsletter subscriber          13.6x predictor of a $4k+ buyer
  +3  clicked something recently
  +2  opened something recently
  +2  already registered interest in the bootcamp era (bootcamp opt in etc.)
  +1  has a first name (a text that can be personalised)
  -3  already enrolled in the SMS qualifier (mid-conversation with the bot)

Nothing is sent or tagged. This writes a file.

Usage:  python3 bootcamp/build_sms_list.py [outdir]
Needs:  GHL_SMS_API_KEY, GHL_SMS_LOCATION_ID,
        GHL_EMAIL_API_KEY, GHL_EMAIL_LOCATION_ID
"""
import os, sys, csv, re, pathlib, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ghl.client import GHLClient
from ghl.segments import all_of
from ghl.sending import SUPPRESSION_TAGS

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '/mnt/project-files/bootcamp')

# Owners, members, refund/cancel requests and anything suppressed. Same set the
# qualifier enroller uses, plus the email suppression tags: a bootcamp invite
# going to someone who asked to be left alone is the same mistake in either
# channel.
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
uoo vsl: cancelled|marketmentorappremoval|remove from bootcamp""".replace('\n', '|').split('|') if t.strip()}
EXCL |= {t.lower() for t in SUPPRESSION_TAGS}

ATTENDED = re.compile(r'attend', re.I)
CLICKED = re.compile(r'^clicked|clicked', re.I)
OPENED = re.compile(r'^opened|opened', re.I)

TEXTABLE = [
    {'field': 'phone', 'operator': 'exists'},
    {'field': 'dnd', 'operator': 'eq', 'value': False},
    *[{'field': 'dndSettings.SMS.status', 'operator': 'not_eq', 'value': s}
      for s in ('active', 'permanent')],
]


def excluded_emails_in_email_account():
    """Lowercased emails carrying any exclusion tag in the main/EMAIL account."""
    cl = GHLClient(os.environ['GHL_EMAIL_API_KEY'], os.environ['GHL_EMAIL_LOCATION_ID'])
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


def us_mobile(phone):
    d = re.sub(r'\D', '', phone or '')
    if len(d) == 11 and d.startswith('1'):
        d = d[1:]
    if len(d) != 10:
        return None
    if d.startswith('800') or d.startswith('8005551212'):
        return None
    return '+1' + d


def score(tags, first):
    tl = [t.lower() for t in tags]
    s = 0
    why = []
    if any(ATTENDED.search(t) for t in tl):
        s += 6; why.append('attended a webinar')
    if 'weekly newsletter subscriber' in tl:
        s += 4; why.append('newsletter')
    if any(CLICKED.search(t) for t in tl):
        s += 3; why.append('clicked')
    if any(OPENED.search(t) for t in tl):
        s += 2; why.append('opened')
    if any(t.startswith('bootcamp') or 'prop' in t for t in tl):
        s += 2; why.append('past bootcamp interest')
    if (first or '').strip():
        s += 1
    if 'ai qualifying v2' in tl:
        s -= 3; why.append('in the qualifier')
    return s, ', '.join(why)


def main():
    cl = GHLClient(os.environ['GHL_SMS_API_KEY'], os.environ['GHL_SMS_LOCATION_ID'])
    print('reading exclusion tags from the main account ...', file=sys.stderr)
    other = excluded_emails_in_email_account()
    print('  %d emails excluded there' % len(other), file=sys.stderr)

    stats = {'seen': 0, 'excl_sms': 0, 'excl_email_acct': 0, 'bad_phone': 0,
             'registered': 0, 'dupe': 0, 'kept': 0}
    seen_phones = set()
    rows = []
    for c in cl.search_contacts(filters=all_of(*TEXTABLE)):
        stats['seen'] += 1
        if stats['seen'] % 5000 == 0:
            print('  %d read, %d kept' % (stats['seen'], stats['kept']), file=sys.stderr)
        tags = c.get('tags') or []
        tl = {t.lower() for t in tags}
        if tl & EXCL:
            stats['excl_sms'] += 1; continue
        if 'bootcamp registered' in tl:
            stats['registered'] += 1; continue
        email = (c.get('email') or '').strip().lower()
        if email and email in other:
            stats['excl_email_acct'] += 1; continue
        phone = us_mobile(c.get('phone'))
        if not phone:
            stats['bad_phone'] += 1; continue
        if phone in seen_phones:
            stats['dupe'] += 1; continue
        seen_phones.add(phone)
        s, why = score(tags, c.get('firstName'))
        rows.append({
            'sms_contact_id': c.get('id'),
            'first_name': c.get('firstName') or '',
            'last_name': c.get('lastName') or '',
            'phone': phone,
            'email': c.get('email') or '',
            'score': s,
            'why': why,
            'in_qualifier': 'yes' if 'ai qualifying v2' in tl else '',
            'date_added': (c.get('dateAdded') or '')[:10],
        })
        stats['kept'] += 1

    rows.sort(key=lambda r: (-r['score'], r['date_added'] or ''), reverse=False)
    for i, r in enumerate(rows, 1):
        r['rank'] = i
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.date.today().isoformat()
    path = OUT / ('bootcamp-sms-list-%s.csv' % stamp)
    with path.open('w', newline='', encoding='utf-8') as fh:
        cols = ['rank'] + [c for c in rows[0] if c != 'rank']
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print('\n'.join('%-18s %d' % kv for kv in stats.items()), file=sys.stderr)
    print('wrote %s (%d rows)' % (path, len(rows)))
    buckets = {}
    for r in rows:
        buckets[r['score']] = buckets.get(r['score'], 0) + 1
    for s in sorted(buckets, reverse=True):
        print('  score %2d: %d' % (s, buckets[s]))


if __name__ == '__main__':
    main()
