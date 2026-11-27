// K'hal Yismach Moshe · Spin to Win — public experience.
// API: GET /api/campaign, GET /api/status, POST /api/spin {name,email,phone,consent,consent_rules,marketing,request_id}.

const $ = (id) => document.getElementById(id);
const $$ = (sel) => document.querySelectorAll(sel);
const gsap = window.gsap || null;
if (gsap) gsap.ticker.lagSmoothing(0); // keep UI animations on real time even if WebGL frames are slow
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const LETTERS = ['נ', 'ג', 'ה', 'ש'];
const state = { max: 360, unit: 100, remaining: null, open: true, closedMsg: '', busy: false, requestId: newId(), campaign: null, processor: 'simulated' };

const PKGS = { chai: { n: 1, total: 180, label: 'Chai ticket · $180' }, pair: { n: 2, total: 300, label: '2 entries · $300' } };
const pkgNow = () => { const r = document.querySelector('input[name="pkg"]:checked'); return r && PKGS[r.value] ? r.value : 'spin'; };
const spinTexts = {};
function applyPkg() {
  const p = pkgNow(), f = PKGS[p];
  for (const id of ['authLede', 'authBox', 'authText']) if (!(id in spinTexts)) spinTexts[id] = $(id).innerHTML;
  const go = $('go').querySelector('span'); if (!('go' in spinTexts)) spinTexts.go = go.textContent;
  if (!f) { for (const id of ['authLede', 'authBox', 'authText']) $(id).innerHTML = spinTexts[id]; go.textContent = spinTexts.go; return; }
  const what = f.n === 1 ? 'one entry' : `${f.n} entries`;
  $('authLede').innerHTML = `Your card is charged <b>$${f.total}</b> for ${what}. The dreidel still spins to give you ${f.n === 1 ? 'a random number' : 'two random numbers'}.`;
  $('authBox').innerHTML = `<div><span>Your choice</span><strong>${f.label}</strong></div><div><span>You’re charged</span><strong>$${f.total}</strong></div>`;
  $('authText').textContent = `I authorize a charge of $${f.total} for ${what}.`;
  go.textContent = `Pay $${f.total} & spin`;
}
function newId() { return crypto.randomUUID ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join(''); }
const money = (cents) => '$' + (cents / 100).toLocaleString('en-US', { minimumFractionDigits: cents % 100 ? 2 : 0, maximumFractionDigits: 2 });
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ───────────── ambient gold dust ───────────── */
(function dust() {
  const c = $('dust'), g = c.getContext('2d');
  let w, h, parts = [];
  const spawn = (any) => ({ x: Math.random() * w, y: any ? Math.random() * h : h + 10, r: Math.random() * 1.4 + 0.3,
    vy: -(Math.random() * 0.22 + 0.05), vx: (Math.random() - 0.5) * 0.1, tw: Math.random() * 6.3, ts: Math.random() * 0.02 + 0.005 });
  function resize() {
    const dpr = Math.min(devicePixelRatio || 1, 2); w = innerWidth; h = innerHeight;
    c.width = w * dpr; c.height = h * dpr; g.setTransform(dpr, 0, 0, dpr, 0, 0);
    parts = Array.from({ length: w < 700 ? 34 : 70 }, () => spawn(true));
  }
  function frame() {
    g.clearRect(0, 0, w, h);
    for (const p of parts) {
      if (!reduced) { p.x += p.vx; p.y += p.vy; p.tw += p.ts; }
      if (p.y < -10) Object.assign(p, spawn(false));
      const a = 0.18 + 0.5 * (0.5 + 0.5 * Math.sin(p.tw));
      const grd = g.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 4);
      grd.addColorStop(0, `rgba(255,228,170,${a})`); grd.addColorStop(1, 'rgba(255,200,110,0)');
      g.fillStyle = grd; g.beginPath(); g.arc(p.x, p.y, p.r * 4, 0, 6.283); g.fill();
    }
    if (!reduced) requestAnimationFrame(frame);
  }
  addEventListener('resize', resize); resize(); frame();
})();

/* ───────────── background music (starts only from the speaker button) ─────────────
   YouTube: YouTube's own embedded player, kept visible (as YouTube requires) in a small dock.
   Upload: an audio file the organization has the rights to, looped quietly. */
const music = (() => {
  // The YouTube player is created (paused) shortly after the page loads, so that a tap on the speaker button can start it
  // with sound immediately: browsers only allow sound inside the tap itself, not seconds later after a player loads.
  let cfg = { source: 'off' }, audio = null, player = null, ready = false, wanted = false, apiLoading = false, preloadTimer = null;
  const dock = () => $('musicDock');
  const show = (v) => { dock().classList.toggle('on', v); dock().setAttribute('aria-hidden', v ? 'false' : 'true'); };
  function playYT() { if (!ready) return; try { player.unMute(); player.setVolume(40); player.playVideo(); } catch {} }
  function createPlayer() {
    if (player || !cfg.youtube || !window.YT || !YT.Player) return;
    const el = document.createElement('div'); $('musicPlayer').replaceChildren(el);
    player = new YT.Player(el, {
      width: 200, height: 200, videoId: cfg.youtube,
      playerVars: { loop: 1, playlist: cfg.youtube, playsinline: 1, rel: 0, controls: 1, origin: location.origin },
      events: { onReady: () => { ready = true; if (wanted) playYT(); } },
    });
  }
  function loadYT() {
    if (window.YT && YT.Player) return createPlayer();
    if (apiLoading) return; apiLoading = true;
    const prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => { if (prev) prev(); createPlayer(); };
    const sc = document.createElement('script'); sc.src = 'https://www.youtube.com/iframe_api'; document.head.appendChild(sc);
  }
  function start() {
    wanted = true;
    if (cfg.source === 'youtube' && cfg.youtube) {
      $('musicTitle').textContent = cfg.title || 'Now playing'; show(true);
      if (ready) playYT(); else loadYT();  // if it was still loading, it starts when ready (or tap ▶ in the player)
    } else if (cfg.source === 'upload' && cfg.url) {
      if (!audio) { audio = new Audio(cfg.url); audio.loop = true; audio.volume = 0.4; }
      audio.play().catch(() => {});
    }
  }
  function stop() {
    wanted = false;
    if (ready) { try { player.pauseVideo(); } catch {} }
    show(false);
    if (audio) audio.pause();
  }
  function configure(c) {
    const next = { source: c.music_source || 'off', youtube: c.music_youtube || '', title: c.music_title || '', url: c.music_url || '', autostart: c.music_autostart !== false };
    if (JSON.stringify(next) === JSON.stringify(cfg)) return;
    stop(); clearTimeout(preloadTimer);
    if (player) { try { player.destroy(); } catch {} }
    player = null; ready = false; audio = null; cfg = next; $('musicPlayer').innerHTML = '';
    $('musicTitle').textContent = cfg.title || 'Now playing';
    if (cfg.source === 'youtube' && cfg.youtube) preloadTimer = setTimeout(loadYT, cfg.autostart ? 600 : 2500);
    if (cfg.source === 'upload' && cfg.url) { audio = new Audio(cfg.url); audio.loop = true; audio.volume = 0.4; audio.preload = 'auto'; }
  }
  return { start, stop, configure, get autostart() { return cfg.autostart && cfg.source !== 'off'; } };
})();

/* ───────────── sound (opt-in, off by default) ───────────── */
const sound = (() => {
  let ctx = null, on = false, lastTick = 0, userOff = false;
  const btns = [$('sound'), $('rSound')];  // nav button + the one on the result card
  const sync = () => btns.forEach(b => b.setAttribute('aria-pressed', on ? 'true' : 'false'));
  const ac = () => (ctx ||= new (window.AudioContext || window.webkitAudioContext)());
  function toggle(byUser) { on = !on; if (!on && byUser) userOff = true; sync(); if (on) { ac().resume(); tick(true); music.start(); } else music.stop(); }
  btns.forEach(b => b.addEventListener('click', (e) => { e.stopPropagation(); toggle(e.isTrusted); }));
  sync();
  const env = (n, t, a, d, p) => { n.gain.setValueAtTime(0.0001, t); n.gain.exponentialRampToValueAtTime(p, t + a); n.gain.exponentialRampToValueAtTime(0.0001, t + a + d); };
  function tick(force) {
    if (!on) return; const now = performance.now(); if (!force && now - lastTick < 45) return; lastTick = now;
    const c = ac(), t = c.currentTime, o = c.createOscillator(), gn = c.createGain();
    o.type = 'triangle'; o.frequency.setValueAtTime(2300, t); o.frequency.exponentialRampToValueAtTime(900, t + 0.03);
    env(gn, t, 0.002, 0.05, 0.06); o.connect(gn).connect(c.destination); o.start(t); o.stop(t + 0.07);
  }
  function whoosh() {
    if (!on) return; const c = ac(), t = c.currentTime, len = 1.4;
    const buf = c.createBuffer(1, c.sampleRate * len, c.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    const s = c.createBufferSource(), f = c.createBiquadFilter(), gn = c.createGain();
    s.buffer = buf; f.type = 'bandpass'; f.Q.value = 1.2; f.frequency.setValueAtTime(300, t); f.frequency.exponentialRampToValueAtTime(2600, t + len * 0.8);
    env(gn, t, 0.4, len - 0.4, 0.1); s.connect(f).connect(gn).connect(c.destination); s.start(t);
  }
  function chime() {
    if (!on) return; const c = ac(), t0 = c.currentTime;
    [523.25, 659.25, 783.99, 1046.5, 1318.5, 1568].forEach((fq, i) => {
      const t = t0 + i * 0.085;
      for (const [type, mul, peak] of [['sine', 1, 0.11], ['triangle', 2, 0.025]]) {
        const o = c.createOscillator(), gn = c.createGain(); o.type = type; o.frequency.value = fq * mul;
        env(gn, t, 0.01, 1.6, peak); o.connect(gn).connect(c.destination); o.start(t); o.stop(t + 1.8);
      }
    });
  }
  return { tick, whoosh, chime, off() { userOff = true; if (on) toggle(true); }, on() { if (!on) toggle(false); }, get userOff() { return userOff; } };
})();
// "autostart": the music starts when the dreidel starts spinning (see runSpin); the Music button works any time.
$('musicClose').addEventListener('click', () => sound.off());

function celebrate() {
  // fine gold dust drifting down: celebratory without being festive
  const fire = window.confetti; if (!fire || reduced) return;
  const dust = { colors: ['#fff3d6', '#f3dca6', '#ecd29a', '#cfa95f', '#b38a3f'], shapes: ['circle'], scalar: 0.45, gravity: 0.22, decay: 0.955, drift: 0, ticks: 520, disableForReducedMotion: true, zIndex: 80 };
  fire({ ...dust, particleCount: 90, spread: 160, startVelocity: 16, origin: { x: 0.5, y: 0.18 } });
  setTimeout(() => { fire({ ...dust, particleCount: 40, angle: 70, spread: 50, startVelocity: 22, origin: { x: 0.1, y: 0.35 } }); fire({ ...dust, particleCount: 40, angle: 110, spread: 50, startVelocity: 22, origin: { x: 0.9, y: 0.35 } }); }, 260);
}

/* ───────────── 3D dreidel ───────────── */
async function createDreidel(el) {
  const THREE = await import('three');
  const { RoundedBoxGeometry } = await import('three/addons/geometries/RoundedBoxGeometry.js');
  try { await Promise.race([document.fonts.load('900 200px "Frank Ruhl Libre"', 'נגהש'), new Promise(r => setTimeout(r, 2500))]); } catch {}

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.1;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  el.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  const lookAt = new THREE.Vector3(0, 1.75, 0);

  // Studio environment: dark room with warm softboxes for rich gold reflections.
  const pmrem = new THREE.PMREMGenerator(renderer);
  {
    const s = new THREE.Scene();
    s.add(new THREE.Mesh(new THREE.BoxGeometry(30, 30, 30), new THREE.MeshBasicMaterial({ color: 0x050407, side: THREE.BackSide })));
    const panel = (w, h, hex, k, pos) => {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(hex).multiplyScalar(k), side: THREE.DoubleSide }));
      m.position.set(...pos); m.lookAt(0, 0, 0); s.add(m);
    };
    panel(10, 3, 0xfff1d6, 4, [0, 10, 2]); panel(3, 8, 0xffd9a0, 3, [-9, 2, 5]); panel(3, 8, 0xfff4e0, 2.2, [9, 3, -1]);
    panel(14, 1.2, 0xffbf5e, 1.6, [0, -5, 7]); panel(2.5, 9, 0xffd8a0, 0.5, [0, 2, -10]); panel(9, 5, 0xfff0d8, 2.4, [0, 3, 12]); panel(4, 4, 0xffd9a8, 1.6, [-6, 1, 9]); panel(6, 1.5, 0xffe2a8, 2.5, [4, 6, 8]);
    scene.environment = pmrem.fromScene(s, 0.02).texture;
  }

  scene.add(new THREE.HemisphereLight(0xfff0d8, 0x120c06, 0.35));
  const key = new THREE.SpotLight(0xfff0d0, 260, 30, Math.PI / 7, 0.7, 1.6);
  key.position.set(2.2, 10, 4.5); key.target.position.set(0, 0.8, 0);
  key.castShadow = true; key.shadow.mapSize.set(2048, 2048); key.shadow.bias = -0.0004; key.shadow.radius = 6; key.shadow.camera.near = 4; key.shadow.camera.far = 20;
  scene.add(key, key.target);
  const rim = new THREE.DirectionalLight(0xffc878, 2.2); rim.position.set(-4, 5, -6); scene.add(rim);
  const under = new THREE.PointLight(0xffb44d, 6, 7, 1.6); under.position.set(0, 0.35, 1.4); scene.add(under);

  // brushed gold: anisotropic highlights stretched across the faces, like satin-finished jewelry
  const gold = new THREE.MeshPhysicalMaterial({ color: 0xe4b55a, metalness: 1, roughness: 0.3, anisotropy: 0.7, anisotropyRotation: Math.PI / 2, clearcoat: 0.35, clearcoatRoughness: 0.22, envMapIntensity: 1.4 });
  const goldFlat = gold.clone(); goldFlat.flatShading = true;

  function faceMaterial(letter) {
    const S = 1024;
    const mk = () => { const c = document.createElement('canvas'); c.width = c.height = S; return [c, c.getContext('2d')]; };
    const [col, g] = mk(), [rgh, r] = mk(), [bmp, b] = mk();
    const grad = g.createLinearGradient(0, 0, S, S);
    grad.addColorStop(0, '#fff0c4'); grad.addColorStop(0.35, '#e8bb62'); grad.addColorStop(0.6, '#c8953c'); grad.addColorStop(1, '#f4d48c');
    g.fillStyle = grad; g.fillRect(0, 0, S, S);
    for (let i = 0; i < 900; i++) { g.fillStyle = `rgba(255,250,235,${Math.random() * 0.05})`; g.fillRect(0, Math.random() * S, S, Math.random() * 2); }
    r.fillStyle = '#4c4c4c'; r.fillRect(0, 0, S, S); b.fillStyle = '#ffffff'; b.fillRect(0, 0, S, S);
    const frame = (ctx, inset, lw, style) => { ctx.strokeStyle = style; ctx.lineWidth = lw; ctx.beginPath(); ctx.roundRect(inset, inset, S - inset * 2, S - inset * 2, 40); ctx.stroke(); };
    frame(g, 74, 12, 'rgba(92,60,14,.55)'); frame(g, 92, 3, 'rgba(255,244,210,.7)'); frame(b, 74, 12, '#7a7a7a'); frame(r, 74, 12, '#707070');
    const font = '900 620px "Frank Ruhl Libre", "David", "Times New Roman", serif';
    for (const ctx of [g, r, b]) { ctx.font = font; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; }
    g.fillStyle = 'rgba(255,246,220,.7)'; g.fillText(letter, S / 2 + 7, S / 2 + 46);
    g.fillStyle = '#4a2e08'; g.fillText(letter, S / 2, S / 2 + 38);
    r.fillStyle = '#9a9a9a'; r.fillText(letter, S / 2, S / 2 + 38);
    b.fillStyle = '#000'; b.fillText(letter, S / 2, S / 2 + 38);
    const tex = (c, srgb) => { const t = new THREE.CanvasTexture(c); if (srgb) t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = renderer.capabilities.getMaxAnisotropy(); return t; };
    return new THREE.MeshPhysicalMaterial({ map: tex(col, true), roughnessMap: tex(rgh), bumpMap: tex(bmp), bumpScale: 4, metalness: 1, roughness: 1, clearcoat: 0.5, clearcoatRoughness: 0.15, envMapIntensity: 1.35 });
  }

  // tilt group (wobble/precession) → spin group (rotation about its own axis)
  const tilt = new THREE.Group(), spin = new THREE.Group(); tilt.add(spin); scene.add(tilt);
  const B = 1.6, CONE_H = 1.15;
  // BoxGeometry face order: +x, -x, +y, -y, +z, -z.  Face k faces the camera when spin.rotation.y = k·π/2.
  const body = new THREE.Mesh(new RoundedBoxGeometry(B, B, B, 6, 0.13),
    [faceMaterial(LETTERS[3]), faceMaterial(LETTERS[1]), gold, gold, faceMaterial(LETTERS[0]), faceMaterial(LETTERS[2])]);
  body.position.y = CONE_H + B / 2;
  const cone = new THREE.Mesh(new THREE.ConeGeometry((B / 2) * Math.SQRT2 - 0.06, CONE_H, 4, 1), goldFlat);
  cone.rotation.set(Math.PI, Math.PI / 4, 0); cone.position.y = CONE_H / 2;
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.05, 16, 12), gold); tip.position.y = 0.035;
  const collar = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.34, 0.09, 48), gold); collar.position.y = CONE_H + B + 0.045;
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.16, 0.92, 48), gold); stem.position.y = CONE_H + B + 0.55;
  const knob = new THREE.Mesh(new THREE.SphereGeometry(0.17, 32, 24), gold); knob.position.y = CONE_H + B + 1.01;
  for (const m of [body, cone, tip, collar, stem, knob]) { m.castShadow = true; spin.add(m); }

  // illuminated platform
  const plat = new THREE.Group(); scene.add(plat);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(2.7, 2.85, 0.24, 128),
    new THREE.MeshPhysicalMaterial({ color: 0x120f0b, metalness: 0.8, roughness: 0.32, clearcoat: 0.8, clearcoatRoughness: 0.1, envMapIntensity: 0.7 }));
  base.position.y = -0.12; base.receiveShadow = true;
  const top = new THREE.Mesh(new THREE.CircleGeometry(2.45, 128), new THREE.MeshPhysicalMaterial({ color: 0x15110c, metalness: 0.2, roughness: 0.55, clearcoat: 0.25, envMapIntensity: 0.35 }));
  top.rotation.x = -Math.PI / 2; top.position.y = 0.002; top.receiveShadow = true;
  const ringMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(0xffd27a).multiplyScalar(1.6), toneMapped: false });
  const ring1 = new THREE.Mesh(new THREE.TorusGeometry(2.5, 0.022, 16, 220), ringMat); ring1.rotation.x = Math.PI / 2; ring1.position.y = 0.01;
  const ring2 = new THREE.Mesh(new THREE.TorusGeometry(2.83, 0.012, 12, 220), ringMat); ring2.rotation.x = Math.PI / 2; ring2.position.y = -0.02;
  const glowTex = (() => {
    const c = document.createElement('canvas'); c.width = c.height = 256; const g = c.getContext('2d');
    const gr = g.createRadialGradient(128, 128, 0, 128, 128, 128);
    gr.addColorStop(0, 'rgba(255,210,120,.9)'); gr.addColorStop(0.35, 'rgba(255,180,80,.35)'); gr.addColorStop(1, 'rgba(255,170,60,0)');
    g.fillStyle = gr; g.fillRect(0, 0, 256, 256); const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  })();
  const halo = new THREE.Mesh(new THREE.PlaneGeometry(10, 10), new THREE.MeshBasicMaterial({ map: glowTex, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.55 }));
  halo.rotation.x = -Math.PI / 2; halo.position.y = -0.26;
  const pool = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 3.2), new THREE.MeshBasicMaterial({ map: glowTex, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.22 }));
  pool.rotation.x = -Math.PI / 2; pool.position.y = 0.006;
  plat.add(base, top, ring1, ring2, halo, pool);

  // Entry dial: the platform's front edge is a turning bezel with one tick per entry and a number every 10
  // (360 entries = one per degree). It stops with the assigned number under the gold pointer at the front.
  const BEZ_R = 2.88, BEZ_H = 0.42, BEZ_Y = -0.19;
  const dialCanvas = document.createElement('canvas'); dialCanvas.width = 4096; dialCanvas.height = 256;
  const dialTex = new THREE.CanvasTexture(dialCanvas); dialTex.colorSpace = THREE.SRGBColorSpace; dialTex.anisotropy = 8;
  dialTex.wrapS = THREE.RepeatWrapping;
  const bezel = new THREE.Mesh(new THREE.CylinderGeometry(BEZ_R, BEZ_R, BEZ_H, 360, 1, true),
    new THREE.MeshBasicMaterial({ map: dialTex, toneMapped: false }));
  bezel.position.y = BEZ_Y;
  const dialSpin = new THREE.Group(); dialSpin.add(bezel); plat.add(dialSpin);
  let dialCount = 0;
  function drawDial(n) {
    if (!n || n === dialCount) return; dialCount = n;
    const g = dialCanvas.getContext('2d'), W = 4096, H = 256;
    const bg = g.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, '#1c3a2c'); bg.addColorStop(0.14, '#0b241a'); bg.addColorStop(0.86, '#071a12'); bg.addColorStop(1, '#1c3a2c');  // deep emerald bezel
    g.fillStyle = bg; g.fillRect(0, 0, W, H);
    g.fillStyle = 'rgba(255,214,140,.85)'; g.fillRect(0, 6, W, 3); g.fillRect(0, H - 9, W, 3);
    const labelEvery = n <= 400 ? 10 : Math.ceil(n / 360) * 10;
    // texels are ~2.8x wider than tall on the bezel, so text is squeezed horizontally to look right
    const squeeze = (2 * Math.PI * BEZ_R / W) / (BEZ_H / H);
    for (let i = 1; i <= n; i++) {
      if (n > 720 && i % Math.ceil(n / 360)) continue;
      const x = ((i - 1) / n) * W, major = i % labelEvery === 0, mid = !major && i % 5 === 0;
      g.fillStyle = major ? 'rgba(255,226,160,.95)' : mid ? 'rgba(236,210,154,.7)' : 'rgba(236,210,154,.4)';
      const len = major ? 40 : mid ? 28 : 18, w = major ? 3 : 2;
      g.fillRect(x - w / 2, 12, w, len); g.fillRect(x - w / 2, H - 12 - len, w, len);
      if (major) {
        g.save(); g.translate(x, H / 2 + 4); g.scale(1 / squeeze, 1);
        g.font = '600 122px "Cormorant Garamond", Georgia, serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
        const grad = g.createLinearGradient(0, -50, 0, 50); grad.addColorStop(0, '#fff3d6'); grad.addColorStop(0.5, '#ecd29a'); grad.addColorStop(1, '#b98d45');
        g.fillStyle = grad; g.fillText(String(i), 0, 0); g.restore();
      }
    }
    dialTex.needsUpdate = true;
  }
  drawDial(360);
  document.fonts && document.fonts.ready.then(() => { const k = dialCount; dialCount = 0; drawDial(k); });
  // pointer: a glowing gold wedge above the bezel's front, and a hairline across it marking the exact entry
  const ptrShape = new THREE.Shape(); ptrShape.moveTo(-0.11, 0.2); ptrShape.lineTo(0.11, 0.2); ptrShape.lineTo(0, 0); ptrShape.closePath();
  const pointer = new THREE.Mesh(new THREE.ShapeGeometry(ptrShape), ringMat); pointer.position.set(0, 0.03, BEZ_R + 0.02);
  const hair = new THREE.Mesh(new THREE.PlaneGeometry(0.014, BEZ_H + 0.04), ringMat); hair.position.set(0, BEZ_Y, BEZ_R + 0.01);
  plat.add(pointer, hair);
  let dialAngle = 0, dialVel = -0.12, dialLanding = null;
  const dialTarget = (num) => ((-((num - 1) / dialCount) * Math.PI * 2) % TAU_D + TAU_D) % TAU_D;
  const TAU_D = Math.PI * 2;

  const N = innerWidth < 700 ? 90 : 170, pos = new Float32Array(N * 3), seed = new Float32Array(N);
  for (let i = 0; i < N; i++) { const a = Math.random() * 6.283, rr = 1.6 + Math.random() * 3.4; pos.set([Math.cos(a) * rr, Math.random() * 5, Math.sin(a) * rr], i * 3); seed[i] = Math.random(); }
  const sg = new THREE.BufferGeometry(); sg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const sparkles = new THREE.Points(sg, new THREE.PointsMaterial({ size: 0.05, map: glowTex, color: 0xffe3a6, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  scene.add(sparkles);

  let baseDist = 10;
  function resize() {
    const w = el.clientWidth, h = el.clientHeight; if (!w || !h) return;
    renderer.setSize(w, h, false); camera.aspect = w / h;
    const vfov = THREE.MathUtils.degToRad(camera.fov), hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
    baseDist = Math.max(4.5 / Math.tan(vfov / 2), 3.3 / Math.tan(hfov / 2));
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(el); resize();

  const TAU = Math.PI * 2, QUARTER = Math.PI / 2, FACE_OFFSET = -0.38, MAX_V = 27;
  let mode = 'idle', angle = 0.6, vel = 0.45, hover = 0.32, wob = 0.05, prec = 0, zoom = 1, glow = 0, lastQuarter = 0;
  let landing = null, settleT = 0, onLanded = null, visible = true;
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(el);

  const clock = new THREE.Clock();
  (function loop() {
    requestAnimationFrame(loop);
    const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
    if (!visible && mode === 'idle') return;
    let tHover = 0.32, tWob = 0.05, precRate = 0.9, tZoom = 1;
    if (mode === 'idle') dialVel += ((reduced ? -0.03 : -0.12) - dialVel) * Math.min(1, dt * 1.5);
    else if (mode === 'rev') dialVel += (-MAX_V * 0.22 - dialVel) * Math.min(1, dt * 2.2);
    if (mode === 'land' && dialLanding) {
      const pd = Math.min(1, (performance.now() - dialLanding.start) / dialLanding.dur), ed = 1 - Math.pow(1 - pd, 3);
      dialAngle = dialLanding.from + (dialLanding.to - dialLanding.from) * ed;
    } else if (mode === 'idle' || mode === 'rev') dialAngle += dialVel * dt;
    dialSpin.rotation.y = dialAngle;
    if (mode === 'idle' || mode === 'revealed') {
      vel += ((reduced ? 0.15 : 0.45) - vel) * Math.min(1, dt * 1.5); angle += vel * dt;
      if (mode === 'revealed') { tHover = 0; tWob = 0.015; tZoom = 0.9; vel = 0; }
    } else if (mode === 'rev') {
      vel += (MAX_V - vel) * Math.min(1, dt * 2.2); angle += vel * dt; tHover = 0; tWob = 0.025; precRate = 9; tZoom = 0.88;
    } else if (mode === 'land') {
      const p = Math.min(1, (performance.now() - landing.start) / landing.dur), e = 1 - Math.pow(1 - p, 3), prev = angle;
      angle = landing.from + (landing.to - landing.from) * e; vel = (angle - prev) / Math.max(dt, 1e-3);
      const slow = 1 - Math.min(1, vel / MAX_V);
      tHover = 0; tWob = 0.025 + 0.17 * slow * slow * (1 - p * p); precRate = 2 + vel * 0.35; tZoom = 0.88;
      if (p >= 1) { mode = 'settle'; settleT = 0; vel = 0; }
    } else if (mode === 'settle') {
      settleT += dt; tHover = 0; tZoom = 0.86; tWob = 0.12 * Math.exp(-settleT * 3.2) * Math.abs(Math.cos(settleT * 9)); precRate = 4;
      if (settleT > 0.9) { mode = 'revealed'; glow = 1; onLanded && onLanded(); onLanded = null; }
    }
    const q = Math.floor(angle / QUARTER);
    if (q !== lastQuarter) { lastQuarter = q; if (mode === 'land' && vel < 16) sound.tick(); }
    hover += (tHover - hover) * Math.min(1, dt * 3); wob += (tWob - wob) * Math.min(1, dt * 4);
    prec += precRate * dt; zoom += (tZoom - zoom) * Math.min(1, dt * 1.6); glow = Math.max(0, glow - dt * 0.6);
    spin.rotation.y = angle;
    tilt.position.y = hover + (mode === 'idle' && !reduced ? Math.sin(t * 1.3) * 0.06 : 0);
    tilt.rotation.x = wob * Math.cos(prec); tilt.rotation.z = wob * Math.sin(prec);
    ringMat.color.setRGB(1.6 + glow * 2.4, 1.29 + glow * 1.6, 0.75 + glow * 0.6);
    halo.material.opacity = 0.5 + glow * 0.5 + (mode === 'rev' || mode === 'land' ? 0.12 : 0);
    under.intensity = 6 + glow * 30;
    const sp = sg.attributes.position;
    if (!reduced) { for (let i = 0; i < N; i++) { let y = sp.getY(i) + dt * (0.12 + seed[i] * 0.25) * (mode === 'rev' ? 3 : 1); if (y > 5.2) y = 0; sp.setY(i, y); } sp.needsUpdate = true; }
    sparkles.rotation.y += dt * (mode === 'rev' ? 0.6 : 0.05);
    const d = baseDist * zoom;
    camera.position.set(Math.sin(t * 0.15) * 0.4, 2.0 + 1.1 * zoom, d); camera.lookAt(lookAt);
    renderer.render(scene, camera);
  })();

  return {
    rev() { mode = 'rev'; sound.whoosh(); },
    land(number) {
      return new Promise((resolve) => {
        const k = number % 4, v0 = Math.max(vel, 8);
        const desired = ((k * QUARTER + FACE_OFFSET) % TAU + TAU) % TAU;
        let to = angle + v0 * (reduced ? 0.6 : 4.4) / 3;
        to += ((desired - (to % TAU)) % TAU + TAU) % TAU;
        landing = { from: angle, to, start: performance.now(), dur: (3 * (to - angle) / v0) * 1000 };
        // dial: keep turning the same way, ease out over the same time, and stop with this number at the pointer
        const want = dialTarget(number), raw = Math.abs(dialVel) * (landing.dur / 1000) / 3;
        const cur = ((dialAngle % TAU_D) + TAU_D) % TAU_D, end = cur - raw;
        const extra = (((end - want) % TAU_D) + TAU_D) % TAU_D;
        dialLanding = { from: dialAngle, to: dialAngle - raw - extra, start: landing.start, dur: landing.dur };
        lastQuarter = Math.floor(angle / QUARTER); onLanded = resolve; mode = 'land';
      });
    },
    abort() { mode = 'idle'; dialLanding = null; }, idle() { mode = 'idle'; dialLanding = null; dialVel = -0.12; },
    setCount(n) { drawDial(n); },
  };
}

function createFallback() {
  const img = $('fallback').querySelector('img'); $('fallback').hidden = false;
  return {
    rev() { img.style.transition = 'transform 1.5s linear'; img.style.transform = 'rotate(1440deg)'; },
    land() { return new Promise(r => { img.style.transition = 'transform 2.4s cubic-bezier(.1,.7,.2,1)'; img.style.transform = 'rotate(2520deg)'; setTimeout(r, 2400); }); },
    abort() { img.style.transform = ''; }, idle() { img.style.transition = 'none'; img.style.transform = ''; }, setCount() {},
  };
}

/* Rolling number under the dreidel: races while it spins, slows as it lands, and stops on the assigned number. */
const counter = (() => {
  let timer = null, delay = 45, slowing = false;
  const el = () => $('spinCounter'), num = () => $('scNum');
  const roll = () => {
    num().textContent = 1 + Math.floor(Math.random() * (state.max || 360));
    if (slowing) delay = Math.min(delay * 1.13, 380);
    timer = setTimeout(roll, delay);
  };
  return {
    start() { clearTimeout(timer); delay = reduced ? 140 : 45; slowing = false; el().classList.remove('locked'); el().classList.add('on'); if (!reduced) roll(); else num().textContent = '…'; },
    slow() { slowing = true; },
    lock(n) { clearTimeout(timer); num().textContent = n; el().classList.add('locked'); },
    hide() { clearTimeout(timer); el().classList.remove('on', 'locked'); },
  };
})();

let dreidel = null;
const IDLE_HINT = 'Tap the dreidel to play';
const dreidelReady = createDreidel($('three')).catch((err) => { console.warn('3D unavailable, using fallback', err); return createFallback(); })
  .then(d => { dreidel = d; setHint(IDLE_HINT); return d; });
function setHint(text) { const h = $('spinHint'); h.textContent = text; if (gsap && text) gsap.fromTo(h, { opacity: 0, y: 6 }, { opacity: 0.85, y: 0, duration: 0.5 }); }

/* ───────────── campaign content ───────────── */
function setText(sel, v) { $$(sel).forEach(e => { if (v) e.textContent = v; }); }
let slideTimer = null, slideSig = '';
// list: [{img, logo?, name?}]. Restaurant slides also show that restaurant's logo and name: in the side list on wide
// screens (the highlight moves down the list as the photos change; click a name to jump to it), or a small label on phones.
function setSlides(list) {
  const sig = list.map(s => s.img + (s.logo || '') + (s.name || '')).join('|'); if (sig === slideSig) return; slideSig = sig;
  const box = $('heroSlides'), cap = $('heroCaption'), rail = $('heroRail'); clearInterval(slideTimer);
  const period = reduced ? 9000 : 5500;
  box.innerHTML = list.map(s => `<div class="slide" style="background-image:url('${esc(s.img)}')"></div>`).join('');
  document.querySelector('.hero').classList.toggle('has-slides', list.length > 0);
  const slides = [...box.children]; if (!slides.length) { cap.innerHTML = ''; rail.hidden = true; return; }
  const named = list.every(s => s.name);
  rail.hidden = !named;
  rail.style.setProperty('--period', period + 'ms');
  rail.innerHTML = named ? `<div class="rail-logo" id="railLogo"></div><ol>${list.map((s, n) => `<li><button type="button" data-slide="${n}"><span class="rn">${String(n + 1).padStart(2, '0')}</span><span class="rt">${esc(s.name)}</span><i class="rbar"></i></button></li>`).join('')}</ol>` : '';
  const items = [...rail.querySelectorAll('li')];
  const label = (s) => {
    cap.classList.remove('on');
    const lg = $('railLogo'); if (lg) lg.classList.remove('on');
    setTimeout(() => {
      cap.innerHTML = s.name ? `${s.logo ? `<img src="${esc(s.logo)}" alt="">` : ''}<span>${esc(s.name)}</span>` : '';
      if (s.name) cap.classList.add('on');
      if (lg) { lg.innerHTML = s.logo ? `<img src="${esc(s.logo)}" alt="">` : ''; if (s.logo) lg.classList.add('on'); }
    }, 450);
  };
  let i = -1;
  const show = (n) => {
    if (n === i) return;
    const prev = slides[i];
    if (prev) { prev.classList.add('out'); prev.classList.remove('on'); setTimeout(() => prev.classList.remove('out'), 2000); }
    i = n; slides[i].classList.add('on'); label(list[i]);
    items.forEach((li, k) => { li.classList.toggle('on', k === i); li.classList.toggle('past', k < i); });
    const bar = items[i] && items[i].querySelector('.rbar'); if (bar) { bar.style.animation = 'none'; void bar.offsetWidth; bar.style.animation = ''; }
  };
  const start = () => { clearInterval(slideTimer); if (slides.length > 1) slideTimer = setInterval(() => show((i + 1) % slides.length), period); };
  rail.onclick = (e) => { const b = e.target.closest('[data-slide]'); if (b) { show(+b.dataset.slide); start(); } };
  show(0); start();
  // preload the rest so each fade is clean
  list.slice(1).forEach(s => { const im = new Image(); im.src = s.img; if (s.logo) { const lg = new Image(); lg.src = s.logo; } });
}

function renderCampaign(c) {
  state.campaign = c;
  for (const k of ['presents', 'title', 'subtitle', 'intro', 'tagline', 'prize_title', 'prize_description', 'org_name']) setText(`[data-c="${k}"]`, c[k]);
  document.title = `${c.title} · ${c.org_name}`;
  // headline: one line per sentence, last line in gold italic
  const lines = (c.headline || '').split(/(?<=\.)\s+/).filter(Boolean);
  // keep each line's last two words together ("Fine Dining.") so lines break gracefully
  $('headline').innerHTML = lines.map(l => `<span class="l"><span>${esc(l).replace(/ (\S+)$/, '\u00a0$1')}</span></span>`).join('');
  const fromRestaurants = (c.restaurants || []).filter(r => r.photo).map(r => ({ img: r.photo, logo: r.logo, name: r.name }));
  const custom = (c.hero_images || []).map(u => ({ img: u }));
  setSlides(c.hero_source === 'custom' || !fromRestaurants.length ? custom : fromRestaurants);
  music.configure(c);
  $('pending').hidden = $('termsPending').hidden = !!c.prizes_confirmed;
  $('prizeKicker').textContent = c.prizes_confirmed ? 'The grand prize' : 'Proposed prize package';
  if (Array.isArray(c.prize_items) && c.prize_items.length) $('prizeItems').innerHTML = c.prize_items.map(i => `<li>${esc(i)}</li>`).join('');

  const each = String(c.dining_each || '').trim();
  const eachN = parseInt(each.replace(/[^0-9]/g, ''), 10);
  $$('[data-dine-each]').forEach(e => { e.textContent = each; });
  $('dineBadge').hidden = !each;
  $('dineTotal').textContent = eachN && c.restaurants.length ? '$' + (eachN * c.restaurants.length).toLocaleString() : '';
  const list = $('guideList');
  list.innerHTML = c.restaurants.map((r, i) => `
    <li class="dish"><span class="line"></span>
      <span class="no">${String(i + 1).padStart(2, '0')}</span>
      <div>
        ${r.photo ? `<div class="media"><img loading="lazy" src="${esc(r.photo)}" alt=""></div>` : ''}
        ${r.logo ? `<div class="logo"><img loading="lazy" src="${esc(r.logo)}" alt="${esc(r.name)} logo"></div>` : ''}
        <h3>${esc(r.name)}${each ? ` <span class="dine-chip">${esc(each)}</span>` : ''}</h3>
        ${r.location ? `<p class="loc">${esc(r.location)}</p>` : ''}
        ${r.description ? `<p class="desc">${esc(r.description)}</p>` : ''}
      </div>
    </li>`).join('');

  const t = c.transport || {};
  $('ride').hidden = t.enabled === false;
  $('ride-h').textContent = t.title || '';
  $('rideAmount').textContent = t.amount || '';
  $('rideLabel').textContent = t.amount_label || '';
  $('rideDetail').textContent = t.detail || '';
  if (t.image) $('ridePhoto').style.backgroundImage = `url("${t.image}")`;
  $('rideBrand').innerHTML = t.logo ? `<img src="${esc(t.logo)}" alt="${esc(t.brand || '')}">` : `<span class="uber-word">${esc(t.brand || '')}</span>`;
  const total = parseInt(String(t.amount || '').replace(/[^0-9]/g, ''), 10);
  const per = total && c.restaurants.length ? '$' + Math.round(total / c.restaurants.length).toLocaleString() : '';
  if (per) $('ridePer').textContent = per;
  $('rideBadge').hidden = t.enabled === false;
  if (per) $('rbPer').textContent = per;
  $('rbTotal').textContent = t.amount || '';
  const n = c.restaurants.length;
  $('cardStack').innerHTML = [n - 2, n - 1, n].filter(x => x > 0).map(i => `<figure class="gcard"><div class="g-top"><span class="g-brand">${esc(t.brand || '')}</span><span class="g-chip">Gift card</span></div><span class="g-amt">${esc(per)}</span><div class="g-foot"><span>Date night ${i}</span><span>of ${n}</span></div></figure>`).join('');

  const d = c.drawing; const bits = [];
  if (c.drawing_date) bits.push(`Drawing: ${esc(c.drawing_date)}.`);
  if (d && d.commitment) bits.push(`Drawing commitment (SHA-256): <code>${esc(d.commitment)}</code>, published ${esc(d.committed_at)} UTC. Results can be verified at <a href="/api/drawing">/api/drawing</a>.`);
  $('drawInfo').innerHTML = bits.join(' ');
  if (c.auth_text) $('authText').textContent = c.auth_text;
  if (c.marketing_text) $('marketingText').textContent = c.marketing_text;
  $$('.minAge').forEach(e => { e.textContent = c.min_age || 18; });
  $$('[data-npn]').forEach(e => { e.hidden = !c.free_entry_enabled; });
  const ph = (v, label) => v ? esc(v) : `<mark class="ph">${esc(label)}</mark>`;
  $('footLegal').innerHTML = `<p><strong>${ph(c.org_legal_name, 'Organization legal name')}</strong> · ${ph(c.org_nonprofit_status, 'Nonprofit status')} · EIN ${ph(c.org_ein, 'EIN')}</p>
    <p>${ph(c.org_address, 'Mailing address')} · ${ph(c.org_email, 'Contact email')} · ${ph(c.org_phone, 'Phone')}</p>
    ${c.campaign_number ? `<p>Campaign #${esc(c.campaign_number)}</p>` : ''}
    <p>Contributions may not be tax-deductible. Consult your tax adviser.</p>`;
  animateHeadline();
}

function renderStatus(s) {
  state.processor = s.processor || 'simulated';
  const live = state.processor === 'stripe_live';
  $('consentNote').textContent = live ? '' : state.processor === 'stripe_test'
    ? 'Stripe test mode: no real charge. Test card 4242 4242 4242 4242, any future date, any CVC.'
    : 'Sandbox demo: no real charge occurs.';
  $$('.sandbox-pill, [data-test-only]').forEach(e => { e.hidden = live; });
  if (dreidel && dreidel.setCount) dreidel.setCount(s.max_tickets); else dreidelReady.then(d => d.setCount && d.setCount(s.max_tickets));
  state.max = s.max_tickets; state.unit = s.unit_price_cents; state.remaining = s.remaining; state.open = s.sales_open; state.closedMsg = s.sales_message;
  $$('.maxT').forEach(e => { e.textContent = s.max_tickets; });
  $$('[data-unit]').forEach(e => { e.textContent = money(s.unit_price_cents); });
  $$('.maxPriceT').forEach(e => { e.textContent = money(s.unit_price_cents * s.max_tickets); });
  $('maxPrice').textContent = money(s.unit_price_cents * s.max_tickets);
  $$('[data-ex]').forEach(e => { e.textContent = money(18 * s.unit_price_cents); });
  for (const id of ['remaining', 'remaining2']) tweenNumber($(id), s.remaining);
  $('mbRemaining').textContent = s.remaining;
  const claimed = s.max_tickets - s.remaining, min = (state.campaign && state.campaign.progress_min) ?? 50;
  $('claimed').hidden = claimed < Math.max(1, min);
  $('clN').textContent = claimed; $('clBar').style.width = (claimed / s.max_tickets * 100).toFixed(1) + '%';
  $$('[data-open-checkout]').forEach(b => { b.disabled = !s.sales_open || state.busy; });
  $$('.cta[data-open-checkout] > span').forEach(sp => { sp.textContent = s.sales_open ? (sp.closest('.mobile-bar') ? 'Spin' : 'Spin the Dreidel') : (s.remaining ? 'Entries closed' : 'All entries claimed'); });
  if (!s.sales_open && !state.busy) setHint(s.sales_message);
}
function tweenNumber(el, to) {
  const from = parseInt(el.textContent, 10);
  if (!gsap || isNaN(from) || reduced) { el.textContent = to; return; }
  const o = { v: from }; gsap.to(o, { v: to, duration: 1.1, ease: 'power2.out', onUpdate: () => { el.textContent = Math.round(o.v); } });
}
/* ───────────── share-and-earn links ───────────── */
const referral = (() => {
  let incoming = null;  // the link this visitor arrived through
  const params = new URLSearchParams(location.search), fromUrl = (params.get('ref') || '').toLowerCase().replace(/[^a-z0-9-]/g, '').slice(0, 40);
  if (fromUrl) { store.set('ym-ref', fromUrl); params.delete('ref'); history.replaceState(null, '', location.pathname + (params.toString() ? '?' + params : '') + location.hash); }
  const code = fromUrl || store.get('ym-ref') || '';
  function fillBox(box, a, c) {
    box.hidden = false;
    box.querySelector('[data-sb-sold]').textContent = a.sold;
    box.querySelector('[data-sb-th]').textContent = a.threshold;
    const hasReward = !!a.reward;
    box.querySelector('[data-sb-of]').hidden = !hasReward;
    box.querySelector('.sb-bar').hidden = !hasReward;
    box.querySelector('[data-sb-bar]').style.width = Math.min(100, a.sold / a.threshold * 100) + '%';
    box.querySelector('[data-sb-link]').value = a.link;
    const text = `${(c && c.share_text) || 'Spin the dreidel and win a year of date nights:'} ${a.link}`;
    box.querySelector('[data-sb-wa]').href = 'https://wa.me/?text=' + encodeURIComponent(text);
    if (a.earned) box.querySelector('.sb-progress').innerHTML = `<strong>${a.sold}</strong> entries through your link. <b>You’ve earned it!</b> We’ll be in touch.`;
  }
  document.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-sb-copy]'); if (!b) return;
    const inp = b.parentElement.querySelector('input');
    try { await navigator.clipboard.writeText(inp.value); } catch { inp.select(); document.execCommand && document.execCommand('copy'); }
    b.textContent = 'Copied'; setTimeout(() => { b.textContent = 'Copy'; }, 1600);
  });
  async function lookup(c) {
    if (!c) return null;
    try { const r = await fetch('/api/ambassadors/' + encodeURIComponent(c)); return r.ok ? r.json() : null; } catch { return null; }
  }
  async function init(camp) {
    const on = !!camp.referral_enabled;
    $('earn').hidden = !on;
    if (camp.referral_reward) $$('[data-earn-lede]').forEach(e => { e.innerHTML = `Share your personal link. When <b>${esc(String(camp.referral_threshold))}</b> entries are made through it, we’ll thank you with <b>${esc(camp.referral_reward)}</b>.`; });
    $$('[data-earn-terms]').forEach(e => { e.textContent = camp.referral_terms || ''; });
    if (!on) return;
    if (code && !incoming) {
      incoming = await lookup(code);
      if (incoming) { $('refName').textContent = incoming.first_name; $('refChip').hidden = false; } else store.set('ym-ref', '');
    }
    const mine = store.get('ym-my-ref');
    if (mine) { const a = await lookup(mine); if (a) { fillBox($('earn').querySelector('[data-sharebox]'), a, camp); $('earnForm').hidden = true; } }
  }
  $('earnForm').addEventListener('submit', async (e) => {
    e.preventDefault(); $('earnErr').textContent = '';
    try {
      const r = await fetch('/api/ambassadors', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: $('earnName').value.trim(), email: $('earnEmail').value.trim() }) });
      const a = await r.json(); if (!r.ok) throw new Error(a.error || 'Please try again.');
      store.set('ym-my-ref', a.code); $('earnForm').hidden = true; fillBox($('earn').querySelector('[data-sharebox]'), a, state.campaign);
    } catch (err) { $('earnErr').textContent = err.message; }
  });
  return {
    init,
    get code() { return incoming ? incoming.code : ''; },
    showMine(a) {
      $('share').hidden = !!a;
      if (!a) { $('rEarn').hidden = true; return; }
      store.set('ym-my-ref', a.code); $('rEarn').hidden = false; fillBox($('rEarn').querySelector('[data-sharebox]'), a, state.campaign);
      const box = $('earn').querySelector('[data-sharebox]'); fillBox(box, a, state.campaign); $('earnForm').hidden = true;
    },
  };
})();

async function loadCampaign() {
  try { const r = await fetch('/api/campaign', { cache: 'no-store' }); const d = await r.json(); renderCampaign(d.campaign); renderStatus(d.status); revealSections(); referral.init(d.campaign); }
  catch { $('remaining').textContent = '—'; }
}
async function refreshStatus() { try { const r = await fetch('/api/status', { cache: 'no-store' }); if (r.ok) renderStatus(await r.json()); } catch {} }
loadCampaign();
setInterval(() => { if (!document.hidden && !state.busy) refreshStatus(); }, 12000);

/* ───────────── checkout ───────────── */
const sheet = $('sheet'), panel = $('checkout');
let lastFocus = null;
function openCheckout() {
  if (state.busy) return;
  if (!state.open) { setHint(state.closedMsg); return; }
  lastFocus = document.activeElement; showStep(1); $('error').textContent = '';
  sheet.hidden = false; document.body.style.overflow = 'hidden'; updateBar();
  if (gsap) { gsap.fromTo('.sheet-backdrop', { opacity: 0 }, { opacity: 1, duration: 0.3 }); gsap.fromTo(panel, { y: 40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: 'power3.out' }); }
  setTimeout(() => (($('name').value ? $('next') : $('name')).focus()), 80);
}
function closeCheckout(restore = true) {
  if (sheet.hidden) return;
  const done = () => { sheet.hidden = true; document.body.style.overflow = ''; if (restore && lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true }); updateBar(); };
  if (gsap) gsap.to(panel, { y: 30, opacity: 0, duration: 0.22, ease: 'power2.in', onComplete: done }); else done();
}
function showStep(n) {
  $('step1').hidden = n !== 1; $('step2').hidden = n !== 2; $('p2').classList.toggle('on', n === 2);
  if (gsap) gsap.fromTo(n === 1 ? '#step1' : '#step2', { opacity: 0, x: n === 1 ? -14 : 14 }, { opacity: 1, x: 0, duration: 0.35, ease: 'power2.out' });
}
const validEmail = (e) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e);
const validPhone = (p) => /^[0-9+()\-.\s]+$/.test(p) && (p.replace(/\D/g, '').length >= 7) && (p.replace(/\D/g, '').length <= 15);
document.addEventListener('change', (e) => {
  if (e.target.name !== 'pkg') return;
  state.requestId = newId(); payment = null; $('payEl').innerHTML = ''; applyPkg();
});
$('next').addEventListener('click', () => {
  const name = $('name').value.trim(), email = $('email').value.trim(), phone = $('phone').value.trim();
  const fail = (msg, el) => { $('error').textContent = msg; el.focus(); };
  if (!name) return fail('Please enter your name.', $('name'));
  if (!validEmail(email)) return fail('Please enter a valid email address.', $('email'));
  if (!validPhone(phone)) return fail('Please enter a valid phone number.', $('phone'));
  $('error').textContent = ''; applyPkg(); showStep(2); setTimeout(() => $('consent').focus(), 50);
  preparePayment().catch(err => { $('payEl').innerHTML = ''; $('error').textContent = err.message || 'Could not load the secure card form.'; });
});

/* Stripe (test mode): card details go from the browser straight to Stripe; our server only sees ids. */
let stripeJs = null, payment = null;
function loadStripe() {
  return stripeJs || (stripeJs = new Promise((res, rej) => {
    const s = document.createElement('script'); s.src = 'https://js.stripe.com/v3/';
    s.onload = () => res(window.Stripe); s.onerror = () => { stripeJs = null; rej(new Error('Could not load the secure card form. Check your connection.')); };
    document.head.appendChild(s);
  }));
}
async function preparePayment() {
  if (!state.processor.startsWith('stripe')) { $('payEl').hidden = true; return; }
  if (payment && payment.rid === state.requestId) return;
  const box = $('payEl'); box.hidden = false; box.innerHTML = '<p class="pay-loading">Loading secure card form…</p>';
  const rid = state.requestId;
  const [StripeCtor, r] = await Promise.all([loadStripe(), fetch('/api/payment-intent', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: $('name').value.trim(), email: $('email').value.trim(), request_id: rid, package: pkgNow() }) })]);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'Could not start the card authorization.');
  const stripe = StripeCtor(d.publishable_key);
  const elements = stripe.elements({ clientSecret: d.client_secret,
    fonts: [{ cssSrc: 'https://fonts.googleapis.com/css2?family=Manrope:wght@400;600&display=swap' }],
    appearance: { theme: 'night', variables: { colorPrimary: '#ecd29a', colorBackground: '#0d0f16', colorText: '#efe8da',
      colorDanger: '#ff9c88', fontFamily: 'Manrope, system-ui, sans-serif', borderRadius: '12px' } } });
  box.innerHTML = '';
  elements.create('payment', { layout: 'tabs' }).mount(box);
  payment = { rid, pi: d.payment_intent, stripe, elements };
}
async function authorizeCard(p) {
  if (!state.processor.startsWith('stripe')) return null;
  if (!payment || payment.rid !== state.requestId) throw new Error('The card form is still loading. Please try again.');
  const { error, paymentIntent } = await payment.stripe.confirmPayment({ elements: payment.elements, redirect: 'if_required',
    confirmParams: { return_url: location.origin + '/', payment_method_data: { billing_details: { name: p.name, email: p.email, phone: p.phone } } } });
  if (error) throw new Error(error.message || 'Your card was not authorized.');
  if (!paymentIntent || paymentIntent.status !== 'requires_capture') throw new Error('Your card was not authorized. Please try another card.');
  return payment.pi;
}
$('back').addEventListener('click', () => { $('error').textContent = ''; showStep(1); });
for (const el of [$('name'), $('email'), $('phone')]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('next').click(); } });
sheet.addEventListener('click', (e) => { if (e.target.closest('[data-close]')) closeCheckout(); });
function trapFocus(e, container) {
  const f = [...container.querySelectorAll('button,input,a[href]')].filter(x => !x.closest('[hidden]') && !x.disabled);
  if (!f.length) return; const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}
addEventListener('keydown', (e) => {
  if (!sheet.hidden) { if (e.key === 'Escape') closeCheckout(); if (e.key === 'Tab') trapFocus(e, panel); }
  else if (!$('reveal').hidden) { if (e.key === 'Escape') closeReveal(); if (e.key === 'Tab') trapFocus(e, $('reveal')); }
});
$$('[data-open-checkout]').forEach(b => b.addEventListener('click', openCheckout));
$('three').addEventListener('click', () => { if (!state.busy && $('reveal').hidden) openCheckout(); });

$('checkout').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!$('consent').checked) { $('error').textContent = 'Please confirm the payment authorization to spin.'; return; }
  if (!$('consentRules').checked) { $('error').textContent = 'Please confirm your eligibility and agree to the Official Rules.'; return; }
  const payload = { name: $('name').value.trim(), email: $('email').value.trim(), phone: $('phone').value.trim(), consent: true, consent_rules: true, marketing: $('marketing').checked, ref: referral.code, request_id: state.requestId, package: pkgNow() };
  const go = $('go'), label = go.querySelector('span'), txt = label.textContent;
  try {
    go.disabled = true; if (state.processor.startsWith('stripe')) label.textContent = 'Authorizing card…';
    const pi = await authorizeCard(payload);
    if (pi) payload.payment_intent = pi;
  } catch (err) { $('error').textContent = err.message; return; }
  finally { go.disabled = false; label.textContent = txt; }
  closeCheckout(false); await runSpin(payload);
});

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
async function runSpin(payload) {
  state.busy = true; $$('[data-open-checkout]').forEach(b => { b.disabled = true; }); updateBar();
  const d3 = dreidel || await dreidelReady;
  $('spin').scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'center' });
  if (music.autostart && !sound.userOff) sound.on();  // music starts with the spin (unless the visitor turned it off)
  setHint(''); d3.rev(); counter.start();
  let data;
  try {
    const [res] = await Promise.all([
      fetch('/api/spin', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }),
      sleep(reduced ? 300 : 1500),
    ]);
    data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'We couldn’t complete your spin.');
  } catch (err) {
    d3.abort(); counter.hide(); state.busy = false; setHint(IDLE_HINT);
    await refreshStatus(); openCheckout(); showStep(2);
    $('error').textContent = err && err.message && err.message !== 'Failed to fetch' ? err.message : 'Connection problem. Please try again; you will not be charged twice.';
    return;
  }
  counter.slow();
  await d3.land(data.number);
  counter.lock(data.number);
  await sleep(reduced ? 200 : 900);
  reveal(data);
  state.requestId = newId(); state.busy = false; refreshStatus();
}

/* ───────────── reveal ───────────── */
function reveal(d) {
  const letter = LETTERS[d.number % 4];
  const shown = (d.numbers && d.numbers.length > 1) ? d.numbers.join(' & ') : String(d.number);
  counter.hide(); setHint(`Landed on ${letter} · № ${shown}`);
  sound.chime(); celebrate();
  $('rLetter').textContent = letter;
  const art = (state.campaign || {}).reveal_image, cap = (state.campaign || {}).reveal_caption || '';
  $('rArt').hidden = !art; if (art) { $('rArtImg').src = art; $('rArtCap').textContent = cap; $('rArtCap').hidden = !cap; }
  $('rConf').textContent = d.confirmation; $('rAuth').textContent = d.authorization_id || '—';
  const st = $('rStatus'); st.classList.remove('warn');
  if (d.payment_status === 'paid') {
    const mode = d.processor === 'stripe_live' ? '' : d.processor === 'stripe_test' ? ' (Stripe test mode)' : ' (sandbox)';
    st.textContent = d.email_status === 'sent' ? `Thank you! Donation received${mode}. Your entry confirmation is on its way to your inbox.`
      : `Thank you! Donation received${mode}. Your entry confirmation is ready.`;
  } else { st.classList.add('warn'); st.textContent = 'Your number is held, but the payment didn’t go through. Our team will contact you to complete it.'; }
  const c = state.campaign || {};
  const myLink = d.my_link ? d.my_link.link : `${location.origin}/`;
  $('share').href = 'https://wa.me/?text=' + encodeURIComponent(`${c.share_text || 'Spin the dreidel and win a year of date nights:'} ${myLink}`);
  referral.showMine(d.my_link);
  const layer = $('reveal'); layer.hidden = false; document.body.style.overflow = 'hidden'; updateBar();
  setTimeout(() => $('again').focus({ preventScroll: true }), 50);
  $('rNumber').parentElement.classList.toggle('two', shown !== String(d.number));
  if (!gsap || reduced) { $('rNumber').textContent = shown; $('rAmount').textContent = d.amount_display; return; }
  $('rNumber').textContent = '0'; $('rAmount').textContent = money(0);
  const tl = gsap.timeline();
  tl.fromTo('.reveal-backdrop', { opacity: 0 }, { opacity: 1, duration: 0.5 })
    .fromTo('.reveal-card', { opacity: 0, y: 40, scale: 0.92 }, { opacity: 1, y: 0, scale: 1, duration: 0.7, ease: 'power3.out' }, 0.1);
  if (art) tl.fromTo('.r-art', { opacity: 0, scale: 0.6, rotate: -6 }, { opacity: 1, scale: 1, rotate: 0, duration: 0.9, ease: 'back.out(1.8)' }, 0.25);
  tl.call(() => { $('rNumber').textContent = shown; }, null, 0.25);
  tl.fromTo('.big-number', { scale: 1.25 }, { scale: 1, duration: 0.9, ease: 'elastic.out(1,0.5)' });
  const amt = { v: 0 }, cents = Math.round(d.amount * 100);
  tl.to(amt, { v: cents, duration: 0.9, ease: 'power2.out', onUpdate: () => { $('rAmount').textContent = money(Math.round(amt.v / 100) * 100); }, onComplete: () => { $('rAmount').textContent = d.amount_display; } }, '<0.1');
  tl.from('.r-status, .r-meta > div, .r-actions > *', { opacity: 0, y: 12, stagger: 0.06, duration: 0.4 }, '<');
}
function closeReveal(then) {
  const layer = $('reveal');
  const done = () => { layer.hidden = true; document.body.style.overflow = ''; counter.hide(); dreidel && dreidel.idle(); setHint(state.open ? IDLE_HINT : state.closedMsg); updateBar(); then && then(); };
  if (gsap && !reduced) gsap.to('.reveal-card', { opacity: 0, y: -20, duration: 0.3, onComplete: done }); else done();
}
$('done').addEventListener('click', () => closeReveal());
$('again').addEventListener('click', () => closeReveal(() => { $('consent').checked = false; $('consentRules').checked = false; openCheckout(); }));

/* ───────────── nav, mobile bar ───────────── */
let ctaVisible = true;
function updateBar() { $('mobileBar').classList.toggle('show', !ctaVisible && sheet.hidden && $('reveal').hidden && !state.busy && state.open); }
new IntersectionObserver(([e]) => { ctaVisible = e.isIntersecting; updateBar(); }, { threshold: 0.1 }).observe($('cta'));
addEventListener('scroll', () => { $('nav').classList.toggle('scrolled', scrollY > 40); }, { passive: true });

/* ───────────── motion choreography ───────────── */
let headlineDone = false;
function animateHeadline() {
  if (!gsap || reduced || headlineDone) return; headlineDone = true;
  gsap.from('.headline .l > span', { yPercent: 110, duration: 1.1, ease: 'power4.out', stagger: 0.12, delay: 0.25 });
}
if (gsap && !reduced) {
  gsap.from('.crest', { scale: 0.7, opacity: 0, duration: 1.2, ease: 'power3.out' });
  gsap.from('.hero .kicker, .wordmark', { opacity: 0, y: 14, duration: 0.8, stagger: 0.1, delay: 0.15, ease: 'power3.out' });
  gsap.from('.ride-badge, .intro, .tagline, .pillars li, .hero-actions', { opacity: 0, y: 18, duration: 0.8, stagger: 0.08, delay: 0.75, ease: 'power3.out' });
  gsap.from('.stage', { opacity: 0, scale: 0.94, duration: 1.4, delay: 0.3, ease: 'power3.out' });
  gsap.from('.nav', { opacity: 0, y: -16, duration: 0.8, delay: 0.4 });
}
let sectionsDone = false;
function revealSections() {
  if (!gsap || !window.ScrollTrigger || reduced || sectionsDone) return; sectionsDone = true;
  gsap.registerPlugin(ScrollTrigger);
  gsap.utils.toArray('.ov-card, .section-head > *, .steps li, .facts, .play-cta').forEach(el =>
    gsap.from(el, { opacity: 0, y: 28, duration: 0.9, ease: 'power3.out', scrollTrigger: { trigger: el, start: 'top 90%' } }));
  gsap.utils.toArray('.dish').forEach((el, i) =>
    gsap.from(el, { opacity: 0, y: 36, duration: 0.9, delay: (i % 2) * 0.08, ease: 'power3.out', scrollTrigger: { trigger: el, start: 'top 92%' } }));
  gsap.from('.gcard', { opacity: 0, y: 60, rotate: 0, duration: 1.1, stagger: 0.15, ease: 'power3.out', clearProps: 'opacity,transform', scrollTrigger: { trigger: '.cards-stack', start: 'top 80%' } });
  gsap.from('.ride-copy > *', { opacity: 0, y: 30, duration: 1, stagger: 0.1, ease: 'power3.out', scrollTrigger: { trigger: '.ride', start: 'top 70%' } });
  gsap.fromTo('.ride-photo', { yPercent: -6 }, { yPercent: 6, ease: 'none', scrollTrigger: { trigger: '.ride', start: 'top bottom', end: 'bottom top', scrub: true } });
}
