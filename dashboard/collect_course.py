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
import os, sys, json, re, datetime, pathlib, urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ghl.client import GHLClient

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

    url = os.environ.get('COURSE_REPORT_URL')
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
