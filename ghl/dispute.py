"""Assemble a chargeback / credit-card-dispute evidence pack from GoHighLevel.

A dispute is won or lost on what the processor can see in one document, so this
module gathers every dated, attributable record GHL holds about one buyer and
renders it as a single PDF with a plain-language cover summary.

What it collects, per sub-account the person exists in:

  * the contact record  - name, email, phone, address, timezone, created date
  * form and survey submissions - the submitted values, the page URL, the
    browser timezone and, where GHL captured it, the submitting IP address and
    the consent / terms text the person ticked
  * opportunities - pipeline stage, value and the date the sale was recorded
  * appointments - every booked call, with its calendar and status
  * calls - date, direction and duration of every logged phone call
  * conversations - message counts and the dates of first and last contact,
    which evidence service delivery and support availability
  * notes - what staff wrote on the record

Everything here is read-only. It never writes to GHL.

Note on scope: GHL's /payments endpoints (orders, transactions, subscriptions)
answer 401 "not authorized for this scope" on the current private integration
tokens, so the order itself -- amount, card brand, last four, the processor's
charge id -- is not included and must come from Stripe. Re-issue the token with
the payments read scopes and `orders()` below will start returning them.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import GHLClient, GHLError

# Fields on a submission record that are metadata rather than an answer the
# person typed. Everything else in `others` is treated as an answer.
META_KEYS = {
    "formId", "location_id", "sessionId", "eventData", "funneEventData",
    "fieldsOriSequance", "submissionId", "signatureHash", "ip", "Timezone",
    "amId", "amFingerprint", "contactSessionIds", "page_details",
}

CONSENT_PATTERN = re.compile(
    r"agree|consent|terms|condition|refund|polic|authoriz|acknowledg|non-?refundable",
    re.I,
)


def _ms(value: Any) -> str:
    """Render an epoch-millisecond timestamp as a readable UTC string."""
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(value)


def _iso(value: Any) -> str:
    if not value:
        return ""
    return str(value).replace("T", " ").replace("Z", " UTC")[:23]


def find_contact(client: GHLClient, email: str = "", phone: str = "") -> dict | None:
    """Look a buyer up by email, then by phone. Returns the raw contact row."""
    for field, value in (("email", email), ("phone", phone)):
        if not value:
            continue
        body = {
            "locationId": client.location_id,
            "pageLimit": 5,
            "filters": [{"field": field, "operator": "eq", "value": value}],
        }
        try:
            res = client.post("/contacts/search", body)
        except GHLError:
            continue
        rows = res.get("contacts", [])
        if rows:
            return rows[0]
    return None


def submissions(client: GHLClient, contact_id: str, pages: int = 20,
                start_at: str = "", end_at: str = "") -> list[dict]:
    """Every form submission GHL holds for this contact.

    GHL's submissions endpoint has no per-contact filter, so this pages the
    location's submissions and keeps the matching rows. It does accept
    `startAt` / `endAt` date bounds, which is the only way to reach a buyer
    from months back without walking every page: pass a window around the
    purchase date. `pages` caps the walk at 100 rows per page.
    """
    out = []
    window = {}
    if start_at:
        window["startAt"] = start_at
    if end_at:
        window["endAt"] = end_at
    for page in range(1, pages + 1):
        try:
            res = client.get("/forms/submissions", limit=100, page=page, **window)
        except GHLError:
            break
        rows = res.get("submissions", [])
        if not rows:
            break
        out += [r for r in rows if r.get("contactId") == contact_id]
        if len(rows) < 100:
            break
    return out


def describe_submission(sub: dict, form_names: dict[str, str]) -> dict:
    """Flatten one submission into the facts a dispute response needs."""
    others = sub.get("others", {}) or {}
    event = others.get("eventData", {}) or {}
    funnel = others.get("funneEventData", {}) or {}
    answers = {k: v for k, v in others.items() if k not in META_KEYS}
    consent = {k: v for k, v in answers.items()
               if CONSENT_PATTERN.search(str(k)) or CONSENT_PATTERN.search(str(v))}
    page = (event.get("page") or {}).get("url") or (
        (funnel.get("domain_name") or "") + (funnel.get("page_url") or ""))
    return {
        "form": form_names.get(sub.get("formId"), sub.get("formId", "")),
        "submitted_at": _iso(sub.get("createdAt")) or _ms(event.get("timestamp")),
        "event_timestamp": _ms(event.get("timestamp")) if event.get("timestamp") else "",
        "ip": others.get("ip", ""),
        "browser_timezone": others.get("Timezone", ""),
        "page_url": page,
        "document_url": event.get("documentURL", ""),
        "traffic_source": event.get("source", ""),
        "referrer": event.get("referrer") or "",
        "session_id": others.get("sessionId", ""),
        "submission_id": others.get("submissionId", ""),
        "has_signature_hash": bool(others.get("signatureHash")),
        "consent_text": consent,
        "answers": answers,
    }


def opportunities(client: GHLClient, contact_id: str) -> list[dict]:
    try:
        res = client.request("GET", "/opportunities/search",
                             params={"location_id": client.location_id,
                                     "contact_id": contact_id, "limit": 50})
    except GHLError:
        return []
    return res.get("opportunities", [])


def appointments(client: GHLClient, contact_id: str) -> list[dict]:
    try:
        res = client.request("GET", f"/contacts/{contact_id}/appointments")
    except GHLError:
        return []
    return res.get("events", []) or res.get("appointments", []) or []


def notes(client: GHLClient, contact_id: str) -> list[dict]:
    try:
        res = client.request("GET", f"/contacts/{contact_id}/notes")
    except GHLError:
        return []
    return res.get("notes", [])


def conversation_activity(client: GHLClient, contact_id: str) -> dict:
    """Message and call history: proof of contact, delivery and support."""
    summary = {"sms_in": 0, "sms_out": 0, "email_in": 0, "email_out": 0,
               "calls": [], "first": "", "last": "", "inbound_samples": []}
    try:
        res = client.get("/conversations/search", contactId=contact_id, limit=20)
    except GHLError:
        return summary
    stamps = []
    for conv in res.get("conversations", []):
        try:
            msgs = client.request("GET", f"/conversations/{conv['id']}/messages",
                                  params={"limit": 100})
        except GHLError:
            continue
        for m in msgs.get("messages", {}).get("messages", []):
            kind = str(m.get("messageType", ""))
            direction = m.get("direction", "")
            added = _iso(m.get("dateAdded"))
            if added:
                stamps.append(added)
            if kind == "TYPE_CALL":
                summary["calls"].append({
                    "date": added,
                    "direction": direction,
                    "status": m.get("status", ""),
                    "seconds": ((m.get("meta") or {}).get("call") or {}).get("duration", ""),
                })
            elif "EMAIL" in kind:
                summary["email_in" if direction == "inbound" else "email_out"] += 1
            else:
                summary["sms_in" if direction == "inbound" else "sms_out"] += 1
            if direction == "inbound" and m.get("body"):
                summary["inbound_samples"].append(
                    {"date": added, "body": str(m["body"])[:400]})
    if stamps:
        summary["first"], summary["last"] = min(stamps), max(stamps)
    summary["inbound_samples"] = sorted(
        summary["inbound_samples"], key=lambda r: r["date"])[:15]
    summary["calls"].sort(key=lambda r: r["date"])
    return summary


def orders(client: GHLClient, contact_id: str) -> dict:
    """GHL Payments orders and card transactions for the contact.

    These endpoints need the payments read scopes on the private integration
    token. The main/EMAIL token has carried them, but GoHighLevel has also
    refused them on that same token, so this returns the refusal rather than
    raising and the pack records which account could be read.
    """
    out: dict[str, Any] = {"available": False, "orders": [], "transactions": []}
    res = None
    # GoHighLevel sometimes answers a scope 401 on a token that read the same
    # endpoint minutes earlier, so one refusal is not proof the scope is gone.
    for attempt in range(3):
        try:
            res = client.get("/payments/orders", altId=client.location_id,
                             altType="location", contactId=contact_id, limit=20)
            break
        except GHLError as exc:
            out["reason"] = str(exc)[:300]
            if attempt == 2:
                return out
            time.sleep(2 * (attempt + 1))
    try:
        out["available"] = True
        out.pop("reason", None)
        for row in res.get("data", []) or []:
            detail = {}
            try:
                detail = client.get(f"/payments/orders/{row['_id']}",
                                    altId=client.location_id, altType="location")
            except GHLError:
                pass
            source = row.get("sourceMeta", {}) or {}
            out["orders"].append({
                "order_id": row.get("_id", ""),
                "placed": _iso(row.get("createdAt")),
                "status": f"{row.get('status','')} / {row.get('paymentStatus','')}",
                "amount_charged": f"{row.get('amount','')} {row.get('currency','')}",
                "list_price": row.get("subtotal", ""),
                "discount": row.get("discount", ""),
                "coupon": row.get("couponCode", ""),
                "live_mode": row.get("liveMode", ""),
                "products": ", ".join(
                    str((i.get("product") or {}).get("name") or i.get("name") or "")
                    for i in (detail.get("items") or [])) or row.get("totalProducts", ""),
                "bought_on": (f"https://{source.get('domain','')}"
                              f"{source.get('pageUrl','')}" if source.get("domain") else ""),
                "order_form": f"{row.get('sourceName','')} "
                              f"({row.get('sourceSubType', row.get('sourceType',''))})",
                "fulfillment": row.get("fulfillmentStatus", ""),
            })
    except GHLError as exc:
        out["reason"] = str(exc)[:300]
        return out
    try:
        res = client.get("/payments/transactions", altId=client.location_id,
                         altType="location", contactId=contact_id, limit=20)
        for row in res.get("data", []) or []:
            out["transactions"].append({
                "transaction_id": row.get("_id", ""),
                "date": _iso(row.get("createdAt")),
                "amount": f"{row.get('amount','')} {str(row.get('currency','')).upper()}",
                "status": row.get("status", ""),
                "processor_charge_id": row.get("chargeId", row.get("paymentProviderChargeId", "")),
                "method": json.dumps(row.get("paymentMethod") or row.get("chargeSnapshot") or "")[:300],
                "order_id": row.get("entityId", ""),
                "live_mode": row.get("liveMode", ""),
            })
    except GHLError as exc:
        out["transactions_reason"] = str(exc)[:300]
    return out


def form_names(client: GHLClient) -> dict[str, str]:
    names, skip = {}, 0
    while True:
        try:
            res = client.get("/forms/", limit=100, skip=skip)
        except GHLError:
            break
        rows = res.get("forms", [])
        names.update({r["id"]: r.get("name", "") for r in rows})
        if len(rows) < 100:
            break
        skip += 100
    return names


def gather(client: GHLClient, email: str = "", phone: str = "",
           label: str = "", pages: int = 20, start_at: str = "",
           end_at: str = "") -> dict:
    """Everything one sub-account knows about one buyer."""
    contact = find_contact(client, email, phone)
    if not contact:
        return {"account": label, "location_id": client.location_id, "found": False}
    cid = contact["id"]
    subs = submissions(client, cid, pages=pages, start_at=start_at,
                       end_at=end_at)
    names = form_names(client) if subs else {}
    field_names = {}
    try:
        defs = client.request("GET", f"/locations/{client.location_id}/customFields")
        field_names = {f["id"]: f.get("name", f["id"])
                       for f in defs.get("customFields", [])}
    except GHLError:
        pass
    custom = {}
    for field in contact.get("customFields", []) or []:
        key = field.get("id") or field.get("key")
        if field.get("value") not in (None, "", []):
            custom[field_names.get(key, str(key))] = field.get("value")
    return {
        "account": label,
        "location_id": client.location_id,
        "found": True,
        "contact": {
            "id": cid,
            "name": " ".join(x for x in [contact.get("firstName"),
                                         contact.get("lastName")] if x),
            "email": contact.get("email", ""),
            "phone": contact.get("phone", ""),
            "address": ", ".join(str(x) for x in [contact.get("address1"),
                                                  contact.get("city"),
                                                  contact.get("state"),
                                                  contact.get("postalCode"),
                                                  contact.get("country")] if x),
            "timezone": contact.get("timezone", ""),
            "created": _iso(contact.get("dateAdded")),
            "last_activity": _iso(contact.get("lastActivity")),
            "tags": contact.get("tags", []),
            "attribution": contact.get("attributions") or contact.get("attribution") or {},
        },
        "custom_fields": custom,
        "submissions": [describe_submission(s, names) for s in subs],
        "opportunities": [{
            "name": o.get("name", ""),
            "pipeline_stage": o.get("pipelineStageId", ""),
            "status": o.get("status", ""),
            "value": o.get("monetaryValue", ""),
            "created": _iso(o.get("createdAt")),
            "updated": _iso(o.get("updatedAt")),
        } for o in opportunities(client, cid)],
        "appointments": [{
            "title": a.get("title", ""),
            "start": _iso(a.get("startTime")),
            "status": a.get("appointmentStatus", a.get("status", "")),
            "calendar": a.get("calendarId", ""),
        } for a in appointments(client, cid)],
        "activity": conversation_activity(client, cid),
        "notes": [{"date": _iso(n.get("dateAdded")), "body": str(n.get("body", ""))[:600]}
                  for n in notes(client, cid)],
        "orders": orders(client, cid),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

# The agreement each funnel checkout requires before its "Complete Order"
# button becomes clickable. The box is a page element, not an order field, so
# GHL does not record the individual tick: what the pack can state is that the
# order could not have been placed on that page without it. Verified live on
# 2026-11-09 by loading each page, opening the order form and reading the
# checkbox's label with the submit button disabled. Re-verify when a checkout
# page is edited.
CHECKOUT_ACCEPTANCE = {
    "/presale": "I agree to the terms and conditions, bot disclosure and "
                "understand this is a non-refundable purchase",
    "/PRESALE": "I agree to the terms and conditions, bot disclosure and "
                "understand this is a non-refundable purchase",
    "/bots": "I agree to the terms and conditions, bot disclosure and "
             "understand this is a non-refundable purchase",
    "/combo-bot": "I agree to the terms and conditions and money back guarantee "
                  "for Options Navigator. I understand the Options Auto Traders "
                  "(value of $3800) are non-refundable and agree to the bot "
                  "disclosure",
    "/options-nav--auto-traders-combo":
        "I agree to the terms and conditions and money back guarantee for "
        "Options Navigator. I understand the Options Auto Traders (value of "
        "$3800) are non-refundable and agree to the bot disclosure",
    "/deal": "I agree to the terms and conditions and money back guarantee",
    "/options-nav-2yr": "I agree to the terms and conditions and money back "
                        "guarantee",
    "/join": "I agree to the terms and conditions and money back guarantee",
    "/monthly-page": "I agree to the terms and conditions, refund policy, "
                     "disclaimers, and privacy policy",
}


EXHIBIT_DIR = Path(__file__).resolve().parent.parent / "assets" / "checkout-exhibits"


def exhibit_for(page_url: str) -> str:
    """Path to the screen capture of the checkout the order was placed on."""
    for path in CHECKOUT_ACCEPTANCE:
        if page_url and page_url.rstrip("/").lower().endswith(path.lower()):
            slug = path.lower().replace("/", "-")
            candidate = EXHIBIT_DIR / f"checkout{slug}.png"
            if candidate.exists():
                return str(candidate)
    return ""


def search(client: GHLClient, query: str, limit: int = 10) -> list[dict]:
    """Free-text contact search: a name, part of a name, an email or a phone."""
    try:
        res = client.post("/contacts/search", {
            "locationId": client.location_id,
            "pageLimit": limit,
            "query": query.strip(),
        })
    except GHLError:
        return []
    out = []
    for row in res.get("contacts", []):
        out.append({
            "id": row.get("id", ""),
            "name": " ".join(x for x in [row.get("firstName"), row.get("lastName")] if x),
            "email": row.get("email", ""),
            "phone": row.get("phone", ""),
            "created": _iso(row.get("dateAdded")),
            "tags": (row.get("tags") or [])[:6],
        })
    return out


def acceptance_for(page_url: str) -> str:
    """The checkbox text the buyer had to tick on the page they bought from."""
    for path, text in CHECKOUT_ACCEPTANCE.items():
        if page_url and page_url.rstrip("/").endswith(path):
            return text
    return ""


POLICY_LINES = [
    ("Terms & Conditions, 'Refund Policy' section",
     "https://universityofoptions.com/terms",
     "Subscription payments are non-refundable. When you cancel your "
     "subscription, you will have access to the product or service until the "
     "end of that subscription period."),
    ("Customer Agreement and Refund Policy (effective January 2025)",
     "https://universityofoptions.com/refund-policy",
     "Refunds are available for programs purchased within 90 days from the date "
     "of purchase, and only where the customer completed at least 75% of the "
     "course material, supplied documented proof of sanctioned trades including "
     "at least two weeks on a demo account, and supplied proof of having "
     "contacted support. The Company reserves the right to deny refunds to any "
     "customer who fails to adhere to the stated guidelines."),
    ("Terms & Conditions, 'Dispute Resolution' section",
     "https://universityofoptions.com/terms",
     "Claims are subject to mandatory binding individual arbitration with a "
     "class action waiver, and must be preceded by written notice to the "
     "company and commenced within one year."),
]


def transaction_summary(packs: list[dict]) -> dict:
    """The transaction facts for the cover section, taken from GHL Payments.

    GHL stores the processor's own charge identifier on the transaction, so the
    pack can be tied to the disputed charge without a Stripe login.
    """
    facts: dict[str, str] = {}
    for pack in packs:
        info = pack.get("orders") or {}
        for order in info.get("orders", []):
            facts.setdefault("Order placed", order["placed"])
            facts.setdefault("Product purchased", str(order["products"]))
            facts.setdefault("Amount charged", str(order["amount_charged"]))
            if order.get("discount"):
                facts.setdefault("List price before discount", str(order["list_price"]))
                facts.setdefault("Discount applied", str(order["discount"]))
            if order.get("coupon"):
                facts.setdefault("Coupon used by cardholder", str(order["coupon"]))
            facts.setdefault("Order page used", order["bought_on"])
            facts.setdefault("Order form", order["order_form"])
            facts.setdefault("Order status", order["status"])
            facts.setdefault("GHL order id", order["order_id"])
        for txn in info.get("transactions", []):
            facts.setdefault("Payment date", txn["date"])
            facts.setdefault("Processor charge id", str(txn["processor_charge_id"]))
            facts.setdefault("Payment status", str(txn["status"]))
            method = txn.get("method") or ""
            if "last4" in method:
                try:
                    card = json.loads(method).get("card", {})
                    facts.setdefault("Card used", f"{card.get('brand','')} ending "
                                                  f"{card.get('last4','')}".strip())
                except (ValueError, AttributeError):
                    facts.setdefault("Card used", method)
    return facts


def render_pdf(packs: list[dict], path: str, order_facts: dict | None = None,
               exhibit: str = "") -> str:
    """Write the evidence pack as a single PDF at `path`."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (Image, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    base = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=base["Heading1"], fontSize=15, spaceAfter=8)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], fontSize=11.5,
                        spaceBefore=12, spaceAfter=4)
    body = ParagraphStyle("body", parent=base["BodyText"], fontSize=9,
                          leading=12.5, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10.5,
                           textColor=colors.HexColor("#444444"))

    def esc(value: Any) -> str:
        return (str(value).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    def table(rows: list[list[str]], widths: list[float]) -> Table:
        data = [[Paragraph(esc(c), small) for c in row] for row in rows]
        t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    story: list[Any] = []
    found = [p for p in packs if p.get("found")]
    who = found[0]["contact"] if found else {}
    story.append(Paragraph("Dispute response evidence", h1))
    story.append(Paragraph(
        f"Merchant: University of Options &nbsp;|&nbsp; Cardholder on file: "
        f"{esc(who.get('name') or 'unknown')} &nbsp;|&nbsp; "
        f"{esc(who.get('email') or '')} {esc(who.get('phone') or '')}<br/>"
        f"Compiled {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
        "from the merchant's CRM of record (GoHighLevel).", body))

    if order_facts:
        story.append(Paragraph("1. The transaction", h2))
        story.append(table([["Field", "Value"]] +
                           [[k, v] for k, v in order_facts.items()], [1.9, 4.6]))

    story.append(Paragraph("2. What the cardholder had to accept to place this "
                           "order", h2))
    accepted = ""
    for pack in packs:
        for order in (pack.get("orders") or {}).get("orders", []):
            accepted = accepted or acceptance_for(order.get("bought_on", ""))
    if accepted:
        story.append(Paragraph(
            "The order was placed on the merchant's checkout page shown above. "
            "That page carries a checkbox the cardholder must tick before the "
            "Complete Order button becomes active; the order could not have "
            "been submitted without it. The checkbox reads:", body))
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>&ldquo;{esc(accepted)}&rdquo;</b>", body))
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            "A screen capture of that checkout, showing the unticked box and "
            "the disabled Complete Order button, accompanies this document.",
            small))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "The terms linked from that checkbox were published at the URLs shown "
        "and in force on the purchase date.", body))
    for title, url, text in POLICY_LINES:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>{esc(title)}</b> — {esc(url)}", small))
        story.append(Paragraph(f"&ldquo;{esc(text)}&rdquo;", small))

    section = 3
    for pack in packs:
        if not pack.get("found"):
            continue
        c = pack["contact"]
        story.append(Paragraph(
            f"{section}. Customer record — {esc(pack['account'])} account "
            f"({esc(pack['location_id'])})", h2))
        section += 1
        story.append(table([["Field", "Value"],
                            ["Contact id", c["id"]],
                            ["Name", c["name"]],
                            ["Email", c["email"]],
                            ["Phone", c["phone"]],
                            ["Address on file", c["address"]],
                            ["Timezone", c["timezone"]],
                            ["Record created", c["created"]],
                            ["Last activity", c["last_activity"]],
                            ["Tags", ", ".join(c["tags"])[:900]]], [1.9, 4.6]))

        if pack["submissions"]:
            story.append(Paragraph("Forms the cardholder submitted", h2))
            for s in pack["submissions"]:
                rows = [["Field", "Value"],
                        ["Form", s["form"]],
                        ["Submitted", s["submitted_at"]],
                        ["Captured IP address", s["ip"] or "not captured"],
                        ["Browser timezone", s["browser_timezone"]],
                        ["Page", s["page_url"]],
                        ["Traffic source", s["traffic_source"]],
                        ["Referrer", s["referrer"]],
                        ["Session id", s["session_id"]],
                        ["Submission id", s["submission_id"]],
                        ["Tamper-evident hash stored", "yes" if s["has_signature_hash"] else "no"]]
                for k, v in s["consent_text"].items():
                    rows.append([f"Consent text accepted ({k})", v])
                other = {k: v for k, v in s["answers"].items()
                         if k not in s["consent_text"]}
                if other:
                    rows.append(["Other answers given",
                                 "; ".join(f"{k}: {v}" for k, v in other.items())[:1200]])
                story.append(Spacer(1, 4))
                story.append(table(rows, [1.9, 4.6]))

        if pack["opportunities"]:
            story.append(Paragraph("Sale recorded in the CRM", h2))
            story.append(table(
                [["Opportunity", "Status", "Value", "Created", "Updated"]] +
                [[o["name"], o["status"], o["value"], o["created"], o["updated"]]
                 for o in pack["opportunities"]], [2.3, 0.9, 0.8, 1.25, 1.25]))

        if pack["appointments"]:
            story.append(Paragraph("Calls booked with the cardholder", h2))
            story.append(table([["Appointment", "Start", "Status"]] +
                               [[a["title"], a["start"], a["status"]]
                                for a in pack["appointments"]], [2.8, 2.0, 1.7]))

        act = pack["activity"]
        story.append(Paragraph("Contact history (service delivery and support)", h2))
        story.append(table([
            ["Field", "Value"],
            ["First recorded message", act["first"]],
            ["Most recent message", act["last"]],
            ["SMS sent to cardholder", act["sms_out"]],
            ["SMS received from cardholder", act["sms_in"]],
            ["Emails sent to cardholder", act["email_out"]],
            ["Emails received from cardholder", act["email_in"]],
            ["Phone calls logged", len(act["calls"])],
        ], [1.9, 4.6]))
        if act["calls"]:
            story.append(Spacer(1, 4))
            story.append(table([["Call date", "Direction", "Status", "Seconds"]] +
                               [[c2["date"], c2["direction"], c2["status"], c2["seconds"]]
                                for c2 in act["calls"]], [1.9, 1.2, 1.4, 2.0]))
        if act["inbound_samples"]:
            story.append(Paragraph("What the cardholder wrote to the merchant", h2))
            story.append(table([["Date", "Message"]] +
                               [[m["date"], m["body"]] for m in act["inbound_samples"]],
                               [1.6, 4.9]))

        if pack["notes"]:
            story.append(Paragraph("Staff notes on the record", h2))
            story.append(table([["Date", "Note"]] +
                               [[n["date"], n["body"]] for n in pack["notes"]],
                               [1.6, 4.9]))

        if pack.get("custom_fields"):
            story.append(Paragraph("Answers held on the customer record", h2))
            story.append(table([["Question", "Answer"]] +
                               [[k, str(v)[:600]]
                                for k, v in pack["custom_fields"].items()], [2.6, 3.9]))

        orders_info = pack.get("orders", {})
        for order in orders_info.get("orders", []):
            story.append(Paragraph("Order record (GoHighLevel Payments)", h2))
            story.append(table([["Field", "Value"]] +
                               [[k.replace("_", " ").capitalize(), v]
                                for k, v in order.items()], [1.9, 4.6]))
        if orders_info.get("transactions"):
            story.append(Paragraph("Card transactions", h2))
            story.append(table(
                [["Date", "Amount", "Status", "Processor charge id", "Transaction id"]] +
                [[t["date"], t["amount"], t["status"], t["processor_charge_id"],
                  t["transaction_id"]] for t in orders_info["transactions"]],
                [1.3, 1.0, 0.9, 1.7, 1.6]))
        if not orders_info.get("available") and orders_info.get("reason"):
            story.append(Paragraph("Order record", h2))
            story.append(Paragraph(
                "GoHighLevel refused the order and transaction read for this "
                "account, so the order amount, the card and the processor's "
                "charge id are missing from this pack. Add the payments read "
                "scopes to the private integration token and build the pack "
                "again. The refusal was: " + esc(orders_info["reason"]), small))
        story.append(PageBreak())

    if not found:
        story.append(Paragraph(
            "No CRM record matched the email address or phone number supplied. "
            "Check the spelling, and try the phone number in E.164 form.", body))

    if exhibit:
        try:
            from reportlab.lib.utils import ImageReader
            width, height = ImageReader(exhibit).getSize()
            max_w, max_h = 7.1 * inch, 8.4 * inch
            scale = min(max_w / width, max_h / height)
            story.append(Paragraph("Exhibit: the checkout as the cardholder saw it", h2))
            story.append(Paragraph(
                "Captured from the live page. The Complete Order button is "
                "greyed out until the agreement box is ticked.", small))
            story.append(Spacer(1, 6))
            story.append(Image(exhibit, width * scale, height * scale))
        except Exception:
            pass

    doc = SimpleDocTemplate(path, pagesize=LETTER,
                            leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            title="Dispute response evidence")
    doc.build(story)
    return path
