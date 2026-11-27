// Raffle administration. All participant-supplied values are escaped before rendering.
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const money = (n) => '$' + Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 });
  const cents = (c) => money((c || 0) / 100);
  const STATUS = { paid: 'Paid', pending_capture: 'Pending', capture_failed: 'Payment failed', refunded: 'Refunded', released: 'Released', free: 'Free (mail-in)', disqualified: 'Disqualified' };
  const cellCls = (s) => s === 'free' ? 'mailin' : s;
  const S = { data: null, tx: [], mails: [], activity: [], campaign: null, drawing: null, tab: 'overview' };

  async function api(path, opts = {}) {
    const o = { ...opts, headers: { 'X-Requested-With': 'raffle-admin', ...(opts.body && !(opts.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...(opts.headers || {}) }, credentials: 'same-origin' };
    if (o.body && !(o.body instanceof FormData) && typeof o.body !== 'string') o.body = JSON.stringify(o.body);
    const r = await fetch(path, o);
    const d = await r.json().catch(() => ({}));
    if (r.status === 401 && path !== '/api/admin/login') { showLogin(); throw new Error('Please sign in.'); }
    if (!r.ok) throw new Error(d.error || `Request failed (${r.status})`);
    return d;
  }
  let toastT;
  function toast(msg, bad) { const t = $('toast'); t.textContent = msg; t.classList.toggle('bad', !!bad); t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, 3800); }

  /* auth */
  function showLogin() { $('shell').hidden = true; $('login').hidden = false; setTimeout(() => $('lu').focus(), 30); }
  $('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault(); $('loginErr').textContent = '';
    try { await api('/api/admin/login', { method: 'POST', body: { username: $('lu').value, password: $('lp').value } }); $('lp').value = ''; boot(); }
    catch (err) { $('loginErr').textContent = err.message; }
  });
  $('logout').addEventListener('click', async () => { await api('/api/admin/logout', { method: 'POST' }).catch(() => {}); showLogin(); });

  /* tabs */
  $('tabs').addEventListener('click', (e) => { const b = e.target.closest('button[data-tab]'); if (b) go(b.dataset.tab); });
  function go(tab) {
    S.tab = tab;
    document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
    document.querySelectorAll('[data-panel]').forEach(p => { p.hidden = p.dataset.panel !== tab; });
    ({ overview: loadOverview, entries: loadOverview, payments: loadTx, emails: loadMails, drawing: loadDrawing, ambassadors: loadAmb, campaign: loadCampaign, checklist: loadChecklist, activity: loadActivity }[tab])();
    history.replaceState(null, '', '#' + tab);
  }

  async function boot() {
    try { await api('/api/admin/me'); } catch { return; }
    $('login').hidden = true; $('shell').hidden = false;
    go((location.hash || '#overview').slice(1).replace(/[^a-z]/g, '') || 'overview');
  }

  /* overview + entries */
  async function loadOverview() {
    const d = S.data = await api('/api/admin');
    $('payBadge').textContent = d.payment_mode === 'live' ? 'LIVE payments' : 'Test payments';
    const camp = S.campaign || (await api('/api/admin/campaign')).campaign; S.campaign = camp;
    $('campName').textContent = camp.title;
    const c = d.counts;
    $('stats').innerHTML = [
      ['Funds raised', money(d.total), `${d.payment_mode === 'live' ? 'live' : 'test'} · max ${money(d.max_gross)}`, 'hl'],
      ['Tickets sold', `${c.paid + c.pending_capture + c.capture_failed}`, `of ${d.max_tickets}`],
      ['Free entries', c.free, c.disqualified ? `${c.disqualified} disqualified` : 'mail-in, same drawing'],
      ['Remaining', d.remaining, d.sales_open ? 'entries open' : esc(d.sales_message)],
      ['Failed payments', c.capture_failed, c.capture_failed ? 'needs attention' : 'none'],
      ['Refunded', money(d.refunded_total), `${c.refunded} ticket${c.refunded === 1 ? '' : 's'}`],
      ['Entry price', `${money(d.min_price)}–${money(d.max_price)}`, 'number × ' + money(d.unit_price_cents / 100)],
    ].map(([k, v, s, cls]) => `<div class="stat ${cls || ''}"><span>${k}</span><strong>${v}</strong><em>${s}</em></div>`).join('');
    const byNum = new Map(d.entries.filter(e => e.status !== 'released').map(e => [e.number, e]));
    const winners = new Set((S.drawing && S.drawing.winners) || []);
    let html = '';
    for (let n = 1; n <= d.max_tickets; n++) {
      const e = byNum.get(n);
      html += e ? `<button class="cell ${cellCls(e.status)}${winners.has(n) ? ' win' : ''}" data-entry="${e.id}" title="#${n} · ${esc(e.name)} · ${STATUS[e.status]}">${n}</button>`
                : `<span class="cell free" title="#${n} available">${n}</span>`;
    }
    $('grid').innerHTML = html;
    $('gridInfo').textContent = `${byNum.size} of ${d.max_tickets} numbers issued · highest issued #${d.highest_issued || '—'}`;
    renderEntries();
  }
  $('grid').addEventListener('click', (e) => { const b = e.target.closest('[data-entry]'); if (!b) return; const en = S.data.entries.find(x => x.id == b.dataset.entry); $('q').value = String(en.number); $('fStatus').value = ''; go('entries'); });
  $('refresh').addEventListener('click', () => loadOverview().then(() => toast('Updated')));

  function renderEntries() {
    if (!S.data) return;
    const q = $('q').value.trim().toLowerCase(), f = $('fStatus').value;
    const rows = S.data.entries.filter(e => (!f || e.status === f) && (!q || String(e.number) === q.replace('#', '') || `${e.name} ${e.email} ${e.phone}`.toLowerCase().includes(q)));
    $('entryRows').innerHTML = rows.map(e => `<tr>
      <td class="num"><b>#${e.number}</b></td>
      <td>${esc(e.name)}<span class="sub">${esc(e.email)}</span></td>
      <td class="num">${esc(e.phone)}</td>
      <td class="num">${e.method === 'free' ? 'Free' : money(e.amount)}${e.package && e.package !== 'spin' ? `<span class="sub">${esc(e.package_label)}</span>` : ''}${e.rules_version ? `<span class="sub" title="${esc(e.consent_text || '')}">consent ${esc(e.consent_at || '')} · rules ${esc(e.rules_version)}${e.marketing_opt_in ? ' · marketing ✓' : ''}</span>` : ''}${e.received_at ? `<span class="sub">received ${esc(e.received_at)}</span>` : ''}</td>
      <td><span class="chip ${e.status}">${STATUS[e.status]}</span></td>
      <td>${e.email_status ? `<span class="chip ${e.email_status}">${e.email_status}</span>` : '<span class="sub">—</span>'}</td>
      <td class="num">${esc(e.created)}</td>
      <td class="acts">${actions(e)}</td></tr>`).join('') || '<tr><td colspan="8" class="muted">No entries match.</td></tr>';
    $('entryCount').textContent = `${rows.length} of ${S.data.entries.length} entries`;
  }
  function actions(e) {
    const b = (act, label, cls = '') => `<button class="btn sm ${cls}" data-act="${act}" data-id="${e.id}" data-n="${e.number}">${label}</button>`;
    if (e.status === 'paid') return b('resend-email', 'Resend email') + b('refund', 'Refund', 'danger');
    if (e.status === 'free') return b('resend-email', 'Resend email') + b('disqualify', 'Disqualify', 'danger');
    if (e.status === 'capture_failed' || e.status === 'pending_capture') return b('retry-capture', 'Retry payment') + b('release', 'Release number', 'danger');
    return '';
  }
  $('q').addEventListener('input', renderEntries); $('fStatus').addEventListener('change', renderEntries);
  $('entryRows').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]'); if (!btn) return;
    const { act, id, n } = btn.dataset;
    let body;
    if (act === 'refund') { const reason = prompt(`Refund ticket #${n}? The ticket becomes void for the drawing and the number is not re-issued.\n\nReason (optional):`); if (reason === null) return; body = { reason }; }
    if (act === 'disqualify') { const reason = prompt(`Disqualify free entry #${n}? It is removed from the drawing and the number is not re-issued.\n\nReason:`); if (reason === null) return; body = { reason }; }
    if (act === 'release' && !confirm(`Void the authorization for ticket #${n} and return the number to the pool?`)) return;
    btn.disabled = true;
    try { const r = await api(`/api/admin/entries/${id}/${act}`, { method: 'POST', body: body || {} }); toast(r.message || (act === 'resend-email' ? `Email ${r.email_status}` : 'Done'), r.ok === false); await loadOverview(); }
    catch (err) { toast(err.message, true); btn.disabled = false; }
  });

  /* check / cash payments */
  const offSum = () => {
    const fd = new FormData($('offForm')), amt = parseFloat(String(fd.get('amount') || '').replace(/[$,]/g, '')), n = parseInt(fd.get('entries'), 10);
    $('offSummary').textContent = amt > 0 && n > 0 ? `${n} entr${n === 1 ? 'y' : 'ies'} with random numbers, ${money(amt)} total.` : '';
  };
  $('offForm').addEventListener('input', offSum);
  $('addOffline').addEventListener('click', () => { $('offForm').reset(); $('offErr').textContent = ''; offSum(); S.offRid = crypto.randomUUID(); $('offDlg').showModal(); });
  $('offSubmit').addEventListener('click', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData($('offForm')).entries()); body.request_id = S.offRid;
    $('offErr').textContent = ''; $('offSubmit').disabled = true;
    try {
      const r = await api('/api/admin/offline-entries', { method: 'POST', body });
      $('offDlg').close(); toast(`Added: #${r.numbers.join(', #')}${r.email_status ? ` · email ${r.email_status}` : ' · no email sent'}`); S.data = null; await loadOverview();
    } catch (err) { $('offErr').textContent = err.message; } finally { $('offSubmit').disabled = false; }
  });

  /* mail-in (free) entries */
  $('addFree').addEventListener('click', () => { $('freeForm').reset(); $('freeErr').textContent = ''; S.freeRid = crypto.randomUUID(); S.allowDup = false; $('freeDlg').showModal(); });
  $('freeSubmit').addEventListener('click', async (e) => {
    e.preventDefault();
    const fd = new FormData($('freeForm')), body = Object.fromEntries(fd.entries());
    body.certified = fd.has('certified'); body.signed = fd.has('signed'); body.request_id = S.freeRid; body.allow_duplicate = S.allowDup;
    $('freeErr').textContent = ''; $('freeSubmit').disabled = true;
    try {
      const r = await api('/api/admin/free-entries', { method: 'POST', body });
      $('freeDlg').close(); toast(`Free entry registered: #${r.number}${r.email_status ? ` · email ${r.email_status}` : ''}`); S.data = null; await loadOverview();
    } catch (err) {
      $('freeErr').textContent = err.message;
      if (/identical free entry/.test(err.message)) { S.allowDup = true; $('freeErr').textContent += ' Click Register again to confirm.'; }
    } finally { $('freeSubmit').disabled = false; }
  });

  /* payments */
  async function loadTx() { S.tx = (await api('/api/admin/transactions')).transactions; renderTx(); }
  function renderTx() {
    const q = $('tq').value.trim().toLowerCase(), k = $('tKind').value, st = $('tStatus').value;
    const rows = S.tx.filter(t => (!k || t.kind === k) && (!st || t.status === st) && (!q || `${t.provider_ref} ${t.email} ${t.number} ${t.request_id}`.toLowerCase().includes(q.replace('#', ''))));
    $('txRows').innerHTML = rows.map(t => `<tr><td class="num">${esc(t.created)}</td><td>${esc(t.kind)}</td><td><span class="chip ${t.status}">${esc(t.status)}</span></td>
      <td class="num">${cents(t.amount_cents)}</td><td class="num">${t.number ? '#' + t.number : '—'}</td><td>${esc(t.email || '')}</td><td class="mono">${esc(t.provider_ref || '—')}</td><td>${esc(t.message || '')}</td></tr>`).join('') || '<tr><td colspan="8" class="muted">No transactions.</td></tr>';
  }
  ['tq', 'tKind', 'tStatus'].forEach(id => $(id).addEventListener('input', renderTx));

  /* emails */
  async function loadMails() { S.mails = (await api('/api/admin/emails')).emails; renderMails(); }
  function renderMails() {
    const q = $('eq').value.trim().toLowerCase(), st = $('eStatus').value;
    const rows = S.mails.filter(m => (!st || m.status === st) && (!q || `${m.to_addr} ${m.number}`.toLowerCase().includes(q.replace('#', ''))));
    $('mailRows').innerHTML = rows.map(m => `<tr><td class="num">${esc(m.created)}</td><td>${esc(m.to_addr)}</td><td class="num">${m.number ? '#' + m.number : '—'}</td><td>${esc(m.subject)}</td>
      <td><span class="chip ${m.status}">${esc(m.status)}</span>${m.error ? `<span class="sub">${esc(m.error)}</span>` : ''}</td>
      <td class="acts"><button class="btn sm" data-preview="${m.id}">Preview</button>${m.entry_id ? `<button class="btn sm" data-resend="${m.entry_id}">Resend</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">No emails yet.</td></tr>';
  }
  ['eq', 'eStatus'].forEach(id => $(id).addEventListener('input', renderMails));
  $('mailRows').addEventListener('click', async (e) => {
    const p = e.target.closest('[data-preview]'), r = e.target.closest('[data-resend]');
    if (p) { const m = await api(`/api/admin/emails/${p.dataset.preview}`); const f = document.createElement('iframe'); f.setAttribute('sandbox', ''); f.srcdoc = m.body_html; $('modalBody').replaceChildren(f); $('modal').showModal(); }
    if (r) { try { const d = await api(`/api/admin/entries/${r.dataset.resend}/resend-email`, { method: 'POST', body: {} }); toast(`Email ${d.email_status}`); loadMails(); } catch (err) { toast(err.message, true); } }
  });

  /* drawing */
  async function loadDrawing() {
    const d = await api('/api/admin/drawing'); S.drawing = d.drawing;
    const card = $('drawCard'), dr = d.drawing;
    if (!dr) {
      card.innerHTML = `<h3>No drawing yet</h3><p class="muted">${d.eligible} paid ticket${d.eligible === 1 ? '' : 's'} eligible. Publish a commitment before entries close.</p><button class="btn primary" id="commit">Publish drawing commitment</button>`;
    } else if (!dr.drawn_at) {
      card.innerHTML = `<h3>Commitment published</h3><dl class="kv"><dt>Commitment (SHA-256)</dt><dd class="mono">${esc(dr.commitment)}</dd><dt>Published</dt><dd>${esc(dr.committed_at)} UTC</dd><dt>Eligible now</dt><dd>${d.eligible} paid tickets</dd><dt>Entries</dt><dd>${d.sales_open ? 'Still open: close entries before drawing.' : 'Closed'}</dd></dl>
        <div class="row"><label>Public entropy value (announced in advance)<input id="entropy" placeholder="e.g. NY Numbers Midday 2026-12-21: 4 7 1"></label><button class="btn primary" id="draw" ${d.sales_open ? 'disabled' : ''}>Draw winner${S.campaign && S.campaign.winners > 1 ? 's' : ''}</button></div>`;
    } else {
      card.innerHTML = `<h3>Winner${dr.winners.length > 1 ? 's' : ''} drawn</h3>
        <div class="stats">${dr.winner_entries.map(w => `<div class="stat hl"><span>Ticket</span><strong>#${w.number}</strong><em>${esc(w.name)} · ${esc(w.email)} · ${esc(w.phone)}</em></div>`).join('')}</div>
        <dl class="kv"><dt>Drawn</dt><dd>${esc(dr.drawn_at)} UTC</dd><dt>Commitment</dt><dd class="mono">${esc(dr.commitment)}</dd><dt>Revealed seed</dt><dd class="mono">${esc(dr.seed)}</dd>
        <dt>Public entropy</dt><dd>${esc(dr.public_entropy)}</dd><dt>Eligible list hash</dt><dd class="mono">${esc(dr.eligible_hash)}</dd><dt>Algorithm</dt><dd class="small">${esc(dr.algorithm)}</dd></dl>
        <a class="btn" href="/api/drawing" target="_blank" rel="noopener">Public verification data ↗</a>`;
    }
    const cm = $('commit'); if (cm) cm.onclick = async () => { if (!confirm('Publish the drawing commitment now? This cannot be undone.')) return; try { await api('/api/admin/drawing/commit', { method: 'POST', body: {} }); toast('Commitment published'); loadDrawing(); } catch (err) { toast(err.message, true); } };
    const dw = $('draw'); if (dw) dw.onclick = async () => { const v = $('entropy').value.trim(); if (!v) { toast('Enter the public entropy value first.', true); return; } if (!confirm('Run the drawing now? It can only be done once.')) return; try { await api('/api/admin/drawing/draw', { method: 'POST', body: { public_entropy: v } }); toast('Drawing complete'); loadDrawing(); } catch (err) { toast(err.message, true); } };
  }

  /* campaign settings */
  const F = (label, key, type = 'text', help = '') => `<label>${label}${type === 'textarea' ? `<textarea data-k="${key}"></textarea>` : `<input type="${type}" data-k="${key}">`}${help ? `<p class="help">${help}</p>` : ''}</label>`;
  async function loadCampaign() {
    const d = await api('/api/admin/campaign'); S.campaign = d.campaign; const st = d.status; S.maxLoaded = st.max_tickets;
    const c = d.campaign;
    $('campForm').innerHTML = `
      <fieldset><legend>Branding</legend><div class="fgrid">
        ${F('Organization', 'org_name')}${F('“Presents” line', 'presents')}${F('Campaign name', 'title')}${F('Subtitle', 'subtitle')}</div>
        <div class="fgrid" style="margin-top:14px">${F('Main headline', 'headline', 'textarea', 'Each sentence becomes its own line; the last line is set in gold.')}${F('Introduction', 'intro', 'textarea')}${F('Tagline', 'tagline', 'textarea')}${F('WhatsApp share text', 'share_text', 'textarea')}</div></fieldset>
      <fieldset><legend>Prize</legend><div class="fgrid">${F('Prize heading', 'prize_title')}${F('Prize description', 'prize_description', 'textarea')}${F('Amount at each restaurant', 'dining_each', 'text', 'e.g. $300 (shown on the top badge and on each restaurant). Leave blank to hide.')}<label>Prize highlights (one per line)<textarea id="prizeItemsF">${esc((c.prize_items || []).join('\n'))}</textarea></label></div>
        <label style="margin-top:16px">Top-of-page slideshow shows<select data-k="hero_source"><option value="restaurants">Each restaurant’s photo and logo (from the list below)</option><option value="custom">The custom slides below</option></select></label>
        <p class="help" style="margin-top:12px">Custom slides (dishes fade in and out behind the headline; use restaurant photos with permission)</p><div class="fgrid">${[0,1,2,3,4,5,6,7].map(i => imgField(`Slide ${i + 1}`, `hs:${i}`, (c.hero_images || [])[i])).join('')}</div><div class="fgrid" style="margin-top:14px">${imgField('Prize image', 'prize_image', c.prize_image)}${imgField('Picture on the number-reveal card (e.g. the Rav, “בשמחה תמיד”)', 'reveal_image', c.reveal_image)}</div>
        <div class="fgrid" style="margin-top:10px">${F('Caption under that picture (optional)', 'reveal_caption')}</div>
        <label class="check" style="margin-top:14px"><input type="checkbox" data-k="prizes_confirmed"> Restaurant participation and prize terms are confirmed (hides the “subject to confirmation” notice)</label></fieldset>
      <fieldset><legend>Share &amp; earn links</legend>
        <p class="help" style="margin-top:0">Every donor gets a personal link after spinning, and anyone can get one in the “Share your link” section. The Ambassadors tab tracks how many paid entries came through each link. Leave the reward blank to track only; fill it in to show the reward and progress publicly.</p>
        <label class="check"><input type="checkbox" data-k="referral_enabled"> Offer personal share links</label>
        <div class="fgrid" style="margin-top:14px">${F('Reward (optional; blank = tracking only)', 'referral_reward', 'text', 'e.g. A Tomahawk steak from Gourmet Glatt')}${F('Entries needed for the reward', 'referral_threshold', 'number')}</div>
        <label style="margin-top:14px">Reward terms (shown under the share box)<textarea data-k="referral_terms"></textarea></label></fieldset>
      <fieldset><legend>Background music</legend>
        <p class="help" style="margin-top:0">Music starts only when a visitor taps the speaker button (browsers block music that plays by itself). A YouTube song plays in YouTube’s own small player, which stays visible, as YouTube requires. Upload an audio file only if the organization has the rights to it.</p>
        <div class="fgrid"><label>Music<select data-k="music_source"><option value="youtube">A YouTube video</option><option value="upload">An uploaded audio file</option><option value="off">No music</option></select></label>
        <label class="check" style="align-self:end"><input type="checkbox" data-k="music_autostart"> Start the music when the dreidel starts spinning</label>
        ${F('YouTube link', 'music_youtube', 'text', 'Paste the video link, e.g. https://www.youtube.com/watch?v=…')}${F('Song title shown in the player', 'music_title')}</div>
        <div style="margin-top:14px" class="audiofield" id="musicField"></div></fieldset>
      <fieldset><legend>Restaurants &amp; sponsors</legend><div class="rlist" id="rlist"></div><button type="button" class="btn" id="addR" style="margin-top:12px">+ Add restaurant</button></fieldset>
      <fieldset><legend>Transportation</legend>
        <label class="check"><input type="checkbox" data-t="enabled"> Show the transportation section</label>
        <div class="fgrid" style="margin-top:14px">
          <label>Section title<input data-t="title"></label><label>Amount<input data-t="amount"></label><label>Amount label<input data-t="amount_label"></label><label>Brand name<input data-t="brand"></label></div>
        <label style="margin-top:14px">Detail<textarea data-t="detail"></textarea></label>
        <div class="fgrid" style="margin-top:14px">${imgField('Brand logo (use official assets with permission)', 't:logo', c.transport.logo)}${imgField('Background image', 't:image', c.transport.image)}</div></fieldset>
      <fieldset><legend>Entries &amp; schedule</legend><div class="fgrid">
        <label>Number of entries<input type="number" min="1" max="5000" id="maxTickets" value="${st.max_tickets}"><p class="help">Numbers 1–N. Cannot go below the highest number issued.</p></label>
        <label>Donation per number ($)<input type="number" min="0.01" step="0.01" id="unitPrice" value="${(c.unit_price_cents / 100).toFixed(2)}"><p class="help">Donation = number × this. Locked once entries are issued.</p></label>
        <label>Number of winners<input type="number" min="1" max="100" data-k="winners"></label>
        <label>Drawing date (shown publicly)<input data-k="drawing_date" placeholder="e.g. Sunday, December 21, 2026"></label>
        <label>Show the “entries claimed” bar from<input type="number" min="0" data-k="progress_min"><p class="help">Hidden until this many entries are claimed, so early numbers don’t look small.</p></label>
        <label>Entries open<input type="datetime-local" data-k="start_at"></label>
        <label>Entries close<input type="datetime-local" data-k="end_at"></label></div>
        <p class="help" id="grossHelp"></p>
        <label class="check" style="margin-top:10px"><input type="checkbox" data-k="sales_paused"> Pause entries</label></fieldset>
      <fieldset><legend>Organization &amp; legal information</legend>
        <p class="legal-note">Leave a field blank until it is verified. Blank fields appear on the site as highlighted placeholders, never as made-up information.</p>
        <div class="fgrid">${F('Full legal name', 'org_legal_name')}${F('Nonprofit status (once verified)', 'org_nonprofit_status', 'text', 'e.g. a New York not-for-profit corporation, tax-exempt under 501(c)(3)')}${F('Federal EIN', 'org_ein')}
        ${F('Physical mailing address', 'org_address', 'text', 'Also used as the mail-in entry address.')}${F('Contact email', 'org_email', 'email')}${F('Contact telephone', 'org_phone', 'tel')}</div>
        <div class="fgrid" style="margin-top:14px">${F('Purpose of the campaign', 'campaign_purpose', 'textarea')}</div></fieldset>
      <fieldset><legend>Giveaway rules</legend><div class="fgrid">
        ${F('Campaign identification number', 'campaign_number', 'text', 'Required on every mail-in entry.')}${F('Rules version', 'rules_version', 'text', 'Recorded with every entry’s consent. Change it whenever the rules change.')}
        ${F('Minimum age', 'min_age', 'number')}${F('Eligible locations', 'eligible_regions', 'text', 'e.g. the State of New York, as approved by counsel')}
        ${F('Entries per person (0 = no limit)', 'entries_per_person', 'number', 'Applies equally to donation and free entries.')}${F('Days for winner to respond', 'claim_days', 'number')}
        ${F('Drawing procedure', 'drawing_method', 'text', 'e.g. conducted live and in public view at …')}${F('County for disputes (New York)', 'governing_county')}
        ${F('Prize approximate retail value (ARV)', 'prize_arv')}</div>
        <div class="fgrid" style="margin-top:14px">${F('Excluded people', 'exclusions', 'textarea', 'Blank uses the standard exclusion (sponsor staff, volunteers and their families).')}${F('Gift card conditions', 'prize_terms', 'textarea', 'Issuer, face values, expiration dates, reservations, transportation credit terms, geographic limits.')}${F('Source of the prizes', 'prize_source', 'textarea')}${F('Record retention (privacy policy)', 'privacy_retention', 'textarea')}</div>
        <label class="check" style="margin-top:14px"><input type="checkbox" data-k="free_entry_enabled"> Free mail-in entry is offered (shows the No Purchase Necessary disclaimer and the free-entry form)</label>
        <label class="check" style="margin-top:8px"><input type="checkbox" data-k="winner_anonymous_allowed"> The winner may choose to be announced as “Anonymous”</label></fieldset>
      <fieldset><legend>Consent wording</legend><div class="fgrid">
        ${F('Payment authorization', 'auth_language', 'textarea', 'Placeholders: {org} {min} {max}. Shown with an unchecked checkbox before payment; saved with each entry.')}${F('Optional marketing consent', 'marketing_consent_text', 'textarea', 'Separate, unchecked, and never required. Placeholder: {org}')}</div></fieldset>
      <fieldset><legend>Rules &amp; policy pages</legend>
        <p class="help" style="margin-top:0">Leave blank to use the generated drafts at <a href="/rules" target="_blank">/rules</a>, <a href="/free-entry" target="_blank">/free-entry</a>, <a href="/privacy" target="_blank">/privacy</a> and <a href="/terms" target="_blank">/terms</a>. To use counsel’s final text, paste it here: a blank line separates paragraphs, and a line starting with # is a heading.</p>
        <div class="fgrid">${F('Official Rules (replaces the draft)', 'official_rules', 'textarea')}${F('Free entry instructions (replaces the draft)', 'free_entry_instructions', 'textarea')}${F('Privacy Policy (replaces the draft)', 'privacy_policy', 'textarea')}${F('Terms and Conditions (replaces the draft)', 'terms_text', 'textarea')}</div>
        <label style="margin-top:14px">Winner announcement (shown on /winners after the drawing, with the winner’s permission)<textarea data-k="winner_info"></textarea></label></fieldset>
      <fieldset><legend>Approvals</legend><div class="fgrid">
        <label>Legal approval (rules, structure, free entry)<select data-k="legal_approval_status"><option value="not_started">Not started</option><option value="in_review">In review with counsel</option><option value="approved">Approved by counsel</option></select></label>
        <label>Payment processor approval (Stripe)<select data-k="processor_approval_status"><option value="not_started">Not started</option><option value="in_review">Requested</option><option value="approved">Approved in writing</option></select></label></div>
        <p class="help">Until legal approval is marked, the rules pages and the free-entry form show a “Draft pending legal review” notice. Payments stay in test mode regardless; switching to live payments is a separate code change.</p></fieldset>
      <fieldset><legend>Alerts for the team</legend>
        <label>Send a copy of every new entry to<input data-k="notify_emails" placeholder="name@example.com, another@example.com"></label>
        <p class="help">Each donation and each registered mail-in entry sends a short alert: number, amount, name, contact details, which share link it came through, and running totals. Separate several addresses with commas. Requires the email settings (Gmail app password) on the server.</p></fieldset>
      <fieldset><legend>Confirmation email</legend>
        <label>Subject<input data-k="email_subject"></label>
        <label style="margin-top:14px">Body<textarea data-k="email_body" style="min-height:180px"></textarea></label>
        <p class="help">Placeholders: {name} {number} {amount} {confirmation} {campaign} {org} {drawing_date}</p></fieldset>`;
    document.querySelectorAll('#campForm [data-k]').forEach(el => { const v = c[el.dataset.k]; if (el.type === 'checkbox') el.checked = !!v; else el.value = v ?? ''; });
    document.querySelectorAll('#campForm [data-t]').forEach(el => { const v = c.transport[el.dataset.t]; if (el.type === 'checkbox') el.checked = v !== false; else el.value = v ?? ''; });
    S.rest = c.restaurants.map(r => ({ ...r })); renderRest(); S.musicUrl = c.music_url || ''; renderMusic();
    $('legalBadge').hidden = c.legal_approval_status === 'approved';
    $('addR').onclick = () => { S.rest.push({ name: '', location: '', description: '', logo: '', photo: '' }); renderRest(); };
    const gross = () => { const n = +$('maxTickets').value || 0, u = Math.round((+$('unitPrice').value || 0) * 100); $('grossHelp').textContent = `Donations of ${cents(u)}–${cents(u * n)} · maximum gross proceeds ${cents(u * n * (n + 1) / 2)}`; };
    $('maxTickets').oninput = gross; $('unitPrice').oninput = gross; gross();
  }
  function renderMusic() {
    const u = S.musicUrl;
    $('musicField').innerHTML = `<span class="help" style="display:block;margin:0 0 6px">Uploaded audio file (MP3, M4A or OGG, up to 20 MB)</span>${u ? `<audio controls preload="none" src="${esc(u)}" style="width:100%;max-width:420px"></audio>` : '<span class="none">No file uploaded</span>'}
      <div style="margin-top:8px;display:flex;gap:8px"><label class="btn sm">Upload audio<input type="file" accept="audio/mpeg,audio/mp4,audio/ogg,.mp3,.m4a,.ogg" hidden data-audio></label>${u ? '<button type="button" class="btn sm" data-audio-clear>Remove</button>' : ''}</div>`;
  }
  function imgField(label, key, val) {
    return `<div class="imgfield" data-img="${key}"><span class="help" style="flex-basis:100%;margin:0">${label}</span>${val ? `<img src="${esc(val)}" alt="">` : '<span class="none">No image</span>'}
      <input type="hidden" value="${esc(val || '')}"><label class="btn sm">Upload<input type="file" accept="image/png,image/jpeg,image/webp" hidden></label>${val ? '<button type="button" class="btn sm" data-clear>Remove</button>' : ''}</div>`;
  }
  function renderRest() {
    $('rlist').innerHTML = S.rest.map((r, i) => `<div class="ritem" data-i="${i}">
      <div class="ritem-h"><strong>${String(i + 1).padStart(2, '0')} · ${esc(r.name) || 'New restaurant'}</strong><span><button type="button" class="btn sm" data-mv="-1">↑</button> <button type="button" class="btn sm" data-mv="1">↓</button> <button type="button" class="btn sm danger" data-rm>Remove</button></span></div>
      <div class="fgrid"><label>Name<input data-r="name" value="${esc(r.name)}"></label><label>Location<input data-r="location" value="${esc(r.location)}"></label></div>
      <label>Description<textarea data-r="description">${esc(r.description)}</textarea></label>
      <div class="fgrid">${imgField('Official logo (with permission)', 'r:logo', r.logo)}${imgField('Photo (with permission)', 'r:photo', r.photo)}</div></div>`).join('');
  }
  $('campForm').addEventListener('input', (e) => { const it = e.target.closest('.ritem'); if (it && e.target.dataset.r) S.rest[it.dataset.i][e.target.dataset.r] = e.target.value; });
  $('campForm').addEventListener('click', (e) => {
    const it = e.target.closest('.ritem');
    if (it && e.target.closest('[data-rm]')) { if (confirm('Remove this restaurant?')) { S.rest.splice(+it.dataset.i, 1); renderRest(); } }
    const mv = e.target.closest('[data-mv]');
    if (it && mv) { const i = +it.dataset.i, j = i + +mv.dataset.mv; if (j >= 0 && j < S.rest.length) { [S.rest[i], S.rest[j]] = [S.rest[j], S.rest[i]]; renderRest(); } }
    if (e.target.closest('[data-audio-clear]')) { S.musicUrl = ''; renderMusic(); }
    const clr = e.target.closest('[data-clear]');
    if (clr) setImg(clr.closest('[data-img]'), '');
  });
  $('campForm').addEventListener('change', async (e) => {
    if (e.target.type !== 'file' || !e.target.files[0]) return;
    if (e.target.hasAttribute('data-audio')) {
      const fd = new FormData(); fd.append('file', e.target.files[0]);
      try { toast('Uploading…'); const r = await api('/api/admin/upload', { method: 'POST', body: fd }); S.musicUrl = r.url; renderMusic(); toast('Audio uploaded. Choose “An uploaded audio file” and save.'); } catch (err) { toast(err.message, true); }
      return;
    }
    const box = e.target.closest('[data-img]'), fd = new FormData(); fd.append('file', e.target.files[0]);
    try { const r = await api('/api/admin/upload', { method: 'POST', body: fd }); setImg(box, r.url); toast('Image uploaded. Save to apply.'); } catch (err) { toast(err.message, true); }
  });
  function setImg(box, url) {
    const key = box.dataset.img, it = box.closest('.ritem');
    if (it) { S.rest[it.dataset.i][key.slice(2)] = url; renderRest(); return; }
    const parent = box.parentElement, label = box.querySelector('.help').textContent;
    box.outerHTML = imgField(label, key, url); void parent;
  }
  $('saveCampaign').addEventListener('click', async () => {
    const body = {}, transport = {};
    document.querySelectorAll('#campForm [data-k]').forEach(el => { body[el.dataset.k] = el.type === 'checkbox' ? el.checked : el.value; });
    document.querySelectorAll('#campForm [data-t]').forEach(el => { transport[el.dataset.t] = el.type === 'checkbox' ? el.checked : el.value; });
    const imgVal = (k) => { const b = document.querySelector(`#campForm [data-img="${k}"] input[type=hidden]`); return b ? b.value : ''; };
    body.prize_image = imgVal('prize_image'); body.reveal_image = imgVal('reveal_image'); body.hero_images = [0,1,2,3,4,5,6,7].map(i => imgVal(`hs:${i}`)).filter(Boolean); body.prize_items = $('prizeItemsF').value.split('\n'); transport.logo = imgVal('t:logo'); transport.image = imgVal('t:image');
    body.transport = transport; body.restaurants = S.rest; body.music_url = S.musicUrl || ''; body.winners = parseInt(body.winners, 10) || 1;
    body.unit_price_cents = Math.round(parseFloat($('unitPrice').value) * 100);
    for (const k of ['min_age', 'entries_per_person', 'claim_days', 'referral_threshold', 'progress_min']) { body[k] = parseInt(body[k], 10); if (Number.isNaN(body[k])) delete body[k]; }
    try {
      const newMax = parseInt($('maxTickets').value, 10);
      if (newMax !== S.maxLoaded) await api('/api/admin/settings', { method: 'POST', body: { max_tickets: newMax } });
      await api('/api/admin/campaign', { method: 'PUT', body }); S.data = null; S.campaign = null;
      toast('Campaign saved'); loadCampaign();
    } catch (err) { toast(err.message, true); }
  });

  /* ambassadors (share-and-earn links) */
  const REWARD = { none: '—', earned: 'Reward due', fulfilled: 'Reward given' };
  async function loadAmb() {
    const d = await api('/api/admin/ambassadors'); S.amb = d; loadShare();
    $('ambIntro').textContent = `${d.ambassadors.length} personal links. Counts are paid entries made by other people through each link (a person’s own entries don’t count). Donors get a link automatically after they spin; you can also create one here for a volunteer.${d.reward ? ` Public reward: ${d.reward} at ${d.threshold} entries.` : ' No reward is shown publicly.'}`;
    renderAmb();
  }
  function renderAmb() {
    if (!S.amb) return;
    const q = $('ambQ').value.trim().toLowerCase(), th = S.amb.threshold;
    const rows = S.amb.ambassadors.filter(a => !q || `${a.name} ${a.email} ${a.code}`.toLowerCase().includes(q));
    $('ambRows').innerHTML = rows.map(a => {
      const st = a.reward_status === 'none' && a.earned ? 'earned' : a.reward_status;
      return `<tr><td>${esc(a.name)}<span class="sub">${esc(a.email)}${a.phone ? ' · ' + esc(a.phone) : ''}</span></td>
      <td class="mono"><a href="${esc(a.link)}" target="_blank" rel="noopener">${esc(a.code)}</a> <button class="btn sm" data-copy="${esc(a.link)}">Copy</button></td>
      <td class="num"><b>${a.sold}</b>${S.amb.reward ? ` / ${th}${a.earned ? ' <span class="chip paid">reached</span>' : ''}` : ''}</td>
      <td class="num">${money(a.raised)}</td>
      <td><select data-reward="${a.id}">${Object.entries(REWARD).map(([k, v]) => `<option value="${k}" ${k === st ? 'selected' : ''}>${v}</option>`).join('')}</select></td>
      <td class="num">${esc((a.created || '').slice(0, 10))}<span class="sub">${esc(a.source)}</span></td></tr>`;
    }).join('') || '<tr><td colspan="6" class="muted">No links yet.</td></tr>';
  }
  $('ambQ').addEventListener('input', renderAmb);
  $('ambRefresh').addEventListener('click', () => loadAmb().then(() => toast('Updated')));
  $('ambRows').addEventListener('click', async (e) => { const b = e.target.closest('[data-copy]'); if (b) { try { await navigator.clipboard.writeText(b.dataset.copy); toast('Link copied'); } catch { prompt('Copy this link:', b.dataset.copy); } } });
  $('ambRows').addEventListener('change', async (e) => {
    const sel = e.target.closest('[data-reward]'); if (!sel) return;
    try { await api(`/api/admin/ambassadors/${sel.dataset.reward}/reward`, { method: 'POST', body: { status: sel.value } }); toast('Reward status saved'); loadAmb(); } catch (err) { toast(err.message, true); }
  });
  async function loadShare() {
    try { const d = await api('/api/admin/share-emails');
      $('shareCount').textContent = d.running ? `Sending… ${d.sent + d.failed} of ${d.total} done${d.failed ? ` (${d.failed} failed, see Emails)` : ''}.`
        : (d.total ? `Last run: ${d.sent} sent${d.failed ? `, ${d.failed} failed (see Emails)` : ''}. ` : '') + `${d.pending} ${d.pending === 1 ? 'person hasn’t' : 'people haven’t'} been sent their link yet.`;
      $('shareGo').disabled = d.running || !d.pending || !d.smtp;
      if (!d.smtp) $('shareCount').textContent += ' Email sending is not set up.';
      if (d.running) setTimeout(loadShare, 3000); else if (S.shareWasRunning) loadAmb();
      S.shareWasRunning = d.running;
    } catch (err) { $('shareCount').textContent = err.message; }
  }
  $('shareGo').addEventListener('click', async () => {
    if (!confirm('Email a personal share link to everyone who hasn’t received one yet?')) return;
    try { const r = await api('/api/admin/share-emails', { method: 'POST', body: { confirm: 'SEND' } }); toast(`Sending to ${r.total}…`); loadShare(); }
    catch (err) { toast(err.message, true); }
  });
  $('ambAdd').addEventListener('click', async () => {
    try { const r = await api('/api/admin/ambassadors', { method: 'POST', body: { name: $('ambName').value, email: $('ambEmail').value, phone: $('ambPhone').value } });
      toast(r.created ? 'Link created' : 'This email already has a link'); $('ambName').value = $('ambEmail').value = $('ambPhone').value = ''; loadAmb(); }
    catch (err) { toast(err.message, true); }
  });

  /* launch checklist */
  async function loadChecklist() {
    const d = await api('/api/admin/checklist');
    $('ckSummary').textContent = `${d.done} of ${d.total} complete`;
    $('ckPay').textContent = { stripe_live: 'Payments: LIVE', stripe_test: 'Payments: Stripe test mode' }[d.payments] || 'Payments: simulated (test)';
    $('ctCard').hidden = !(d.payments === 'stripe_live' && d.test_entries > 0);
    $('ctCount').textContent = `${d.test_entries || 0} test entries waiting to be cleared.`;
    let html = '', group = '';
    for (const i of d.items) {
      if (i.group !== group) { group = i.group; html += `<p class="ck-group">${esc(group)}</p>`; }
      html += `<div class="ck${i.done ? ' done' : ''}" data-ck="${esc(i.id)}">` +
        (i.auto ? `<span class="mark ${i.done ? 'ok' : 'no'}">${i.done ? '✓' : ''}</span>` : `<input type="checkbox" ${i.done ? 'checked' : ''} aria-label="Done">`) +
        `<span class="lbl">${esc(i.label)}${i.auto ? '<span class="tag">auto</span>' : ''}</span>` +
        (i.hint ? `<span class="meta">${esc(i.hint)}</span>` : '') +
        (i.auto ? '' : `<input class="note" placeholder="Note (who, when, reference)" value="${esc(i.note || '')}">${i.updated ? `<span class="meta">Updated ${esc(i.updated)} UTC by ${esc(i.by || '')}</span>` : ''}`) +
        '</div>';
    }
    $('ckList').innerHTML = html;
  }
  async function saveCk(row) {
    try { await api(`/api/admin/checklist/${row.dataset.ck}`, { method: 'POST', body: { done: row.querySelector('input[type=checkbox]').checked, note: row.querySelector('.note').value } }); toast('Checklist updated'); loadChecklist(); }
    catch (err) { toast(err.message, true); }
  }
  $('ckList').addEventListener('change', (e) => { const row = e.target.closest('[data-ck]'); if (row && (e.target.type === 'checkbox' || e.target.classList.contains('note'))) saveCk(row); });
  $('ctGo').addEventListener('click', async () => {
    if (prompt('This archives the database, then removes every test entry, payment and email.\n\nType CLEAR TEST ENTRIES to continue:') !== 'CLEAR TEST ENTRIES') return;
    try { const r = await api('/api/admin/clear-test-entries', { method: 'POST', body: { confirm: 'CLEAR TEST ENTRIES' } }); toast(`${r.cleared} test entries cleared. Entries are open.`); loadChecklist(); }
    catch (err) { toast(err.message, true); }
  });
  $('ncGo').addEventListener('click', async () => {
    const number = $('ncNumber').value.trim();
    if (!number) { toast('Enter the new campaign number.', true); return; }
    if (prompt(`This archives and clears all entries, payments, emails and the drawing for the current campaign.\n\nType START NEW CAMPAIGN to continue:`) !== 'START NEW CAMPAIGN') return;
    const body = { confirm: 'START NEW CAMPAIGN', campaign_number: number };
    try { const r = await api('/api/admin/new-campaign', { method: 'POST', body }); toast(`New campaign started. Archived as ${r.archived}`); S.data = null; S.campaign = null; loadChecklist(); }
    catch (err) {
      if (/no drawing yet/.test(err.message) && confirm('This campaign has entries but no drawing yet. Archive it and start the new campaign anyway?')) {
        try { const r = await api('/api/admin/new-campaign', { method: 'POST', body: { ...body, without_drawing: true } }); toast(`New campaign started. Archived as ${r.archived}`); loadChecklist(); } catch (e2) { toast(e2.message, true); }
      } else toast(err.message, true);
    }
  });

  /* activity */
  async function loadActivity() { S.activity = (await api('/api/admin/activity')).activity; renderAct(); }
  function renderAct() {
    const q = $('aq').value.trim().toLowerCase();
    const rows = S.activity.filter(a => !q || `${a.actor} ${a.action} ${a.detail}`.toLowerCase().includes(q));
    $('actRows').innerHTML = rows.map(a => `<tr><td class="num">${esc(a.created)}</td><td>${esc(a.actor)}</td><td>${esc(a.action.replace(/_/g, ' '))}</td><td class="mono">${esc(a.detail)}</td></tr>`).join('') || '<tr><td colspan="4" class="muted">No activity.</td></tr>';
  }
  $('aq').addEventListener('input', renderAct);

  boot().catch(showLogin);
})();
