"""Spreads Bot proof of use for the dispute pack: get it, check it, decide whether it goes in.

The facts come from the Spreads Bot server (TripleTrader) as the JSON that its read-only
lookup prints (ghl/spreads_usage.py is a copy of that lookup). There are two ways to get it:

  * pasted: someone with server access runs the lookup and pastes its output, or
  * fetched: when SPREADS_BOT_LOOKUP_URL and SPREADS_BOT_LOOKUP_TOKEN are set (Replit
    Secrets), the page asks the server's read-only lookup link by the buyer's email.

Only an account that was FOUND goes into the PDF. "No account", "several possible accounts"
and any error are shown to the closer on the page and left out of the pack, because a
processor should never be handed a section that says the buyer did not use the product.
"""

from __future__ import annotations

import os

from . import spreads_usage

URL_VAR = "SPREADS_BOT_LOOKUP_URL"
TOKEN_VAR = "SPREADS_BOT_LOOKUP_TOKEN"


def configured() -> bool:
    return bool(os.environ.get(URL_VAR) and os.environ.get(TOKEN_VAR))


def from_paste(text: str) -> dict:
    """The pasted lookup output (the whole terminal paste is fine)."""
    try:
        return spreads_usage.from_json(text)
    except Exception as exc:
        return {"status": "error", "error": "the pasted text is not a Spreads Bot lookup (%s)"
                % str(exc)[:120]}


def fetch(email: str, name: str = "", timeout: float = 150.0, session=None) -> dict | None:
    """Ask the server's read-only lookup link. None when it is not configured."""
    if not configured() or not (email or name):
        return None
    import requests
    s = session or requests
    try:
        r = s.get(os.environ[URL_VAR], params={"email": email or "", "name": name or "", "logs": "1"},
                  headers={"Authorization": "Bearer " + os.environ[TOKEN_VAR]},
                  timeout=timeout)
    except Exception as exc:
        return {"status": "error", "error": "could not reach the Spreads Bot server: %s" % str(exc)[:160]}
    if r.status_code != 200:
        return {"status": "error", "error": "the Spreads Bot server answered HTTP %s" % r.status_code}
    try:
        return spreads_usage.from_json(r.text)
    except Exception as exc:
        return {"status": "error", "error": "unreadable answer from the Spreads Bot server (%s)"
                % str(exc)[:120]}


def ghl_ips(packs: list[dict]) -> list[str]:
    """Every IP GoHighLevel captured on this buyer's form submissions."""
    out = []
    for p in packs or []:
        for s in p.get("submissions") or []:
            ip = (s.get("ip") or "").strip()
            if ip and ip not in out:
                out.append(ip)
    return out


def blocks_for_pdf(result: dict | None, packs: list[dict]) -> list[dict]:
    """The PDF blocks, or [] when the section must not go in (see the module docstring)."""
    if not result or result.get("status") != "found":
        return []
    return spreads_usage.pdf_blocks(result, ghl_ips=ghl_ips(packs))


def page_line(result: dict | None) -> str:
    """One plain sentence for the closer about what happened with the Spreads Bot section."""
    if result is None:
        return ""
    st = result.get("status")
    if st == "found":
        return "Spreads Bot: account found, proof of use added to the pack."
    if st == "error":
        return "Spreads Bot: not added. " + result.get("error", "")
    return "Spreads Bot: not added. " + spreads_usage.summary_text(result)
