// Renders /rules, /free-entry, /privacy, /terms, /contact and /winners from GET /api/legal.
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // "[[Label]]" marks a value the organization has not supplied yet.
  const fmt = (s) => esc(s).replace(/\[\[(.+?)\]\]/g, '<mark class="ph">$1</mark>')
    .replace(/(Official Rules|Free Entry Instructions|Privacy Policy)(?![^<]*<\/mark>)/g, (m) => {
      const href = { 'Official Rules': '/rules', 'Free Entry Instructions': '/free-entry', 'Privacy Policy': '/privacy' }[m];
      return location.pathname === href ? m : `<a href="${href}">${m}</a>`;
    });
  const ORDER = ['rules', 'free-entry', 'privacy', 'terms', 'contact', 'winners'];
  const slug = location.pathname.replace(/^\/|\/$/g, '') || 'rules';

  fetch('/api/legal').then(r => r.json()).then(d => {
    const doc = d.docs[slug] || d.docs.rules;
    document.title = `${doc.title} · ${d.title}`;
    $('campTitle').textContent = d.title;
    $('docTitle').textContent = doc.title;
    $('tabs').innerHTML = ORDER.filter(k => d.docs[k]).map(k => [k, d.docs[k]]).map(([k, v]) => `<a href="/${k}"${k === slug ? ' aria-current="page"' : ''}>${esc(v.title)}</a>`).join('');
    $('draft').hidden = !d.draft;
    $('meta').innerHTML = `${esc(d.title)} · Campaign ${fmt(d.campaign_number)}${d.rules_version ? ` · Rules version ${esc(d.rules_version)}` : ''}`;
    if (d.npn && (slug === 'rules' || slug === 'free-entry')) { $('npn').hidden = false; $('npn').innerHTML = `<strong>${esc(d.npn.split('.')[0])}.</strong>${esc(d.npn.slice(d.npn.indexOf('.') + 1))}`; }
    $('formLink').hidden = !(slug === 'free-entry' && d.free_entry_enabled);
    $('body').innerHTML = doc.sections.map(s => `<section>${s.h ? `<h2>${esc(s.h)}</h2>` : ''}${s.p.map(p => `<p>${fmt(p)}</p>`).join('')}</section>`).join('');
    const o = d.org;
    $('foot').innerHTML = `<p><strong>${fmt(o.org)}</strong> · ${fmt(o.status)} · EIN ${fmt(o.ein)}</p><p>${fmt(o.addr)} · ${fmt(o.email)} · ${fmt(o.phone)}</p>
      ${d.npn ? `<p class="small">${esc(d.npn)}</p>` : ''}<nav>${ORDER.filter(k => d.docs[k]).map(k => [k, d.docs[k]]).map(([k, v]) => `<a href="/${k}">${esc(v.title)}</a>`).join('')}</nav>`;
  }).catch(() => { $('body').innerHTML = '<p>Could not load this page. Please refresh.</p>'; });
})();
