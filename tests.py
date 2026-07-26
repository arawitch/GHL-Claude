#!/usr/bin/env python3
"""Offline tests for the parts that fail quietly.

    python3 tests.py

No network and no pytest. Everything here is either pure filter construction or
a stubbed transport, because the bugs worth catching in this toolkit are the
ones that produce a plausible answer rather than an error: a suppression guard
that stops matching, a send list that comes back empty because its input field
is unpopulated, a slot that drops out of a send plan.
"""

from __future__ import annotations

import time
import types

from ghl import reactivation, segments, sending, weekly
from ghl.client import GHLClient, GHLError, GHLScopeError

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
    else:
        FAILURES.append(label)
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


# -- transport -----------------------------------------------------------

class _Resp:
    def __init__(self, code: int, text: str):
        self.status_code, self.text, self.headers = code, text, {}

    @property
    def content(self) -> bytes:
        return self.text.encode()

    def json(self) -> dict:
        return {"ok": True}


def _client(responses: list[_Resp]) -> GHLClient:
    c = GHLClient(token="pit-test", location_id="loc")
    it = iter(responses)
    c.session = types.SimpleNamespace(request=lambda *a, **k: next(it), headers={})
    return c


TIMEOUT_BODY = '{"statusCode":401,"message":"Command timed out"}'
SCOPE_BODY = '{"statusCode":401,"message":"The token is not authorized for this scope."}'


def test_401_is_two_different_errors() -> None:
    """GHL answers 401 for a slow query and for a bad scope. Only one retries."""
    print("\n401 classification")
    slept = []
    real_sleep, time.sleep = time.sleep, slept.append
    try:
        c = _client([_Resp(401, TIMEOUT_BODY), _Resp(401, TIMEOUT_BODY), _Resp(200, "{}")])
        check("a timed-out 401 is retried until it succeeds",
              c.request("GET", "/x") == {"ok": True})

        c = _client([_Resp(401, SCOPE_BODY), _Resp(200, "{}")])
        try:
            c.request("GET", "/x")
            check("a scope 401 raises rather than retrying", False)
        except GHLScopeError:
            check("a scope 401 raises rather than retrying", True)

        c = _client([_Resp(401, TIMEOUT_BODY)] * 4)
        try:
            c.request("GET", "/x", attempts=4)
            check("a timed-out 401 still raises once retries run out", False)
        except GHLScopeError:
            check("a timed-out 401 still raises once retries run out", False,
                  "misclassified as a scope error")
        except GHLError:
            check("a timed-out 401 still raises once retries run out", True)
    finally:
        time.sleep = real_sleep

    check("cli.py can catch a scope error as GHLError",
          issubclass(GHLScopeError, GHLError))
    check("a scope error explains how to fix itself",
          "Private Integrations" in str(GHLScopeError(401, "GET", "/x", SCOPE_BODY)))


# -- suppression ---------------------------------------------------------

def _email_dnd_values(filters: list[dict], operator: str) -> set[str]:
    return {f["value"] for f in filters
            if f.get("field") == "dndSettings.Email.status" and f.get("operator") == operator}


def test_email_dnd_covers_every_on_status() -> None:
    """Per-channel DND is not a boolean; "permanent" also means DND is on."""
    print("\nemail DND guard")
    # Asserted literally rather than against EMAIL_DND_ON_STATUSES: MAILABLE is
    # generated from that constant, so comparing the two only proves the loop
    # ran. These are the values observed live -- "active" on the Email channel,
    # "permanent" on SMS and RCS and therefore possible on Email.
    expected = {"active", "permanent"}
    check("MAILABLE excludes every status that means DND is on",
          _email_dnd_values(segments.MAILABLE, "not_eq") == expected,
          f"got {_email_dnd_values(segments.MAILABLE, 'not_eq')}, expected {expected}")
    check("the shared status list still lists both",
          set(segments.EMAIL_DND_ON_STATUSES) == expected)

    check("MAILABLE never asserts a status positively",
          not _email_dnd_values(segments.MAILABLE, "eq"),
          "eq on an unused status matches every contact, silently disabling the filter")

    or_filters = reactivation.never_upload()[0]["filters"]
    check("never_upload catches every DND-on status too",
          _email_dnd_values(or_filters, "eq") == set(segments.EMAIL_DND_ON_STATUSES))

    check("verify_candidates requires every DND-on status to be absent",
          _email_dnd_values(reactivation.verify_candidates()[0]["filters"], "not_eq")
          == set(segments.EMAIL_DND_ON_STATUSES))

    check("the two reactivation cohorts agree on what DND means",
          _email_dnd_values(or_filters, "eq")
          == _email_dnd_values(reactivation.verify_candidates()[0]["filters"], "not_eq"))


def test_suppression_tags_reach_every_send_tier() -> None:
    print("\nsuppression tags")
    for name, builder in [("safe", sending.safe_send), ("engaged", sending.engaged),
                          ("validated", sending.validated)]:
        blob = repr(builder())
        missing = [t for t in sending.SUPPRESSION_TAGS if repr(t) not in blob]
        check(f"{name} excludes all {len(sending.SUPPRESSION_TAGS)} suppression tags",
              not missing, f"missing: {missing}")
        check(f"{name} carries the mailability guard", "dndSettings.Email.status" in blob)

    check("the worst tags are present at all",
          all(t in sending.SUPPRESSION_TAGS for t in ("spamtrap", "complainer", "do not email")))


def test_validated_tier_reports_missing_data() -> None:
    """An empty validated tier must be distinguishable from a clean one."""
    print("\nvalidEmail availability")

    class Stub:
        def __init__(self, n): self.n = n
        def count_contacts(self, filters=None): return self.n

    check("no validEmail data is detected", sending.validation_data_available(Stub(0)) is False)
    check("populated validEmail is detected", sending.validation_data_available(Stub(5)) is True)


# -- send plan -----------------------------------------------------------

def test_plan_surfaces_failures() -> None:
    print("\nweekly send plan")

    class Failing:
        def __init__(self): self.n = 0
        def count_contacts(self, filters=None):
            self.n += 1
            if self.n == 3:
                raise GHLScopeError(401, "POST", "/contacts/search", SCOPE_BODY)
            return 100

    rows = weekly.plan(Failing(), "7/24")
    broken = [r for r in rows if r[2] < 0]
    check("a failed slot is reported, not counted as zero", len(broken) == 1)
    check("the failure carries its reason", bool(broken and broken[0][3]))
    check("healthy slots keep their counts",
          all(n == 100 for _, _, n, _ in rows if n >= 0))

    class Boom:
        def count_contacts(self, filters=None): raise ValueError("bug in a filter builder")

    try:
        weekly.plan(Boom(), "7/24")
        check("a programming error is not swallowed as a missing tag", False)
    except ValueError:
        check("a programming error is not swallowed as a missing tag", True)

    for reminders in ("webinarjam", "ghl"):
        slots = weekly.slots_for(reminders)
        check(f"{reminders} slot names are unique",
              len({s for s, _, _ in slots}) == len(slots))


def test_track_b_excludes_registrants() -> None:
    print("\ntrack separation")
    blob = repr(weekly.unregistered("7/24"))
    check("track B excludes registrants",
          "'not_eq'" in blob and "7/24 register" in blob)
    check("track B inherits suppression rather than reimplementing it",
          all(repr(t) in blob for t in sending.SUPPRESSION_TAGS))
    check("track A is exactly the registrant tag",
          "7/24 register" in repr(weekly.registered("7/24")))


# -- export --------------------------------------------------------------

def test_export_columns_cannot_be_reimported_as_tags() -> None:
    print("\nexport columns")
    check("the tag column is not named 'tags'", "tags" not in segments.EXPORT_COLUMNS)
    check("the tag column warns against importing it",
          "tags_REFERENCE_DO_NOT_IMPORT" in segments.EXPORT_COLUMNS)
    check("email is exported", "email" in segments.EXPORT_COLUMNS)


def test_all_of_flattens_nested_lists() -> None:
    print("\nfilter construction")
    out = segments.all_of({"a": 1}, [{"b": 2}, {"c": 3}])
    check("all_of flattens list arguments", len(out[0]["filters"]) == 3)
    check("all_of builds an AND group", out[0]["group"] == "AND")
    check("mailable() folds the guard in",
          len(segments.mailable({"a": 1})[0]["filters"]) == 1 + len(segments.MAILABLE))


def main() -> int:
    for fn in [test_401_is_two_different_errors,
               test_email_dnd_covers_every_on_status,
               test_suppression_tags_reach_every_send_tier,
               test_validated_tier_reports_missing_data,
               test_plan_surfaces_failures,
               test_track_b_excludes_registrants,
               test_export_columns_cannot_be_reimported_as_tags,
               test_all_of_flattens_nested_lists]:
        fn()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s): " + ", ".join(FAILURES))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
