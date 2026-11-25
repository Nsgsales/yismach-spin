import csv, hmac, io, json, os, re, secrets, time
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory, session
from werkzeug.middleware.proxy_fix import ProxyFix

import legal
import raffle_core as core

BASE = Path(__file__).resolve().parent

# Payments stay in sandbox until regulatory and payment processor approval.
if os.environ.get('RAFFLE_PAYMENT_MODE', 'sandbox') != 'sandbox':
    raise SystemExit('Live payments are not enabled. Payments must remain in sandbox mode pending approval.')

UPLOAD_TYPES = {b'\x89PNG': '.png', b'\xff\xd8\xff': '.jpg', b'RIFF': '.webp', b'ID3': '.mp3', b'OggS': '.ogg'}
AUDIO_EXTS = ('.mp3', '.m4a', '.ogg')


def create_app(db_path=None):
    app = Flask(__name__, static_folder=None)
    if os.environ.get('RAFFLE_PROXY_FIX') == '1':  # behind Render's (or any) HTTPS proxy
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    db = Path(db_path or os.environ.get('RAFFLE_DB', str(BASE / 'raffle.sqlite')))
    uploads = Path(os.environ.get('RAFFLE_UPLOADS', str(BASE / 'uploads')))
    uploads.mkdir(parents=True, exist_ok=True)
    archive = Path(os.environ.get('RAFFLE_ARCHIVE', str(db.parent / 'archive')))
    admin_user = os.environ.get('RAFFLE_ADMIN_USER', 'admin')
    admin_password = os.environ.get('RAFFLE_ADMIN_PASSWORD', 'local-demo-only')
    api_token = os.environ.get('RAFFLE_ADMIN_TOKEN', 'local-demo-only')
    app.config.update(
        SECRET_KEY=os.environ.get('RAFFLE_SECRET_KEY') or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
        SESSION_COOKIE_SECURE=os.environ.get('RAFFLE_SECURE_COOKIES') == '1',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=20 * 1024 * 1024)
    production = os.environ.get('RAFFLE_ENV') == 'production'
    if production and (admin_password == 'local-demo-only' or len(admin_password) < 12 or not os.environ.get('RAFFLE_SECRET_KEY')):
        raise SystemExit('Production needs RAFFLE_ADMIN_PASSWORD (12+ characters) and RAFFLE_SECRET_KEY.')
    if admin_password == 'local-demo-only':
        print(' * WARNING: default admin credentials (admin / local-demo-only). Set RAFFLE_ADMIN_PASSWORD before sharing.')
    core.init_db(db)
    try:
        gateway = core.make_gateway(os.environ)
    except ValueError as e:
        raise SystemExit(str(e))
    print(f' * Payments: {gateway.name}' + (' (Stripe TEST mode, no real charges)' if gateway.name == 'stripe_test' else ' (simulated)'))
    login_attempts = defaultdict(deque)

    def connect():
        return core.connect(db)

    # ─────────────── pages & assets ───────────────
    @app.after_request
    def headers(resp):
        resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
        resp.headers.setdefault('Referrer-Policy', 'same-origin')
        if os.environ.get('RAFFLE_ALLOW_INDEXING') != '1' or request.path.startswith(('/api', '/admin')):
            resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
        if app.config['SESSION_COOKIE_SECURE']:
            resp.headers.setdefault('Strict-Transport-Security', 'max-age=31536000')
        if request.path.startswith('/api/admin') or request.path == '/admin':
            resp.headers['Cache-Control'] = 'no-store'
            resp.headers['X-Frame-Options'] = 'DENY'
        return resp

    @app.get('/')
    def home():
        return send_from_directory(BASE, 'index.html')

    @app.get('/<any(rules, "free-entry", privacy, terms, contact, winners):doc>')
    def legal_page(doc):
        return send_from_directory(BASE, 'legal.html')

    @app.get('/free-entry-form.pdf')
    def free_entry_form():
        with connect() as c:
            camp, info = core.get_campaign(c), core.summary(c)
        if not camp.get('free_entry_enabled'):
            return 'Free entry is not enabled.', 404
        return Response(legal.free_entry_pdf(camp, info), mimetype='application/pdf',
                        headers={'Content-Disposition': 'inline; filename=free-entry-form.pdf'})

    @app.get('/admin')
    def admin_page():
        return send_from_directory(BASE, 'admin.html')

    @app.get('/assets/<path:name>')
    def assets(name):
        if name in ('logo.png', 'flyer.png'):
            return send_from_directory(BASE, name)
        if not re.fullmatch(r'[a-z0-9-]+(/[a-z0-9-]+)?\.(css|js|png|jpg|jpeg|webp|svg|json)', name):
            return '', 404
        return send_from_directory(BASE / 'assets', name)

    @app.get('/uploads/<name>')
    def uploaded(name):
        if not re.fullmatch(r'[a-f0-9]{24}\.(png|jpg|webp|mp3|m4a|ogg)', name):
            return '', 404
        return send_from_directory(uploads, name)

    # ─────────────── public API ───────────────
    def public_status(c):
        s = core.summary(c)
        s['processor'] = gateway.name
        s['stripe_publishable_key'] = gateway.publishable_key
        return s

    @app.get('/api/status')
    def status():
        with connect() as c:
            return jsonify(public_status(c))

    @app.post('/api/payment-intent')
    def payment_intent():
        if gateway.name != 'stripe_test':
            return jsonify(error='Card payments are not enabled.'), 404
        d = request.get_json(silent=True) or {}
        email, rid = str(d.get('email', '')).strip(), str(d.get('request_id', ''))
        if not (core.EMAIL_RE.fullmatch(email) and core.RID_RE.fullmatch(rid)):
            return jsonify(error='Please check your details.'), 400
        with connect() as c:
            info = core.summary(c)
            camp = core.get_campaign(c)
            if c.execute('SELECT 1 FROM entries WHERE request_id=?', (rid,)).fetchone():
                return jsonify(error='This entry was already completed.'), 409
            if core.limit_reached(c, camp, email):
                return jsonify(error='You have reached the entry limit for this campaign.'), 409
        if not info['sales_open']:
            return jsonify(error=info['sales_message']), 409
        max_auth = info['unit_price_cents'] * info['max_tickets']
        try:
            pi_id, secret = gateway.create_intent(max_auth, rid, email, f"{camp['title']} entry (hold up to {core.money(max_auth)})")
        except core.StripeError as e:
            return jsonify(error=f'Payment setup failed: {e}'), 502
        return jsonify(payment_intent=pi_id, client_secret=secret, publishable_key=gateway.publishable_key, amount=max_auth)

    @app.get('/api/campaign')
    def campaign_public():
        with connect() as c:
            camp = core.get_campaign(c)
            data = {k: camp[k] for k in core.PUBLIC_CAMPAIGN_KEYS}
            d = c.execute('SELECT commitment, committed_at, drawn_at FROM drawings ORDER BY id DESC LIMIT 1').fetchone()
            data['drawing'] = dict(d) if d else None
            info = core.summary(c)
            data['auth_text'] = core.auth_text(camp, info)
            data['marketing_text'] = camp['marketing_consent_text'].replace('{org}', core.org_display(camp))
            data['legal_draft'] = camp.get('legal_approval_status') != 'approved'
            return jsonify(campaign=data, status=public_status(c))

    def latest_drawing(c):
        d = c.execute('SELECT drawn_at, winners FROM drawings ORDER BY id DESC LIMIT 1').fetchone()
        return {'drawn_at': d['drawn_at'], 'winners': json.loads(d['winners'])} if d and d['drawn_at'] else None

    @app.get('/api/legal')
    def legal_public():
        with connect() as c:
            camp, info = core.get_campaign(c), core.summary(c)
            out = legal.build(camp, info, latest_drawing(c), request.host_url.rstrip('/'))
        out['auth_text'] = core.auth_text(camp, info)
        return jsonify(out)

    @app.get('/api/drawing')
    def drawing_public():
        """Everything needed to independently verify a completed drawing."""
        with connect() as c:
            d = c.execute('SELECT * FROM drawings ORDER BY id DESC LIMIT 1').fetchone()
        if not d:
            return jsonify(drawing=None)
        out = dict(commitment=d['commitment'], committed_at=d['committed_at'], algorithm=d['algorithm'])
        if d['drawn_at']:
            out.update(seed=d['seed'], public_entropy=d['public_entropy'], drawn_at=d['drawn_at'],
                       eligible=json.loads(d['eligible']), eligible_hash=d['eligible_hash'], winners=json.loads(d['winners']))
        return jsonify(drawing=out)

    @app.post('/api/spin')
    def spin():
        d = request.get_json(silent=True) or {}
        name = str(d.get('name', '')).strip()
        email = str(d.get('email', '')).strip()
        phone = core.clean_phone(d.get('phone'))
        rid = str(d.get('request_id', ''))
        if not (1 <= len(name) <= 120 and len(email) <= 254 and core.EMAIL_RE.fullmatch(email)):
            return jsonify(error='Please enter your name and a valid email address.'), 400
        if phone is None:
            return jsonify(error='Please enter a valid phone number.'), 400
        if not core.RID_RE.fullmatch(rid) or d.get('consent') is not True:
            return jsonify(error='Please confirm the payment authorization.'), 400
        if d.get('consent_rules') is not True:
            return jsonify(error='Please confirm your eligibility and agree to the Official Rules.'), 400
        marketing = 1 if d.get('marketing') is True else 0

        def result(entry, camp):
            return jsonify(number=entry['number'], amount=entry['amount_cents'] / 100,
                           amount_display=core.money(entry['amount_cents']),
                           confirmation=core.confirmation_code(entry['number']), authorization_id=entry['authorization_id'],
                           payment_status=entry['status'], payment_mode=core.PAYMENT_MODE, simulated=gateway.name != 'stripe_test', processor=gateway.name,
                           email_status=entry_email_status(entry['id']), title=camp['title'])

        def entry_email_status(entry_id):
            with connect() as c2:
                r = c2.execute('SELECT status FROM emails WHERE entry_id=? ORDER BY id DESC LIMIT 1', (entry_id,)).fetchone()
            return r['status'] if r else None

        c = connect()
        try:
            prior = c.execute('SELECT * FROM entries WHERE request_id=?', (rid,)).fetchone()
            camp = core.get_campaign(c)
            if prior:  # idempotent retry: never charge twice
                if prior['name'] != name or prior['email'] != email:
                    return jsonify(error='Request conflict.'), 409
                return result(prior, camp)
            info = core.summary(c)
            if info['sales_open'] and core.limit_reached(c, camp, email):
                info = dict(info, sales_open=False, sales_message='You have reached the entry limit for this campaign.')
            if not info['sales_open']:
                held, hold_id, _ = gateway.authorize(0, email, payment_intent_id=d.get('payment_intent'), request_id=rid) \
                    if d.get('payment_intent') and gateway.name == 'stripe_test' else (False, None, '')
                if held:  # release the card hold: no number can be assigned
                    ok_v, ref, vmsg = gateway.void(hold_id)
                    core.record_txn(c, 'void', 0, ok_v, ref, vmsg + ' (sales closed)', request_id=rid)
                    c.commit()
                return jsonify(error=info['sales_message']), 409
            m, unit = info['max_tickets'], info['unit_price_cents']
            max_auth = unit * m

            # 1. Authorize the maximum possible amount before a number is assigned.
            ok, auth_id, msg = gateway.authorize(max_auth, email, payment_intent_id=d.get('payment_intent'), request_id=rid)
            core.record_txn(c, 'authorize', max_auth, ok, auth_id, msg, request_id=rid)
            core.log(c, 'public', 'authorization_' + ('approved' if ok else 'declined'), email=email, amount_cents=max_auth)
            c.commit()
            if not ok:
                return jsonify(error='Your payment authorization was declined. No number was assigned.'), 402

            # 2. Assign a random available number inside a write lock.
            c.execute('BEGIN IMMEDIATE')
            prior = c.execute('SELECT * FROM entries WHERE request_id=?', (rid,)).fetchone()
            if prior:  # a concurrent duplicate submission won the race
                c.rollback()
                ok_v, ref, vmsg = gateway.void(auth_id)
                core.record_txn(c, 'void', max_auth, ok_v, ref, vmsg + ' (duplicate request)', request_id=rid)
                c.commit()
                return result(prior, camp)
            m = core.get_max_tickets(c)
            taken = core.active_numbers(c)
            available = [n for n in range(1, m + 1) if n not in taken]
            if not available:
                c.rollback()
                ok_v, ref, vmsg = gateway.void(auth_id)
                core.record_txn(c, 'void', max_auth, ok_v, ref, vmsg + ' (sold out)', request_id=rid)
                c.commit()
                return jsonify(error='All entries have been claimed. Your authorization was released.'), 409
            n = secrets.choice(available)
            amount = n * unit
            cur = c.execute('''INSERT INTO entries(number,name,email,phone,request_id,amount_cents,status,authorization_id,
                                 method,consent_at,consent_text,rules_version,campaign_number,marketing_opt_in)
                               VALUES(?,?,?,?,?,?,'pending_capture',?,'donation',?,?,?,?,?)''',
                            (n, name, email, phone, rid, amount, auth_id, core.now_iso(),
                             core.auth_text(camp, info) + ' | Eligibility and Official Rules accepted.',
                             camp.get('rules_version'), camp.get('campaign_number'), marketing))
            entry_id = cur.lastrowid
            core.log(c, 'public', 'number_assigned', entry_id=entry_id, number=n, amount_cents=amount,
                     rules_version=camp.get('rules_version'), marketing_opt_in=marketing)
            c.commit()

            # 3. Capture exactly the assigned amount.
            ok_c, cap_id, cmsg = gateway.capture(auth_id, amount, email)
            core.record_txn(c, 'capture', amount, ok_c, cap_id, cmsg, entry_id=entry_id, request_id=rid)
            c.execute("UPDATE entries SET status=?, capture_id=?, updated=CURRENT_TIMESTAMP WHERE id=?",
                      ('paid' if ok_c else 'capture_failed', cap_id, entry_id))
            core.log(c, 'public', 'capture_' + ('succeeded' if ok_c else 'failed'), entry_id=entry_id, amount_cents=amount)
            c.commit()
            entry = c.execute('SELECT * FROM entries WHERE id=?', (entry_id,)).fetchone()

            # 4. Confirmation email (logged to the outbox unless SMTP is configured).
            if ok_c:
                core.deliver_email(c, entry, camp)
                c.commit()
            return result(entry, camp)
        finally:
            c.close()

    # ─────────────── admin auth ───────────────
    def authorized():
        if session.get('admin') == admin_user:
            return True
        return hmac.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + api_token)

    def actor():
        return 'admin:' + (session.get('admin') or 'api-token')

    @app.before_request
    def admin_guard():
        p = request.path
        if not p.startswith('/api/admin') or p in ('/api/admin/login',):
            return None
        if not authorized():
            return jsonify(error='Please sign in.'), 401
        if request.method != 'GET' and session.get('admin'):
            # CSRF: session-authenticated writes must come from our own scripts (custom header + same origin).
            origin = request.headers.get('Origin')
            if request.headers.get('X-Requested-With') != 'raffle-admin' or (origin and origin.rstrip('/') != request.host_url.rstrip('/')):
                return jsonify(error='Request blocked.'), 403
        return None

    @app.post('/api/admin/login')
    def login():
        ip = request.remote_addr or '?'
        q = login_attempts[ip]
        now = time.time()
        while q and now - q[0] > 300:
            q.popleft()
        if len(q) >= 8:
            return jsonify(error='Too many attempts. Try again in a few minutes.'), 429
        d = request.get_json(silent=True) or {}
        u, p = str(d.get('username', '')), str(d.get('password', ''))
        if hmac.compare_digest(u, admin_user) & hmac.compare_digest(p, admin_password):
            session.clear()
            session.permanent = True
            session['admin'] = admin_user
            q.clear()
            with connect() as c:
                core.log(c, 'admin:' + admin_user, 'login', ip=ip)
            return jsonify(ok=True, user=admin_user)
        q.append(now)
        with connect() as c:
            core.log(c, 'public', 'login_failed', ip=ip, username=u[:60])
        return jsonify(error='Invalid username or password.'), 401

    @app.post('/api/admin/logout')
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get('/api/admin/me')
    def me():
        return jsonify(user=session.get('admin') or 'api-token')

    # ─────────────── admin data ───────────────
    @app.get('/api/admin')
    def admin():
        with connect() as c:
            rows = [dict(r) for r in c.execute('''SELECT id,number,name,email,phone,amount_cents,status,authorization_id,capture_id,
                     refund_id,created,updated,method,street,city,state,zip,country,consent_at,consent_text,rules_version,
                     campaign_number,marketing_opt_in,received_at,notes FROM entries ORDER BY id DESC''')]
            for r in rows:
                r['amount'] = r['amount_cents'] / 100
                last = c.execute('SELECT status FROM emails WHERE entry_id=? ORDER BY id DESC LIMIT 1', (r['id'],)).fetchone()
                r['email_status'] = last['status'] if last else None
            paid = sum(r['amount_cents'] for r in rows if r['status'] == 'paid')
            refunded = sum(r['amount_cents'] for r in rows if r['status'] == 'refunded')
            highest = c.execute("SELECT MAX(number) FROM entries WHERE status != 'released'").fetchone()[0] or 0
            counts = {s: sum(1 for r in rows if r['status'] == s) for s in ('paid', 'pending_capture', 'capture_failed', 'refunded', 'released', 'free', 'disqualified')}
            info = core.summary(c)
        return jsonify(entries=rows, total=paid / 100, refunded_total=refunded / 100, highest_issued=highest, counts=counts, **info)

    @app.get('/api/admin/transactions')
    def transactions():
        with connect() as c:
            rows = [dict(r) for r in c.execute('''SELECT t.*, e.number, e.email FROM transactions t LEFT JOIN entries e ON e.id=t.entry_id
                                                  ORDER BY t.id DESC LIMIT 2000''')]
        return jsonify(transactions=rows)

    @app.get('/api/admin/emails')
    def emails():
        with connect() as c:
            rows = [dict(r) for r in c.execute('''SELECT m.id,m.entry_id,m.to_addr,m.subject,m.status,m.error,m.created,m.sent_at,e.number
                                                  FROM emails m LEFT JOIN entries e ON e.id=m.entry_id ORDER BY m.id DESC LIMIT 2000''')]
        return jsonify(emails=rows)

    @app.get('/api/admin/emails/<int:eid>')
    def email_preview(eid):
        with connect() as c:
            r = c.execute('SELECT * FROM emails WHERE id=?', (eid,)).fetchone()
        if not r:
            return jsonify(error='Not found.'), 404
        return jsonify(dict(r))

    @app.get('/api/admin/activity')
    def activity():
        with connect() as c:
            rows = [dict(r) for r in c.execute('SELECT * FROM activity ORDER BY id DESC LIMIT 1000')]
        return jsonify(activity=rows)

    def load_entry(c, entry_id):
        return c.execute('SELECT * FROM entries WHERE id=?', (entry_id,)).fetchone()

    @app.post('/api/admin/entries/<int:entry_id>/resend-email')
    def resend(entry_id):
        with connect() as c:
            e = load_entry(c, entry_id)
            if not e or e['status'] not in core.ELIGIBLE_STATUSES:
                return jsonify(error='Only paid or free entries can receive a confirmation.'), 409
            status = core.deliver_email(c, e, core.get_campaign(c), actor())
        return jsonify(ok=True, email_status=status)

    @app.post('/api/admin/entries/<int:entry_id>/retry-capture')
    def retry_capture(entry_id):
        c = connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            e = load_entry(c, entry_id)
            if not e or e['status'] not in ('capture_failed', 'pending_capture'):
                c.rollback()
                return jsonify(error='This entry has no failed payment to retry.'), 409
            attempts = c.execute("SELECT COUNT(*) FROM transactions WHERE entry_id=? AND kind='capture'", (entry_id,)).fetchone()[0]
            ok, ref, msg = gateway.capture(e['authorization_id'], e['amount_cents'], e['email'], attempt=attempts + 1)
            core.record_txn(c, 'capture', e['amount_cents'], ok, ref, msg + ' (admin retry)', entry_id=entry_id)
            if ok:
                c.execute("UPDATE entries SET status='paid', capture_id=?, updated=CURRENT_TIMESTAMP WHERE id=?", (ref, entry_id))
            core.log(c, actor(), 'capture_retry_' + ('succeeded' if ok else 'failed'), entry_id=entry_id)
            c.commit()
            if ok:
                core.deliver_email(c, load_entry(c, entry_id), core.get_campaign(c), actor())
                c.commit()
            return jsonify(ok=ok, message=msg)
        finally:
            c.close()

    @app.post('/api/admin/entries/<int:entry_id>/release')
    def release(entry_id):
        """Void a failed authorization and return the number to the pool."""
        c = connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            e = load_entry(c, entry_id)
            if not e or e['status'] not in ('capture_failed', 'pending_capture'):
                c.rollback()
                return jsonify(error='Only entries with a failed payment can be released.'), 409
            ok, ref, msg = gateway.void(e['authorization_id'])
            core.record_txn(c, 'void', e['amount_cents'], ok, ref, msg, entry_id=entry_id)
            c.execute("UPDATE entries SET status='released', updated=CURRENT_TIMESTAMP WHERE id=?", (entry_id,))
            core.log(c, actor(), 'entry_released', entry_id=entry_id, number=e['number'])
            c.commit()
            return jsonify(ok=True)
        finally:
            c.close()

    @app.post('/api/admin/entries/<int:entry_id>/refund')
    def refund(entry_id):
        d = request.get_json(silent=True) or {}
        reason = str(d.get('reason', '')).strip()[:300]
        c = connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            e = load_entry(c, entry_id)
            if not e or e['status'] != 'paid':
                c.rollback()
                return jsonify(error='Only paid entries can be refunded.'), 409
            ok, ref, msg = gateway.refund(e['capture_id'], e['amount_cents'])
            core.record_txn(c, 'refund', e['amount_cents'], ok, ref, msg + (f' Reason: {reason}' if reason else ''), entry_id=entry_id)
            if ok:  # refunded tickets are void for the drawing; the number is not re-issued
                c.execute("UPDATE entries SET status='refunded', refund_id=?, updated=CURRENT_TIMESTAMP WHERE id=?", (ref, entry_id))
            core.log(c, actor(), 'refund_' + ('issued' if ok else 'failed'), entry_id=entry_id, number=e['number'], reason=reason)
            c.commit()
            return jsonify(ok=ok, message=msg)
        finally:
            c.close()

    @app.post('/api/admin/free-entries')
    def free_entry_add():
        """Register a verified mail-in (free) entry. It gets a random unused number from the same pool, with no payment."""
        d = request.get_json(silent=True) or {}
        f = {k: str(d.get(k, '') or '').strip() for k in ('first', 'last', 'email', 'street', 'city', 'state', 'zip', 'country',
                                                        'received_at', 'notes', 'request_id')}
        phone = core.clean_phone(d.get('phone'))
        name = f"{f['first']} {f['last']}".strip()
        missing = [k for k in ('first', 'last', 'street', 'city', 'state', 'zip', 'country', 'received_at') if not f[k]]
        if missing or phone is None or not core.EMAIL_RE.fullmatch(f['email']):
            return jsonify(error='Every field on the form is required: ' + ', '.join(missing or ['valid email and phone'])), 400
        if any(len(v) > 300 for v in f.values()):
            return jsonify(error='A field is too long.'), 400
        if d.get('certified') is not True or d.get('signed') is not True:
            return jsonify(error='The form must include the signed eligibility certification and agreement to the Official Rules.'), 400
        if not core.RID_RE.fullmatch(f['request_id']):
            return jsonify(error='Missing request id.'), 400
        try:
            received = core.datetime.fromisoformat(f['received_at'])
        except ValueError:
            return jsonify(error='Enter the date the entry was received.'), 400
        c = connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            prior = c.execute('SELECT * FROM entries WHERE request_id=?', (f['request_id'],)).fetchone()
            if prior:
                c.rollback()
                return jsonify(ok=True, number=prior['number'], entry_id=prior['id'], duplicate_request=True)
            camp = core.get_campaign(c)
            if not camp.get('free_entry_enabled'):
                c.rollback()
                return jsonify(error='Free entry is not enabled for this campaign.'), 409
            start, end = (core.datetime.fromisoformat(camp[k]) if camp.get(k) else None for k in ('start_at', 'end_at'))
            if (start and received < start) or (end and received > end):
                c.rollback()
                return jsonify(error='This entry was received outside the Entry Period and is void.'), 409
            if core.limit_reached(c, camp, f['email']):
                c.rollback()
                return jsonify(error='This person has already reached the per-person entry limit.'), 409
            same = c.execute('''SELECT number FROM entries WHERE method='free' AND status='free' AND lower(name)=lower(?)
                                 AND lower(street)=lower(?) AND zip=? AND received_at=?''', (name, f['street'], f['zip'], f['received_at'])).fetchone()
            if same and d.get('allow_duplicate') is not True:
                c.rollback()
                return jsonify(error=f'An identical free entry received the same day is already registered (#{same[0]}). '
                                     'Confirm it is a separate envelope to register it.', possible_duplicate=same[0]), 409
            m = core.get_max_tickets(c)
            taken = core.active_numbers(c)
            available = [n for n in range(1, m + 1) if n not in taken]
            if not available:
                c.rollback()
                return jsonify(error='All entries have been issued. This free entry cannot be accepted.'), 409
            n = secrets.choice(available)
            cur = c.execute('''INSERT INTO entries(number,name,email,phone,request_id,amount_cents,status,method,street,city,state,zip,
                                 country,consent_at,consent_text,rules_version,campaign_number,received_at,notes)
                               VALUES(?,?,?,?,?,0,'free','free',?,?,?,?,?,?,?,?,?,?,?)''',
                            (n, name, f['email'], phone, f['request_id'], f['street'], f['city'], f['state'], f['zip'], f['country'],
                             core.now_iso(), 'Signed mail-in form: eligibility certification and Official Rules agreement.',
                             camp.get('rules_version'), camp.get('campaign_number'), f['received_at'], f['notes']))
            entry_id = cur.lastrowid
            core.log(c, actor(), 'free_entry_registered', entry_id=entry_id, number=n, received_at=f['received_at'])
            c.commit()
            entry = load_entry(c, entry_id)
            email_status = core.deliver_email(c, entry, camp, actor())
            c.commit()
            return jsonify(ok=True, number=n, entry_id=entry_id, email_status=email_status)
        finally:
            c.close()

    @app.post('/api/admin/entries/<int:entry_id>/disqualify')
    def disqualify(entry_id):
        d = request.get_json(silent=True) or {}
        reason = str(d.get('reason', '')).strip()[:300]
        with connect() as c:
            e = load_entry(c, entry_id)
            if not e or e['status'] != 'free':
                return jsonify(error='Only free entries can be disqualified here; refund paid entries instead.'), 409
            c.execute("UPDATE entries SET status='disqualified', notes=trim(coalesce(notes,'')||' Disqualified: '||?), "
                      "updated=CURRENT_TIMESTAMP WHERE id=?", (reason, entry_id))
            core.log(c, actor(), 'entry_disqualified', entry_id=entry_id, number=e['number'], reason=reason)
        return jsonify(ok=True, message=f"Entry #{e['number']} disqualified.")

    # ─────────────── pre-launch checklist ───────────────
    def checklist_items(c):
        camp, info = core.get_campaign(c), core.summary(c)
        manual = json.loads((c.execute("SELECT value FROM settings WHERE key='checklist'").fetchone() or ['{}'])[0])
        filled = lambda *ks: all(str(camp.get(k) or '').strip() for k in ks)  # noqa: E731
        auto = [
            ('Campaign information', [
                ('org', 'Organization details: legal name, nonprofit status, EIN, address, email, phone',
                 filled('org_legal_name', 'org_nonprofit_status', 'org_ein', 'org_address', 'org_email', 'org_phone')),
                ('campaign', 'Campaign number and purpose', filled('campaign_number', 'campaign_purpose')),
                ('dates', 'Entry opening and closing dates, and the drawing date (Admin → Campaign → Entries & schedule)',
                 filled('start_at', 'end_at', 'drawing_date')),
                ('prize', 'Prize value and eligibility', filled('prize_arv', 'eligible_regions')),
            ]),
            ('Website setup', [
                ('admin_pw', 'Private admin password set', admin_password != 'local-demo-only'),
                ('secret', 'Session secret key set (RAFFLE_SECRET_KEY)', bool(os.environ.get('RAFFLE_SECRET_KEY'))),
                ('https', 'Served over HTTPS with secure cookies (RAFFLE_SECURE_COOKIES=1)', app.config['SESSION_COOKIE_SECURE']),
                ('smtp', 'Confirmation emails send (SMTP_* settings, including the Gmail app password)', core.smtp_configured()),
                ('stripe', 'Stripe connected in test mode (STRIPE_SECRET_KEY / STRIPE_PUBLISHABLE_KEY)', gateway.name == 'stripe_test'),
                ('indexing', 'Search engines allowed (RAFFLE_ALLOW_INDEXING=1, at public launch)', os.environ.get('RAFFLE_ALLOW_INDEXING') == '1'),
            ]),
            ('Approvals', [
                ('legal', 'Legal review complete (Admin → Campaign → Approvals)', camp.get('legal_approval_status') == 'approved'),
                ('processor', 'Stripe approval in writing (Admin → Campaign → Approvals)', camp.get('processor_approval_status') == 'approved'),
            ]),
        ]
        prize_note = (f"Current prize value {camp.get('prize_arv') or 'not set'}. Registration and a bond apply only above $5,000 "
                      f"in total prizes; re-check if the prize grows.")
        manual_items = [
            ('Approvals', [
                ('m_structure', 'Confirm the New York structure (free-entry sweepstakes with mail-in entry) and that the random '
                                '$1–$360 donation format is permitted', ''),
                ('m_369e', 'NY Secretary of State game-of-chance registration and bond (GBL § 369-e), if required', prize_note),
                ('m_states', 'Confirm eligible states (nationwide preferred) and exclude any that restrict this format', ''),
                ('m_stripe', 'Stripe: written approval to accept giveaway donations on the organization’s own account', ''),
            ]),
            ('Prize', [
                ('m_giftcards', 'Final gift card terms and prize sources entered in Admin → Campaign → Giveaway rules', ''),
                ('m_brands', 'Permission to use restaurant logos and photos, and the Uber name', ''),
                ('m_tax', 'Winner tax process: collect W-9, issue Form 1099 if required', ''),
            ]),
            ('Launch', [
                ('m_gmail', 'Create a Gmail app password for yismachspin@gmail.com and enter it as SMTP_PASSWORD on Render', ''),
                ('m_render', 'Deploy to Render (render.yaml) with the persistent disk, and connect the custom domain', ''),
                ('m_test', 'End-to-end test on the live site: test-card donation, mail-in entry, emails, drawing on a copy', ''),
                ('m_zoom', 'Schedule the Zoom drawing, share the link with entrants, and record it', ''),
                ('m_live', 'Switch Stripe to live keys (a developer change, only after the approvals above)', ''),
            ]),
        ]
        out = []
        for group, items in auto:
            for key, label, done in items:
                out.append(dict(id=key, group=group, label=label, done=bool(done), auto=True))
        for group, items in manual_items:
            for key, label, note in items:
                m = manual.get(key, {})
                out.append(dict(id=key, group=group, label=label, auto=False, done=bool(m.get('done')), note=m.get('note', ''),
                                hint=note, updated=m.get('at'), by=m.get('by')))
        return out

    @app.get('/api/admin/checklist')
    def checklist():
        with connect() as c:
            items = checklist_items(c)
        return jsonify(items=items, done=sum(i['done'] for i in items), total=len(items),
                       live_payments=False, payments=gateway.name)

    @app.post('/api/admin/checklist/<key>')
    def checklist_set(key):
        d = request.get_json(silent=True) or {}
        c = connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            if key not in {i['id'] for i in checklist_items(c) if not i['auto']}:
                c.rollback()
                return jsonify(error='Unknown or automatic checklist item.'), 404
            row = c.execute("SELECT value FROM settings WHERE key='checklist'").fetchone()
            manual = json.loads(row[0]) if row else {}
            manual[key] = dict(done=bool(d.get('done')), note=str(d.get('note', '') or '').strip()[:500], at=core.now_iso(), by=actor())
            c.execute("INSERT INTO settings(key,value) VALUES('checklist',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (json.dumps(manual),))
            core.log(c, actor(), 'checklist_updated', item=key, done=manual[key]['done'], note=manual[key]['note'])
            c.commit()
            return jsonify(ok=True)
        finally:
            c.close()

    @app.post('/api/admin/new-campaign')
    def new_campaign():
        """Reuse the platform: archive this campaign's full database, then clear entries, payments, emails and the drawing.
        Campaign settings (branding, restaurants, legal text) are kept for editing; the new campaign number is required."""
        d = request.get_json(silent=True) or {}
        number = str(d.get('campaign_number', '')).strip()
        if d.get('confirm') != 'START NEW CAMPAIGN' or not re.fullmatch(r'[A-Za-z0-9-]{3,40}', number):
            return jsonify(error='Type START NEW CAMPAIGN and give the new campaign number (letters, numbers, dashes).'), 400
        c = connect()
        try:
            camp = core.get_campaign(c)
            if number == camp.get('campaign_number'):
                return jsonify(error='Use a new campaign number.'), 400
            pending = c.execute("SELECT COUNT(*) FROM entries WHERE status IN ('pending_capture','capture_failed')").fetchone()[0]
            issued = c.execute("SELECT COUNT(*) FROM entries WHERE status != 'released'").fetchone()[0]
            drawn = c.execute('SELECT COUNT(*) FROM drawings WHERE drawn_at IS NOT NULL').fetchone()[0]
            if pending:
                return jsonify(error='Resolve entries with pending or failed payments first.'), 409
            if issued and not drawn and d.get('without_drawing') is not True:
                return jsonify(error='This campaign has entries but no drawing yet.', needs_override=True), 409
            archive.mkdir(parents=True, exist_ok=True)
            stamp = core.now_iso().replace(' ', '_').replace(':', '')
            dest = archive / f"campaign-{re.sub(r'[^A-Za-z0-9-]', '', camp.get('campaign_number') or 'unnumbered')}-{stamp}.sqlite"
            with core.connect(dest) as out:
                c.backup(out)
            c.execute('BEGIN IMMEDIATE')
            for t in ('entries', 'transactions', 'emails', 'drawings'):
                c.execute(f'DELETE FROM {t}')
            c.execute("DELETE FROM settings WHERE key='checklist'")
            camp.update(campaign_number=number, start_at='', end_at='', drawing_date='', winner_info='', sales_paused=True,
                        legal_approval_status='not_started', processor_approval_status='not_started')
            c.execute("UPDATE settings SET value=? WHERE key='campaign'", (json.dumps(camp),))
            core.log(c, actor(), 'new_campaign_started', archived_to=dest.name, campaign_number=number)
            c.commit()
            return jsonify(ok=True, archived=dest.name)
        finally:
            c.close()

    # ─────────────── settings & campaign ───────────────
    @app.post('/api/admin/settings')
    def admin_settings():
        d = request.get_json(silent=True) or {}
        try:
            new_max = int(d.get('max_tickets'))
        except (TypeError, ValueError):
            return jsonify(error='Maximum tickets must be a whole number.'), 400
        if not (1 <= new_max <= core.MAX_TICKETS_CEILING):
            return jsonify(error=f'Maximum tickets must be between 1 and {core.MAX_TICKETS_CEILING}.'), 400
        c = connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            highest = c.execute("SELECT MAX(number) FROM entries WHERE status != 'released'").fetchone()[0] or 0
            if new_max < highest:
                c.rollback()
                return jsonify(error=f'Ticket #{highest} has already been issued; the maximum cannot be set below {highest}.'), 409
            old = core.get_max_tickets(c)
            c.execute("INSERT INTO settings(key,value) VALUES('max_tickets',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(new_max),))
            core.log(c, actor(), 'max_tickets_changed', old=old, new=new_max)
            c.commit()
            return jsonify(core.summary(c))
        finally:
            c.close()

    @app.get('/api/admin/campaign')
    def campaign_get():
        with connect() as c:
            return jsonify(campaign=core.get_campaign(c), status=core.summary(c))

    @app.put('/api/admin/campaign')
    def campaign_put():
        d = request.get_json(silent=True) or {}
        c = connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            cur = core.get_campaign(c)
            try:
                new = core.validate_campaign(d, cur)
            except (ValueError, TypeError) as e:
                c.rollback()
                return jsonify(error=str(e)), 400
            sold = c.execute("SELECT COUNT(*) FROM entries WHERE status != 'released'").fetchone()[0]
            if new['unit_price_cents'] != cur['unit_price_cents'] and sold:
                c.rollback()
                return jsonify(error='Entry pricing cannot change after tickets have been issued.'), 409
            c.execute("UPDATE settings SET value=? WHERE key='campaign'", (json.dumps(new),))
            changed = sorted(k for k in new if new[k] != cur.get(k))
            core.log(c, actor(), 'campaign_updated', fields=changed)
            c.commit()
            return jsonify(campaign=new, status=core.summary(c))
        finally:
            c.close()

    @app.post('/api/admin/upload')
    def upload():
        f = request.files.get('file')
        if not f:
            return jsonify(error='No file.'), 400
        head = f.stream.read(12)
        f.stream.seek(0)
        ext = next((e for sig, e in UPLOAD_TYPES.items() if head.startswith(sig)), None)
        if ext == '.webp' and head[8:12] != b'WEBP':
            ext = None
        if not ext and head[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'):  # MP3 without an ID3 tag
            ext = '.mp3'
        if not ext and head[4:8] == b'ftyp':
            ext = '.m4a'
        if not ext:
            return jsonify(error='Upload a PNG, JPG or WebP image, or an MP3, M4A or OGG audio file.'), 400
        size = f.stream.seek(0, 2)
        f.stream.seek(0)
        if ext not in AUDIO_EXTS and size > 6 * 1024 * 1024:
            return jsonify(error='Images must be 6 MB or smaller.'), 400
        name = secrets.token_hex(12) + ext
        f.save(uploads / name)
        with connect() as c:
            core.log(c, actor(), 'audio_uploaded' if ext in AUDIO_EXTS else 'image_uploaded', file=name, original=(f.filename or '')[:120])
        return jsonify(url='/uploads/' + name)

    # ─────────────── drawing ───────────────
    @app.get('/api/admin/drawing')
    def admin_drawing():
        with connect() as c:
            d = c.execute('SELECT * FROM drawings ORDER BY id DESC LIMIT 1').fetchone()
            info = core.summary(c)
            eligible = c.execute("SELECT COUNT(*) FROM entries WHERE status IN ('paid','free')").fetchone()[0]
        out = None
        if d:
            out = {k: d[k] for k in d.keys() if k != 'seed'}
            if d['drawn_at']:
                out['seed'] = d['seed']
                out['winners'] = json.loads(d['winners'])
                winners = out['winners']
                with connect() as c:
                    out['winner_entries'] = [dict(r) for r in c.execute(
                        f"SELECT number,name,email,phone,method FROM entries WHERE status IN ('paid','free') AND number IN ({','.join('?' * len(winners))})", winners)] if winners else []
        return jsonify(drawing=out, eligible=eligible, sales_open=info['sales_open'])

    @app.post('/api/admin/drawing/commit')
    def drawing_commit():
        with connect() as c:
            d = c.execute('SELECT drawn_at FROM drawings ORDER BY id DESC LIMIT 1').fetchone()
            if d and not d['drawn_at']:
                return jsonify(error='A drawing commitment already exists.'), 409
            if d and d['drawn_at']:
                return jsonify(error='The drawing has already taken place.'), 409
            commitment = core.commit_drawing(c)
            core.log(c, actor(), 'drawing_committed', commitment=commitment)
        return jsonify(commitment=commitment)

    @app.post('/api/admin/drawing/draw')
    def drawing_draw():
        body = request.get_json(silent=True) or {}
        entropy = str(body.get('public_entropy', '')).strip()[:200]
        if not entropy:
            return jsonify(error='Enter the public entropy value announced in advance (for example, a lottery result).'), 400
        c = connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            d = c.execute('SELECT * FROM drawings ORDER BY id DESC LIMIT 1').fetchone()
            if not d:
                c.rollback()
                return jsonify(error='Publish a drawing commitment first.'), 409
            if d['drawn_at']:
                c.rollback()
                return jsonify(error='The drawing has already taken place.'), 409
            info = core.summary(c)
            if info['sales_open']:
                c.rollback()
                return jsonify(error='Close entries first (pause sales, set an end date, or sell out).'), 409
            eligible = [r[0] for r in c.execute("SELECT number FROM entries WHERE status IN ('paid','free') ORDER BY number")]
            if not eligible:
                c.rollback()
                return jsonify(error='There are no eligible entries to draw from.'), 409
            count = int(core.get_campaign(c)['winners'])
            winners, ehash = core.pick_winners(d['seed'], entropy, eligible, count)
            c.execute('UPDATE drawings SET public_entropy=?, drawn_at=?, eligible=?, eligible_hash=?, winners=? WHERE id=?',
                      (entropy, core.now_iso(), json.dumps(eligible), ehash, json.dumps(winners), d['id']))
            core.log(c, actor(), 'drawing_completed', winners=winners, eligible_count=len(eligible), eligible_hash=ehash)
            c.commit()
            return jsonify(winners=winners, eligible_hash=ehash, eligible_count=len(eligible))
        finally:
            c.close()

    # ─────────────── export ───────────────
    @app.get('/api/admin/export')
    def export():
        s = io.StringIO()
        w = csv.writer(s)
        w.writerow(['Ticket', 'Amount', 'Status', 'Method', 'Payment mode', 'Authorization ID', 'Capture ID', 'Refund ID',
                    'Name', 'Email', 'Phone', 'Street', 'City', 'State', 'ZIP', 'Country', 'Received (mail-in)',
                    'Consent at (UTC)', 'Rules version', 'Campaign number', 'Marketing opt-in', 'UTC created'])

        def safe(v):
            v = '' if v is None else str(v)
            return "'" + v if v.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else v

        with connect() as c:
            for r in c.execute('SELECT * FROM entries ORDER BY number, id'):
                w.writerow([r['number'], f"{r['amount_cents'] / 100:.2f}", r['status'], r['method'], r['payment_mode'], r['authorization_id'],
                            r['capture_id'], r['refund_id'], safe(r['name']), safe(r['email']), safe(r['phone']),
                            safe(r['street']), safe(r['city']), safe(r['state']), safe(r['zip']), safe(r['country']),
                            r['received_at'], r['consent_at'], r['rules_version'], r['campaign_number'],
                            'yes' if r['marketing_opt_in'] else 'no', r['created']])
            core.log(c, actor(), 'csv_exported')
        return Response(s.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': 'attachment; filename=raffle-entries.csv'})

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', '5000')), debug=False, threaded=True)
