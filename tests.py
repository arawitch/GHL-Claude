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

from ghl import adattr, campaigns, reactivation, segments, sending, smstarget, sync, weekly
from ghl import webinarjam
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
    # "permanent" on SMS and RCS and therefore possible on Email. Add to this
    # set only alongside the constant, never instead of it.
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


# -- campaign ranking ----------------------------------------------------

def test_metric_extraction_is_shape_tolerant() -> None:
    """The statistics response shape is undocumented, so extraction must adapt."""
    print("\ncampaign metrics")
    shapes = [
        {"delivered": 100, "uniqueOpens": 40, "uniqueClicks": 10},
        {"stats": {"delivered": 100, "opened": 40, "clicked": 10}},
        {"data": [{"totalDelivered": 100, "opens": 40, "clicks": 10}]},
        {"result": {"nested": {"deliveredCount": 100, "openCount": 40, "clickCount": 10}}},
    ]
    for i, shape in enumerate(shapes):
        m = campaigns.extract_metrics(shape)
        check(f"shape {i} yields delivered/opens/clicks",
              (m.get("delivered"), m.get("opens"), m.get("clicks")) == (100, 40, 10),
              f"got {m}")

    check("unique counts win over totals",
          campaigns.extract_metrics({"uniqueOpens": 40, "totalOpens": 90})["opens"] == 40,
          "a rate built on total opens can exceed 100% and is not comparable")
    check("booleans are not mistaken for counters",
          "opens" not in campaigns.extract_metrics({"opened": True}))
    check("an empty payload yields no metrics", campaigns.extract_metrics({}) == {})


def test_ranking_excludes_rather_than_zeroes_missing_data() -> None:
    print("\ncampaign ranking")
    rows = [
        {"subject": "a", "open_rate": 30.0},
        {"subject": "b", "open_rate": 55.0},
        {"subject": "c", "open_rate": None},
        {"subject": "d", "open_rate": 12.0},
    ]
    ranked = campaigns.rank(rows, by="open_rate")
    check("ordered high to low", [r["subject"] for r in ranked] == ["b", "a", "d"])
    check("a send with no data is dropped, not ranked last",
          "c" not in [r["subject"] for r in ranked],
          "absent data and zero engagement are different findings")
    check("top truncates", len(campaigns.rank(rows, by="open_rate", top=2)) == 2)


def test_zero_delivery_does_not_crash_or_flatter() -> None:
    """Nov-Dec 2025 has real sends with 0 delivered; they must not divide by zero."""
    print("\nzero-delivery sends")

    class Stub:
        def get(self, path, **kw):
            if path.endswith("/statistics"):
                return {"delivered": 0, "opened": 0, "clicked": 0}
            raise AssertionError(path)

    sched = [{"id": "x", "name": "n", "subject": "s", "totalCount": 40000,
              "successCount": 0, "processed": 40000, "bulkActionVersion": "v2",
              "dateScheduled": 1762000000000}]
    rows = campaigns.build_rows(Stub(), sched)
    check("open_rate is None, not 0.0, when nothing was delivered",
          rows[0]["open_rate"] is None)
    check("such a send is excluded from the ranking",
          campaigns.rank(rows, by="open_rate") == [])


def test_bulk_threshold_and_counter_flag() -> None:
    print("\nbulk filtering")
    check("default bulk threshold is 3,000", campaigns.BULK_MIN_RECIPIENTS == 3000)
    v1 = {"bulkActionVersion": "v1", "processed": 0, "queuedCount": 6916}
    v2 = {"bulkActionVersion": "v2", "processed": 47746}
    check("v1 records are flagged as unusable", campaigns.has_usable_counters(v1) is False)
    check("v2 records with processed counts are usable",
          campaigns.has_usable_counters(v2) is True)


def test_an_unfinished_event_yields_only_registration():
    """attended_live is "No" for everyone before the session runs.

    Deriving absence from that marks every registrant a no-show days early and
    feeds them the replay sequence. This happened: 64 registrants were tagged
    absent seven hours before a 2 PM Pacific session.
    """
    row = {"attended_live": "No", "attended_replay": "No"}
    check("before the event only 'register' is returned",
          webinarjam.classify(row, event_finished=False) == ["register"],
          str(webinarjam.classify(row, event_finished=False)))
    check("after the event absence is derived",
          "absent" in webinarjam.classify(row, event_finished=True))


def test_zero_watch_time_is_not_a_view():
    """4 of the 10 10/1 replay viewers logged 00:00:00 -- opened and left.

    Replay watchers convert at 6.5% against 1.4% for registrants who watched
    nothing, so a zero-second open in the replay cohort hands a no-show the
    warmest follow-up in the sequence.
    """
    opened_and_left = {"attended_replay": "Yes", "time_replay": "00:00:00"}
    roles = webinarjam.classify(opened_and_left)
    check("a 0-second replay view does not earn the replay role",
          "replay" not in roles, str(roles))
    check("and it reads as absent instead", "absent" in roles, str(roles))

    real = {"attended_replay": "Yes", "time_replay": "00:25:00"}
    check("a 25-minute replay view does earn it",
          "replay" in webinarjam.classify(real))

    flash_live = {"attended_live": "Yes", "time_live": "00:00:03"}
    check("a 3-second live 'attendance' is not attendance",
          "attended" not in webinarjam.classify(flash_live),
          str(webinarjam.classify(flash_live)))


def test_ownership_skip_list_excludes_the_retired_fx_tags():
    """"new bot user" is the retired FX bot: 163 contacts, zero bot orders.

    Asserted as literals rather than against the constant, so widening the
    constant cannot quietly make this pass.
    """
    owns = {t.lower() for t in smstarget.OWNS_PITCHED_PRODUCT}
    for wrong in ("new bot user", "new bot", "bot installed", "new combo purchase",
                  "bot web invite", "flight path attended", "flight path absent"):
        check(f"{wrong!r} is not treated as ownership", wrong not in owns)
    for right in ("options bot sale", "options bot presale", "options auto trader",
                  "option and bot combo", "option bot combo", "flight path member"):
        check(f"{right!r} is treated as ownership", right in owns)


def test_phone_normalisation_rejects_junk_and_fixes_double_country_code():
    """The registration form accepts free text, and WJ prepends +1 blindly."""
    f = webinarjam.phone_of
    check("a plain 10-digit US number normalises",
          f({"phone_country_code": "+1", "phone_number": "704-779-5005"}) == "+17047795005")
    check("a survey answer in the phone field is rejected",
          f({"phone_number": "Iwanttobringinextracashbytradingoptions"}) is None)
    check("a bare hyphen is rejected", f({"phone_number": "-"}) is None)
    check("a truncated number is rejected",
          f({"phone_country_code": "+1", "phone_number": "3006"}) is None)
    check("a non-US country code is not given a leading 1",
          f({"phone_country_code": "+44", "phone_number": "7932149848"}) == "+447932149848")


class _FakeGHL:
    """A contact database small enough to assert against."""

    def __init__(self, tags_by_email: dict[str, list[str]]):
        self.db = {e: {"id": f"id-{e}", "tags": list(t)}
                   for e, t in tags_by_email.items()}
        self.location_id = "loc"
        self.added: list[tuple[str, list[str]]] = []
        self.removed: list[tuple[str, list[str]]] = []
        self.created: list[dict] = []

    def search_contacts(self, filters=None, **kw):
        want = filters[0]["value"]
        return [self.db[want]] if want in self.db else []

    def request(self, method, path, json=None, **kw):
        if path == "/contacts/":
            self.created.append(json)
            return {"contact": {"id": "new"}}
        cid = path.split("/")[2]
        (self.added if method == "POST" else self.removed).append((cid, json["tags"]))
        return {}


def test_contradictory_state_tags_are_cleared():
    """An evergreen room reuses one namespace, so tags must be re-asserted.

    marka797@gmail.com registered again having attended nothing, and still
    carried "everwebinar attended" and "everwebinar replay" from an earlier
    session -- the tags said he both attended and did not.
    """
    print("\nattendance state is re-asserted, not accumulated")
    ghl = _FakeGHL({"m@x.com": ["everwebinar attended", "everwebinar replay",
                                "everwebinar register", "10/1 attended"]})
    rep = sync.SyncReport()
    sync._write_one(ghl, ghl.db["m@x.com"],
                    ["everwebinar register", "everwebinar absent"], True, rep,
                    "main", set(), None,
                    ["everwebinar attended", "everwebinar replay"])
    removed = sorted(t for _, tags in ghl.removed for t in tags)
    check("the contradicted tags come off",
          removed == ["everwebinar attended", "everwebinar replay"], str(removed))
    check("another event's tags are untouched",
          "10/1 attended" not in removed, str(removed))
    added = sorted(t for _, tags in ghl.added for t in tags)
    check("the true state goes on", "everwebinar absent" in added, str(added))


def test_owners_are_recorded_but_not_prospected():
    """jmacfarlane watched 38 minutes and was tagged nothing, holding "uoo member".

    Recording what happened and deciding who to sell to are separate jobs.
    """
    print("\nownership withholds the prospect tag, not the record")
    owner = _FakeGHL({"o@x.com": ["uoo member"]})
    rep = sync.SyncReport()
    sync._write_one(owner, owner.db["o@x.com"], ["everwebinar attended"], True,
                    rep, "main", {"uoo member"}, "everwebinar prospect", [])
    added = sorted(t for _, tags in owner.added for t in tags)
    check("an owner still gets the attendance tag",
          added == ["everwebinar attended"], str(added))
    check("and is counted as skipped for prospecting", rep.skipped.get("main") == 1)

    lead = _FakeGHL({"l@x.com": []})
    rep2 = sync.SyncReport()
    sync._write_one(lead, lead.db["l@x.com"], ["everwebinar attended"], True,
                    rep2, "main", {"uoo member"}, "everwebinar prospect", [])
    added2 = sorted(t for _, tags in lead.added for t in tags)
    check("a non-owner gets both",
          added2 == ["everwebinar attended", "everwebinar prospect"], str(added2))


def test_missing_registrants_are_created_only_when_asked():
    """Two evergreen registrants who watched 29:55 and 14:30 had no record."""
    print("\ncreating contacts for registrants GHL has never seen")
    row = {"first_name": "K", "last_name": "W", "phone_country_code": "+1",
           "phone_number": "7274123088"}
    on = _FakeGHL({})
    rep2 = sync.SyncReport()
    sync._create_one(on, "new@x.com", row,
                     ["everwebinar attended", "everwebinar prospect"],
                     "everwebinar", True, rep2, "main")
    check("the contact is created and counted",
          rep2.created == 1 and len(on.created) == 1)
    made = on.created[0] if on.created else {}
    check("it carries the phone, normalised", made.get("phone") == "+17274123088",
          str(made.get("phone")))
    check("and both the attendance and prospect tags",
          sorted(made.get("tags") or []) ==
          ["everwebinar attended", "everwebinar prospect"], str(made.get("tags")))

    junk = _FakeGHL({})
    sync._create_one(junk, "j@x.com", {"phone_number": "Iwanttotradeoptions"},
                     ["everwebinar absent"], "everwebinar", True,
                     sync.SyncReport(), "main")
    check("a junk phone is omitted rather than written",
          "phone" not in (junk.created[0] if junk.created else {"phone": 1}))


def test_two_registrations_on_one_record_merge_rather_than_fight():
    """Attendance is a union: if any registration attended, the person did.

    Ricky Puckett registered for 10/1 twice on one phone number --
    cpdaltexuoo@gmail.com attended 50 minutes, cpdaltex@gmail.com did not show
    -- and only the second address has a GHL record, so both rows resolve to it.
    Written row by row, one set "10/1 attended" and the next removed it. The 50
    minutes was the half that lost.
    """
    print("\ntwo registrations landing on one contact")
    def collapse(*role_sets):
        roles = set().union(*role_sets)
        if "attended" in roles:          # mirrors sync()
            roles.discard("absent")
        return roles

    check("the union keeps attendance and drops absence",
          collapse({"register", "attended"}, {"register", "absent"})
          == {"register", "attended"})
    # "absent" means did not attend LIVE, so it coexists with "replay" -- that
    # pair is the no-show who later watched the recording, 21 of 9/24's
    # registrants and 16 of 10/1's. Collapsing on replay stripped all 77.
    check("a no-show who watched the replay keeps BOTH absent and replay",
          collapse({"register", "absent", "replay"})
          == {"register", "absent", "replay"},
          str(sorted(collapse({"register", "absent", "replay"}))))
    check("attending live still beats a second absent registration",
          collapse({"register", "attended", "replay"}, {"register", "absent"})
          == {"register", "attended", "replay"})
    roles = collapse({"register", "attended"}, {"register", "absent"})

    ghl = _FakeGHL({"r@x.com": ["10/1 absent"]})
    rep = sync.SyncReport()
    sync._write_one(ghl, ghl.db["r@x.com"], ["10/1 register", "10/1 attended"],
                    True, rep, "main", set(), None,
                    [f"10/1 {sync.SUFFIXES[r]}" for r in sync.STATE_ROLES
                     if r not in roles])
    added = sorted(t for _, tags in ghl.added for t in tags)
    removed = sorted(t for _, tags in ghl.removed for t in tags)
    check("the record ends up attended", "10/1 attended" in added, str(added))
    check("and the stale absence is cleared",
          removed == ["10/1 absent"], str(removed))
    check("replay is cleared too, since neither row watched one",
          "10/1 replay" not in added)



# -- ad attribution decoding ------------------------------------------------
# Three ways this quietly produces a plausible answer: it annotates a lead that
# never came from an ad, it reports a pre-July ad's unrelated utm_term id as a
# missing lookup, or it re-annotates a contact a previous run already did and
# leaves two notes on the record.

AD_MAP = {
    "campaigns": {"120249892092040617": "JH Schedules - 10/9/26"},
    "adsets": {"120249892092060617": "Broad"},
    "ads": {"120249892092000617": "Ad 1"},
}


def test_id_based_attribution_decodes_to_names():
    decoded = adattr.decode({
        "utmSource": "ig", "utmMedium": "paid",
        "campaign": "120249892092040617",
        "utmTerm": "120249892092060617",
        "utmContent": "120249892092000617",
        "url": "https://ad.universityofoptions.com/schedule/sta?fbclid=abc",
    }, AD_MAP)
    check("campaign id decodes", decoded["campaign"] == "JH Schedules - 10/9/26", str(decoded))
    check("ad set id decodes", decoded["adset"] == "Broad", str(decoded))
    check("ad id decodes", decoded["creative"] == "Ad 1", str(decoded))
    check("platform is spelled out", decoded["platform"] == "Instagram", str(decoded))
    check("raw ids are kept alongside the names",
          decoded["campaign_id"] == "120249892092040617"
          and decoded["ad_id"] == "120249892092000617", str(decoded))
    check("query string is dropped from the landing page",
          decoded["landing_page"].endswith("/schedule/sta"), str(decoded))
    check("nothing is reported as missing", decoded["undecoded"] == "", str(decoded))


def test_name_based_attribution_is_left_alone():
    # Pre-July ads sent names, put the ad set name in utm_medium, and an id in
    # utm_term that is not an ad set at all. That id must not be reported.
    decoded = adattr.decode({
        "utmSource": "facebook", "utmMedium": "Testing Phase",
        "campaign": "*2026 VSL Campaign*",
        "utmTerm": "120241611943720617",
        "utmContent": "Dan- Multi Creative",
    }, AD_MAP)
    check("existing campaign name survives", decoded["campaign"] == "*2026 VSL Campaign*",
          str(decoded))
    check("ad set comes from utm_medium", decoded["adset"] == "Testing Phase", str(decoded))
    check("an unrelated utm_term id is not flagged as missing",
          decoded["undecoded"] == "", str(decoded))


def test_unknown_id_is_reported_not_invented():
    decoded = adattr.decode({"campaign": "129999999999999999",
                             "utmContent": "128888888888888888",
                             "utmMedium": "paid", "utmSource": "fb"}, AD_MAP)
    check("unknown ids stay as ids", decoded["campaign"] == "129999999999999999", str(decoded))
    check("unknown ids are listed for the lookup table",
          decoded["undecoded"] == "129999999999999999,128888888888888888", str(decoded))


def test_non_ad_traffic_is_not_annotated():
    for attribution in ({"sessionSource": "Direct traffic", "medium": "calendar"},
                        {"medium": "csv_import"},
                        {}):
        check("no note for traffic with no ad behind it",
              adattr.decode(attribution, AD_MAP) is None, str(attribution))


def test_a_second_run_skips_what_the_first_one_wrote():
    done = {"customFields": [{"id": adattr.FIELD_IDS["ad_name"], "value": "Ad 1"}]}
    blank = {"customFields": [{"id": adattr.FIELD_IDS["ad_name"], "value": ""}]}
    check("annotated contact is skipped", adattr.already_annotated(done) is True)
    check("empty field is not mistaken for done", adattr.already_annotated(blank) is False)
    check("contact with no fields is not skipped", adattr.already_annotated({}) is False)


def test_shipped_lookup_table_covers_the_live_campaigns():
    table = adattr.load_map()
    for campaign in ("120249892092040617", "120248828199470617"):
        check(f"live campaign {campaign} is in the shipped map",
              campaign in table["campaigns"])
    check("map has the ads for the live campaigns",
          len(table["ads"]) >= 20, str(len(table["ads"])))


def test_spreads_bot_section_only_when_an_account_is_found():
    import json, os, tempfile
    from ghl import spreads_bot, spreads_usage
    found = {"version": "a1720-4", "status": "found", "matched_on": "email", "query": {"email": "j@x.com"},
             "account": {"user_id": 7, "email": "j@x.com", "name": "Jane", "created_at": "2026-09-01T14:00:00+00:00",
                         "last_login": "", "last_login_ip": "", "live_approved_at": "", "broker": "tradier",
                         "broker_connected_at": ""},
             "ip_events": [{"at": "2026-09-10T14:59:00+00:00", "ip": "203.0.113.7", "user_agent": "M",
                            "event": "Accepted the Live Trading Authorization", "detail": "", "source": "x"}],
             "ip_usage": [], "sessions": {}, "visits": [], "history_since": "", "settings_dates": [],
             "settings_changes": [], "trades": {"count": 2, "contracts": 2, "trading_days": 2, "first": "2026-09-03",
             "last": "2026-09-04", "by_kind": {"Spreads Bot (placed at broker)": 2},
             "by_month": [{"month": "2026-09", "Spreads Bot (placed at broker)": 2}], "dates": []},
             "activity": {"last_activity": "2026-09-04"}, "limits": []}
    packs = [{"submissions": [{"ip": "203.0.113.7"}, {"ip": ""}]}]
    pasted = "noise\n" + spreads_usage.JSON_BEGIN + "\n" + json.dumps(found) + "\n" + spreads_usage.JSON_END
    r = spreads_bot.from_paste(pasted)
    check("a pasted lookup parses", r.get("status") == "found")
    blocks = spreads_bot.blocks_for_pdf(r, packs)
    heads = [b["heading"] for b in blocks]
    check("the IP match block is built from the CRM form IPs",
          "IP address match: CRM opt-in vs Spreads Bot" in heads and
          any("203.0.113.7" in str(b["rows"]) for b in blocks if b["heading"].startswith("IP address match")))
    nf = dict(found, status="not_found", account={})
    check("no account: nothing goes in the pack", spreads_bot.blocks_for_pdf(nf, packs) == [])
    check("an error: nothing goes in the pack",
          spreads_bot.blocks_for_pdf(spreads_bot.from_paste("not json"), packs) == [])
    check("the closer is told why", spreads_bot.page_line(nf).startswith("Spreads Bot: not added."))
    saved = {k: os.environ.pop(k, None) for k in (spreads_bot.URL_VAR, spreads_bot.TOKEN_VAR)}
    try:
        check("not configured: no fetch", spreads_bot.fetch("j@x.com") is None)
        os.environ[spreads_bot.URL_VAR] = "https://example.invalid/api/proof-of-use"
        os.environ[spreads_bot.TOKEN_VAR] = "t" * 40
        seen = {}

        class _R:
            status_code, text = 200, json.dumps(found)

        def _get(url, params=None, headers=None, timeout=None):
            seen.update(url=url, params=params, headers=headers)
            return _R()
        got = spreads_bot.fetch("j@x.com", session=types.SimpleNamespace(get=_get))
        check("fetch sends the email and the bearer token",
              got.get("status") == "found" and seen["params"]["email"] == "j@x.com"
              and seen["headers"]["Authorization"] == "Bearer " + "t" * 40 and seen["params"].get("logs") == "1")
        class _R404:
            status_code, text = 404, "Not Found"
        bad = spreads_bot.fetch("j@x.com", session=types.SimpleNamespace(get=lambda *a, **k: _R404()))
        check("a refused fetch is an error, not a section", bad.get("status") == "error"
              and spreads_bot.blocks_for_pdf(bad, packs) == [])
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    try:
        import reportlab  # noqa: F401
    except ImportError:
        print("  skip  PDF render (reportlab not installed)")
        return
    from ghl import dispute
    out = os.path.join(tempfile.mkdtemp(), "t.pdf")
    dispute.render_pdf([], out, spreads_blocks=blocks)
    check("the PDF renders with the section", os.path.getsize(out) > 1000)


def main() -> int:
    for fn in [test_id_based_attribution_decodes_to_names,
               test_name_based_attribution_is_left_alone,
               test_unknown_id_is_reported_not_invented,
               test_non_ad_traffic_is_not_annotated,
               test_a_second_run_skips_what_the_first_one_wrote,
               test_shipped_lookup_table_covers_the_live_campaigns,
               test_401_is_two_different_errors,
               test_email_dnd_covers_every_on_status,
               test_suppression_tags_reach_every_send_tier,
               test_validated_tier_reports_missing_data,
               test_plan_surfaces_failures,
               test_track_b_excludes_registrants,
               test_export_columns_cannot_be_reimported_as_tags,
               test_all_of_flattens_nested_lists,
               test_metric_extraction_is_shape_tolerant,
               test_ranking_excludes_rather_than_zeroes_missing_data,
               test_zero_delivery_does_not_crash_or_flatter,
               test_bulk_threshold_and_counter_flag,
               test_an_unfinished_event_yields_only_registration,
               test_zero_watch_time_is_not_a_view,
               test_ownership_skip_list_excludes_the_retired_fx_tags,
               test_phone_normalisation_rejects_junk_and_fixes_double_country_code,
               test_contradictory_state_tags_are_cleared,
               test_owners_are_recorded_but_not_prospected,
               test_missing_registrants_are_created_only_when_asked,
               test_two_registrations_on_one_record_merge_rather_than_fight,
               test_spreads_bot_section_only_when_an_account_is_found]:
        fn()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s): " + ", ".join(FAILURES))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
