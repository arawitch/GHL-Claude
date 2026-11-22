"""Tag the TradeFundrr broadcast audience in the main/EMAIL account.

Everyone on the engaged list or the bootcamp cold pool who has NOT registered
for the bootcamp, because the broadcast email asks people to sign up and a
registrant must not receive it.

The tag avoids a "bootcamp" prefix: the live dashboard counts every tag
starting with that word.

Usage:  python3 bootcamp/tag_broadcast_audience.py [--go]
"""
import os, sys, time, json, pathlib, threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ghl.client import GHLClient

TAG = 'bc tfr broadcast'
SOURCES = ['current email list', 'bc email cold nov30']
SKIP = {'bootcamp registered', 'do not email', 'do not contact', 'never send', TAG}
STATE = '/mnt/project-files/bootcamp/broadcast-tagging.json'
WORKERS = 8

lock = threading.Lock()
done = err = 0


def tag_one(cl, cid):
    global done, err
    for attempt in range(5):
        try:
            cl.request('POST', '/contacts/%s/tags' % cid, json={'tags': [TAG]})
            with lock:
                done += 1
                if done % 1000 == 0:
                    json.dump({'tagged': done, 'errors': err}, open(STATE, 'w'))
                    print('  %d tagged' % done, flush=True)
            return
        except Exception as e:
            if any(c in str(e) for c in ('429', '502', '503')):
                time.sleep(1.5 * (attempt + 1))
                continue
            break
    with lock:
        err += 1


def main():
    go = '--go' in sys.argv
    cl = GHLClient(os.environ['GHL_EMAIL_API_KEY'], 'IyorbIIbJLsMLaqy8j1P')
    seen, targets = set(), []
    skipped = dict.fromkeys(('dupe', 'registered', 'suppressed', 'noemail', 'dnd', 'already'), 0)
    for src in SOURCES:
        for c in cl.search_contacts(
                filters=[{'field': 'tags', 'operator': 'eq', 'value': src}]):
            if c['id'] in seen:
                skipped['dupe'] += 1
                continue
            seen.add(c['id'])
            low = {t.strip().lower() for t in (c.get('tags') or [])}
            if TAG in low:
                skipped['already'] += 1
                continue
            if 'bootcamp registered' in low:
                skipped['registered'] += 1
                continue
            if low & SKIP:
                skipped['suppressed'] += 1
                continue
            if not (c.get('email') or '').strip():
                skipped['noemail'] += 1
                continue
            e = (c.get('dndSettings') or {}).get('Email') or {}
            if c.get('dnd') or e.get('status') in ('permanent', 'active'):
                skipped['dnd'] += 1
                continue
            targets.append(c['id'])

    print('read %d unique' % len(seen))
    for k, v in skipped.items():
        print('  %-11s %d' % (k, v))
    print('  to tag     %d' % len(targets))
    if not go:
        print('DRY RUN - add --go to tag.')
        return

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for cid in targets:
            pool.submit(tag_one, cl, cid)
    json.dump({'tagged': done, 'errors': err}, open(STATE, 'w'))
    print('tagged %d, errors %d, %.1f min, tag "%s"'
          % (done, err, (time.time() - t0) / 60, TAG))


if __name__ == '__main__':
    main()
