"""Shared vocabulary for picking setter-call targets out of the two GHL accounts."""
import re, datetime

TODAY = datetime.datetime(2026, 10, 19, tzinfo=datetime.timezone.utc)

# --- product ownership: tags that mean the person already bought one of the three ---
OWN_BOT = ["bot installed", "new bot", "new bot user", "option and bot combo", "option bot combo",
           "options bot sale", "new combo purchase", "bot customer", "4/16 bot check"]
OWN_NAV = ["options navigator purchased", "options nav new purchase", "options nav 4k new purchase",
           "new options purchase", "options member", "options vtf access"]
OWN_FUT = ["futures new purchase", "futures 4k new purchase", "futures vtf access",
           "futures oh vtf access", "fs member", "futures member"]
OWN_GENERIC = ["customer", "purchased", "uoo member", "won", "uoo vsl: won", "oh purchase",
               "june oh purchase", "gold member", "flight path member", "current masters member",
               "prop bootcamp member", "fx customer", "purchased tv bundle", "bootcamp purchase",
               "njc frontend buyer", "njc workshop purchase", "ready for install", "bot"]
OWNERSHIP = {"options bot": OWN_BOT, "options navigator": OWN_NAV, "futures": OWN_FUT,
             "paying customer": OWN_GENERIC}

# --- cannot or should not be called ---
NOCALL_TAGS = ["dnd", "do not call", "bad number", "no/bad number", "wrong number", "spam likely",
               "spamtrap", "invalid contact", "verified bad", "bad data", "seed account"]
DISQUALIFY_TAGS = ["unqualified", "bad lead", "bad fit", "total loser", "zz probe",
                   "test webhook", "webhook test 2", "webhook test 3"]

# --- pipeline stages, by name, grouped by what they tell us -------------------
STAGE_OWNED = ["closed", "purchased", "completed purchase", "won", "in the trading room",
               "new bot customer", "bot installed", "ready for install", "review call booked",
               "review call completed", "new futures member", "futures support issues",
               "bot swaps", "account swaps", "ticket completed", "ticket complete",
               "on going tickets", "closed tickets", "urgent issues", "normal issues",
               "working tickets", "questions", "tech support", "set up appointment booked",
               "verbal agreement to purchase", "pay link sent", "bootcamp- joined"]
STAGE_BOOKED = ["2. booked appointment", "booked appointment", "appointment made", "scheduled",
                "booked", "booked (in woosender)", "scheduled meeting with closer",
                "bootcamp- call booked", "3. showed", "showed", "showed "]
STAGE_DEAD = ["unqualified", "disqualified", "bad lead", "invalid contact", "no/bad number",
              "lost"]
STAGE_ACTIVE = ["1. new lead", "new lead", "lead", "lead ", "responded", "responded ", "engaged",
                "follow up", "followed up", "5. followed up", "optin lead", "qualified",
                "bootcamp- engaged", "hotlist", "pitched", "sent live trading link",
                "set link", "sent for closer", "move to drip campaign", "price check zone",
                "not ready yet", "bad timing", "bad timing/maybe later", "follow up (setter)",
                "sent follow up info", "need classification"]

# --- engagement tag shapes ----------------------------------------------------
DATE_TAG = re.compile(r"^(\d{1,2})/(\d{1,2})\b(.*)$")
ATTEND_WORDS = {"attended": 3, "attendee": 3, "live": 3, "highly engaged": 3, "showed": 3,
                "replay": 2, "watched replay": 2, "register": 1, "registrant": 1, "registered": 1,
                "prospect": 1, "absent": 0, "absentee": 0, "no-show": 0}
CLICK_WORDS = ["click", "opened", "open "]
REPLY_TAGS = ["replied", "responded", "replied to cta", "outbound engaged", "engaged",
              "hot email lead", "hot webinar lead", "hot web leads", "hotlead", "hotlist",
              "#hotlist", "interested", "potential", "warm"]

def tag_date(tag):
    """Date behind a tag like '10/1 attended', read as the most recent such date on or before today."""
    m = DATE_TAG.match(tag)
    if not m:
        return None
    mo, da = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12 and 1 <= da <= 31):
        return None
    for year in (TODAY.year, TODAY.year - 1, TODAY.year - 2):
        try:
            d = datetime.datetime(year, mo, da, tzinfo=datetime.timezone.utc)
        except ValueError:
            return None
        if d <= TODAY:
            return d
    return None

def webinar_role(tag):
    """('attended'|'replay'|'register'|'absent', date) for a dated webinar tag, else None."""
    d = tag_date(tag)
    if d is None:
        return None
    rest = DATE_TAG.match(tag).group(3).strip()
    for word, weight in sorted(ATTEND_WORDS.items(), key=lambda kv: -len(kv[0])):
        if word in rest:
            return word, weight, d
    return None

def days_ago(iso):
    if not iso:
        return None
    s = str(iso).replace("Z", "+00:00")
    try:
        d = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return (TODAY - d).days

def digits(phone):
    return re.sub(r"\D", "", phone or "")

def callable_phone(phone):
    n = digits(phone)
    if len(n) == 11 and n.startswith("1"):
        n = n[1:]
    if len(n) != 10:
        return None                       # non-US / malformed, Juan can't dial it reliably
    if n[0] in "01" or n[3] in "01":
        return None                       # invalid NANP area/exchange code
    if len(set(n)) <= 2:
        return None                       # 5555555555 and friends
    return "+1" + n
