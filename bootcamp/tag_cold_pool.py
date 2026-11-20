"""Tag the bootcamp cold-pool email audience in the main/EMAIL account.

The audience is the two re-engagement waves MINUS anyone who already got the
bootcamp invite email on 2026-11-16 (the engaged list, which overlaps wave 1
by 9,807), minus registrants and anyone suppressed.

The tag deliberately does NOT start with "bootcamp": the live dashboard counts
every tag beginning with that word, so a 19k audience tag would wreck the
Bootcamp tab's registration numbers.

Usage:  python3 bootcamp/tag_cold_pool.py [--go]
"""
import os, sys, time, json, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ghl.client import GHLClient

TAG = 'bc email cold nov30'
SOURCES = ['email reeng w2', 'email reeng w1']
SKIP_TAGS = {'bootcamp invited', 'bootcamp registered', 'do not email',
             'do not contact', 'never send', TAG}
STATE = '/mnt/project-files/bootcamp/cold-pool-tagging.json'


def fetch(cl, tag):
    # offset paging is capped at page * pageLimit <= 10,000, so use the
    # searchAfter cursor helper instead.
    return cl.search_contacts(
        filters=[{'field': 'tags', 'operator': 'eq', 'value': tag}])


def main():
    go = '--go' in sys.argv
    cl = GHLClient(os.environ['GHL_EMAIL_API_KEY'], 'IyorbIIbJLsMLaqy8j1P')

    seen, targets = set(), []
    stats = dict.fromkeys(('already', 'invited', 'registered', 'suppressed',
                           'noemail', 'dnd', 'dupe'), 0)
    for src in SOURCES:
        for c in fetch(cl, src):
            cid = c['id']
            if cid in seen:
                stats['dupe'] += 1
                continue
            seen.add(cid)
            low = {t.strip().lower() for t in (c.get('tags') or [])}
            if TAG in low:
                stats['already'] += 1
                continue
            if 'bootcamp invited' in low:
                stats['invited'] += 1
                continue
            if 'bootcamp registered' in low:
                stats['registered'] += 1
                continue
            if low & SKIP_TAGS:
                stats['suppressed'] += 1
                continue
            if not (c.get('email') or '').strip():
                stats['noemail'] += 1
                continue
            em = (c.get('dndSettings') or {}).get('Email') or {}
            if c.get('dnd') or em.get('status') in ('permanent', 'active'):
                stats['dnd'] += 1
                continue
            targets.append(cid)

    print('read %d unique contacts across %s' % (len(seen), SOURCES))
    for k, v in stats.items():
        print('  %-11s %d' % (k, v))
    print('  to tag     %d' % len(targets))
    if not go:
        print('DRY RUN - add --go to tag.')
        return

    done = err = 0
    for cid in targets:
        try:
            cl.request('POST', '/contacts/%s/tags' % cid, json={'tags': [TAG]})
            done += 1
        except Exception:
            err += 1
        if done % 250 == 0:
            json.dump({'tagged': done, 'errors': err, 'target': len(targets)},
                      open(STATE, 'w'), indent=1)
            print('  %d / %d' % (done, len(targets)), flush=True)
        time.sleep(0.12)
    json.dump({'tagged': done, 'errors': err, 'target': len(targets)},
              open(STATE, 'w'), indent=1)
    print('tagged %d, errors %d, tag "%s"' % (done, err, TAG))


if __name__ == '__main__':
    main()
