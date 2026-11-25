# K'hal Yismach Moshe · Spin to Win

Private prototype of a luxury raffle site: a year of date nights (dinner for two at 10 kosher restaurants plus $1,500 in Uber gift cards), entered by spinning a 3D dreidel.

**Payments are sandbox-only.** Live transactions stay disabled until the raffle format, charitable-gaming requirements and payment processor are approved. The app refuses to start if `RAFFLE_PAYMENT_MODE` is set to anything other than `sandbox`. Restaurant participation and prize terms must be confirmed before publication.

## Run it (WSL / Linux)

    python3 -m venv ~/raffle-venv
    ~/raffle-venv/bin/pip install -r requirements.txt
    ~/raffle-venv/bin/python app.py

- Public site: http://127.0.0.1:5000
- Admin: http://127.0.0.1:5000/admin (default `admin` / `local-demo-only`; set your own, see below)
- Locally, `./start.sh` loads the private settings from `admin-login.env` (never committed).

To start over, stop the server and delete `raffle.sqlite`. Older databases (250- and 360-ticket versions) are migrated automatically, and every issued number is kept.

## Configuration (environment variables)

| Variable | Purpose |
|---|---|
| `RAFFLE_ADMIN_USER`, `RAFFLE_ADMIN_PASSWORD` | Admin login (change before sharing) |
| `RAFFLE_SECRET_KEY` | Session signing key (set it so logins survive restarts) |
| `RAFFLE_ADMIN_TOKEN` | Bearer token for scripted API access |
| `RAFFLE_DB`, `RAFFLE_UPLOADS` | Database file and upload folder |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS` | Deliver confirmation emails. Without them, emails go to the admin outbox only |
| `RAFFLE_SECURE_COOKIES=1` | Secure cookies when served over HTTPS |
| `RAFFLE_ENV=production` | Refuses to start without a strong admin password and secret key |
| `RAFFLE_PROXY_FIX=1` | Trust the HTTPS proxy's forwarded headers (Render) |
| `RAFFLE_ALLOW_INDEXING=1` | Allow search engines (otherwise `noindex`) |
| `RAFFLE_ARCHIVE` | Folder for archived campaigns |
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` | Stripe **test** keys (`sk_test_…`, `pk_test_…`). Live keys are refused. Without them, payments are simulated |

## Stripe (test mode)

With Stripe test keys set, step 2 of checkout shows Stripe's own card form (Payment Element). Card details go from the visitor's browser straight to Stripe; this server only sees PaymentIntent and charge ids.

1. When the visitor reaches step 2, the server creates a PaymentIntent for the maximum amount ($360) with `capture_method=manual`. This is an authorization hold, not a charge.
2. The browser confirms the card with Stripe.
3. `/api/spin` checks that the PaymentIntent belongs to this entry and is in `requires_capture`, then assigns a number.
4. The server captures exactly the assigned amount (`amount_to_capture`). Stripe releases the rest of the hold automatically.

Sold-out and closed-sales cases release the hold. Admin refunds go through Stripe refunds. The test card is 4242 4242 4242 4242 with any future date and any CVC; 4000 0000 0000 0002 is declined.

Before using a live Stripe account, confirm with Stripe that raffle sales are allowed on it. Stripe treats lotteries and raffles as restricted businesses and requires prior approval.

## Deploy to Render (spin.yismachmosheofwoodmere.com)

`render.yaml` is a Render Blueprint. It defines one web service, `yismach-spin` (Starter plan with a 1 GB persistent disk for the database, uploads and campaign archives), served by gunicorn with HTTPS and the custom domain `spin.yismachmosheofwoodmere.com`.

1. Push this folder to a private GitHub repository. `.gitignore` keeps the database, uploads and `admin-login.env` out of it.
2. In Render: **New → Blueprint**, then pick the repository. Render reads `render.yaml`.
3. When it asks for the secret values, enter:
   - `RAFFLE_ADMIN_PASSWORD`: 12+ characters. The app refuses to start in production without it.
   - `SMTP_PASSWORD`: the Gmail app password for yismachspin@gmail.com. Leave it blank to keep emails in the admin outbox.
   - `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY`: **test** keys only. Leave them blank for simulated payments.
   
   `RAFFLE_SECRET_KEY` and `RAFFLE_ADMIN_TOKEN` are generated automatically.
4. DNS at GoDaddy (the domain's DNS host): add **one** record. Nothing else changes, so the shul website at `yismachmosheofwoodmere.com` and `www` is untouched.

   | Type | Name | Value | TTL |
   |---|---|---|---|
   | CNAME | `spin` | `yismach-spin.onrender.com` | 1 hour |

   Use the exact `.onrender.com` address shown on the service's page in Render. If the name was taken, Render adds a suffix.
5. In Render → the service → **Settings → Custom Domains**, click **Verify** next to `spin.yismachmosheofwoodmere.com`. Render issues the SSL certificate automatically, usually within minutes of DNS resolving. The domain has no CAA records, so nothing blocks issuance.
6. Sign in at `https://spin.yismachmosheofwoodmere.com/admin` and work through **Launch checklist**.

Search engines are blocked by an `X-Robots-Tag: noindex` header until `RAFFLE_ALLOW_INDEXING=1` is set. Payments stay in test mode: live Stripe keys are refused by the code.

### Reusing the platform for future campaigns

Admin → Launch checklist → **Start a new campaign** archives the current campaign's full database to `/var/data/archive/`, clears entries, payments, emails and the drawing, sets the new campaign number, and pauses entries until new dates are set. Branding, restaurants and rules text are kept for editing.

## Compliance features (drafts for counsel)

- **Legal pages:** `/rules` (16 sections), `/free-entry`, `/privacy`, `/terms`, `/contact` and `/winners` are generated from Admin → Campaign. Any unverified value (legal name, EIN, address, eligible states, ARV, etc.) shows as a highlighted placeholder, never an invented fact. Counsel's final text can be pasted in to replace any generated page. Every page shows "Draft pending legal review" until legal approval is marked in the admin.
- **Printable mail-in form:** `/free-entry-form.pdf`.
- **No-purchase-necessary disclaimer:** shown near the entry button, in checkout and in the footer, with links. It appears only while free entry is enabled.
- **Consent:** checkout has an unchecked payment-authorization checkbox (min/max shown), a required eligibility + Official Rules checkbox, and a separate optional marketing checkbox. Each entry stores the consent text, timestamp, rules version and campaign number.
- **Free entries:** registered from Admin → Entries → "Register mail-in entry". Each gets a random unused number from the same 1–N pool, with no payment, and joins the same drawing. The admin enforces the entry deadline, a per-person limit (applied equally to both methods) and duplicate checks. Disqualifications are logged.
- **Approval tracking:** legal and payment-processor approval status are kept in the campaign settings. Payments stay in test mode regardless.

## How an entry works

1. The visitor enters their name, email and phone, and authorizes a charge of $1 to $360.
2. The sandbox gateway authorizes the maximum amount, so no number is assigned if the authorization is declined.
3. Inside a SQLite write lock, the server picks a random unused number with `secrets.choice`. A partial unique index also guarantees each number is issued only once.
4. Only the assigned amount is captured. Retries with the same `request_id` return the same ticket and never charge twice.
5. A ticket email is sent through SMTP or written to the outbox, and the visitor can share on WhatsApp.

Sandbox test scenarios: an email containing `+decline` is declined, and an email containing `+capturefail` fails at capture. Use them to exercise the admin's retry and release flows.

## Admin

The admin has these sections: Overview (funds raised, sold and remaining, a 1–N ticket board), Entries (search and filter; resend email, retry payment, release number, refund), Payments (full transaction ledger), Emails (outbox with preview and resend), Drawing, Campaign settings and Activity log. Everything is editable in Campaign settings: branding, headline, prize, the restaurant/sponsor list with logo and photo uploads, transportation section, ticket count, price per number, winners, drawing date, entry window and email templates. Pricing locks once tickets are issued.

**Auditable drawing:** publish a SHA-256 commitment to a secret seed before entries close, and announce a public entropy source in advance (e.g. a lottery result). After entries close, enter that value and draw. The seed, entropy, eligible list and algorithm are published at `/api/drawing` for independent verification.

## Before going live

- Obtain charitable-gaming and payment-processor approval (including random variable pricing), then replace `SandboxGateway` with the processor's hosted checkout or tokenized flow. Never collect card numbers on this server.
- Confirm each restaurant and upload its **official logo and photos only with permission**. The same applies to the Uber logo, which needs Uber's brand-asset permission. Restaurant descriptions and locations were drafted from public listings and should be checked with each restaurant.
- Set strong admin credentials and a secret key, serve over HTTPS, and configure SMTP.
- Add age/location checks, official rules, privacy policy and record retention as required.

## Tests

    ~/raffle-venv/bin/pip install pytest
    ~/raffle-venv/bin/python -m pytest -q tests

## Credits

Photography: "New York Midtown Skyline at night" by Diliff (CC BY-SA 3.0) and "New York City at night HDR" by Paulo Barcellos Jr. (CC BY-SA 2.0), via Wikimedia Commons.
