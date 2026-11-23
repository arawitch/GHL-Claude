"""Collect Credit Spreads course funnel results into one JSON document.

Two sources, because neither one knows everything:

  * GoHighLevel SMS sub-account tags. The Replit course app tags the contact
    as they move through the funnel, so a tag count is a count of *known*
    people - someone who signed up and can be followed up with.
  * The course app's own private report. It counts raw events including
    anonymous visits, which GHL never sees, so it is the only place the real
    page_view / lesson_start / lesson_120s totals live.

Written as:

    <outdir>/course/status.json

Usage:  python3 dashboard/collect_course.py [outdir]
Needs:  GHL_SMS_API_KEY, GHL_SMS_LOCATION_ID, and optionally
        COURSE_REPORT_URL (the private report link, key included). Without it
        the report half is left out rather than guessed at.
"""
import os, sys, json, re, csv, io, datetime, pathlib, urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ghl.client import GHLClient
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from people import tagged

# Every tag the funnel writes, in the order a person meets them. The label is
# what the dashboard shows; the tag is what the course app and the DM workflow
# actually write, so a rename in GoHighLevel has to be mirrored here.
FUNNEL = [
    ('dm_sent',      'cs course dm sent',        'DM sent'),
    ('signed_up',    'cs course signup',         'Signed up'),
    ('delivered',    'cs course delivered',      'Course link sent'),
    ('l1_opened',    'cs lesson 1 opened',       'Lesson 1 opened'),
    ('l1_watched',   'cs lesson 1 watched',      'Lesson 1 watched'),
    ('l2_opened',    'cs lesson 2 opened',       'Lesson 2 opened'),
    ('l2_watched',   'cs lesson 2 watched',      'Lesson 2 watched'),
    ('l3_opened',    'cs lesson 3 opened',       'Lesson 3 opened'),
    ('l3_watched',   'cs lesson 3 watched',      'Lesson 3 watched'),
    ('guide',        'cs guide downloaded',      'Guide downloaded'),
    ('cheat_sheet',  'cs cheat sheet downloaded','Cheat sheet downloaded'),
    ('offer_click',  'cs offer clicked',         'Offer clicked'),
]

# "Watched" is the course app's 2-minute visible-tab timer, which is the
# closest thing to real viewership available: the page cannot see whether the
# Descript player is actually playing, so a tab left open on a lesson counts.
# Say so on the dashboard rather than calling it a view.


def tag_total(cl, loc, tag):
    """How many contacts carry this tag right now.

    /contacts/search reports `total` for the whole filter, so one call with
    pageLimit 1 answers the question without walking every contact.
    """
    r = cl.post('/contacts/search', {
        'locationId': loc, 'pageLimit': 1, 'page': 1,
        'filters': [{'field': 'tags', 'operator': 'eq', 'value': tag}]})
    t = r.get('total')
    return int(t) if isinstance(t, (int, float)) else len(r.get('contacts') or [])


def report_numbers(url):
    """Event totals and the lesson funnel from the course app's own report.

    The report only renders HTML (format=json returns the same page), and its
    CSV holds the subscriber table but not the event totals, so the totals are
    read out of the HTML tables. If the shape of that page changes, this
    returns what it could find and leaves the rest out - it never guesses.
    """
    req = urllib.request.Request(url, headers={'User-Agent': 'uoo-dashboard'})
    html = urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace')

    def cells(row):
        return [re.sub(r'<[^>]+>', '', c).strip()
                for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S)]

    events, lessons = {}, {}
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        c = cells(row)
        if len(c) == 2 and re.fullmatch(r'[a-z0-9_]+', c[0]) and c[1].isdigit():
            events[c[0]] = int(c[1])
        if len(c) == 4 and c[0] in ('1', '2', '3') and c[1].isdigit():
            lessons[c[0]] = {'distinct_viewers': int(c[1]),
                             'known_subscribers': int(c[2])}
    known = re.search(r'·\s*([\d,]+)\s+known subscribers', html)
    out = {'events': events, 'lessons': lessons}
    if known:
        out['known_subscribers'] = int(known.group(1).replace(',', ''))
    return out


# ---------------------------------------------------------------------------
# Bootcamp warm-up cohort
#
# The free course is being sent to bootcamp registrants as pre-work, and the
# `cs ...` tags are shared with the 29,000-person email re-engagement waves, so
# a bare tag count cannot answer "are the registrants watching it". The answer
# is the intersection: `bootcamp registered` AND each course tag.
#
# Two complications, both handled here rather than in the page:
#   * 94.8% of contacts exist in BOTH sub-accounts, so counting each account
#     and adding would roughly double the cohort. The two lists are pulled in
#     full and deduped on email, falling back to phone.
#   * the course app writes its tag to whichever account answers for the id in
#     the link, so one person's registration tag and course tags can sit on
#     different records. Tags are unioned per person before counting.
# The cohort is small (low hundreds), so this is two paged searches, not a
# per-contact walk.
WARMUP_TAG = 'bootcamp registered'
EXCLUDE_TAGS = ('do not contact', 'do not email', 'never send')


def warmup_cohort(clients, subs=None):
    """Course progress for the people carrying WARMUP_TAG, deduped.

    `clients` is a list of (account_label, GHLClient). `subs` is the course
    report's subscriber table keyed by subscriber id, which is the only place
    a *click* shows up: landing on the course page writes no GoHighLevel tag,
    so without it someone who opened the link and bounced is indistinguishable
    from someone who never clicked. A person is matched on any of their
    contact ids, since the link may carry either account's.

    Returns None when no account carries the tag at all, so the panel stays
    off the page until the warm-up actually goes out.
    """
    people, partial = tagged(clients, WARMUP_TAG)
    if not people:
        return None

    course_tags = [(key, tag, lab) for key, tag, lab in FUNNEL
                   if tag.startswith('cs lesson') or key in
                   ('guide', 'cheat_sheet', 'offer_click')]
    rows = [{'key': key, 'tag': tag, 'label': lab,
             'count': sum(1 for r in people.values() if tag in r['tags'])}
            for key, tag, lab in course_tags]

    subs = subs or {}
    clicked = opened = 0
    for r in people.values():
        # Named `seen`, not `rows`: this used to shadow the funnel rows built
        # above and shipped an empty tag table to the dashboard.
        seen = [subs[i] for i in r['ids'] if i in subs]
        if seen:
            clicked += 1
            if any(x.get('lessons') for x in seen):
                opened += 1
    touched = sum(1 for r in people.values()
                  if any(t.startswith('cs ') for t in r['tags'])
                  or any(i in subs for i in r['ids']))
    unreachable = sum(1 for r in people.values()
                      if r['dnd'] or any(t in r['tags'] for t in EXCLUDE_TAGS))
    return {
        'tag': WARMUP_TAG,
        'registered': len(people),
        'in_both_accounts': sum(1 for r in people.values() if len(r['accounts']) > 1),
        'clicked_through': clicked,
        'opened_a_lesson': opened,
        'any_course_activity': touched,
        'no_course_activity': len(people) - touched,
        'excluded_from_sending': unreachable,
        'funnel': rows,
    }


def report_subscribers(url):
    """The report's subscriber table, keyed by subscriber id.

    The HTML report shows the same rows, but the CSV is a stable contract
    where the HTML is a layout that can be restyled, so the CSV is what the
    click count is built on. `lessons_opened` is a comma-separated list and
    is empty for someone who loaded the page and started nothing - which is
    exactly the state that has no GoHighLevel tag.
    """
    sep = '&' if '?' in url else '?'
    req = urllib.request.Request(url + sep + 'format=csv',
                                 headers={'User-Agent': 'uoo-dashboard'})
    text = urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace')
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        sid = (row.get('subscriber_id') or '').strip()
        if not sid:
            continue
        lessons = [x.strip() for x in (row.get('lessons_opened') or '').split(',')
                   if x.strip()]
        out[sid] = {'lessons': lessons,
                    'last_activity': (row.get('last_activity_utc') or '').strip()}
    return out


def main():
    outdir = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else 'dashout')
    cl = GHLClient(os.environ['GHL_SMS_API_KEY'], os.environ['GHL_SMS_LOCATION_ID'])
    loc = os.environ['GHL_SMS_LOCATION_ID']

    doc = {
        'updated_at': datetime.datetime.now(datetime.timezone.utc)
                      .isoformat(timespec='seconds'),
        'funnel': [],
    }
    for key, tag, label in FUNNEL:
        try:
            doc['funnel'].append({'key': key, 'tag': tag, 'label': label,
                                  'count': tag_total(cl, loc, tag)})
        except Exception as e:
            print('tag %s failed: %s' % (tag, e), file=sys.stderr)
            doc['funnel'].append({'key': key, 'tag': tag, 'label': label,
                                  'count': None})

    clients = [('sms', cl)]
    if os.environ.get('GHL_EMAIL_API_KEY') and os.environ.get('GHL_EMAIL_LOCATION_ID'):
        clients.append(('email', GHLClient(os.environ['GHL_EMAIL_API_KEY'],
                                          os.environ['GHL_EMAIL_LOCATION_ID'])))
    url = os.environ.get('COURSE_REPORT_URL')
    subs = {}
    if url:
        try:
            subs = report_subscribers(url)
        except Exception as e:
            print('subscriber csv failed: %s' % e, file=sys.stderr)
    try:
        warm = warmup_cohort(clients, subs)
        if warm:
            doc['warmup'] = warm
    except Exception as e:
        print('warmup cohort failed: %s' % e, file=sys.stderr)

    if url:
        try:
            doc['report'] = report_numbers(url)
        except Exception as e:
            print('report fetch failed: %s' % e, file=sys.stderr)

    (outdir / 'course').mkdir(parents=True, exist_ok=True)
    (outdir / 'course' / 'status.json').write_text(json.dumps(doc, indent=1))
    print(json.dumps(doc, indent=1))


if __name__ == '__main__':
    main()
