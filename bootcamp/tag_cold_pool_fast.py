"""Same audience as tag_cold_pool.py, tagged with concurrent workers.

Re-reads the two waves live and skips anyone who already carries the tag, so
it is safe to run after a partial serial run. Threads are capped well inside
GHL's ~100 requests / 10s per location, with backoff on 429.
"""
import os, sys, time, json, pathlib, threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ghl.client import GHLClient

TAG = 'bc email cold nov30'
SOURCES = ['email reeng w2', 'email reeng w1']
SKIP = {'bootcamp invited', 'bootcamp registered', 'do not email',
        'do not contact', 'never send', TAG}
STATE = '/mnt/project-files/bootcamp/cold-pool-tagging.json'
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
                if done % 500 == 0:
                    json.dump({'tagged': done, 'errors': err}, open(STATE, 'w'))
                    print('  %d tagged' % done, flush=True)
            return
        except Exception as e:
            if '429' in str(e) or '502' in str(e) or '503' in str(e):
                time.sleep(1.5 * (attempt + 1))
                continue
            break
    with lock:
        err += 1


def main():
    cl = GHLClient(os.environ['GHL_EMAIL_API_KEY'], 'IyorbIIbJLsMLaqy8j1P')
    seen, targets = set(), []
    for src in SOURCES:
        for c in cl.search_contacts(
                filters=[{'field': 'tags', 'operator': 'eq', 'value': src}]):
            if c['id'] in seen:
                continue
            seen.add(c['id'])
            low = {t.strip().lower() for t in (c.get('tags') or [])}
            if low & SKIP or not (c.get('email') or '').strip():
                continue
            em = (c.get('dndSettings') or {}).get('Email') or {}
            if c.get('dnd') or em.get('status') in ('permanent', 'active'):
                continue
            targets.append(c['id'])
    print('remaining to tag: %d' % len(targets), flush=True)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for cid in targets:
            pool.submit(tag_one, cl, cid)
    json.dump({'tagged': done, 'errors': err}, open(STATE, 'w'))
    print('tagged %d, errors %d, %.1f min' % (done, err, (time.time() - t0) / 60))


if __name__ == '__main__':
    main()
