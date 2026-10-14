#!/bin/bash
# Installs what `python3 tests.py` and `python3 cli.py` need, so a cloud
# session can run them without a first-failure round trip.
#
# The toolkit has no dependency manifest: `requests` is its only third-party
# import, and .github/workflows/webinar-sync.yml installs exactly that. This
# keeps the two in step rather than introducing a second source of truth.
set -euo pipefail

# Local checkouts are already set up by whoever made them; this is only for
# the fresh containers cloud sessions get.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

python3 -m pip install --quiet --disable-pip-version-check --root-user-action=ignore requests

# The credentials live in the environment, so a session that starts without
# them will fail on the first API call rather than at import. Say so now,
# while there is somewhere to say it.
missing=()
for var in GHL_API_KEY GHL_LOCATION_ID; do
  [ -n "${!var:-}" ] || missing+=("$var")
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "note: ${missing[*]} not set -- offline tests still run, live API calls will not" >&2
fi

# Import-only check: catches a broken checkout now instead of mid-task. The
# suite itself is offline and fast, but running it here would hide a genuine
# test failure inside session startup.
python3 -c "import ghl.client, ghl.sync, ghl.webinarjam" >/dev/null
