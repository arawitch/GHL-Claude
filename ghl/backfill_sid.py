"""Write each contact's own GoHighLevel id into the "CS Course SID" field.

Why this exists: an SMS link to the course has to be a GHL trigger link,
because signalpilot.bot is carrier-blocked. A trigger link's destination URL
accepts contact merge fields, so it can be personalised - but GoHighLevel
offers no `contact.id` merge field, only name, email, phone, address, source
and custom fields. Putting the id into a custom field is the way to get it
into the link, which is what lets the course app identify the visitor and tag
them. See the trigger link memory for the proof that the click is per-contact.

    python3 ghl/backfill_sid.py "bootcamp registered"        # dry run
    python3 ghl/backfill_sid.py "bootcamp registered" --go    # write
    python3 ghl/backfill_sid.py --all --go                    # every contact

The value is the contact's own id, so this is idempotent: a contact already
holding the right value is skipped, and re-running costs one read per person
and no writes. The update merges custom fields rather than replacing them -
verified against a contact carrying two other fields before writing anything
in bulk - so nothing else on the record is touched.

Needs: GHL_SMS_API_KEY, GHL_SMS_LOCATION_ID.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ghl.client import GHLClient  # noqa: E402

FIELD_KEY = 'contact.cs_course_sid'
FIELD_NAME = 'CS Course SID'


def field_id(cl):
    """The custom field's id, looked up by key so a rename cannot break this."""
    # Not cl.get(): that helper adds locationId, which this endpoint rejects
    # with a 422 because the id is already in the path.
    r = cl.request('GET', '/locations/%s/customFields' % cl.location_id,
                   params={'model': 'contact'})
    for f in r.get('customFields', []):
        if f.get('fieldKey') == FIELD_KEY:
            return f['id']
    raise SystemExit('No custom field with key %s. Create "%s" (text) first.'
                     % (FIELD_KEY, FIELD_NAME))


def current_value(contact, fid):
    for f in contact.get('customFields') or []:
        if f.get('id') == fid:
            return f.get('value')
    return None


def main():
    args = [a for a in sys.argv[1:] if a not in ('--go', '--all')]
    go = '--go' in sys.argv
    every = '--all' in sys.argv
    if not every and not args:
        raise SystemExit(__doc__)

    cl = GHLClient(os.environ['GHL_SMS_API_KEY'], os.environ['GHL_SMS_LOCATION_ID'])
    fid = field_id(cl)
    filters = ([] if every else
               [{'field': 'tags', 'operator': 'eq', 'value': args[0]}])

    scanned = written = already = failed = 0
    for c in cl.search_contacts(filters=filters):
        scanned += 1
        cid = c['id']
        # The search payload already carries customFields, so the usual case
        # costs no extra request. Only fall back to reading the contact when
        # the key is missing, which matters at 49k contacts: one read each
        # would double the run and half the day's API budget.
        if 'customFields' in c:
            full = c
        else:
            try:
                full = cl.get('/contacts/%s' % cid).get('contact', {})
            except Exception as e:
                print('read %s failed: %s' % (cid, e), file=sys.stderr)
                failed += 1
                continue
        if current_value(full, fid) == cid:
            already += 1
            continue
        if not go:
            written += 1
            continue
        try:
            cl.request('PUT', '/contacts/%s' % cid,
                       json={'customFields': [{'id': fid, 'value': cid}]})
            written += 1
        except Exception as e:
            print('write %s failed: %s' % (cid, e), file=sys.stderr)
            failed += 1
        if written and written % 50 == 0:
            print('  %d written...' % written, file=sys.stderr)
            time.sleep(1)

    print('%s: %d scanned, %d %s, %d already correct, %d failed'
          % ('WROTE' if go else 'DRY RUN', scanned, written,
             'written' if go else 'would be written', already, failed))


if __name__ == '__main__':
    main()
