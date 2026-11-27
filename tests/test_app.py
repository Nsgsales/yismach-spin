import json, os, sqlite3, sys, threading, uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('RAFFLE_DB', str(ROOT / 'tests' / '.import-only.sqlite'))
os.environ['RAFFLE_UPLOADS'] = str(ROOT / 'tests' / '.uploads')

import app as appmod  # noqa: E402
import raffle_core as core  # noqa: E402

ADMIN = {'X-Requested-With': 'raffle-admin'}


@pytest.fixture
def make(tmp_path):
    def _make(db=None):
        a = appmod.create_app(str(db or tmp_path / 'r.sqlite'))
        a.config['TESTING'] = True
        return a
    return _make


@pytest.fixture
def app(make):
    return make()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(app):
    c = app.test_client()
    r = c.post('/api/admin/login', json={'username': 'admin', 'password': 'local-demo-only'})
    assert r.status_code == 200
    return c


def spin(client, email='t@example.com', rid=None, **kw):
    body = dict(name='Test Person', email=email, phone='(718) 555-0100', consent=True, consent_rules=True, request_id=rid or str(uuid.uuid4()))
    body.update(kw)
    return client.post('/api/spin', json=body)


def test_status_defaults(client):
    s = client.get('/api/status').json
    assert s['max_tickets'] == 360 and s['remaining'] == 360
    assert s['min_price'] == 1 and s['max_price'] == 360 and s['max_gross'] == 64980
    assert s['payment_mode'] == 'sandbox' and s['sales_open'] is True


def test_public_campaign_has_ten_restaurants_and_uber(client):
    d = client.get('/api/campaign').json['campaign']
    names = [r['name'] for r in d['restaurants']]
    assert len(names) == 10 and "Mike's Bistro" in names and 'Bison & Bourbon' in names and 'Anju' not in names
    assert d['transport']['amount'] == '$1,500'
    assert 'email_body' not in d  # admin-only fields are not public


def test_spin_assigns_number_amount_and_email(client, admin):
    r = spin(client)
    assert r.status_code == 200, r.json
    d = r.json
    assert 1 <= d['number'] <= 360 and d['amount'] == d['number']
    assert d['payment_status'] == 'paid' and d['email_status'] == 'logged'
    tx = admin.get('/api/admin/transactions').json['transactions']
    kinds = sorted(t['kind'] for t in tx)
    assert kinds == ['authorize', 'capture']
    auth = next(t for t in tx if t['kind'] == 'authorize')
    cap = next(t for t in tx if t['kind'] == 'capture')
    assert auth['amount_cents'] == 36000 and cap['amount_cents'] == d['number'] * 100


def test_validation(client):
    assert spin(client, phone='abc').status_code == 400
    assert spin(client, consent=False).status_code == 400
    assert spin(client, email='nope').status_code == 400


def test_idempotent_retry_never_charges_twice(client, admin):
    rid = str(uuid.uuid4())
    a, b = spin(client, rid=rid).json, spin(client, rid=rid).json
    assert a['number'] == b['number']
    caps = [t for t in admin.get('/api/admin/transactions').json['transactions'] if t['kind'] == 'capture']
    assert len(caps) == 1
    assert spin(client, rid=rid, email='other@example.com').status_code == 409


def test_sell_out_unique_numbers_and_total(make, tmp_path):
    a = make()
    c = a.test_client()
    nums = {spin(c).json['number'] for _ in range(360)}
    assert nums == set(range(1, 361))
    r = spin(c)
    assert r.status_code == 409
    ad = a.test_client()
    ad.post('/api/admin/login', json={'username': 'admin', 'password': 'local-demo-only'})
    assert ad.get('/api/admin').json['total'] == 64980


def test_concurrent_spins_never_duplicate(make):
    a = make()
    results, lock = [], threading.Lock()

    def worker():
        c = a.test_client()
        for _ in range(15):
            r = spin(c)
            with lock:
                results.append(r.json['number'])
    ts = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(results) == 120 and len(set(results)) == 120


def test_declined_authorization_assigns_nothing(client):
    r = spin(client, email='t+decline@example.com')
    assert r.status_code == 402
    assert client.get('/api/status').json['remaining'] == 360


def test_capture_failure_retry_and_release(client, admin):
    d = spin(client, email='t+capturefail@example.com').json
    assert d['payment_status'] == 'capture_failed' and d['email_status'] is None
    entry = admin.get('/api/admin').json['entries'][0]
    assert entry['status'] == 'capture_failed'
    r = admin.post(f"/api/admin/entries/{entry['id']}/retry-capture", headers=ADMIN)
    assert r.json['ok'] is True
    assert admin.get('/api/admin').json['entries'][0]['status'] == 'paid'
    # second failed entry gets released back to the pool
    d2 = spin(client, email='u+capturefail@example.com').json
    e2 = next(e for e in admin.get('/api/admin').json['entries'] if e['number'] == d2['number'])
    assert admin.post(f"/api/admin/entries/{e2['id']}/release", headers=ADMIN).json['ok']
    assert client.get('/api/status').json['remaining'] == 359


def test_refund(client, admin):
    spin(client)
    e = admin.get('/api/admin').json['entries'][0]
    assert admin.post(f"/api/admin/entries/{e['id']}/refund", json={'reason': 'test'}, headers=ADMIN).json['ok']
    data = admin.get('/api/admin').json
    assert data['entries'][0]['status'] == 'refunded' and data['total'] == 0
    assert admin.post(f"/api/admin/entries/{e['id']}/refund", json={}, headers=ADMIN).status_code == 409


def test_admin_requires_login_and_csrf_header(app, client):
    assert client.get('/api/admin').status_code == 401
    assert client.post('/api/admin/login', json={'username': 'admin', 'password': 'wrong'}).status_code == 401
    c = app.test_client()
    c.post('/api/admin/login', json={'username': 'admin', 'password': 'local-demo-only'})
    assert c.post('/api/admin/settings', json={'max_tickets': 400}).status_code == 403  # missing CSRF header
    assert c.post('/api/admin/settings', json={'max_tickets': 400}, headers=ADMIN).status_code == 200
    # legacy bearer token still works for scripts
    assert client.get('/api/admin', headers={'Authorization': 'Bearer local-demo-only'}).status_code == 200


def test_login_rate_limited(client):
    for _ in range(8):
        client.post('/api/admin/login', json={'username': 'admin', 'password': 'x'})
    assert client.post('/api/admin/login', json={'username': 'admin', 'password': 'local-demo-only'}).status_code == 429


def test_max_tickets_rules(client, admin):
    spin(client)
    highest = admin.get('/api/admin').json['highest_issued']
    if highest > 1:
        assert admin.post('/api/admin/settings', json={'max_tickets': highest - 1}, headers=ADMIN).status_code == 409
    r = admin.post('/api/admin/settings', json={'max_tickets': 400}, headers=ADMIN).json
    assert r['max_tickets'] == 400 and r['max_gross'] == 80200


def test_campaign_settings_and_price_lock(client, admin):
    r = admin.put('/api/admin/campaign', json={'title': 'Chanukah Spin', 'winners': 2, 'unit_price_cents': 200}, headers=ADMIN)
    assert r.status_code == 200 and r.json['status']['max_price'] == 720
    assert client.get('/api/campaign').json['campaign']['title'] == 'Chanukah Spin'
    d = spin(client).json
    assert d['amount'] == d['number'] * 2
    assert admin.put('/api/admin/campaign', json={'unit_price_cents': 100}, headers=ADMIN).status_code == 409
    assert admin.put('/api/admin/campaign', json={'prize_image': 'https://evil.example/x.png'}, headers=ADMIN).status_code == 400
    assert len(client.get('/api/campaign').json['campaign']['hero_images']) == 5
    assert admin.put('/api/admin/campaign', json={'hero_images': ['https://evil.example/x.png']}, headers=ADMIN).status_code == 400
    assert admin.put('/api/admin/campaign', json={'hero_images': ['/assets/img/avenue.jpg', '']}, headers=ADMIN).status_code == 200
    assert client.get('/api/campaign').json['campaign']['hero_images'] == ['/assets/img/avenue.jpg']
    assert admin.put('/api/admin/campaign', json={'prize_items': ['A', ' ', 'B']}, headers=ADMIN).status_code == 200
    assert client.get('/api/campaign').json['campaign']['prize_items'] == ['A', 'B']


def test_sales_window(client, admin):
    admin.put('/api/admin/campaign', json={'start_at': '2099-01-01T10:00'}, headers=ADMIN)
    r = spin(client)
    assert r.status_code == 409 and 'open' in r.json['error']
    admin.put('/api/admin/campaign', json={'start_at': '', 'sales_paused': True}, headers=ADMIN)
    assert spin(client).status_code == 409


def test_auditable_drawing(client, admin):
    for _ in range(20):
        spin(client)
    assert admin.post('/api/admin/drawing/draw', json={'public_entropy': 'x'}, headers=ADMIN).status_code == 409  # no commitment
    commit = admin.post('/api/admin/drawing/commit', headers=ADMIN).json['commitment']
    assert client.get('/api/drawing').json['drawing']['commitment'] == commit
    assert 'seed' not in client.get('/api/drawing').json['drawing']
    assert admin.post('/api/admin/drawing/draw', json={'public_entropy': 'x'}, headers=ADMIN).status_code == 409  # sales open
    admin.put('/api/admin/campaign', json={'sales_paused': True}, headers=ADMIN)
    r = admin.post('/api/admin/drawing/draw', json={'public_entropy': 'NY Pick-3 123'}, headers=ADMIN).json
    pub = client.get('/api/drawing').json['drawing']
    import hashlib
    assert hashlib.sha256(pub['seed'].encode()).hexdigest() == commit
    winners, ehash = core.pick_winners(pub['seed'], pub['public_entropy'], pub['eligible'], 1)
    assert winners == pub['winners'] == r['winners'] and ehash == pub['eligible_hash']
    assert admin.post('/api/admin/drawing/draw', json={'public_entropy': 'again'}, headers=ADMIN).status_code == 409


def test_email_outbox_and_resend(client, admin):
    spin(client)
    e = admin.get('/api/admin').json['entries'][0]
    assert admin.post(f"/api/admin/entries/{e['id']}/resend-email", headers=ADMIN).json['email_status'] == 'logged'
    mails = admin.get('/api/admin/emails').json['emails']
    assert len(mails) == 2 and f"#{e['number']}" in mails[0]['subject']
    body = admin.get(f"/api/admin/emails/{mails[0]['id']}").json
    assert f"#{e['number']}" in body['body_html'] and 'Test mode' in body['body_html']


def test_csv_export_is_injection_safe(client, admin):
    spin(client, name='=HYPERLINK("x")')
    csv = admin.get('/api/admin/export').data.decode()
    assert "'=HYPERLINK" in csv and 'Phone' in csv.splitlines()[0]


def test_activity_log(client, admin):
    spin(client)
    actions = [a['action'] for a in admin.get('/api/admin/activity').json['activity']]
    for a in ('login', 'authorization_approved', 'number_assigned', 'capture_succeeded', 'email_logged'):
        assert a in actions


def test_upload_accepts_images_only(admin):
    import io
    png = b'\x89PNG\r\n\x1a\n' + b'0' * 64
    r = admin.post('/api/admin/upload', data={'file': (io.BytesIO(png), 'a.png')}, headers=ADMIN, content_type='multipart/form-data')
    assert r.status_code == 200 and r.json['url'].endswith('.png')
    r = admin.post('/api/admin/upload', data={'file': (io.BytesIO(b'<script>'), 'a.html')}, headers=ADMIN, content_type='multipart/form-data')
    assert r.status_code == 400


def test_migrates_v1_and_v2_databases(make, tmp_path):
    db = tmp_path / 'old.sqlite'
    c = sqlite3.connect(db)
    c.execute('CREATE TABLE entries (number INTEGER PRIMARY KEY CHECK(number BETWEEN 1 AND 250), name TEXT NOT NULL,email TEXT NOT NULL, request_id TEXT UNIQUE NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP)')
    c.execute("INSERT INTO entries(number,name,email,request_id) VALUES(17,'Old','o@example.com','oldrequest-000000001')")
    c.commit()
    c.close()
    a = make(db)
    cl = a.test_client()
    assert cl.get('/api/status').json['remaining'] == 359
    nums = {spin(cl).json['number'] for _ in range(50)}
    assert 17 not in nums


def test_live_needs_both_live_keys_and_switch():
    live = {'STRIPE_SECRET_KEY': 'rk_live_x', 'STRIPE_PUBLISHABLE_KEY': 'pk_live_x'}
    with pytest.raises(ValueError, match='RAFFLE_LIVE_PAYMENTS'):
        core.make_gateway(live)  # live keys without the switch
    with pytest.raises(ValueError):
        core.make_gateway({'STRIPE_SECRET_KEY': 'sk_test_x', 'STRIPE_PUBLISHABLE_KEY': 'pk_test_x', 'RAFFLE_LIVE_PAYMENTS': '1'})
    with pytest.raises(ValueError):
        core.make_gateway({'RAFFLE_LIVE_PAYMENTS': '1'})  # switch without keys
    with pytest.raises(ValueError):
        core.make_gateway({'STRIPE_SECRET_KEY': 'rk_live_x', 'STRIPE_PUBLISHABLE_KEY': 'pk_test_x', 'RAFFLE_LIVE_PAYMENTS': '1'})
    assert core.make_gateway(dict(live, RAFFLE_LIVE_PAYMENTS='1')).name == 'stripe_live'
    assert core.make_gateway({}).name == 'simulated'


class FakeStripe:
    """In-memory stand-in for the Stripe API (test mode), used to exercise the real StripeGateway."""

    def __init__(self):
        self.intents, self.calls, self.n = {}, [], 0

    def __call__(self, key, method, path, params, idem=None):
        assert key.startswith(('sk_test_', 'rk_live_'))
        self.calls.append((method, path, dict(params), idem))
        parts = path.strip('/').split('/')
        if path == '/v1/payment_intents' and method == 'POST':
            for pi in self.intents.values():  # idempotency
                if pi['_idem'] == idem:
                    return pi
            self.n += 1
            pid = f'pi_test{self.n}'
            pi = {'id': pid, 'client_secret': pid + '_secret_x', 'amount': int(params['amount']), 'status': 'requires_payment_method',
                  'amount_capturable': 0, 'metadata': {'request_id': params['metadata[request_id]']}, '_idem': idem}
            self.intents[pid] = pi
            return pi
        if parts[:2] == ['v1', 'payment_intents'] and len(parts) == 3:
            if parts[2] not in self.intents:
                raise core.StripeError('No such payment_intent')
            return self.intents[parts[2]]
        if parts[:2] == ['v1', 'payment_intents'] and parts[3] == 'capture':
            pi = self.intents[parts[2]]
            amt = int(params['amount_to_capture'])
            assert pi['status'] == 'requires_capture' and amt <= pi['amount_capturable']
            pi.update(status='succeeded', amount_received=amt, amount_capturable=0, latest_charge='ch_' + parts[2])
            return pi
        if parts[:2] == ['v1', 'payment_intents'] and parts[3] == 'cancel':
            self.intents[parts[2]].update(status='canceled', amount_capturable=0)
            return self.intents[parts[2]]
        if path == '/v1/refunds':
            return {'id': 're_1', 'amount': int(params['amount'])}
        raise AssertionError(path)

    def browser_confirms(self, pid, ok=True):  # what Stripe.js + the card form do in the visitor's browser
        pi = self.intents[pid]
        if ok:
            pi.update(status='requires_capture', amount_capturable=pi['amount'])
        else:
            pi.update(status='requires_payment_method')


@pytest.fixture
def stripe_app(make, monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(core, '_stripe_http', fake)
    monkeypatch.setenv('STRIPE_SECRET_KEY', 'sk_test_123')
    monkeypatch.setenv('STRIPE_PUBLISHABLE_KEY', 'pk_test_123')
    return make(), fake


def test_stripe_live_keys_refused():
    with pytest.raises(ValueError):
        core.StripeGateway('sk_live_abc', 'pk_live_abc')
    with pytest.raises(ValueError):
        core.StripeGateway('sk_test_abc', 'pk_live_abc')


def test_stripe_authorize_capture_flow(stripe_app):
    a, fake = stripe_app
    c = a.test_client()
    s = c.get('/api/status').json
    assert s['processor'] == 'stripe_test' and s['stripe_publishable_key'] == 'pk_test_123'
    rid = str(uuid.uuid4())
    r = c.post('/api/payment-intent', json={'email': 't@example.com', 'request_id': rid})
    assert r.status_code == 200 and r.json['amount'] == 36000
    pid = r.json['payment_intent']
    create = fake.calls[-1]
    assert create[2]['capture_method'] == 'manual' and create[2]['amount'] == 36000
    # no number without a confirmed card hold
    assert spin(c, rid=rid, payment_intent=pid).status_code == 402
    assert spin(c, rid=str(uuid.uuid4())).status_code == 402
    fake.browser_confirms(pid)
    # a hold can't be used for a different entry
    assert spin(c, rid=str(uuid.uuid4()), payment_intent=pid).status_code == 402
    d = spin(c, rid=rid, payment_intent=pid).json
    assert d['payment_status'] == 'paid' and d['processor'] == 'stripe_test' and d['simulated'] is False
    cap = [x for x in fake.calls if x[1].endswith('/capture')]
    assert len(cap) == 1 and cap[0][2]['amount_to_capture'] == d['number'] * 100
    assert fake.intents[pid]['amount_received'] == d['number'] * 100
    # retry is idempotent: no second capture
    assert spin(c, rid=rid, payment_intent=pid).json['number'] == d['number']
    assert len([x for x in fake.calls if x[1].endswith('/capture')]) == 1
    assert c.post('/api/payment-intent', json={'email': 't@example.com', 'request_id': rid}).status_code == 409


def test_stripe_refund_and_sold_out_void(stripe_app):
    a, fake = stripe_app
    c = a.test_client()
    adm = a.test_client()
    adm.post('/api/admin/login', json={'username': 'admin', 'password': 'local-demo-only'})
    adm.post('/api/admin/settings', json={'max_tickets': 1}, headers=ADMIN)

    def enter():
        rid = str(uuid.uuid4())
        pid = c.post('/api/payment-intent', json={'email': 't@example.com', 'request_id': rid}).json['payment_intent']
        fake.browser_confirms(pid)
        return rid, pid
    rid, pid = enter()
    d = spin(c, rid=rid, payment_intent=pid).json
    assert d['number'] == 1
    eid = adm.get('/api/admin', headers=ADMIN).json['entries'][0]['id']
    assert adm.post(f'/api/admin/entries/{eid}/refund', headers=ADMIN).status_code == 200
    assert fake.calls[-1][1] == '/v1/refunds' and fake.calls[-1][2] == {'charge': 'ch_' + pid, 'amount': 100}
    # sold out: no new payment intents can be started
    rid2 = str(uuid.uuid4())
    r = c.post('/api/payment-intent', json={'email': 't@example.com', 'request_id': rid2})
    assert r.status_code == 409


# ───────────── compliance: consent, free entries, legal pages ─────────────

def free_body(**kw):
    b = dict(first='Mail', last='Entrant', street='1 Main St', city='Lawrence', state='NY', zip='11559', country='United States',
             phone='516-555-0100', email='mail@example.com', received_at='2026-12-01', certified=True, signed=True,
             request_id=str(uuid.uuid4()))
    b.update(kw)
    return b


def test_spin_requires_rules_consent_and_records_it(client, admin):
    assert spin(client, consent_rules=False).status_code == 400
    r = spin(client, marketing=True)
    assert r.status_code == 200
    e = admin.get('/api/admin').json['entries'][0]
    assert e['method'] == 'donation' and e['rules_version'] == '2026-1' and e['campaign_number'] == 'YM-2026-01' and e['marketing_opt_in'] == 1
    assert e['consent_at'] and 'not exceeding $360' in e['consent_text']


def test_free_entry_joins_same_pool_and_drawing(client, admin):
    r = admin.post('/api/admin/free-entries', json=free_body(), headers=ADMIN)
    assert r.status_code == 200, r.json
    n = r.json['number']
    assert 1 <= n <= 360 and client.get('/api/status').json['remaining'] == 359
    e = next(x for x in admin.get('/api/admin').json['entries'] if x['number'] == n)
    assert e['status'] == 'free' and e['amount_cents'] == 0 and e['state'] == 'NY'
    # same request id is idempotent; identical envelope needs confirmation
    again = free_body(request_id=str(uuid.uuid4()))
    assert admin.post('/api/admin/free-entries', json=again, headers=ADMIN).status_code == 409
    assert admin.post('/api/admin/free-entries', json=dict(again, allow_duplicate=True), headers=ADMIN).status_code == 200
    # unsigned forms are rejected
    assert admin.post('/api/admin/free-entries', json=free_body(signed=False), headers=ADMIN).status_code == 400
    # free entries are eligible in the drawing
    admin.put('/api/admin/campaign', json={'sales_paused': True}, headers=ADMIN)
    admin.post('/api/admin/drawing/commit', json={}, headers=ADMIN)
    d = admin.post('/api/admin/drawing/draw', json={'public_entropy': 'x'}, headers=ADMIN).json
    assert d['eligible_count'] == 2


def test_free_entry_needs_admin_and_respects_deadline_and_limit(client, admin):
    assert client.post('/api/admin/free-entries', json=free_body(), headers=ADMIN).status_code == 401
    admin.put('/api/admin/campaign', json={'end_at': '2026-12-10T20:00', 'entries_per_person': 1}, headers=ADMIN)
    assert admin.post('/api/admin/free-entries', json=free_body(received_at='2026-12-11'), headers=ADMIN).status_code == 409
    assert admin.post('/api/admin/free-entries', json=free_body(), headers=ADMIN).status_code == 200
    assert admin.post('/api/admin/free-entries', json=free_body(street='2 Other St'), headers=ADMIN).status_code == 409  # limit
    assert spin(client, email='mail@example.com').status_code == 409  # same person, other method


def test_disqualify_free_entry(admin):
    eid = admin.post('/api/admin/free-entries', json=free_body(), headers=ADMIN).json['entry_id']
    r = admin.post(f'/api/admin/entries/{eid}/disqualify', json={'reason': 'not eligible'}, headers=ADMIN)
    assert r.status_code == 200
    e = next(x for x in admin.get('/api/admin').json['entries'] if x['id'] == eid)
    assert e['status'] == 'disqualified'


def test_legal_pages_use_placeholders_not_invented_facts(client, admin):
    for path in ('/rules', '/free-entry', '/privacy', '/terms', '/contact', '/winners'):
        assert client.get(path).status_code == 200
    d = client.get('/api/legal').json
    assert set(d['docs']) == {'rules', 'free-entry', 'privacy', 'terms', 'contact', 'winners'}
    assert d['draft'] is True and d['npn'].startswith('NO PURCHASE OR DONATION NECESSARY')
    text = json.dumps(d['docs']['rules'])
    assert '82-3156516' in text and 'State of New York' in text and 'Florida' not in text and 'Nassau' in text
    assert 'Anonymous' in text and 'Conducted live on Zoom' in text
    admin.put('/api/admin/campaign', json={'org_ein': ''}, headers=ADMIN)
    assert '[[Federal EIN]]' in json.dumps(client.get('/api/legal').json['docs']['rules'])  # blanks never become invented facts
    assert len(d['docs']['rules']['sections']) == 16
    admin.put('/api/admin/campaign', json={'org_ein': '12-3456789', 'official_rules': '# Custom\nCounsel text.', 'legal_approval_status': 'approved'}, headers=ADMIN)
    d = client.get('/api/legal').json
    assert d['draft'] is False and d['docs']['rules']['sections'] == [{'h': 'Custom', 'p': ['Counsel text.']}]
    assert '12-3456789' in json.dumps(d['docs']['contact'])
    assert admin.put('/api/admin/campaign', json={'legal_approval_status': 'yes'}, headers=ADMIN).status_code == 400


def test_free_entry_pdf(client, admin):
    r = client.get('/free-entry-form.pdf')
    assert r.status_code == 200 and r.data[:4] == b'%PDF'
    admin.put('/api/admin/campaign', json={'free_entry_enabled': False}, headers=ADMIN)
    assert client.get('/free-entry-form.pdf').status_code == 404
    assert client.get('/api/legal').json['npn'] == ''


def test_migrates_v3_entries_to_v4(make, tmp_path):
    db = tmp_path / 'v3.sqlite'
    c = sqlite3.connect(db)
    c.execute(core.ENTRIES_V3.split('method TEXT')[0].rstrip().rstrip(',')
              .replace("CHECK(amount_cents >= 0)", "CHECK(amount_cents > 0)") + ')')
    c.execute("INSERT INTO entries(number,name,email,request_id,amount_cents,status) VALUES(42,'Old','o@example.com','oldrequest-000000042',4200,'paid')")
    c.commit()
    c.close()
    cl = make(db).test_client()
    assert cl.get('/api/status').json['remaining'] == 359
    row = sqlite3.connect(db).execute('SELECT method, marketing_opt_in FROM entries WHERE number=42').fetchone()
    assert row == ('donation', 0)


def test_checklist(admin, client):
    d = admin.get('/api/admin/checklist').json
    ids = {i['id']: i for i in d['items']}
    assert ids['org']['done'] and ids['campaign']['done'] and not ids['dates']['done'] and not ids['legal']['done']
    assert d['live_payments'] is False
    assert admin.post('/api/admin/checklist/m_render', json={'done': True, 'note': 'deployed'}, headers=ADMIN).status_code == 200
    assert next(i for i in admin.get('/api/admin/checklist').json['items'] if i['id'] == 'm_render')['done'] is True
    assert admin.post('/api/admin/checklist/org', json={'done': True}, headers=ADMIN).status_code == 404  # automatic items
    assert client.get('/api/admin/checklist').status_code == 401


def test_new_campaign_archives_and_resets(admin, client, tmp_path):
    n = spin(client).json['number']
    bad = admin.post('/api/admin/new-campaign', json={'confirm': 'START NEW CAMPAIGN', 'campaign_number': 'YM-2027-01'}, headers=ADMIN)
    assert bad.status_code == 409 and bad.json['needs_override']
    r = admin.post('/api/admin/new-campaign', json={'confirm': 'START NEW CAMPAIGN', 'campaign_number': 'YM-2027-01',
                                                   'without_drawing': True}, headers=ADMIN)
    assert r.status_code == 200, r.json
    archived = tmp_path / 'archive' / r.json['archived']
    assert sqlite3.connect(archived).execute('SELECT number FROM entries').fetchone()[0] == n
    s = client.get('/api/status').json
    assert s['remaining'] == 360 and s['sales_open'] is False
    camp = client.get('/api/campaign').json['campaign']
    assert camp['campaign_number'] == 'YM-2027-01' and camp['org_ein'] == '82-3156516'


def test_production_requires_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv('RAFFLE_ENV', 'production')
    monkeypatch.delenv('RAFFLE_ADMIN_PASSWORD', raising=False)
    with pytest.raises(SystemExit):
        appmod.create_app(str(tmp_path / 'p.sqlite'))
    monkeypatch.setenv('RAFFLE_ADMIN_PASSWORD', 'a-long-private-password')
    monkeypatch.setenv('RAFFLE_SECRET_KEY', 'x' * 32)
    assert appmod.create_app(str(tmp_path / 'p.sqlite'))


def test_noindex_header_until_launch(client, monkeypatch):
    assert client.get('/').headers['X-Robots-Tag'] == 'noindex, nofollow'
    monkeypatch.setenv('RAFFLE_ALLOW_INDEXING', '1')
    assert 'X-Robots-Tag' not in client.get('/').headers
    assert client.get('/api/status').headers['X-Robots-Tag'] == 'noindex, nofollow'


def test_smtp_needs_password(monkeypatch):
    monkeypatch.setenv('SMTP_HOST', 'smtp.gmail.com')
    monkeypatch.setenv('SMTP_USER', 'yismachmosheow@gmail.com')
    monkeypatch.delenv('SMTP_PASSWORD', raising=False)
    assert core.smtp_configured() is False
    monkeypatch.setenv('SMTP_PASSWORD', 'app-password')
    assert core.smtp_configured() is True


def test_placeholder_secrets_mean_not_configured(monkeypatch):
    assert core.make_gateway({'STRIPE_SECRET_KEY': 'none', 'STRIPE_PUBLISHABLE_KEY': 'none'}).name == 'simulated'
    monkeypatch.setenv('SMTP_HOST', 'smtp.gmail.com')
    monkeypatch.setenv('SMTP_USER', 'x@example.com')
    monkeypatch.setenv('SMTP_PASSWORD', 'none')
    assert core.smtp_configured() is False


def test_music_settings_and_audio_upload(admin, client):
    import io
    c = client.get('/api/campaign').json['campaign']
    assert c['music_source'] == 'youtube' and c['music_youtube'] == 'tfPHaVhsaVU'
    r = admin.put('/api/admin/campaign', json={'music_youtube': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3'}, headers=ADMIN)
    assert r.status_code == 200 and r.json['campaign']['music_youtube'] == 'dQw4w9WgXcQ'
    assert admin.put('/api/admin/campaign', json={'music_youtube': 'not a video'}, headers=ADMIN).status_code == 400
    up = admin.post('/api/admin/upload', data={'file': (io.BytesIO(b'ID3\x04' + b'\0' * 64), 'song.mp3')}, headers=ADMIN)
    assert up.status_code == 200 and up.json['url'].endswith('.mp3')
    assert client.get(up.json['url']).status_code == 200
    r = admin.put('/api/admin/campaign', json={'music_source': 'upload', 'music_url': up.json['url']}, headers=ADMIN)
    assert r.status_code == 200 and r.json['campaign']['music_url'] == up.json['url']
    assert admin.put('/api/admin/campaign', json={'music_url': '/uploads/abc.exe'}, headers=ADMIN).status_code == 400


def test_share_links_count_other_peoples_paid_entries(client, admin):
    r = client.post('/api/ambassadors', json={'name': 'Sarah Cohen', 'email': 'sarah@example.com'})
    assert r.status_code == 200, r.json
    code = r.json['code']
    assert r.json['first_name'] == 'Sarah' and r.json['reward'] == '' and r.json['earned'] is False  # tracking only by default
    admin.put('/api/admin/campaign', json={'referral_reward': 'A Tomahawk steak'}, headers=ADMIN)
    assert 'Tomahawk' in client.get(f'/api/ambassadors/{code}').json['reward']
    assert r.json['link'].endswith('/?ref=' + code)
    # same email returns the same link
    assert client.post('/api/ambassadors', json={'name': 'Sarah', 'email': 'SARAH@example.com'}).json['code'] == code
    admin.put('/api/admin/campaign', json={'referral_threshold': 2}, headers=ADMIN)
    s1 = spin(client, email='a@example.com', ref=code).json
    assert s1['my_link']['code'] != code and s1['my_link']['sold'] == 0  # every entrant gets their own link
    spin(client, email='sarah@example.com', ref=code)           # own link: doesn't count
    spin(client, email='b+decline@example.com', ref=code)       # declined: doesn't count
    assert client.get(f'/api/ambassadors/{code}').json['sold'] == 1
    spin(client, email='c@example.com', ref=code.upper())
    g = client.get(f'/api/ambassadors/{code}').json
    assert g['sold'] == 2 and g['earned'] is True
    rows = admin.get('/api/admin/ambassadors').json['ambassadors']
    top = rows[0]
    assert top['code'] == code and top['sold'] == 2 and top['reward_status'] == 'earned'
    assert admin.post(f"/api/admin/ambassadors/{top['id']}/reward", json={'status': 'fulfilled'}, headers=ADMIN).status_code == 200
    assert client.get('/api/ambassadors/nope-0000').status_code == 404
    assert client.post('/api/ambassadors', json={'name': '', 'email': 'x'}).status_code == 400
    # unknown ref is ignored, entry still works
    assert spin(client, email='d@example.com', ref='does-not-exist').status_code == 200


def test_staff_alert_for_every_entry(client, admin):
    import time as _t
    assert admin.put('/api/admin/campaign', json={'notify_emails': 'not-an-email'}, headers=ADMIN).status_code == 400
    assert admin.put('/api/admin/campaign', json={'notify_emails': 'team@example.com; boss@example.com'}, headers=ADMIN).json['campaign']['notify_emails'] == 'team@example.com, boss@example.com'
    n = spin(client, email='donor@example.com').json['number']
    admin.post('/api/admin/free-entries', json=free_body(), headers=ADMIN)
    for _ in range(200):
        mails = admin.get('/api/admin/emails').json['emails']
        alerts = [m for m in mails if m['to_addr'] in ('team@example.com', 'boss@example.com')]
        if len(alerts) >= 4:
            break
        _t.sleep(0.05)
    assert len(alerts) == 4 and any(f'New entry #{n}:' in m['subject'] for m in alerts)
    assert 'notify_emails' not in client.get('/api/campaign').json['campaign']  # never public


def test_prize_v3_updates_only_untouched_wording():
    import json, sqlite3
    import raffle_core as core
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)')
    c.execute('CREATE TABLE activity(id INTEGER PRIMARY KEY, actor TEXT, action TEXT, detail TEXT)')
    old = {k: v[0] for k, v in core.PRIZE_V3.items()}
    old['share_text'] = 'Hand-written share text'
    c.execute("INSERT INTO settings VALUES('campaign', ?)", (json.dumps(old),))
    core.apply_prize_v3(c)
    core.apply_prize_v3(c)  # runs once only
    data = json.loads(c.execute("SELECT value FROM settings WHERE key='campaign'").fetchone()[0])
    assert data['intro'] == core.PRIZE_V3['intro'][1]
    assert data['prize_items'] == core.PRIZE_V3['prize_items'][1]
    assert data['share_text'] == 'Hand-written share text'


def test_going_live_keeps_entries_closed_until_test_entries_cleared(make, tmp_path, monkeypatch):
    db = tmp_path / 'golive.sqlite'
    test_client = make(db).test_client()
    assert spin(test_client).json['payment_status'] == 'paid'  # a test-mode entry
    fake = FakeStripe()
    monkeypatch.setattr(core, '_stripe_http', fake)
    monkeypatch.setattr(core, 'PAYMENT_MODE', core.PAYMENT_MODE)  # restored after the test
    monkeypatch.setenv('STRIPE_SECRET_KEY', 'rk_live_123')
    monkeypatch.setenv('STRIPE_PUBLISHABLE_KEY', 'pk_live_123')
    monkeypatch.setenv('RAFFLE_LIVE_PAYMENTS', '1')
    a = make(db)
    c, adm = a.test_client(), a.test_client()
    s = c.get('/api/status').json
    assert s['processor'] == 'stripe_live' and s['payment_mode'] == 'live'
    assert s['sales_open'] is False and s['sales_message'] == 'Entries open soon.' and s['test_entries'] == 1
    adm.post('/api/admin/login', json={'username': 'admin', 'password': 'local-demo-only'})
    assert adm.post('/api/admin/clear-test-entries', json={'confirm': 'nope'}, headers=ADMIN).status_code == 400
    r = adm.post('/api/admin/clear-test-entries', json={'confirm': 'CLEAR TEST ENTRIES'}, headers=ADMIN)
    assert r.status_code == 200 and r.json['cleared'] == 1 and (tmp_path / 'archive' / r.json['archive']).exists()
    s = c.get('/api/status').json
    assert s['sales_open'] is True and s['remaining'] == 360
    rid = str(uuid.uuid4())
    pid = c.post('/api/payment-intent', json={'email': 't@example.com', 'request_id': rid}).json['payment_intent']
    fake.browser_confirms(pid)
    d = spin(c, rid=rid, payment_intent=pid).json
    assert d['payment_status'] == 'paid' and d['processor'] == 'stripe_live' and d['payment_mode'] == 'live'
    with sqlite3.connect(db) as raw:
        assert raw.execute('SELECT payment_mode FROM entries').fetchall() == [('live',)]
    # real donations can never be wiped by this button
    assert adm.post('/api/admin/clear-test-entries', json={'confirm': 'CLEAR TEST ENTRIES'}, headers=ADMIN).status_code == 409


def test_confirmation_email_has_share_link(client, admin, monkeypatch):
    monkeypatch.setattr(core, 'SITE_URL', 'https://spin.example.org')
    assert spin(client, email='sharer@example.com').status_code == 200
    em = admin.get('/api/admin/emails').json
    em = em.get('emails', em)
    eid = [e for e in em if e['to_addr'] == 'sharer@example.com'][0]['id']
    body = admin.get(f'/api/admin/emails/{eid}').json
    body = body.get('email', body)
    assert 'https://spin.example.org/?ref=test-person-' in body['body_text']
    assert 'wa.me/?text=' in body['body_html'] and 'Share on WhatsApp' in body['body_html']
    amb = admin.get('/api/admin/ambassadors').json['ambassadors']
    assert any(a['email'] == 'sharer@example.com' for a in amb)


def test_share_emails_sent_once_to_earlier_entrants(client, admin, monkeypatch):
    monkeypatch.setattr(core, 'SITE_URL', '')  # entries made before the feature: confirmation had no link
    for e in ('a@example.com', 'b@example.com', 'a@example.com'):
        assert spin(client, email=e).status_code == 200
    monkeypatch.setattr(core, 'SITE_URL', 'https://spin.example.org')
    sent = []
    monkeypatch.setattr(core, 'smtp_configured', lambda: True)
    monkeypatch.setattr(core, 'smtp_send', lambda to, s, t, h=None: (sent.append((to, s, t)), ('sent', None, core.now_iso()))[1])
    monkeypatch.setattr(appmod.time, 'sleep', lambda s: None)
    assert admin.get('/api/admin/share-emails').json['pending'] == 2
    assert admin.post('/api/admin/share-emails', json={}, headers=ADMIN).status_code == 400
    assert admin.post('/api/admin/share-emails', json={'confirm': 'SEND'}, headers=ADMIN).json['total'] == 2
    for _ in range(200):
        if not admin.get('/api/admin/share-emails').json['running']:
            break
        threading.Event().wait(0.02)
    assert sorted(t for t, _, _ in sent) == ['a@example.com', 'b@example.com']
    a_text = [t for to, _, t in sent if to == 'a@example.com'][0]
    assert '?ref=' in a_text and 'your entry: #' in a_text and a_text.count('#') == 2  # both of a@'s numbers
    assert admin.get('/api/admin/share-emails').json['pending'] == 0
    # a new entry after the blast gets the link in its confirmation and is not queued again
    assert spin(client, email='c@example.com').status_code == 200
    assert admin.get('/api/admin/share-emails').json['pending'] == 0


# ───────────── fixed-price option: $180 for one entry ─────────────

def test_stripe_chai_charges_exact_price(stripe_app):
    a, fake = stripe_app
    c = a.test_client()
    adm = a.test_client()
    adm.post('/api/admin/login', json={'username': 'admin', 'password': 'local-demo-only'})
    rid = str(uuid.uuid4())
    r = c.post('/api/payment-intent', json={'email': 'p@example.com', 'request_id': rid, 'package': 'chai'})
    assert r.status_code == 200 and r.json['amount'] == 18000
    pid = r.json['payment_intent']
    assert fake.intents[pid]['amount'] == 18000  # no $360 hold
    fake.browser_confirms(pid)
    d = spin(c, email='p@example.com', rid=rid, payment_intent=pid, package='chai').json
    assert d['payment_status'] == 'paid' and d['amount'] == 180 and d['amount_display'] == '$180' and len(d['numbers']) == 1
    assert fake.intents[pid]['amount_received'] == 18000
    e = adm.get('/api/admin', headers=ADMIN).json['entries'][0]
    assert e['amount_cents'] == 18000 and e['package_label'] == 'Chai ticket $180'
    mail = adm.get('/api/admin/emails').json['emails'][0]
    assert '$180 (Chai ticket $180)' in adm.get(f"/api/admin/emails/{mail['id']}").json['body_text']
    assert adm.post(f"/api/admin/entries/{e['id']}/refund", headers=ADMIN).json['ok']
    assert fake.calls[-1][2] == {'charge': 'ch_' + pid, 'amount': 18000} and fake.calls[-1][3] == f"refund-entry-{e['id']}"
    assert spin(c, email='p@example.com', rid=rid, payment_intent=pid, package='chai').json['number'] == d['number']  # idempotent


def test_chai_hold_cannot_buy_a_spin(stripe_app):
    """A $180 hold can't be used for a spin, which needs the full $360 hold."""
    a, fake = stripe_app
    c = a.test_client()
    rid = str(uuid.uuid4())
    pid = c.post('/api/payment-intent', json={'email': 's@example.com', 'request_id': rid, 'package': 'chai'}).json['payment_intent']
    fake.browser_confirms(pid)
    assert spin(c, email='s@example.com', rid=rid, payment_intent=pid).status_code == 402


def test_unknown_option_is_a_normal_spin(client):
    d = spin(client, package='pair').json
    assert d['payment_status'] == 'paid' and d['amount'] == d['number']


def test_rules_mention_fixed_price_option(client):
    rules = json.dumps(client.get('/api/legal').json['docs']['rules'])
    assert '$180 for one entry' in rules and 'two entries' not in rules and '$300 for' not in rules
