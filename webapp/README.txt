Dispute evidence page
=====================

A private page where a closer types a buyer's name and gets the evidence
pack back as a PDF. One shared password, no accounts, nothing stored.

What it needs in the environment:

  DISPUTE_PASSWORD      the shared password (make it long)
  FLASK_SECRET_KEY      any long random string; sessions reset without it
  GHL_SMS_API_KEY       private integration token, SMS sub-account
  GHL_SMS_LOCATION_ID   U23Jnu7rscfzAOUmSevW
  GHL_EMAIL_API_KEY     private integration token, main/EMAIL sub-account
  GHL_EMAIL_LOCATION_ID IyorbIIbJLsMLaqy8j1P

  SPREADS_BOT_LOOKUP_URL    https://app.tripletrader.bot/api/proof-of-use
  SPREADS_BOT_LOOKUP_TOKEN  the PROOF_OF_USE_TOKEN made on the bot server (optional pair:
                            without them the pack is built without the Spreads Bot section)

Both tokens need contacts, conversations, calendars and forms read access.
The main/EMAIL token also needs the payments read scopes, or the pack comes
back without the order, the card and the processor's charge id, which are the
most useful parts of it.

To run it:

  pip install -r webapp/requirements.txt
  python3 webapp/app.py

It listens on $PORT, default 5000.

On Replit: put the repository in a Repl, set the variables above as Secrets,
and set the run command to `python3 webapp/app.py`. Replit supplies $PORT.

The checkout screen captures live in assets/checkout-exhibits/ and are
embedded into the pack. Recapture them whenever a checkout page is edited,
otherwise the exhibit will not match what the buyer saw.

Spreads Bot proof of use: when the two SPREADS_BOT_LOOKUP_* Secrets are set, each pack
asks the Spreads Bot server's read-only lookup by the buyer's EMAIL and, only when an
account is found, adds a "Proof of use" section (account dates, every dated action with
its IP, sign-ins and days of use, settings records, trade counts, and any IP that matches
the CRM opt-in). "No account" or an error is shown on the page, never put in the pack.
