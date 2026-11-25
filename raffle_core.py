"""Core raffle logic: storage, campaign config, sandbox payments, email, drawing, audit log.

Payments: simulated, Stripe TEST mode, or Stripe LIVE mode. Live needs live keys AND RAFFLE_LIVE_PAYMENTS=1.
"""
import copy, hashlib, hmac, html, json, os, re, secrets, smtplib, sqlite3
from datetime import datetime, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

PAYMENT_MODE = 'sandbox'  # set to 'live' by create_app when live Stripe payments are switched on
DEFAULT_MAX_TICKETS = 360
MAX_TICKETS_CEILING = 5000
TZ = ZoneInfo('America/New_York')

RESTAURANTS = [
    {"name": "Reserve Cut", "location": "Financial District, Manhattan",
     "description": "Glamorous, big-night steakhouse dining at The Setai on Wall Street."},
    {"name": "Barnea Bistro", "location": "Midtown East, Manhattan",
     "description": "An intimate, contemporary bistro: prime steaks, lamb and a quietly elegant room."},
    {"name": "REN", "location": "Brooklyn",
     "description": "Chef-driven, technique-forward cooking in a refined, upscale setting."},
    {"name": "Mike's Bistro", "location": "Midtown East, Manhattan",
     "description": "A Manhattan kosher fine-dining favorite with a polished, chef-driven menu."},
    {"name": "DOMA Land + Sea", "location": "Cedarhurst, Long Island",
     "description": "Modern American cooking from a wood-fired grill: prime cuts from the land, fish and sushi from the sea."},
    {"name": "The Loft Steakhouse", "location": "Brooklyn",
     "description": "A sophisticated steakhouse made for a classic, indulgent night out."},
    {"name": "Bison & Bourbon", "location": "Park Slope / Gowanus, Brooklyn",
     "description": "One of Brooklyn's grandest kosher steakhouses, with prime meats, a deep bourbon list and inventive cocktails."},
    {"name": "Tabernacle Steakhouse", "location": "Midtown, Manhattan",
     "description": "An upscale Midtown steakhouse with its own sushi program."},
    {"name": "Wall Street Grill", "location": "Financial District, Manhattan",
     "description": "Prime steaks and sushi downtown, with a rooftop garden for warm-weather evenings."},
    {"name": "Bordeaux", "location": "Midwood, Brooklyn",
     "description": "A modern take on the American steakhouse; diners rave about the beef Wellington."},
]

# Logos and photos taken from each restaurant's own website (see README).
RESTAURANT_SLUGS = ["reserve-cut", "barnea-bistro", "ren", "mikes-bistro", "doma", "the-loft", "bison-bourbon",
                    "tabernacle", "wall-street-grill", "bordeaux"]

DEFAULT_CAMPAIGN = {
    "org_name": "K'hal Yismach Moshe",
    "presents": "K'hal Yismach Moshe presents",
    "title": "The Golden Spin",
    "subtitle": "The Ultimate Kosher Foodie Experience",
    "headline": "A Year of Fine Dining. On Us.",
    "intro": "One winner gets $300 to spend at each of 10 of New York's most celebrated kosher restaurants, plus a $150 Uber ride for every night out.",
    "tagline": "Dinner is on us. Your ride is on us. Just bring your appetite.",
    "prize_title": "The Grand Prize",
    "prize_description": "One lucky winner receives $300 to spend at each of these 10 restaurants: $3,000 in fine dining.",
    "dining_each": "$300",  # amount at each restaurant; shown in the hero badge and on every restaurant card
    "prize_items": ["$300 at each of 10 premier kosher restaurants ($3,000 in dining).", "A $150 Uber gift card for each restaurant night ($1,500 in rides).", "Total prize value: $4,500."],
    "prize_image": "",
    "reveal_image": "/assets/img/reveal-rav.jpg", "reveal_caption": "",  # shown on the card that reveals the donor's number
    "hero_images": [f"/assets/img/hero-{i}.jpg" for i in (1, 6, 2, 7, 5)],
    "hero_source": "restaurants",
    # Share-and-earn links: every participant (or anyone who signs up) gets a personal link. Paid entries made by
    # other people through it count toward a thank-you reward. The donor's own odds are never affected.
    # Tracking only by default; a reward and its threshold appear publicly only once the shul fills them in.
    "referral_enabled": True, "referral_threshold": 10, "referral_reward": "", "referral_terms": "",
    # Background music, started only when a visitor taps the speaker button (browsers block autoplay with sound).
    # youtube: YouTube's own visible embedded player (allowed by YouTube); upload: an audio file the organization has rights to.
    "music_source": "youtube", "music_youtube": "tfPHaVhsaVU", "music_autostart": True,
    "music_title": "Yismach Moshe · DJ Farbreng ft. Moshe Storch & Sruly Green (TYH Nation)", "music_url": "",  # top slideshow: each restaurant's photo + logo, or the custom hero_images

    "restaurants": [dict(r, logo=f"/assets/logos/{RESTAURANT_SLUGS[i]}.png",
                         photo=f"/assets/img/r-{RESTAURANT_SLUGS[i]}.jpg")
                    for i, r in enumerate(RESTAURANTS)],
    "transport": {
        "enabled": True,
        "title": "Your ride is on us.",
        "amount": "$1,500",
        "amount_label": "in Uber gift cards",
        "detail": "The winner receives a $150 Uber gift card for each of the 10 date nights.",
        "brand": "Uber",
        "logo": "",
        "image": "/assets/img/avenue.jpg",
    },
    "unit_price_cents": 100,
    "winners": 1,
    "drawing_date": "",
    "start_at": "",
    "end_at": "",
    "sales_paused": False,
    "prizes_confirmed": True,
    "share_text": "The Golden Spin: win $300 at each of 10 of New York's best kosher restaurants, plus $1,500 in Uber rides. Enter from $1:",
    # ── legal & compliance (placeholders until verified; see legal.py) ──
    "org_legal_name": "Yismach Moshe of North Woodmere", "org_nonprofit_status": "a not-for-profit organization",
    "org_ein": "82-3156516", "org_address": "45 Centre St, Woodmere, NY 11598", "org_email": "yismachmosheow@gmail.com",
    "org_phone": "(347) 601-8741",
    "campaign_purpose": "Supporting the religious programs, growth and community activities of Yismach Moshe of North Woodmere.",
    "campaign_number": "YM-2026-01", "rules_version": "2026-1",
    "free_entry_enabled": True, "min_age": 18,
    "eligible_regions": "the 50 United States and the District of Columbia",
    "exclusions": ("Individuals directly responsible for administering the Giveaway or selecting the winner, and their immediate "
                   "family members (spouse, parents, children, siblings) and household members, are not eligible."),
    "entries_per_person": 0, "prize_arv": "$4,500 (preliminary)",
    "prize_terms": ("Final gift card terms, including the issuer, expiration dates and any reservation requirements for each "
                    "restaurant, will be published on this page before the drawing."),
    "prize_source": ("The prize gift cards are purchased by the Sponsor or contributed by sponsors. The final source of each "
                     "gift card will be listed on this page before the drawing."),
    "drawing_method": "Conducted live on Zoom",
    "claim_days": 14, "governing_county": "Nassau",
    "privacy_retention": ("Entry, payment and consent records are kept for as long as required for the Sponsor's tax, audit and "
                          "fundraising record-keeping, and for at least three years after the drawing."),
    "winner_anonymous_allowed": True,
    "auth_language": ("I authorize {org} to charge my payment method the randomly assigned donation amount, not exceeding {max}. "
                      "I understand the donation amount will be determined randomly within the disclosed range of {min} to {max}."),
    "marketing_consent_text": "Keep me informed about future {org} events and fundraisers (optional).",
    "official_rules": "", "free_entry_instructions": "", "privacy_policy": "", "terms_text": "", "winner_info": "",
    "legal_approval_status": "not_started", "processor_approval_status": "not_started",
    "progress_min": 50,  # show the "entries claimed" bar once this many are claimed
    "notify_emails": "",  # staff who get an email for every new entry (comma-separated), set in the admin
    "email_subject": "Your {campaign} entry: #{number}",
    "email_body": ("Dear {name},\n\nThank you for supporting {org}. Your dreidel landed on number {number}.\n\n"
                   "Entry: #{number}\nDonation: {amount}\nConfirmation: {confirmation}\nDrawing date: {drawing_date}\n\n"
                   "Good luck. We hope to see you at the table!\n\n{org}"),
}

PUBLIC_CAMPAIGN_KEYS = ["org_name", "presents", "title", "subtitle", "headline", "intro", "tagline", "prize_title",
                        "prize_description", "dining_each", "prize_items", "progress_min", "prize_image", "reveal_image", "reveal_caption", "hero_images", "hero_source", "referral_enabled", "referral_threshold", "referral_reward", "referral_terms", "music_source", "music_autostart", "music_youtube", "music_title", "music_url", "restaurants", "transport", "winners", "drawing_date",
                        "start_at", "end_at", "prizes_confirmed", "share_text",
                        "org_legal_name", "org_nonprofit_status", "org_ein", "org_address", "org_email", "org_phone",
                        "campaign_purpose", "campaign_number", "rules_version", "free_entry_enabled", "min_age",
                        "eligible_regions", "entries_per_person", "prize_arv", "winner_info", "drawing_method"]

APPROVAL_STATES = ('not_started', 'in_review', 'approved')
LEGAL_TEXT_KEYS = ['org_legal_name', 'org_nonprofit_status', 'org_ein', 'org_address', 'org_email', 'org_phone',
                   'campaign_purpose', 'campaign_number', 'rules_version', 'eligible_regions', 'exclusions', 'prize_arv',
                   'prize_terms', 'prize_source', 'drawing_method', 'governing_county', 'auth_language',
                   'marketing_consent_text', 'privacy_retention', 'official_rules', 'free_entry_instructions', 'privacy_policy', 'terms_text',
                   'winner_info']
LONG_TEXT_KEYS = {'official_rules', 'free_entry_instructions', 'privacy_policy', 'terms_text'}


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def money(cents):
    return f"${cents / 100:,.2f}".replace('.00', '')


def max_gross_cents(n, unit_cents):
    return unit_cents * n * (n + 1) // 2


# ───────────────────────────── database ─────────────────────────────

ENTRIES_V3 = '''CREATE TABLE entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number INTEGER NOT NULL CHECK(number >= 1),
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    request_id TEXT UNIQUE NOT NULL,
    amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
    status TEXT NOT NULL CHECK(status IN ('pending_capture','paid','capture_failed','refunded','released','free','disqualified')),
    payment_mode TEXT NOT NULL DEFAULT 'sandbox' CHECK(payment_mode IN ('sandbox','live')),
    authorization_id TEXT,
    capture_id TEXT,
    refund_id TEXT,
    created TEXT DEFAULT CURRENT_TIMESTAMP,
    updated TEXT DEFAULT CURRENT_TIMESTAMP,
    method TEXT NOT NULL DEFAULT 'donation' CHECK(method IN ('donation','free')),
    street TEXT, city TEXT, state TEXT, zip TEXT, country TEXT,
    consent_at TEXT, consent_text TEXT, rules_version TEXT, campaign_number TEXT,
    marketing_opt_in INTEGER NOT NULL DEFAULT 0,
    received_at TEXT, notes TEXT, ref_code TEXT)'''
ENTRIES_V3_COLS = ['id', 'number', 'name', 'email', 'phone', 'request_id', 'amount_cents', 'status', 'payment_mode',
                   'authorization_id', 'capture_id', 'refund_id', 'created', 'updated']

SCHEMA = [
    'CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
    '''CREATE TABLE IF NOT EXISTS ambassadors (
        id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL,
        phone TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'self', reward_status TEXT NOT NULL DEFAULT 'none',
        fulfilled_at TEXT, notes TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)''',
    'CREATE UNIQUE INDEX IF NOT EXISTS ambassadors_email ON ambassadors(lower(email))',
    '''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER, request_id TEXT, kind TEXT NOT NULL,
        amount_cents INTEGER NOT NULL, status TEXT NOT NULL, provider_ref TEXT, message TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER, to_addr TEXT NOT NULL, subject TEXT NOT NULL,
        body_text TEXT NOT NULL, body_html TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP, sent_at TEXT)''',
    '''CREATE TABLE IF NOT EXISTS activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS drawings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, commitment TEXT NOT NULL, seed TEXT NOT NULL, committed_at TEXT NOT NULL,
        public_entropy TEXT, drawn_at TEXT, eligible TEXT, eligible_hash TEXT, winners TEXT, algorithm TEXT)''',
]


def connect(path):
    c = sqlite3.connect(path, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def init_db(path):
    with connect(path) as c:
        for s in SCHEMA:
            c.execute(s)
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('max_tickets',?)", (str(DEFAULT_MAX_TICKETS),))
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('campaign',?)", (json.dumps(DEFAULT_CAMPAIGN),))
        row = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='entries'").fetchone()
        if row is None:
            c.execute(ENTRIES_V3)
        elif 'amount_cents' not in row[0]:
            # Migrate v1 (250-ticket demo) or v2 (360 + sandbox auth) tables, keeping every issued number.
            cols = {r[1] for r in c.execute('PRAGMA table_info(entries)')}
            c.execute('ALTER TABLE entries RENAME TO entries_old')
            c.execute(ENTRIES_V3)
            auth = 'authorization_id' if 'authorization_id' in cols else "'SANDBOX-AUTH-MIGRATED-'||number"
            c.execute(f'''INSERT INTO entries(number,name,email,request_id,amount_cents,status,authorization_id,capture_id,created,updated)
                          SELECT number,name,email,request_id,number*100,'paid',{auth},'SANDBOX-CAP-MIGRATED-'||number,created,created
                          FROM entries_old''')
            c.execute('DROP TABLE entries_old')
            c.execute("INSERT INTO activity(actor,action,detail) VALUES('system','migrated_entries',?)",
                      (json.dumps({"from_columns": sorted(cols)}),))
        row = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='entries'").fetchone()
        if 'marketing_opt_in' not in row[0]:  # v3 -> v4: free entries, consent record, mailing address
            cols = ','.join(ENTRIES_V3_COLS)
            c.execute('DROP INDEX IF EXISTS entries_number_active')
            c.execute('DROP INDEX IF EXISTS entries_email')
            c.execute('ALTER TABLE entries RENAME TO entries_v3')
            c.execute(ENTRIES_V3)
            c.execute(f'INSERT INTO entries({cols}) SELECT {cols} FROM entries_v3')
            c.execute('DROP TABLE entries_v3')
            c.execute("INSERT INTO activity(actor,action,detail) VALUES('system','migrated_entries','{\"to\": \"v4\"}')")
        row = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='entries'").fetchone()
        if "payment_mode = 'sandbox'" in row[0]:  # v4 -> v5: allow live payments
            old = [r[1] for r in c.execute('PRAGMA table_info(entries)')]
            for ix in ('entries_number_active', 'entries_email', 'entries_ref'):
                c.execute(f'DROP INDEX IF EXISTS {ix}')
            c.execute('ALTER TABLE entries RENAME TO entries_v4')
            c.execute(ENTRIES_V3)
            new = {r[1] for r in c.execute('PRAGMA table_info(entries)')}
            cols = ','.join(k for k in old if k in new)
            c.execute(f'INSERT INTO entries({cols}) SELECT {cols} FROM entries_v4')
            c.execute('DROP TABLE entries_v4')
            c.execute("INSERT INTO activity(actor,action,detail) VALUES('system','migrated_entries','{\"to\": \"v5\"}')")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS entries_number_active ON entries(number) WHERE status != 'released'")
        c.execute('CREATE INDEX IF NOT EXISTS entries_email ON entries(email)')
        if 'ref_code' not in {r[1] for r in c.execute('PRAGMA table_info(entries)')}:
            c.execute('ALTER TABLE entries ADD COLUMN ref_code TEXT')
        c.execute('CREATE INDEX IF NOT EXISTS entries_ref ON entries(ref_code)')
        apply_design_v2(c)
        apply_prize_v3(c)


DESIGN_V2_OLD = {'title': 'Spin to Win', 'headline': '10 Restaurants. 10 Date Nights. One Unforgettable Year.', 'intro': "Imagine spending the next year dining for two at 10 of New York's most celebrated kosher restaurants, without worrying about the bill or the ride home.", 'share_text': "A year of date nights at NYC's finest kosher restaurants, with dinner and Uber rides covered. Spin the dreidel from $1:"}
DESIGN_V2_NEW = {'title': 'The Golden Spin', 'headline': 'A Year of Fine Dining. On Us.', 'intro': "One winner spends the next year dining for two at 10 of New York's most celebrated kosher restaurants, with dinner and the ride home taken care of.", 'share_text': "The Golden Spin: win a year of fine dining for two at 10 of New York's best kosher restaurants, rides included. Enter from $1:"}


PRIZE_V3 = {'intro': ("One winner spends the next year dining for two at 10 of New York's most celebrated kosher restaurants, with dinner and the ride home taken care of.", "One winner gets $300 to spend at each of 10 of New York's most celebrated kosher restaurants, plus a $150 Uber ride for every night out."),
            'prize_description': ('One lucky winner receives dinner for two at each of these 10 restaurants.', 'One lucky winner receives $300 to spend at each of these 10 restaurants: $3,000 in fine dining.'),
            'share_text': ("The Golden Spin: win a year of fine dining for two at 10 of New York's best kosher restaurants, rides included. Enter from $1:", "The Golden Spin: win $300 at each of 10 of New York's best kosher restaurants, plus $1,500 in Uber rides. Enter from $1:"),
            'prize_items': (['Dinner for two at 10 premier kosher restaurants.', 'A $150 Uber gift card for each restaurant night.', '$1,500 in total Uber gift cards.', 'One extraordinary year of fine dining.'], ['$300 at each of 10 premier kosher restaurants ($3,000 in dining).', 'A $150 Uber gift card for each restaurant night ($1,500 in rides).', 'Total prize value: $4,500.'])}


def apply_prize_v3(c):
    """$300 per restaurant: update the stored default prize wording once; hand-edited text stays as it is."""
    if c.execute("SELECT 1 FROM settings WHERE key='migration_prize_v3'").fetchone():
        return
    row = c.execute("SELECT value FROM settings WHERE key='campaign'").fetchone()
    if row:
        data = json.loads(row[0]); changed = []
        for k, (old, new) in PRIZE_V3.items():
            cur = data.get(k)
            if isinstance(cur, str):
                cur = cur.replace('\u2019', "'")
            if cur == old:
                data[k] = new; changed.append(k)
        c.execute("UPDATE settings SET value=? WHERE key='campaign'", (json.dumps(data),))
        if changed:
            log(c, 'system', 'prize_v3_applied', fields=changed)
    c.execute("INSERT INTO settings(key,value) VALUES('migration_prize_v3','1')")


def apply_design_v2(c):
    """The Golden Spin redesign: update stored default wording once; anything edited by hand stays as it is."""
    if c.execute("SELECT 1 FROM settings WHERE key='migration_design_v2'").fetchone():
        return
    row = c.execute("SELECT value FROM settings WHERE key='campaign'").fetchone()
    if row:
        data = json.loads(row[0]); changed = []
        for k, old in DESIGN_V2_OLD.items():
            if data.get(k, '').replace('\u2019', "'") == old:
                data[k] = DESIGN_V2_NEW[k]; changed.append(k)
        t = data.get('transport') or {}
        if t.get('title') == 'Your ride is on us!':
            t['title'] = 'Your ride is on us.'; changed.append('transport.title')
        c.execute("UPDATE settings SET value=? WHERE key='campaign'", (json.dumps(data),))
        if changed:
            log(c, 'system', 'design_v2_applied', fields=changed)
    c.execute("INSERT INTO settings(key,value) VALUES('migration_design_v2','1')")


def log(c, actor, action, **detail):
    c.execute('INSERT INTO activity(actor,action,detail) VALUES(?,?,?)', (actor, action, json.dumps(detail, default=str)))


def get_max_tickets(c):
    row = c.execute("SELECT value FROM settings WHERE key='max_tickets'").fetchone()
    return int(row[0]) if row else DEFAULT_MAX_TICKETS


def get_campaign(c):
    row = c.execute("SELECT value FROM settings WHERE key='campaign'").fetchone()
    data = copy.deepcopy(DEFAULT_CAMPAIGN)
    if row:
        data.update(json.loads(row[0]))
    return data


def active_numbers(c):
    return {r[0] for r in c.execute("SELECT number FROM entries WHERE status != 'released'")}


def sales_state(campaign, remaining):
    """Return (open, reason)."""
    now = datetime.now(TZ)

    def parse(v):
        try:
            return datetime.fromisoformat(v).replace(tzinfo=TZ) if v else None
        except ValueError:
            return None
    start, end = parse(campaign.get('start_at')), parse(campaign.get('end_at'))
    if campaign.get('sales_paused'):
        return False, 'Entries are paused.'
    if start and now < start:
        return False, f"Entries open {start.strftime('%B %-d, %Y at %-I:%M %p')}."
    if end and now >= end:
        return False, 'Entries are closed.'
    if remaining <= 0:
        return False, 'All entries have been claimed.'
    return True, ''


def summary(c):
    campaign = get_campaign(c)
    m = get_max_tickets(c)
    sold = c.execute("SELECT COUNT(*) FROM entries WHERE status IN ('paid','pending_capture','capture_failed')").fetchone()[0]
    free = c.execute("SELECT COUNT(*) FROM entries WHERE status='free'").fetchone()[0]
    taken = len(active_numbers(c))
    remaining = max(m - taken, 0)
    unit = int(campaign['unit_price_cents'])
    is_open, reason = sales_state(campaign, remaining)
    test_entries = test_entry_count(c)
    if PAYMENT_MODE == 'live' and test_entries and is_open:
        is_open, reason = False, 'Entries open soon.'  # test entries must be cleared before real donations are taken
    return dict(test_entries=test_entries, max_tickets=m, sold=sold, free_entries=free, remaining=remaining, unit_price_cents=unit,
                min_price=unit / 100, max_price=unit * m / 100, max_gross=max_gross_cents(m, unit) / 100,
                payment_mode=PAYMENT_MODE, sales_open=is_open, sales_message=reason)


def test_entry_count(c):
    """Entries made while payments were in test/sandbox mode. In live mode they must be cleared before sales open."""
    if PAYMENT_MODE != 'live':
        return 0
    return c.execute("SELECT COUNT(*) FROM entries WHERE payment_mode='sandbox' AND status != 'released'").fetchone()[0]


ELIGIBLE_STATUSES = ('paid', 'free')

CODE_RE = re.compile(r'[a-z0-9-]{3,40}')


def ambassador_by_code(c, code):
    code = str(code or '').strip().lower()
    return c.execute('SELECT * FROM ambassadors WHERE code=?', (code,)).fetchone() if CODE_RE.fullmatch(code) else None


def new_ambassador_code(c, name):
    base = re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')[:20] or 'friend'
    for _ in range(50):
        code = f"{base}-{secrets.token_hex(2)}"
        if not c.execute('SELECT 1 FROM ambassadors WHERE code=?', (code,)).fetchone():
            return code
    return 'friend-' + secrets.token_hex(5)


def get_or_create_ambassador(c, name, email, phone='', source='self'):
    row = c.execute('SELECT * FROM ambassadors WHERE lower(email)=lower(?)', (email,)).fetchone()
    if row:
        return row, False
    code = new_ambassador_code(c, name)
    # OR IGNORE: two simultaneous entries by the same person can't both create a link
    cur = c.execute('INSERT OR IGNORE INTO ambassadors(code,name,email,phone,source) VALUES(?,?,?,?,?)', (code, name, email, phone or '', source))
    row = c.execute('SELECT * FROM ambassadors WHERE lower(email)=lower(?)', (email,)).fetchone()
    return row, cur.rowcount == 1


def ambassador_stats(c, amb):
    """Paid entries by other people through this link."""
    r = c.execute("""SELECT COUNT(*), COALESCE(SUM(amount_cents),0) FROM entries
                     WHERE ref_code=? AND status='paid' AND lower(email)!=lower(?)""", (amb['code'], amb['email'])).fetchone()
    return r[0], r[1]


def org_display(campaign):
    return campaign.get('org_legal_name') or campaign['org_name']


def auth_text(campaign, info):
    vals = _Safe(org=org_display(campaign), min=money(info['unit_price_cents']),
                 max=money(info['unit_price_cents'] * info['max_tickets']))
    return campaign['auth_language'].format_map(vals)


def person_entry_count(c, email):
    return c.execute("SELECT COUNT(*) FROM entries WHERE lower(email)=lower(?) AND status NOT IN ('released','refunded','disqualified')",
                     (email,)).fetchone()[0]


def limit_reached(c, campaign, email):
    lim = int(campaign.get('entries_per_person') or 0)
    return lim > 0 and person_entry_count(c, email) >= lim


# ───────────────────────────── sandbox payments ─────────────────────────────

class SandboxGateway:
    """Simulated processor. No card data is collected or stored anywhere.

    Test scenarios (sandbox only): an email containing '+decline' is declined at authorization;
    an email containing '+capturefail' fails at capture.
    """

    name = 'simulated'
    publishable_key = None

    def authorize(self, amount_cents, email, payment_intent_id=None, request_id=None):
        if '+decline' in email.lower():
            return False, None, 'Sandbox: authorization declined.'
        return True, 'SANDBOX-AUTH-' + secrets.token_hex(8).upper(), 'Sandbox authorization approved.'

    def capture(self, authorization_id, amount_cents, email, attempt=1):
        if '+capturefail' in email.lower() and attempt == 1:
            return False, None, 'Sandbox: capture failed (test scenario).'
        return True, 'SANDBOX-CAP-' + secrets.token_hex(8).upper(), 'Sandbox capture succeeded.'

    def void(self, authorization_id):
        return True, 'SANDBOX-VOID-' + secrets.token_hex(6).upper(), 'Sandbox authorization voided.'

    def refund(self, capture_id, amount_cents):
        return True, 'SANDBOX-REF-' + secrets.token_hex(8).upper(), 'Sandbox refund issued.'


class StripeError(Exception):
    pass


def _stripe_http(secret_key, method, path, params, idempotency_key=None):
    import base64, urllib.error, urllib.parse, urllib.request
    url = 'https://api.stripe.com' + path
    data = urllib.parse.urlencode(params).encode() if method == 'POST' else None
    if method == 'GET' and params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Authorization', 'Basic ' + base64.b64encode((secret_key + ':').encode()).decode())
    if idempotency_key:
        req.add_header('Idempotency-Key', idempotency_key)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get('error', {}).get('message')
        except Exception:
            msg = None
        raise StripeError(msg or f'Stripe error {e.code}') from None
    except urllib.error.URLError as e:
        raise StripeError(f'Could not reach Stripe: {e.reason}') from None


class StripeGateway:
    """Stripe (test or live keys). Card details go from the visitor's browser straight to Stripe
    (Stripe Payment Element); this server only ever sees PaymentIntent and charge ids.

    Flow: a PaymentIntent for the maximum amount with capture_method=manual (an authorization hold),
    then a partial capture of exactly the assigned amount; Stripe releases the rest of the hold.
    """
    def __init__(self, secret_key, publishable_key, http=None, live=False):
        kind = 'live' if live else 'test'
        if not (secret_key.startswith((f'sk_{kind}_', f'rk_{kind}_')) and publishable_key.startswith(f'pk_{kind}_')):
            if live:
                raise ValueError('RAFFLE_LIVE_PAYMENTS=1 needs LIVE Stripe keys (sk_live_/rk_live_ and pk_live_).')
            raise ValueError('Stripe LIVE keys need RAFFLE_LIVE_PAYMENTS=1. Otherwise use TEST keys (sk_test_/rk_test_ and pk_test_).')
        self.live = live
        self.name = 'stripe_live' if live else 'stripe_test'
        self.secret_key, self.publishable_key = secret_key, publishable_key
        self.http = http or _stripe_http

    def _call(self, method, path, params=None, idem=None):
        return self.http(self.secret_key, method, path, params or {}, idem)

    def create_intent(self, amount_cents, request_id, email, description):
        pi = self._call('POST', '/v1/payment_intents', {
            'amount': amount_cents, 'currency': 'usd', 'capture_method': 'manual',
            'payment_method_types[]': 'card', 'description': description,
            'metadata[request_id]': request_id, 'metadata[email]': email}, idem='pi-' + request_id)
        return pi['id'], pi['client_secret']

    def authorize(self, amount_cents, email, payment_intent_id=None, request_id=None):
        if not payment_intent_id or not re.fullmatch(r'pi_[A-Za-z0-9]+', str(payment_intent_id)):
            return False, None, 'No card authorization was provided.'
        try:
            pi = self._call('GET', f'/v1/payment_intents/{payment_intent_id}')
        except StripeError as e:
            return False, None, str(e)
        if (pi.get('metadata') or {}).get('request_id') != request_id:
            return False, None, 'This card authorization belongs to a different entry.'
        if pi.get('status') != 'requires_capture':
            return False, pi.get('id'), f"Card not authorized (Stripe status: {pi.get('status')})."
        if int(pi.get('amount_capturable') or 0) < amount_cents:
            return False, pi.get('id'), 'Card authorization is lower than the maximum entry amount.'
        return True, pi['id'], 'Stripe test authorization confirmed.'

    def capture(self, authorization_id, amount_cents, email, attempt=1):
        try:
            pi = self._call('POST', f'/v1/payment_intents/{authorization_id}/capture',
                            {'amount_to_capture': amount_cents}, idem=f'cap-{authorization_id}-{attempt}')
        except StripeError as e:
            return False, None, str(e)
        if pi.get('status') != 'succeeded':
            return False, None, f"Capture not completed (Stripe status: {pi.get('status')})."
        return True, pi.get('latest_charge') or pi['id'], 'Stripe test capture succeeded; the rest of the hold was released.'

    def void(self, authorization_id):
        if not authorization_id:
            return True, None, 'Nothing to void.'
        try:
            pi = self._call('POST', f'/v1/payment_intents/{authorization_id}/cancel', idem=f'void-{authorization_id}')
        except StripeError as e:
            return False, None, str(e)
        return True, pi.get('id'), 'Stripe authorization hold released.'

    def refund(self, capture_id, amount_cents):
        key = 'charge' if str(capture_id).startswith('ch_') else 'payment_intent'
        try:
            r = self._call('POST', '/v1/refunds', {key: capture_id, 'amount': amount_cents}, idem=f'refund-{capture_id}')
        except StripeError as e:
            return False, None, str(e)
        return True, r.get('id'), 'Stripe test refund issued.'


def make_gateway(env):
    blank = lambda v: '' if v.strip().lower() in ('', 'none', '-', 'off') else v.strip()  # noqa: E731
    sk, pk = blank(env.get('STRIPE_SECRET_KEY', '')), blank(env.get('STRIPE_PUBLISHABLE_KEY', ''))
    live = env.get('RAFFLE_LIVE_PAYMENTS', '').strip() == '1'
    if sk or pk or live:
        return StripeGateway(sk, pk, live=live)
    return SandboxGateway()


def record_txn(c, kind, amount_cents, ok, ref, message, entry_id=None, request_id=None):
    c.execute('INSERT INTO transactions(entry_id,request_id,kind,amount_cents,status,provider_ref,message) VALUES(?,?,?,?,?,?,?)',
              (entry_id, request_id, kind, amount_cents, 'succeeded' if ok else 'failed', ref, message))


# ───────────────────────────── email ─────────────────────────────

class _Safe(dict):
    def __missing__(self, k):
        return '{' + k + '}'


def confirmation_code(number):
    return f'YM-{number:03d}'


def render_email(campaign, entry):
    amount = 'Free entry (no donation)' if entry['status'] == 'free' else money(entry['amount_cents'])
    vals = _Safe(name=entry['name'], number=entry['number'], amount=amount,
                 confirmation=confirmation_code(entry['number']), campaign=campaign['title'],
                 org=campaign['org_name'], drawing_date=campaign.get('drawing_date') or 'To be announced')
    subject = campaign['email_subject'].format_map(vals)
    text = campaign['email_body'].format_map(vals)
    esc = {k: html.escape(str(v)) for k, v in vals.items()}
    body = '<br>'.join(html.escape(line) for line in text.split('\n'))
    html_body = f'''<div style="background:#07080c;padding:32px 12px;font-family:Georgia,serif;color:#f4ecdc">
<div style="max-width:520px;margin:auto;border:1px solid #6b5426;border-radius:18px;padding:32px;background:#0f1118">
<p style="letter-spacing:4px;text-transform:uppercase;font-size:11px;color:#d4a64a;margin:0">{html.escape(campaign['presents'])}</p>
<h1 style="font-size:30px;color:#f2d084;margin:8px 0 18px">{html.escape(campaign['title'])}</h1>
<div style="border:1px dashed #d4a64a;border-radius:14px;padding:20px;text-align:center;margin-bottom:22px">
<p style="margin:0;font-size:11px;letter-spacing:3px;color:#a79f8f;text-transform:uppercase">Your entry</p>
<p style="margin:6px 0;font-size:56px;color:#f2d084;font-weight:bold">#{esc['number']}</p>
<p style="margin:0;color:#f4ecdc">{esc['amount']} · Confirmation {esc['confirmation']}</p></div>
<p style="font-family:Arial,sans-serif;font-size:15px;line-height:1.6;color:#e6dccb">{body}</p>
{'' if PAYMENT_MODE == 'live' else '<p style="font-family:Arial,sans-serif;font-size:11px;color:#8a8273;margin-top:24px">Test mode: no real charge was made.</p>'}
</div></div>'''
    return subject, text, html_body


def smtp_configured():
    """Real email needs a host, and a password whenever a username is set (Gmail: an app password)."""
    pw = os.environ.get('SMTP_PASSWORD', '').strip()
    pw = '' if pw.lower() in ('none', '-', 'off') else pw
    return bool(os.environ.get('SMTP_HOST')) and (not os.environ.get('SMTP_USER') or bool(pw))


def smtp_send(to, subject, text, html_body=None):
    """Returns (status, error, sent_at). Without SMTP settings the message is only kept in the admin outbox."""
    if not smtp_configured():
        return 'logged', None, None
    try:
        msg = EmailMessage()
        msg['Subject'], msg['To'] = subject, to
        msg['From'] = os.environ.get('SMTP_FROM', os.environ.get('SMTP_USER', 'raffle@localhost'))
        msg.set_content(text)
        if html_body:
            msg.add_alternative(html_body, subtype='html')
        with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.environ.get('SMTP_PORT', '587')), timeout=15) as s:
            if os.environ.get('SMTP_STARTTLS', '1') == '1':
                s.starttls()
            if os.environ.get('SMTP_USER'):
                s.login(os.environ['SMTP_USER'], os.environ.get('SMTP_PASSWORD', ''))
            s.send_message(msg)
        return 'sent', None, now_iso()
    except Exception as e:  # keep the entry; surface the failure in the admin outbox
        return 'failed', str(e)[:300], None


def deliver_email(c, entry, campaign, actor='system'):
    subject, text, html_body = render_email(campaign, entry)
    status, err, sent_at = smtp_send(entry['email'], subject, text, html_body)
    c.execute('INSERT INTO emails(entry_id,to_addr,subject,body_text,body_html,status,error,sent_at) VALUES(?,?,?,?,?,?,?,?)',
              (entry['id'], entry['email'], subject, text, html_body, status, err, sent_at))
    log(c, actor, 'email_' + status, entry_id=entry['id'], to=entry['email'], error=err)
    return status


def staff_notice(c, entry, campaign):
    """Build the 'new entry' alert for staff: returns (recipients, subject, text) or None."""
    to = [a.strip() for a in (campaign.get('notify_emails') or '').split(',') if a.strip()]
    if not to:
        return None
    free = entry['status'] == 'free'
    amount = 'Free mail-in entry' if free else money(entry['amount_cents'])
    paid_n, raised = c.execute("SELECT COUNT(*), COALESCE(SUM(amount_cents),0) FROM entries WHERE status='paid'").fetchone()
    free_n = c.execute("SELECT COUNT(*) FROM entries WHERE status='free'").fetchone()[0]
    left = get_max_tickets(c) - len(active_numbers(c))
    ref = ''
    if 'ref_code' in entry.keys() and entry['ref_code']:
        a = c.execute('SELECT name FROM ambassadors WHERE code=?', (entry['ref_code'],)).fetchone()
        ref = f"\nThrough the link of: {a['name'] if a else entry['ref_code']}"
    subject = f"New entry #{entry['number']}: {amount} · {entry['name']}"
    text = (f"{campaign['title']}: new entry\n\nEntry: #{entry['number']}\nDonation: {amount}\nName: {entry['name']}\n"
            f"Email: {entry['email']}\nPhone: {entry['phone'] or '-'}{ref}\n\n"
            f"Totals so far: {paid_n} paid entries, {money(raised)} raised, {free_n} free entries, {left} numbers left.\n")
    return to, subject, text


def send_staff_notice(connect_fn, notice, entry_id):
    """Send the staff alert in the background so the donor never waits for it; record it in the outbox."""
    import threading
    to, subject, text = notice

    def run():
        for addr in to:
            status, err, sent_at = smtp_send(addr, subject, text)
            try:
                with connect_fn() as c2:
                    c2.execute('INSERT INTO emails(entry_id,to_addr,subject,body_text,body_html,status,error,sent_at) VALUES(?,?,?,?,?,?,?,?)',
                               (entry_id, addr, subject, text, '<pre style="font:14px/1.5 sans-serif">' + html.escape(text) + '</pre>',
                                status, err, sent_at))
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()


# ───────────────────────────── auditable drawing ─────────────────────────────

ALGORITHM = ('final_seed = SHA256(seed_hex + public_entropy); eligible = sorted numbers of paid and free (mail-in) entries; '
             'eligible_hash = SHA256(",".join(eligible)); for i in 0..winners-1: '
             'k = int(HMAC_SHA256(final_seed, eligible_hash + ":" + i)) mod len(remaining); winner = remaining.pop(k)')


def commit_drawing(c):
    seed = secrets.token_hex(32)
    commitment = hashlib.sha256(seed.encode()).hexdigest()
    c.execute('INSERT INTO drawings(commitment,seed,committed_at,algorithm) VALUES(?,?,?,?)', (commitment, seed, now_iso(), ALGORITHM))
    return commitment


def pick_winners(seed, public_entropy, eligible, count):
    final_seed = hashlib.sha256((seed + (public_entropy or '')).encode()).digest()
    eligible = sorted(eligible)
    eligible_hash = hashlib.sha256(','.join(map(str, eligible)).encode()).hexdigest()
    remaining, winners = list(eligible), []
    for i in range(min(count, len(remaining))):
        k = int.from_bytes(hmac.new(final_seed, f'{eligible_hash}:{i}'.encode(), hashlib.sha256).digest(), 'big') % len(remaining)
        winners.append(remaining.pop(k))
    return winners, eligible_hash


# ───────────────────────────── validation ─────────────────────────────

EMAIL_RE = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+')
RID_RE = re.compile(r'[a-zA-Z0-9-]{16,80}')


def clean_phone(p):
    p = str(p or '').strip()
    digits = re.sub(r'\D', '', p)
    return p[:32] if 7 <= len(digits) <= 15 and re.fullmatch(r'[0-9+()\-.\s]+', p) else None


def validate_campaign(data, current):
    """Merge admin edits into the campaign config with type checks."""
    out = copy.deepcopy(current)
    text_keys = ['org_name', 'presents', 'title', 'subtitle', 'headline', 'intro', 'tagline', 'prize_title',
                 'prize_description', 'dining_each', 'prize_image', 'reveal_image', 'reveal_caption', 'drawing_date', 'start_at', 'end_at', 'share_text',
                 'email_subject', 'email_body']
    for k in text_keys:
        if k in data:
            v = str(data[k] or '').strip()
            if len(v) > 4000:
                raise ValueError(f'{k} is too long.')
            out[k] = v
    for k in LEGAL_TEXT_KEYS:
        if k in data:
            v = str(data[k] or '').strip()
            if len(v) > (60000 if k in LONG_TEXT_KEYS else 4000):
                raise ValueError(f'{k} is too long.')
            out[k] = v
    for k in ('legal_approval_status', 'processor_approval_status'):
        if k in data:
            if data[k] not in APPROVAL_STATES:
                raise ValueError(f'{k} must be one of {", ".join(APPROVAL_STATES)}.')
            out[k] = data[k]
    if 'notify_emails' in data:
        addrs = [a.strip() for a in re.split(r'[,;\s]+', str(data['notify_emails'] or '')) if a.strip()]
        bad = [a for a in addrs if not EMAIL_RE.fullmatch(a)]
        if bad or len(addrs) > 10:
            raise ValueError('Enter up to 10 valid email addresses, separated by commas.')
        out['notify_emails'] = ', '.join(addrs)
    for k in ('referral_reward', 'referral_terms'):
        if k in data:
            out[k] = str(data[k] or '').strip()[:600]
    for k, lo, hi in (('min_age', 13, 99), ('entries_per_person', 0, 1000), ('claim_days', 1, 365), ('referral_threshold', 1, 360), ('progress_min', 0, 5000)):
        if k in data:
            try:
                v = int(data[k])
            except (TypeError, ValueError):
                raise ValueError(f'{k} must be a whole number.')
            if not lo <= v <= hi:
                raise ValueError(f'{k} must be between {lo} and {hi}.')
            out[k] = v
    if 'prize_items' in data:
        items = data['prize_items']
        if isinstance(items, str):
            items = items.splitlines()
        if not isinstance(items, list):
            raise ValueError('prize_items must be a list.')
        items = [str(i or '').strip()[:300] for i in items]
        out['prize_items'] = [i for i in items if i][:12]
    for k in ('start_at', 'end_at'):
        if out[k]:
            try:
                datetime.fromisoformat(out[k])
            except ValueError:
                raise ValueError(f'{k} must be a date/time like 2026-12-14T20:00.')
    if out.get('start_at') and out.get('end_at') and out['end_at'] <= out['start_at']:
        raise ValueError('The end date must be after the start date.')
    for k in ('sales_paused', 'prizes_confirmed', 'free_entry_enabled', 'winner_anonymous_allowed', 'music_autostart', 'referral_enabled'):
        if k in data:
            out[k] = bool(data[k])
    if 'winners' in data:
        w = int(data['winners'])
        if not 1 <= w <= 100:
            raise ValueError('Number of winners must be between 1 and 100.')
        out['winners'] = w
    if 'unit_price_cents' in data:
        u = int(data['unit_price_cents'])
        if not 1 <= u <= 100000:
            raise ValueError('Price per number must be between $0.01 and $1,000.')
        out['unit_price_cents'] = u
    if 'restaurants' in data:
        rs = []
        for r in data['restaurants'] or []:
            name = str(r.get('name', '')).strip()
            if not name:
                continue
            rs.append({k: str(r.get(k, '') or '').strip()[:600] for k in ('name', 'location', 'description', 'logo', 'photo')})
        if len(rs) > 40:
            raise ValueError('Too many restaurants or sponsors (40 max).')
        out['restaurants'] = rs
    if 'transport' in data and isinstance(data['transport'], dict):
        t = dict(out['transport'])
        for k in ('title', 'amount', 'amount_label', 'detail', 'brand', 'logo', 'image'):
            if k in data['transport']:
                t[k] = str(data['transport'][k] or '').strip()[:600]
        if 'enabled' in data['transport']:
            t['enabled'] = bool(data['transport']['enabled'])
        out['transport'] = t
    for k in ('prize_image', 'reveal_image'):
        if out.get(k) and not re.fullmatch(r'/(assets|uploads)/[A-Za-z0-9._/-]+', out[k]):
            raise ValueError('Images must be uploaded files.')
    if 'music_source' in data:
        if data['music_source'] not in ('youtube', 'upload', 'off'):
            raise ValueError('music_source must be youtube, upload or off.')
        out['music_source'] = data['music_source']
    if 'music_youtube' in data:
        v = str(data['music_youtube'] or '').strip()
        m = re.search(r'(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})', v) or re.fullmatch(r'([A-Za-z0-9_-]{11})', v)
        if v and not m:
            raise ValueError('Enter a YouTube link or video ID.')
        out['music_youtube'] = m.group(1) if m else ''
    if 'music_title' in data:
        out['music_title'] = str(data['music_title'] or '').strip()[:200]
    if 'music_url' in data:
        v = str(data['music_url'] or '').strip()
        if v and not re.fullmatch(r'/(assets|uploads)/[A-Za-z0-9._/-]+\.(mp3|m4a|ogg)', v):
            raise ValueError('Music must be an uploaded MP3, M4A or OGG file.')
        out['music_url'] = v
    if 'hero_source' in data:
        if data['hero_source'] not in ('restaurants', 'custom'):
            raise ValueError('hero_source must be restaurants or custom.')
        out['hero_source'] = data['hero_source']
    if 'hero_images' in data:
        imgs = data['hero_images']
        if not isinstance(imgs, list):
            raise ValueError('hero_images must be a list.')
        imgs = [str(i or '').strip() for i in imgs if str(i or '').strip()][:8]
        for i in imgs:
            if not re.fullmatch(r'/(assets|uploads)/[A-Za-z0-9._/-]+', i):
                raise ValueError('Images must be uploaded files.')
        out['hero_images'] = imgs
    for r in out['restaurants']:
        for k in ('logo', 'photo'):
            if r.get(k) and not re.fullmatch(r'/(assets|uploads)/[A-Za-z0-9._/-]+', r[k]):
                raise ValueError('Images must be uploaded files.')
    for k in ('logo', 'image'):
        v = out['transport'].get(k)
        if v and not re.fullmatch(r'/(assets|uploads)/[A-Za-z0-9._/-]+', v):
            raise ValueError('Images must be uploaded files.')
    return out
