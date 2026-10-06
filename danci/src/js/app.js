/* 单词手账 v3 · 背单词 + 抽卡收集
 * 小红书小工具（离线 H5）：ES2017，无网络请求，无内联脚本。 */
(function () {
  'use strict';

  /* ================= 基础 ================= */
  const $ = s => document.querySelector(s);
  const $$ = s => Array.prototype.slice.call(document.querySelectorAll(s));
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const shuffle = a => { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.random() * (i + 1) | 0; const t = a[i]; a[i] = a[j]; a[j] = t; } return a; };
  const pick = a => a[Math.random() * a.length | 0];
  const pad2 = n => ('0' + n).slice(-2);
  const pad3 = n => ('00' + n).slice(-3);
  const icon = (id, cls) => `<svg class="ic${cls ? ' ' + cls : ''}"><use href="#${id}"/></svg>`;
  const C = window.CATALOG;
  const ORDER = C.ORDER; // N R SR SSR UR LR SECRET
  const TIER = {}; C.TIERS.forEach(t => { TIER[t.t] = t; });

  /* ================= 词表 ================= */
  const WORDS = window.WORDS_RAW.map((r, k) => ({ k, i: r[0], f: r[1], w: r[2], p: r[3], s: r[4], alt: r[5] || [], note: r[6] || '', cp: r[7], cm: r[8], en: r[9], cn: r[10], src: r[11], g: Math.floor(k / 20) + 1 }));
  const N = WORDS.length, GS = 20, NG = Math.ceil(N / GS);
  const BYW = {}; WORDS.forEach(w => { BYW[w.w] = w.k; });
  const groupWords = g => WORDS.slice(g * GS, Math.min(N, (g + 1) * GS));

  /* ================= 存储（9.46+ 容器 Storage，低版本回退浏览器存储） ================= */
  const KEY = 'danci-shouzhang-v3';
  const OLD_KEY = 'danci-shouzhang-688.v1';
  const DEF = {
    v: 3, prog: {}, days: [], today: { d: '', n: 0 },
    set: { count: 20, order: 'rand', auto: true, next: true, sound: true, mode: 'en2zh' },
    cur: 0, tickets: [], pity: { sr: 0, ssr: 0, ur: 0 }, dust: 0, cards: {},
    stat: { draws: 0, tests: 0, best: 0 }, welcome: false, gifts: {}
  };
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function normalize(raw) {
    const st = Object.assign(clone(DEF), raw && typeof raw === 'object' ? raw : {});
    st.set = Object.assign({}, DEF.set, st.set || {});
    st.pity = Object.assign({}, DEF.pity, st.pity || {});
    st.stat = Object.assign({}, DEF.stat, st.stat || {});
    if (!Array.isArray(st.tickets)) st.tickets = [];
    if (!st.cards || typeof st.cards !== 'object') st.cards = {};
    if (!st.gifts || typeof st.gifts !== 'object') st.gifts = {};
    if (!st.prog || typeof st.prog !== 'object') st.prog = {};
    if (!Array.isArray(st.days)) st.days = [];
    if (!(st.cur >= 0 && st.cur < NG)) st.cur = 0;
    Object.keys(st.cards).forEach(k => {
      const o = st.cards[k] || {};
      Object.keys(o).forEach(id => { if (typeof o[id] === 'number') o[id] = { n: o[id], s: { star: o[id] } }; else if (!o[id] || !o[id].s) o[id] = { n: (o[id] && o[id].n) || 1, s: { star: 1 } }; });
    });
    return st;
  }
  let S = normalize(null);
  const STORAGE_MIN = 9460;
  const miniTool = () => window.xhs && window.xhs.miniTool;
  function readBuild(lo) { const e = lo && lo.miniToolEnv; return Number(e && e.buildVersion) || 0; }
  let buildP = null;
  function buildVersion() {
    if (buildP) return buildP;
    buildP = (async () => {
      const v = readBuild(window.xhs && window.xhs.launchOptions);
      if (v) return v;
      const mt = miniTool();
      if (!mt || typeof mt.getLaunchOptions !== 'function') return 0;
      try { return readBuild(await mt.getLaunchOptions()); } catch (e) { return 0; }
    })();
    return buildP;
  }
  async function useContainer() {
    const v = await buildVersion(), mt = miniTool();
    return Math.floor(v / 1000) >= STORAGE_MIN && !!mt && typeof mt.setStorage === 'function' && typeof mt.getStorage === 'function';
  }
  function lsGet(key) { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { return null; } }
  function lsSet(key, str) { try { localStorage.setItem(key, str); return true; } catch (e) { return false; } }
  async function readKey(key) {
    try {
      if (await useContainer()) {
        const r = await miniTool().getStorage({ key });
        const d = r && r.data;
        if (typeof d === 'string' && d) return JSON.parse(d);
        return null;
      }
    } catch (e) { }
    return lsGet(key);
  }
  async function loadState() {
    let raw = await readKey(KEY);
    if (!raw) {
      // 从 v1（手账贴纸版）迁移学习记录：词序一致，可以直接沿用
      const old = await readKey(OLD_KEY);
      if (old && old.prog) raw = { prog: old.prog, days: old.days || [], today: old.today || { d: '', n: 0 } };
    }
    return raw;
  }
  let saving = false, again = false, saveT = null;
  async function flush() {
    if (saving) { again = true; return; }
    saving = true;
    try {
      do {
        again = false;
        let str = null; try { str = JSON.stringify(S); } catch (e) { }
        if (typeof str !== 'string') break;
        let ok = false;
        try { if (await useContainer()) { await miniTool().setStorage({ key: KEY, data: str }); ok = true; } } catch (e) { ok = false; }
        if (!ok) ok = lsSet(KEY, str);
        if (!ok && !flush.warned) { flush.warned = true; toast('保存失败'); }
      } while (again);
    } finally { saving = false; }
  }
  function save() { clearTimeout(saveT); saveT = setTimeout(() => { flush().catch(() => { }); }, 120); }
  document.addEventListener('visibilitychange', () => { if (document.hidden) { clearTimeout(saveT); flush().catch(() => { }); } });

  /* ================= 学习进度 ================= */
  const dayKey = (d) => { d = d || new Date(); return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()); };
  const P = k => S.prog[k] || null;
  const isMastered = k => { const p = P(k); return !!p && p.s >= 2 && p.m !== 1; };
  const inWrong = k => { const p = P(k); if (!p) return false; if (p.m === 1) return true; if (p.m === 0) return false; return p.w > 0 && p.s < 2; };
  const status = k => { const p = P(k); if (!p) return 'new'; if (inWrong(k)) return 'w'; if (isMastered(k)) return 'm'; return 'l'; };
  function record(k, ok, opt) {
    opt = opt || {};
    const p = S.prog[k] || (S.prog[k] = { c: 0, w: 0, s: 0 });
    const before = isMastered(k);
    if (ok) { p.c++; if (!opt.hint) p.s++; if (p.s >= 2) delete p.m; }
    else if (opt.soft) { p.s = 0; }
    else { p.w++; p.s = 0; delete p.m; }
    p.t = Date.now();
    const d = dayKey();
    if (S.today.d !== d) S.today = { d, n: 0 };
    S.today.n++;
    if (S.days.indexOf(d) < 0) { S.days.push(d); if (S.days.length > 400) S.days = S.days.slice(-400); }
    save();
    return !before && isMastered(k);
  }
  function streak() {
    const set = {}; S.days.forEach(d => { set[d] = 1; });
    let n = 0; const d = new Date();
    if (!set[dayKey(d)]) d.setDate(d.getDate() - 1);
    while (set[dayKey(d)]) { n++; d.setDate(d.getDate() - 1); }
    return n;
  }
  const wrongWords = () => WORDS.filter(w => inWrong(w.k));
  const masteredIn = g => groupWords(g).filter(w => isMastered(w.k)).length;

  /* ================= 抽卡：概率、券、保底 ================= */
  const BASE = { SECRET: .2, LR: .8, UR: 3, SSR: 8, SR: 18, R: 30, N: 40 };
  const BOOSTED = ['SECRET', 'LR', 'UR', 'SSR'];
  function rates(m) {
    const r = Object.assign({}, BASE);
    if (m > 1) { let add = 0; BOOSTED.forEach(t => { r[t] = BASE[t] * m; add += r[t] - BASE[t]; }); r.N = BASE.N - add; }
    return r;
  }
  function multOf(right, total) {
    if (!total) return 1;
    const a = right / total;
    return right === total ? 3 : a >= .9 ? 2 : a >= .8 ? 1.5 : a >= .6 ? 1.2 : 1;
  }
  function bonusOf(right, total) {
    if (!total) return 0;
    const a = right / total;
    return right === total ? 5 : a >= .9 ? 3 : a >= .8 ? 2 : a >= .6 ? 1 : 0;
  }
  const fmtP = x => { const v = x < 1 ? Math.round(x * 100) / 100 : Math.round(x * 10) / 10; return String(v) + '%'; };
  const fmtM = m => '×' + String(m);
  const PITY = { sr: 10, ssr: 60, ur: 150 };
  function ticketCount() { return S.tickets.reduce((a, b) => a + b.n, 0); }
  function bestBatch() { let b = null; S.tickets.forEach(t => { if (t.n > 0 && (!b || t.m > b.m)) b = t; }); return b; }
  function addTickets(n, m) {
    if (n <= 0) return;
    const b = S.tickets.find(t => t.m === m);
    if (b) b.n += n; else S.tickets.push({ n, m });
    save();
  }
  function takeTicket() {
    const b = bestBatch(); if (!b) return null;
    b.n--; const m = b.m;
    S.tickets = S.tickets.filter(t => t.n > 0);
    return m;
  }
  function rollTier(m, minRank) {
    const r = rates(m);
    const tiers = ORDER.filter((t, i) => i >= minRank);
    const tot = tiers.reduce((a, t) => a + r[t], 0);
    let x = Math.random() * tot;
    for (let i = tiers.length - 1; i >= 0; i--) { x -= r[tiers[i]]; if (x < 0) return tiers[i]; }
    return tiers[0];
  }
  const SEAL = C.SEAL, SEAL_TIERS = C.SEAL_TIERS;
  function rollSeal() {
    let x = Math.random() * 100;
    for (let i = SEAL_TIERS.length - 1; i >= 0; i--) { x -= SEAL_TIERS[i].rate; if (x < 0) return pick(SEAL_TIERS[i].v).id; }
    return pick(SEAL_TIERS[0].v).id;
  }
  const ownSeals = (k, vid) => { const o = S.cards[k] && S.cards[k][vid]; return o ? Object.keys(o.s) : []; };
  function bestSeal(k, vid) {
    let b = null; ownSeals(k, vid).forEach(id => { if (SEAL[id] && (!b || SEAL[id].rank > SEAL[b].rank)) b = id; });
    return b;
  }
  function sealsOwned() { const o = {}; Object.keys(S.cards).forEach(k => Object.keys(S.cards[k]).forEach(v => Object.keys(S.cards[k][v].s).forEach(id => { o[id] = 1; }))); return o; }
  const ownVids = k => Object.keys(S.cards[k] || {});
  function bestVid(k) {
    let best = null;
    ownVids(k).forEach(id => { const v = C.BY_ID[id]; if (v && (!best || v.rank > C.BY_ID[best].rank)) best = id; });
    return best;
  }
  function pickWord(vid) {
    const seen = {};
    const cand = [];
    WORDS.forEach(w => { const p = P(w.k); if (p && p.c > 0) { cand.push(w); seen[w.k] = 1; } });
    groupWords(S.cur).forEach(w => { if (!seen[w.k]) cand.push(w); });
    const weight = w => { const o = S.cards[w.k]; if (!o) return 3; return o[vid] ? .3 : 1.6; };
    let tot = 0; cand.forEach(w => { tot += weight(w); });
    let x = Math.random() * tot;
    for (const w of cand) { x -= weight(w); if (x < 0) return w; }
    return cand[cand.length - 1];
  }
  function drawOne() {
    const m = takeTicket(); if (m == null) return null;
    let minRank = 0, pity = '';
    if (S.pity.ur >= PITY.ur - 1) { minRank = 4; pity = 'UR'; }
    else if (S.pity.ssr >= PITY.ssr - 1) { minRank = 3; pity = 'SSR'; }
    else if (S.pity.sr >= PITY.sr - 1) { minRank = 2; pity = 'SR'; }
    const tier = rollTier(m, minRank), rank = ORDER.indexOf(tier);
    S.pity.sr = rank >= 2 ? 0 : S.pity.sr + 1;
    S.pity.ssr = rank >= 3 ? 0 : S.pity.ssr + 1;
    S.pity.ur = rank >= 4 ? 0 : S.pity.ur + 1;
    const t = TIER[tier], v = pick(t.v), w = pickWord(v.id);
    const seal = rollSeal();
    const own = S.cards[w.k] || (S.cards[w.k] = {});
    const e = own[v.id] || (own[v.id] = { n: 0, s: {} });
    const newCard = !e.n, newSeal = !e.s[seal];
    const dup = !newCard && !newSeal;   // 单词、卡面、蜡封都一样才算重复
    e.n++; e.s[seal] = (e.s[seal] || 0) + 1;
    const dust = dup ? t.dust : 0;
    S.dust += dust;
    S.stat.draws++;
    const p = rates(m)[tier] / t.v.length;
    return { k: w.k, vid: v.id, tier, rank, dup, dust, m, p, seal, sp: SEAL[seal].p, srank: SEAL[seal].rank, newCard, newSeal, pity: pity && rank <= ORDER.indexOf(pity) ? pity : '' };
  }
  function tierOwned(tier) { let n = 0; Object.keys(S.cards).forEach(k => { Object.keys(S.cards[k]).forEach(id => { if (C.BY_ID[id] && C.BY_ID[id].tier === tier) n++; }); }); return n; }
  function variantOwners(vid) { return Object.keys(S.cards).filter(k => S.cards[k][vid]).map(Number); }
  const collectedWords = () => Object.keys(S.cards).filter(k => ownVids(k).length).length;
  function collectedVariants() { const s = {}; Object.keys(S.cards).forEach(k => ownVids(k).forEach(id => { s[id] = 1; })); return Object.keys(s).length; }
  const DUST_PER_TICKET = 20;

  /* ================= 声音：发音录音 + 音效 =================
   * Web Audio 优先（低延迟、可叠加）；上下文起不来（容器限制、没解锁）时退回 <audio> 元素；
   * 没有录音的词才用系统朗读。
   * iOS：只有 touchend / click 里的 resume() 才算用户手势，所以每次手势都重试，直到真正跑起来；
   * audioSession = playback 让静音键不再静掉网页声音（iOS 17+）。 */
  const TTS = 'speechSynthesis' in window && typeof SpeechSynthesisUtterance !== 'undefined';
  try { if (navigator.audioSession) navigator.audioSession.type = 'playback'; } catch (e) { }
  const SILENT = 'audio/fx/silent.mp3';  // 容器 CSP 不允许 <audio> 用 data: 地址，用包内文件
  function clips() { return window.AUDIO_INLINE || null; }
  function sfxClips() { return window.SFX_INLINE || null; }
  function bytesOf(b64) { const s = atob(b64), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return u; }
  const bufCache = {}, badDecode = {};
  let AC = null, voiceSrc = null, token = 0;
  function getAC() {
    if (!AC) { try { const K = window.AudioContext || window.webkitAudioContext; if (K) AC = new K(); } catch (e) { AC = null; } }
    return AC;
  }
  const acRunning = () => !!(AC && AC.state === 'running');
  function wakeAC() {
    const ac = getAC(); if (!ac || ac.state === 'running') return;
    try { const p = ac.resume(); if (p && p.catch) p.catch(() => { }); } catch (e) { }
    try { const b = ac.createBuffer(1, 1, 22050), s = ac.createBufferSource(); s.buffer = b; s.connect(ac.destination); s.start(0); } catch (e) { }
  }
  // <audio> 元素池：一个给发音，六个轮流给音效。在手势里先各播一次静音，之后才能被程序随时播放
  const voiceEl = new Audio(), sfxEls = [new Audio(), new Audio(), new Audio(), new Audio(), new Audio(), new Audio()];
  let sfxIdx = 0, mediaReady = false;
  [voiceEl].concat(sfxEls).forEach(el => { el.preload = 'auto'; el.setAttribute('playsinline', ''); el.setAttribute('webkit-playsinline', ''); });
  function wakeMedia() {
    if (mediaReady) return;
    [voiceEl].concat(sfxEls).forEach(el => {
      if (el.dataset.ok || !el.paused) return;
      try {
        el.src = SILENT; el.volume = 0;
        const p = el.play();
        const ok = () => { el.dataset.ok = '1'; el.volume = 1; if ([voiceEl].concat(sfxEls).every(x => x.dataset.ok)) mediaReady = true; };
        if (p && p.then) p.then(ok, () => { el.volume = 1; }); else ok();
      } catch (e) { }
    });
  }
  function unlockAudio() { wakeAC(); wakeMedia(); }
  ['touchstart', 'touchend', 'pointerdown', 'pointerup', 'mousedown', 'click', 'keydown'].forEach(ev => document.addEventListener(ev, unlockAudio, { capture: true, passive: true }));
  document.addEventListener('visibilitychange', () => { if (!document.hidden && AC && AC.state !== 'running') wakeAC(); });

  // 解码（带缓存）；失败的条目记下来，以后直接走 <audio>
  function decode(key, b64, ok, fail) {
    if (bufCache[key]) { ok(bufCache[key]); return; }
    if (badDecode[key]) { fail(); return; }
    let done = false;
    const good = b => { if (done) return; done = true; bufCache[key] = b; ok(b); };
    const bad = () => { if (done) return; done = true; badDecode[key] = 1; fail(); };
    try {
      const p = AC.decodeAudioData(bytesOf(b64).buffer, good, bad);
      if (p && p.then) p.then(good, bad);
    } catch (e) { bad(); }
  }
  function mediaPlay(el, src, vol, onend) {
    try {
      el.onended = onend || null; el.onerror = onend || null;
      el.src = src; el.volume = vol == null ? 1 : vol;
      const p = el.play();
      if (p && p.then) p.then(() => { el.dataset.ok = '1'; }, () => { if (onend) onend(); });
      return true;
    } catch (e) { if (onend) onend(); return false; }
  }
  // 播一段 Base64 MP3。voice=true 时打断上一段发音
  function playClip(key, b64, opt) {
    opt = opt || {};
    const my = opt.voice ? token : 0, onend = opt.onend;
    wakeAC();
    const fallback = () => {
      if (opt.voice && my !== token) return;
      // 音效用包内 audio/fx/*.mp3（容器不允许 <audio> 播 data: 地址）
      const src = key[0] === 's' ? 'audio/fx/' + key.slice(1) + '.mp3' : 'data:audio/mpeg;base64,' + b64;
      mediaPlay(opt.voice ? voiceEl : sfxEls[sfxIdx++ % sfxEls.length], src, opt.vol, onend);
    };
    if (!acRunning()) { fallback(); return; }
    decode(key, b64, buf => {
      if (opt.voice && my !== token) return;
      if (!acRunning()) { fallback(); return; }
      try {
        const s = AC.createBufferSource(), g = AC.createGain();
        s.buffer = buf; g.gain.value = opt.vol == null ? 1 : opt.vol;
        s.connect(g); g.connect(AC.destination);
        if (onend) s.onended = () => { if (!opt.voice || my === token) onend(); };
        s.start(AC.currentTime + (opt.delay || 0));
        if (opt.voice) voiceSrc = s;
      } catch (e) { fallback(); }
    }, fallback);
  }
  function stopVoice() {
    token++;
    try { if (voiceSrc) voiceSrc.stop(); } catch (e) { } voiceSrc = null;
    try { voiceEl.pause(); } catch (e) { }
    try { if (TTS) speechSynthesis.cancel(); } catch (e) { }
  }
  function ttsSpeak(text, onend) {
    if (!TTS) { if (onend) onend(); return; }
    try {
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text); u.lang = 'en-US'; u.rate = .86;
      if (onend) { u.onend = onend; u.onerror = onend; }
      speechSynthesis.speak(u);
    } catch (e) { if (onend) onend(); }
  }
  function speak(word, onend) {
    const k = BYW[word], w = k != null ? WORDS[k] : null, CL = clips();
    stopVoice();
    if (!w || !CL || !CL[w.i]) { ttsSpeak(word, onend); return; }
    playClip('w' + w.i, CL[w.i], { voice: true, onend: onend });
  }
  // 音效：合成好的 MP3（tools/sfx.py）；还没加载完时用振荡器顶一下
  function sfx(name, vol, delay) {
    if (!S.set.sound) return;
    const X = sfxClips();
    if (X && X[name]) { if (delay) setTimeout(() => playClip('s' + name, X[name], { vol: vol }), delay * 1000); else playClip('s' + name, X[name], { vol: vol }); return; }
    const alt = { ok: [[880, .14], [1318.5, .22]], bad: [[220, .2, 'triangle', .14], [174.6, .28, 'triangle', .12]], done: [[784, .14], [988, .14], [1175, .14], [1568, .3]] }[name];
    if (alt) tone(alt);
  }
  function tone(seq) {
    if (!S.set.sound) return;
    try {
      wakeAC(); if (!acRunning()) return;
      let t = AC.currentTime + .01;
      seq.forEach(x => {
        const o = AC.createOscillator(), g = AC.createGain();
        o.type = x[2] || 'sine'; o.frequency.value = x[0];
        g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(x[3] || .12, t + .015); g.gain.exponentialRampToValueAtTime(.0001, t + x[1]);
        o.connect(g); g.connect(AC.destination); o.start(t); o.stop(t + x[1] + .02); t += x[1] * .62;
      });
    } catch (e) { }
  }
  const sfxOk = () => sfx('ok');
  const sfxBad = () => sfx('bad');
  const sfxDone = () => sfx('done');
  // 揭晓：按稀有度（卡面等级和蜡封取高）选音效，越稀有越隆重
  const sfxRare = r => sfx(r >= 6 ? 'r6' : r >= 5 ? 'r5' : r >= 4 ? 'r4' : r >= 3 ? 'r3' : r >= 2 ? 'r2' : 'r0');

  /* ================= 通用 UI ================= */
  let toastT = null;
  function toast(msg) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, 2300); }
  function modal(title, text, acts) {
    $('#modalH').textContent = title; $('#modalP').textContent = text;
    const box = $('#modalActs'); box.innerHTML = '';
    acts.forEach(a => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'btn ' + (a.cls || 'soft'); b.textContent = a.label;
      b.addEventListener('click', () => { $('#modal').hidden = true; if (a.fn) a.fn(); });
      box.appendChild(b);
    });
    $('#modal').hidden = false;
  }
  function openSheet(html, onMount) {
    $('#sheetBody').innerHTML = html;
    $('#sheet').hidden = false;
    requestAnimationFrame(() => $('#sheet').classList.add('on'));
    if (onMount) onMount($('#sheetBody'));
  }
  function closeSheet() { const s = $('#sheet'); s.classList.remove('on'); setTimeout(() => { s.hidden = true; $('#sheetBody').innerHTML = ''; }, 220); }
  $('#sheet').addEventListener('click', e => { if (e.target.closest('[data-close-sheet]')) closeSheet(); });
  function segHTML(name, items, cur) {
    return `<div class="seg" data-seg="${name}">` + items.map(x => `<button type="button" data-v="${x[0]}" aria-pressed="${String(x[0]) === String(cur)}">${x[1]}</button>`).join('') + '</div>';
  }
  function bindSeg(root, name, fn) {
    const el = root.querySelector('[data-seg="' + name + '"]'); if (!el) return;
    el.addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      el.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      fn(b.dataset.v);
    });
  }
  function sw(on) { return `<button type="button" class="sw" role="switch" aria-checked="${on}"><i></i></button>`; }
  function wordData(k) { return WORDS[k]; }
  const tierCls = t => 't-' + t;

  /* ================= 视图切换 ================= */
  let view = 'home', prevView = 'home';
  const VIEWS = ['home', 'quiz', 'result', 'draw', 'album', 'gallery', 'book'];
  function show(v, opt) {
    if (view !== v) prevView = view;
    view = v;
    VIEWS.forEach(x => { $('#v-' + x).hidden = x !== v; });
    const tab = { home: 1, album: 1, book: 1 }[v];
    $('#tabs').hidden = !tab;
    $$('#tabs [data-tab-go]').forEach(b => b.setAttribute('aria-current', String(b.dataset.tabGo === v)));
    document.body.className = 'on-' + v;
    if (!(opt && opt.keepScroll)) window.scrollTo(0, 0);
    if (v === 'home') renderHome();
    if (v === 'album') renderAlbum();
    if (v === 'gallery') renderGallery();
    if (v === 'book') renderBook();
    if (v === 'draw') renderDraw();
  }
  $('#tabs').addEventListener('click', e => { const b = e.target.closest('[data-tab-go]'); if (b) show(b.dataset.tabGo); });
  document.addEventListener('click', e => {
    const a = e.target.closest('[data-act]'); if (!a) return;
    const act = a.dataset.act;
    if (act === 'settings') openSettings();
    else if (act === 'groups') openGroups();
    else if (act === 'draw') { e.stopPropagation(); show('draw'); }
    else if (act === 'odds') openOdds();
    else if (act === 'dust') openDust();
    else if (act === 'gallery') show('gallery');
    else if (act === 'album') show('album');
    else if (act === 'home') show('home');
    else if (act === 'test') startTest();
    else if (act === 'back') show(prevView && prevView !== view && prevView !== 'quiz' && prevView !== 'result' ? prevView : 'home');
  });

  /* ================= 首页 ================= */
  const MODES = [
    { id: 'en2zh', name: '英选中', ic: 'i-text-aa-d' },
    { id: 'zh2en', name: '中选英', ic: 'i-translate-d' },
    { id: 'spell', name: '看义拼写', ic: 'i-pencil-simple-line-d' },
    { id: 'listen', name: '听音拼写', ic: 'i-headphones-d' },
    { id: 'flash', name: '闪卡', ic: 'i-cards-d' },
    { id: 'wrong', name: '错词本', ic: 'i-notebook-d' }
  ];
  const TYPE_NAME = { en2zh: '英选中', zh2en: '中选英', spell: '看义拼写', listen: '听音拼写', flash: '闪卡', mix: '混合' };
  const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'], MO = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function todayWord() {
    const d = new Date(); const n = Math.floor(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 864e5);
    return WORDS[(n * 37) % N];
  }
  function renderHome() {
    const d = new Date();
    $('#hDate').textContent = WD[d.getDay()] + ', ' + MO[d.getMonth()] + ' ' + d.getDate();
    $('#hStreak').querySelector('b').textContent = streak();
    const tw = todayWord();
    $('#hQuote').innerHTML = `<div class="q-w">TODAY · ${esc(tw.w.toUpperCase())}</div><em>${esc(tw.en)}</em><span>${esc(tw.cn)}${tw.src ? ' <small>— ' + esc(tw.src) + '</small>' : ''}</span>`;
    $('#hQuote').dataset.k = tw.k;
    const g = S.cur, ws = groupWords(g), mm = masteredIn(g);
    $('#hCont').innerHTML = `<img class="charm" src="img/seal/star.webp" alt="">
      <div class="no">NO. ${pad3(ws[0].i)} – ${pad3(ws[ws.length - 1].i)}</div><h2>第 ${g + 1} 组</h2>
      <div class="ws">${ws.slice(0, 4).map(w => esc(w.w)).join(', ')}…</div>
      <div class="pg"><em><i style="width:${Math.round(mm / ws.length * 100)}%"></i></em><span><b>${mm}</b> / ${ws.length} 已掌握</span></div>
      <button type="button" class="btn dark" id="hGo">继续练习${icon('i-arrow-right')}</button>`;
    $('#hGo').addEventListener('click', () => startGroup(S.set.mode));
    $('#hTickets').textContent = ticketCount();
    $('#hGroupLab').textContent = '第 ' + (g + 1) + ' 组';
    const wn = wrongWords().length;
    $('#hModes').innerHTML = MODES.map(m => `<button type="button" class="m gl${S.set.mode === m.id ? ' on' : ''}" data-mode="${m.id}">${m.id === 'wrong' && wn ? `<span class="cnt">${wn}</span>` : ''}${icon(m.ic)}<b>${m.name}</b></button>`).join('');
    renderFan();
  }
  function renderFan() {
    const fan = $('#hFan'); fan.innerHTML = '';
    // 展示已收集的最稀有三张；还没有卡时展示样卡
    const owned = [];
    Object.keys(S.cards).forEach(k => ownVids(k).forEach(id => owned.push({ k: +k, id, r: C.BY_ID[id].rank })));
    owned.sort((a, b) => b.r - a.r);
    let three = owned.slice(0, 3);
    if (three.length < 3) {
      const sample = [{ k: 0, id: 'ssr1' }, { k: 3, id: 'x1' }, { k: 2, id: 'lr1' }];
      three = three.concat(sample.slice(three.length));
    }
    const pos = [[0, 22, -14], [52, 4, -2], [104, 16, 11]];
    [three[0], three[1], three[2]].forEach((c, i) => {
      const box = document.createElement('div'); box.className = 'fan-c';
      box.style.cssText = `left:${pos[i][0]}px;top:${pos[i][1]}px;transform:rotate(${pos[i][2]}deg)`;
      box.appendChild(CardKit.mini(c.id, WORDS[c.k], {}));
      fan.appendChild(box);
    });
  }
  $('#hModes').addEventListener('click', e => {
    const b = e.target.closest('[data-mode]'); if (!b) return;
    const m = b.dataset.mode;
    if (m === 'wrong') { startWrong(); return; }
    S.set.mode = m; save(); startGroup(m);
  });
  $('#hQuote').addEventListener('click', () => { const k = +$('#hQuote').dataset.k; speak(WORDS[k].w); openWord(k); });
  $('#hTest').addEventListener('click', e => { if (e.target.closest('[data-act]')) return; startTest(); });
  $('#hTest').addEventListener('keydown', e => { if (e.key === 'Enter') startTest(); });
  $('#hStreak').addEventListener('click', () => toast(S.today.d === dayKey() && S.today.n ? `今天已答 ${S.today.n} 题` : '今天还没练'));

  function openGroups() {
    let h = '<h3 class="sh-h">选择分组</h3><div class="grps">';
    for (let g = 0; g < NG; g++) {
      const ws = groupWords(g), mm = masteredIn(g), col = ws.filter(w => S.cards[w.k] && ownVids(w.k).length).length;
      h += `<button type="button" class="g${g === S.cur ? ' on' : ''}" data-g="${g}"><b>${pad2(g + 1)}</b><span>${ws[0].i}–${ws[ws.length - 1].i}</span><em><i style="width:${mm / ws.length * 100}%"></i></em>${col ? `<small>${icon('i-cards-d')}${col}</small>` : ''}</button>`;
    }
    h += '</div>';
    openSheet(h, root => {
      root.querySelector('.grps').addEventListener('click', e => {
        const b = e.target.closest('[data-g]'); if (!b) return;
        S.cur = +b.dataset.g; save(); closeSheet(); renderHome();
        toast('已切换到第 ' + (S.cur + 1) + ' 组');
      });
      const on = root.querySelector('.g.on'); if (on && on.scrollIntoView) setTimeout(() => on.scrollIntoView({ block: 'center' }), 60);
    });
  }

  function openSettings() {
    const st = S.set;
    const h = `<h3 class="sh-h">设置</h3>
      <div class="setr"><span>每轮题数</span>${segHTML('count', [[10, '10'], [20, '20'], [0, '整组']], st.count)}</div>
      <div class="setr"><span>出题顺序</span>${segHTML('order', [['rand', '随机'], ['seq', '顺序'], ['weak', '弱项优先']], st.order)}</div>
      <div class="setr"><span>自动朗读</span><span data-sw="auto">${sw(st.auto)}</span></div>
      <div class="setr"><span>答对自动跳</span><span data-sw="next">${sw(st.next)}</span></div>
      <div class="setr"><span>答题音效</span><span data-sw="sound">${sw(st.sound)}</span></div>
      <div class="setr"><span>单词发音</span><button type="button" class="btn soft sm" id="stVoice">${icon('i-speaker-high')}试听</button></div>
      <div class="setr danger"><button type="button" class="btn ghostd sm" id="stReset">清空学习记录</button><button type="button" class="btn ghostd sm" id="stResetAll">重置全部（含卡册）</button></div>`;
    openSheet(h, root => {
      bindSeg(root, 'count', v => { S.set.count = +v; save(); });
      bindSeg(root, 'order', v => { S.set.order = v; save(); });
      root.querySelectorAll('[data-sw]').forEach(x => x.addEventListener('click', () => {
        const key = x.dataset.sw; S.set[key] = !S.set[key]; save();
        x.querySelector('.sw').setAttribute('aria-checked', String(S.set[key]));
      }));
      root.querySelector('#stVoice').addEventListener('click', () => speak(todayWord().w));
      root.querySelector('#stReset').addEventListener('click', () => modal('清空学习记录？', '卡册和抽卡券会保留。', [
        { label: '先不清空' }, { label: '确认清空', cls: 'warn', fn: () => { S.prog = {}; S.days = []; S.today = { d: '', n: 0 }; save(); closeSheet(); renderHome(); toast('学习记录已清空'); } }]));
      root.querySelector('#stResetAll').addEventListener('click', () => modal('重置全部数据？', '卡册和抽卡券也会清空，无法撤销。', [
        { label: '先不重置' }, { label: '全部重置', cls: 'warn', fn: () => { S = normalize(null); S.welcome = true; save(); closeSheet(); renderHome(); toast('已重置'); } }]));
    });
  }

  /* ================= 来信：兑换码 =================
   * 入口藏在首页卡片的蜡封上：长按，或连点三下。校验见 gift.js（只存指纹），生成见 tools/gift_codes.py。
   * 同一批次每台手机只能领一次。 */
  (function () {
    const host = $('#hCont');
    let timer = null, taps = 0, tapT = null, fired = false;
    const start = e => {
      const c = e.target.closest('.charm'); if (!c) return;
      fired = false; c.classList.remove('pop'); c.classList.add('press');
      clearTimeout(timer); timer = setTimeout(() => { fired = true; c.classList.remove('press'); openLetter(); }, 650);
    };
    const end = () => {
      clearTimeout(timer);
      const c = host.querySelector('.charm.press'); if (!c) return;
      c.classList.remove('press'); c.classList.add('pop'); setTimeout(() => c.classList.remove('pop'), 460);
    };
    host.addEventListener('pointerdown', start);
    ['pointerup', 'pointercancel', 'pointerleave'].forEach(ev => host.addEventListener(ev, end));
    host.addEventListener('contextmenu', e => { if (e.target.closest('.charm')) e.preventDefault(); });
    host.addEventListener('click', e => {
      if (!e.target.closest('.charm') || fired) return;
      taps++; clearTimeout(tapT); tapT = setTimeout(() => { taps = 0; }, 900);
      if (taps >= 3) { taps = 0; openLetter(); }
    });
  })();
  function openLetter() {
    if (!window.GiftCode || !$('#letter').hidden) return;
    unlockAudio();
    const w = $('#letter');
    w.hidden = false; document.documentElement.classList.add('lock');
    $('#ltEnv').className = 'env';
    $('#ltForm').hidden = false; $('#ltDone').hidden = true; $('#ltErr').textContent = ''; $('#ltIn').value = '';
    requestAnimationFrame(() => w.classList.add('on'));
    sfx('flick');
  }
  function closeLetter() {
    const w = $('#letter'); w.classList.remove('on');
    setTimeout(() => {
      w.hidden = true;
      if ($('#reveal').hidden && $('#share').hidden && $('#viewer').hidden) document.documentElement.classList.remove('lock');
      if (view === 'home') renderHome();
    }, 250);
  }
  function redeem() {
    const r = GiftCode.parse($('#ltIn').value), env = $('#ltEnv');
    const fail = msg => { $('#ltErr').textContent = msg; env.classList.remove('shake'); void env.offsetWidth; env.classList.add('shake'); sfx('bad'); };
    if (!r.ok) { fail(r.err === 'format' ? '兑换码是 12 位' : r.err === 'expired' ? '这个兑换码已经过期了' : r.err === 'early' ? GiftCode.dayStr(r.from) + '起才能用' : '这个兑换码不对'); return; }
    if (S.gifts[r.batch]) { fail('这一批你已经领过了'); return; }
    S.gifts[r.batch] = { c: r.code, n: r.n, d: dayKey() };
    addTickets(r.n, 1);
    $('#ltIn').blur();
    $('#ltN').textContent = '×' + r.n; $('#ltN2').textContent = r.n;
    $('#ltForm').hidden = true;
    sfx('open');
    env.classList.add('crack');
    setTimeout(() => env.classList.add('open'), 280);
    setTimeout(() => env.classList.add('open2'), 560);
    setTimeout(() => { env.classList.add('out'); sfx('r3'); confettiBurst(4, '#ltCf', '#letter', .3); }, 720);
    setTimeout(() => { $('#ltDone').hidden = false; }, 1150);
  }
  $('#ltIn').addEventListener('input', e => { const el = e.target, f = GiftCode.fmt(el.value); if (el.value !== f) el.value = f; $('#ltErr').textContent = ''; });
  $('#ltIn').addEventListener('keydown', e => { if (e.key === 'Enter') redeem(); });
  $('#ltGo').addEventListener('click', redeem);
  $('#ltX').addEventListener('click', closeLetter);
  $('#ltKeep').addEventListener('click', closeLetter);
  $('#ltDraw').addEventListener('click', () => { closeLetter(); show('draw'); });

  /* ================= 答题 ================= */
  let Q = null;
  const senses = t => t.replace(/【[^】]*】/g, '').split(/[；;]/).map(x => x.trim()).filter(Boolean);
  const answers = w => [w.w].concat(w.alt).map(x => x.toLowerCase());
  const mainPos = w => (w.s[0] && w.s[0][0]) || '';
  const short = w => w.cp + ' ' + w.cm;
  function poolOrder(pool) {
    if (S.set.order === 'rand') return shuffle(pool);
    if (S.set.order === 'weak') {
      const sc = w => { const p = P(w.k); if (!p) return 1.5; return (inWrong(w.k) ? 3 : 0) + (isMastered(w.k) ? -2 : 1) + p.w * .5 - p.s * .3 + Math.random() * .8; };
      return pool.map(w => [sc(w), w]).sort((a, b) => b[0] - a[0]).map(x => x[1]);
    }
    return pool;
  }
  function startGroup(mode) {
    let pool = poolOrder(groupWords(S.cur));
    if (S.set.count) pool = pool.slice(0, S.set.count);
    begin({ kind: 'group', label: '第 ' + (S.cur + 1) + ' 组', mode, pool });
  }
  function startWrong() {
    const ws = wrongWords();
    if (!ws.length) { toast('错词本是空的'); return; }
    begin({ kind: 'wrong', label: '错词本', mode: 'mix', pool: shuffle(ws).slice(0, 20) });
  }
  function startTest() {
    begin({ kind: 'test', label: '全部测试', mode: 'test', pool: shuffle(WORDS).slice(0, 25) });
  }
  function begin(o) {
    const types = o.mode === 'test' ? ['en2zh', 'en2zh', 'zh2en', 'zh2en', 'spell'] : o.mode === 'mix' ? ['en2zh', 'zh2en', 'spell', 'listen'] : [o.mode];
    Q = { kind: o.kind, label: o.label, mode: o.mode, items: o.pool.map(w => ({ w, type: pick(types) })), i: 0, right: 0, clean: 0, combo: 0, best: 0, wrongs: [], newM: 0, t0: Date.now(), answered: 0 };
    unlockAudio(); getAC();
    show('quiz'); renderQ();
  }
  function gainNow() {
    if (!Q) return 0;
    if (Q.kind === 'test') return Q.right;
    if (Q.mode === 'flash') return 0;
    return Math.floor(Q.clean / 2);
  }
  function distractors(w, n, forType) {
    const tset = {}; senses(w.s.map(x => x[1]).join('；')).forEach(s => s.split('，').forEach(x => { tset[x] = 1; }));
    const pos = mainPos(w), mine = answers(w);
    const clash = c => {
      if (c.k === w.k || answers(c).some(a => mine.indexOf(a) >= 0)) return true;
      return senses(c.s.map(x => x[1]).join('；')).some(s => s.split('，').some(x => tset[x]));
    };
    let same = WORDS.filter(c => mainPos(c) === pos && !clash(c));
    if (same.length < n + 4) same = WORDS.filter(c => !clash(c));
    const out = [];
    if (forType === 'zh2en') {
      const sim = same.map(c => { let p = 0; while (p < c.w.length && p < w.w.length && c.w[p] === w.w[p]) p++; return [p * 2 - Math.abs(c.w.length - w.w.length) * .5 + Math.random(), c]; }).sort((a, b) => b[0] - a[0]).slice(0, 8);
      if (sim.length) out.push(pick(sim)[1]);
    } else {
      const near = same.filter(c => Math.abs(c.k - w.k) < 60);
      if (near.length) out.push(pick(near));
    }
    shuffle(same).forEach(c => { if (out.length < n && out.indexOf(c) < 0 && !out.some(o => short(o) === short(c))) out.push(c); });
    return out.slice(0, n);
  }
  function blankSentence(w) {
    const forms = answers(w);
    let s = w.en, done = false;
    const re = new RegExp('\\b(' + forms.map(f => f.replace(/[-]/g, '\\-')).join('|') + ')[a-z]*', 'i');
    s = s.replace(re, m => { done = true; return '_'.repeat(Math.min(8, Math.max(4, m.length))); });
    return done ? s : '';
  }
  function setTop() {
    const total = Q.items.length;
    $('#qCount').textContent = Math.min(Q.i + 1, total) + ' / ' + total;
    $('#qCombo').querySelector('b').textContent = Q.combo;
    const g = gainNow(); $('#qGain').hidden = !g; $('#qGain').querySelector('b').textContent = g;
  }
  function renderQ() {
    const it = Q.items[Q.i], w = it.w, total = Q.items.length;
    $('#qTrack').style.width = (Q.i / total * 100) + '%';
    setTop();
    $('#qFb').hidden = true; $('#qFb').classList.remove('on');
    it.done = false; it.hint = 0;
    const tag = `<div class="qtag">${esc(Q.label)} · ${TYPE_NAME[it.type]}</div>`;
    const spk = `<button type="button" class="spk gl" data-say aria-label="朗读">${icon('i-speaker-high')}</button>`;
    const stage = $('#qStage');
    if (it.type === 'en2zh' || it.type === 'zh2en') {
      const opts = shuffle([w].concat(distractors(w, 3, it.type)));
      it.opts = opts;
      const head = it.type === 'en2zh'
        ? `<div class="qc gl in">${spk}${tag}<div class="qw">${esc(w.w)}</div><div class="ipa">${esc(w.p)}</div></div>`
        : `<div class="qc gl in">${tag}<div class="qcn"><i>${esc(w.cp)}</i>${esc(w.cm)}</div><div class="qsub">${esc(w.s.map(x => x[0] + '. ' + senses(x[1]).slice(0, 2).join('；')).join('  '))}</div></div>`;
      stage.innerHTML = head + `<div class="opts" id="opts">${opts.map((o, j) => `<button type="button" class="op gl" data-j="${j}"><span class="k">${'ABCD'[j]}</span><span class="t${it.type === 'zh2en' ? ' en' : ''}">${esc(it.type === 'en2zh' ? short(o) : o.w)}</span></button>`).join('')}</div>`;
      $('#opts').addEventListener('click', e => { const b = e.target.closest('.op'); if (b) answerMC(+b.dataset.j); });
      if (it.type === 'en2zh' && S.set.auto) setTimeout(() => speak(w.w), 180);
    } else if (it.type === 'spell' || it.type === 'listen') {
      const L = w.w.length, bl = blankSentence(w);
      const head = it.type === 'spell'
        ? `<div class="qc gl in">${tag}<div class="qcn"><i>${esc(w.cp)}</i>${esc(w.cm)}</div>${bl ? `<div class="qbl">${esc(bl)}</div>` : ''}<div class="qhint">${L} 个字母</div></div>`
        : `<div class="qc gl in">${tag}<button type="button" class="listen" data-say aria-label="再听一遍">${icon('i-headphones-d')}</button><div class="qhint">${L} 个字母</div></div>`;
      stage.innerHTML = head + `<div class="spell">
        <div class="slots" id="slots">${'<span class="slot"></span>'.repeat(L)}<input id="spIn" type="text" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" maxlength="${Math.max.apply(null, answers(w).map(a => a.length))}" aria-label="输入单词"></div>
        <div class="sp-acts" id="spActs">
          <button type="button" class="btn soft" id="hintBtn">${icon('i-lightbulb')}提示</button>
          ${it.type === 'listen' ? `<button type="button" class="btn soft" id="peekBtn">${icon('i-eye')}看释义</button>` : ''}
          <button type="button" class="btn dark" id="checkBtn">检查${icon('i-check')}</button>
        </div><div class="peek" id="peek" hidden></div></div>`;
      const inp = $('#spIn');
      inp.addEventListener('input', paintSlots);
      inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); checkSpell(); } });
      $('#slots').addEventListener('click', () => inp.focus());
      $('#hintBtn').addEventListener('click', () => {
        if (it.done) return;
        const ans = w.w, v = inp.value.toLowerCase(); let p = 0;
        while (p < v.length && p < ans.length && v[p] === ans[p].toLowerCase()) p++;
        if (p >= ans.length) return;
        inp.value = ans.slice(0, p + 1); it.hint++; it.hintTo = Math.max(it.hintTo || 0, p + 1); paintSlots(); inp.focus();
      });
      if ($('#peekBtn')) $('#peekBtn').addEventListener('click', () => { const pk = $('#peek'); pk.hidden = false; pk.textContent = short(w); $('#peekBtn').disabled = true; });
      $('#checkBtn').addEventListener('click', checkSpell);
      paintSlots();
      setTimeout(() => { try { inp.focus({ preventScroll: true }); } catch (e) { inp.focus(); } }, 80);
      if (it.type === 'listen') setTimeout(sayListen, 260);
    } else if (it.type === 'flash') {
      stage.innerHTML = `<div class="flip" id="flip"><div class="flip-in">
          <div class="qc gl face">${spk}${tag}<div class="qw">${esc(w.w)}</div><div class="ipa">${esc(w.p)}</div></div>
          <div class="qc gl face back">${spk}${tag}<div class="qw sm">${esc(w.w)}</div><div class="qcn"><i>${esc(w.cp)}</i>${esc(w.cm)}</div>
            <div class="qline"><em>${esc(w.en)}</em><span>${esc(w.cn)}</span></div></div>
        </div></div>
        <div class="fbtns" id="fbtns">
          <button type="button" class="btn bad" data-r="0">不认识</button>
          <button type="button" class="btn soft" data-r="1">有点印象</button>
          <button type="button" class="btn good" data-r="2">认识</button>
        </div>`;
      $('#flip').addEventListener('click', e => { if (e.target.closest('[data-say]')) return; $('#flip').classList.toggle('on'); });
      $('#fbtns').addEventListener('click', e => { const b = e.target.closest('[data-r]'); if (b) answerFlash(+b.dataset.r); });
      if (S.set.auto) setTimeout(() => speak(w.w), 180);
    }
    stage.querySelectorAll('[data-say]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); if (it.type === 'listen') sayListen(); else speak(w.w); }));
  }
  function sayListen() { const b = $('.listen'); const w = Q.items[Q.i].w; if (b) b.classList.add('playing'); speak(w.w, () => { if (b) b.classList.remove('playing'); }); setTimeout(() => { if (b) b.classList.remove('playing'); }, 2500); }
  function paintSlots() {
    const it = Q.items[Q.i], inp = $('#spIn'); if (!inp) return;
    const v = inp.value.replace(/\s+/g, '');
    $$('#slots .slot').forEach((s, j) => { s.textContent = v[j] || ''; s.className = 'slot' + (j === v.length ? ' cur' : '') + (j < (it.hintTo || 0) ? ' hint' : ''); });
  }
  function bump(ok) {
    if (ok) { Q.combo++; Q.best = Math.max(Q.best, Q.combo); } else Q.combo = 0;
    const c = $('#qCombo'); c.classList.remove('bump'); void c.offsetWidth; if (ok && Q.combo > 1) c.classList.add('bump');
  }
  function settle(ok, it, opt) {
    opt = opt || {};
    it.done = true; Q.answered++;
    if (ok) { Q.right++; if (!opt.hint) Q.clean++; } else Q.wrongs.push(it.w);
    if (record(it.w.k, ok, opt)) Q.newM++;
    bump(ok);
    if (ok) sfxOk(); else sfxBad();
    $('#qTrack').style.width = ((Q.i + 1) / Q.items.length * 100) + '%';
    setTop();
  }
  function feedback(ok, w, extra) {
    const fb = $('#qFb');
    const last = Q.i + 1 >= Q.items.length;
    fb.className = 'fb gl-solid ' + (ok ? 'good' : 'bad');
    fb.innerHTML = `<div class="fb-h">${icon(ok ? 'i-check-circle-f' : 'i-x-circle-f')}${ok ? '答对了' : '答错了'}</div>
      <div class="fb-w"><b>${esc(w.w)}</b><span class="ipa">${esc(w.p)}</span><button type="button" class="spk sm gl" data-say2 aria-label="朗读">${icon('i-speaker-high')}</button></div>
      ${extra || ''}
      <div class="fb-m">${w.s.map(x => `<div><i>${esc(x[0])}.</i>${esc(senses(x[1]).join('；'))}</div>`).join('')}</div>
      <div class="fb-l"><em>${esc(w.en)}</em><span>${esc(w.cn)}${w.src ? ' — ' + esc(w.src) : ''}</span></div>
      <button type="button" class="btn dark wide" id="nextBtn">${last ? '看成绩' : '下一题'}${icon('i-arrow-right')}</button>`;
    fb.hidden = false; requestAnimationFrame(() => fb.classList.add('on'));
    fb.querySelector('[data-say2]').addEventListener('click', () => speak(w.w));
    $('#nextBtn').addEventListener('click', next);
  }
  function answerMC(j) {
    const it = Q.items[Q.i]; if (it.done) return;
    const o = it.opts[j], ok = o === it.w;
    const btns = $$('#opts .op');
    btns[j].classList.add(ok ? 'ok' : 'no');
    if (!ok) btns[it.opts.indexOf(it.w)].classList.add('ok');
    $('#opts').classList.add('locked');
    settle(ok, it);
    if (it.type === 'zh2en' || !ok) speak(it.w.w);
    feedback(ok, it.w);
    if (ok && S.set.next) Q.auto = setTimeout(next, 1200);
  }
  function checkSpell() {
    const it = Q.items[Q.i]; if (it.done) return;
    const inp = $('#spIn'); const v = inp.value.trim().toLowerCase();
    if (!v) { toast('先输入字母再检查'); inp.focus(); return; }
    const ok = answers(it.w).indexOf(v) >= 0, ans = it.w.w;
    $$('#slots .slot').forEach((s, j) => { s.textContent = ans[j]; s.className = 'slot ' + (ok ? 'g' : (v[j] === ans[j].toLowerCase() ? 'g' : 'r')); });
    inp.disabled = true; inp.blur();
    $('#spActs').hidden = true;
    settle(ok, it, { hint: it.hint > 0 });
    speak(it.w.w);
    const extra = ok ? (it.hint ? `<div class="fb-n">用了提示，不计入掌握</div>` : '') : `<div class="fb-n">你写的是 <s>${esc(v)}</s></div>`;
    feedback(ok, it.w, extra);
    if (ok && S.set.next && !it.hint) Q.auto = setTimeout(next, 1400);
  }
  function answerFlash(r) {
    const it = Q.items[Q.i]; if (it.done) return;
    if (r === 1) { it.done = true; Q.answered++; Q.wrongs.push(it.w); record(it.w.k, false, { soft: true }); bump(false); sfx('bad', .7); setTop(); }
    else settle(r === 2, it);
    const flip = $('#flip');
    $$('#fbtns .btn').forEach(b => { b.disabled = true; });
    if (!flip.classList.contains('on')) { flip.classList.add('on'); setTimeout(next, 1100); } else setTimeout(next, 300);
  }
  function next() {
    clearTimeout(Q.auto);
    if (view !== 'quiz') return;
    if (Q.i + 1 >= Q.items.length) { finish(); return; }
    Q.i++; renderQ(); window.scrollTo(0, 0);
  }
  $('#qQuit').addEventListener('click', () => {
    modal('结束这一轮？', Q.answered ? `已答 ${Q.answered} 题，照常结算。` : '还没有答题。', [
      { label: '继续答题' },
      { label: Q.answered ? '结束并结算' : '回到首页', cls: 'dark', fn: () => { clearTimeout(Q.auto); stopVoice(); if (Q.answered) { Q.items = Q.items.slice(0, Q.answered); finish(); } else show('home'); } }]);
  });
  document.addEventListener('keydown', e => {
    if (view !== 'quiz' || !Q || !$('#modal').hidden) return;
    const it = Q.items[Q.i]; if (!it) return;
    if (document.activeElement && document.activeElement.id === 'spIn') return;
    if ((it.type === 'en2zh' || it.type === 'zh2en') && !it.done) {
      const j = '1234'.indexOf(e.key) >= 0 ? '1234'.indexOf(e.key) : 'abcd'.indexOf(e.key.toLowerCase());
      if (j >= 0) { e.preventDefault(); answerMC(j); return; }
    }
    if (it.done && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); next(); }
  });

  /* ================= 结算 ================= */
  let LAST = null;
  function finish() {
    const total = Q.items.length, right = Q.right;
    const secs = Math.round((Date.now() - Q.t0) / 1000);
    const time = secs >= 60 ? Math.floor(secs / 60) + '′' + pad2(secs % 60) + '″' : secs + '″';
    const uniqWrong = []; const seen = {};
    Q.wrongs.forEach(w => { if (!seen[w.k]) { seen[w.k] = 1; uniqWrong.push(w); } });
    let gain = 0, m = 1, bonus = 0;
    if (Q.kind === 'test') {
      m = multOf(right, total); bonus = bonusOf(right, total); gain = right + bonus;
      S.stat.tests++; S.stat.best = Math.max(S.stat.best, Math.round(right / total * 100));
    } else gain = gainNow();
    addTickets(gain, m);
    save();
    sfxDone();
    LAST = { kind: Q.kind, label: Q.label, mode: Q.mode, total, right, pct: total ? Math.round(right / total * 100) : 0, best: Q.best, newM: Q.newM, time, gain, m, bonus, wrongs: uniqWrong, words: Q.items.map(x => x.w), date: new Date() };
    show('result');
    renderResult();
  }
  function ladderHTML(m) {
    const r = rates(m);
    return ORDER.slice().reverse().map(t => {
      const up = m > 1 && BOOSTED.indexOf(t) >= 0, down = m > 1 && t === 'N';
      const v = TIER[t];
      const name = t === 'SECRET' ? `隐藏款${m > 1 ? ' ' + fmtM(m) : ''}` : v.v[0].en + (v.v.length > 1 ? '…' : '');
      const bw = x => Math.max(1.5, Math.min(100, x / 40 * 100));
      return `<div class="lr${up ? ' up' : ''}"><span class="t">${t}</span><span class="n">${esc(name)}</span><span class="bar">${m > 1 && (up || down) ? `<i style="width:${bw(BASE[t])}%"></i>` : ''}<u style="width:${bw(r[t])}%"></u></span><span class="v">${m > 1 && (up || down) ? `<s>${String(BASE[t])}</s>` : ''}<b>${fmtP(r[t])}</b></span></div>`;
    }).join('');
  }
  const RULE_HTML = '正确率 <b>60%</b> 以上 ×1.2 · <b>80%</b> 以上 ×1.5 · <b>90%</b> 以上 ×2 · <b>全对</b> ×3，隐藏款也 ×3<br>十连必出 SR 以上 · 60 抽必出 SSR 以上 · 150 抽必出 UR 以上';
  function renderResult() {
    const R = LAST, body = $('#rBody');
    const wl = R.wrongs.length ? `<div class="wl gl"><h4>${icon('i-lightbulb')}错词</h4>${R.wrongs.map(w => `<button type="button" class="wr" data-k="${w.k}"><b>${esc(w.w)}</b><span>${esc(short(w))}</span></button>`).join('')}</div>` : '';
    if (R.kind === 'test') {
      body.innerHTML = `<div class="rh"><div class="k">全部测试</div><div class="sc">${R.right}<small>/ ${R.total}</small></div>
          <div class="acc">${icon('i-sparkle-f')}正确率 ${R.pct}%</div></div>
        <div class="gain gl"><img src="img/icon3d/ticket.webp" alt=""><div><b>抽卡券 ×${R.gain}</b>${R.m > 1 ? `<span>稀有加成 ${fmtM(R.m)}</span>` : ''}</div><button type="button" class="odds-l" data-act="odds">概率</button></div>
        ${wl}
        <div class="ra"><button type="button" class="btn soft" id="rShare">${icon('i-share-network')}晒成绩</button><button type="button" class="btn holo" data-act="draw">去抽卡 · ${ticketCount()} 张${icon('i-arrow-right')}</button></div>
        <button type="button" class="link" data-act="home">回到首页</button>`;
    } else {
      body.innerHTML = `<div class="rh"><div class="k">${esc(R.label)} · ${TYPE_NAME[R.mode] || ''} · 本轮成绩</div><div class="sc">${R.right}<small>/ ${R.total}</small></div>
          <div class="kv gl"><div><b>${R.pct}%</b><span>正确率</span></div><div><b>${R.best}</b><span>最长连对</span></div><div><b>${R.newM}</b><span>新掌握</span></div><div><b>${R.time}</b><span>用时</span></div></div></div>
        <div class="gain gl">${R.gain ? `<img src="img/icon3d/ticket.webp" alt=""><div><b>抽卡券 ×${R.gain}</b></div>` : `<img src="img/icon3d/cards.webp" alt=""><div><b>${R.mode === 'flash' ? '闪卡不计抽卡券' : '这轮没有抽卡券'}</b></div>`}</div>
        ${wl}
        <div class="ra">
          ${R.wrongs.length ? `<button type="button" class="btn soft" id="rRedo">${icon('i-arrow-counter-clockwise')}重练错词</button>` : `<button type="button" class="btn soft" id="rAgain">${icon('i-shuffle')}再来一轮</button>`}
          <button type="button" class="btn ${ticketCount() ? 'holo' : 'dark'}" ${ticketCount() ? 'data-act="draw"' : 'data-act="test"'}>${ticketCount() ? `去抽卡 · ${ticketCount()} 张` : '去全部测试'}${icon('i-arrow-right')}</button>
        </div>
        <div class="links"><button type="button" class="link" id="rShare">${icon('i-share-network')}晒成绩</button><button type="button" class="link" data-act="home">回到首页</button></div>`;
      if ($('#rRedo')) $('#rRedo').addEventListener('click', () => begin({ kind: 'wrong', label: '重练错词', mode: R.mode === 'flash' ? 'en2zh' : R.mode, pool: shuffle(R.wrongs) }));
      if ($('#rAgain')) $('#rAgain').addEventListener('click', () => startGroup(R.mode === 'mix' ? S.set.mode : R.mode));
    }
    body.querySelectorAll('.wr').forEach(b => b.addEventListener('click', () => openWord(+b.dataset.k)));
    $('#rShare').addEventListener('click', () => shareResult(LAST));
  }

  /* ================= 抽卡页 ================= */
  function renderDraw() {
    const n = ticketCount(), b = bestBatch();
    const toSR = PITY.sr - S.pity.sr, toSSR = PITY.ssr - S.pity.ssr, toUR = PITY.ur - S.pity.ur;
    $('#dBody').innerHTML = `
      <div class="rtop"><button type="button" class="cl" data-act="back" aria-label="返回">${icon('i-x')}</button><div class="tkt">${icon('i-ticket-f')}抽卡券<b>${n}</b></div></div>
      <div class="dt"><div class="r">TIRAGE · 抽卡</div><div class="f">Les cartes</div></div>
      <div class="pack${n ? '' : ' empty'}" id="dPack"><i class="pack-glow"></i><img src="img/pack.webp" alt="卡包"></div>
      <div class="dinfo">${n ? (b.m > 1 ? `<b>${fmtM(b.m)}</b> 加成券` : '基础概率') : '没有抽卡券'}<br>
        <span>保底 SR ${toSR} · SSR ${toSSR} · UR ${toUR}</span></div>
      <div class="dacts">${n ? `<button type="button" class="btn ghost" id="dOne">单抽 · 1 张</button><button type="button" class="btn holo" id="dTen"${n < 10 ? ' disabled' : ''}>十连 · 10 张</button>` : `<button type="button" class="btn holo wide" data-act="test">去全部测试${icon('i-arrow-right')}</button>`}</div>
      <div class="dlinks">
        <button type="button" data-act="odds">${icon('i-chart-bar')}概率与保底</button>
        <button type="button" data-act="dust"><img src="img/icon3d/stardust.webp" alt="">星尘 ${S.dust}</button>
        <button type="button" data-act="gallery">${icon('i-cards-d')}卡面图鉴</button>
      </div>`;
    if ($('#dOne')) { $('#dOne').addEventListener('click', () => doDraw(1)); $('#dTen').addEventListener('click', () => doDraw(10)); }
    if ($('#dPack') && n) $('#dPack').addEventListener('click', () => doDraw(1));
  }
  function doDraw(n) {
    if (ticketCount() < n) { toast('抽卡券不够了'); return; }
    unlockAudio();
    sfx('open');
    const res = [];
    for (let i = 0; i < n; i++) { const r = drawOne(); if (r) res.push(r); }
    save();
    if (n === 1) revealOne(res[0]); else revealTen(res);
  }
  function openOdds() {
    const b = bestBatch(), m = b ? b.m : 1;
    openSheet(`<h3 class="sh-h">概率与保底<span>${m > 1 ? '当前使用 ' + fmtM(m) + ' 加成券' : '当前为基础概率'}</span></h3>
      <div class="ladder plain">${ladderHTML(m)}</div>
      <h3 class="sh-h sm">蜡封<span>独立抽取</span></h3>
      <div class="sealodds">${SEAL_TIERS.slice().reverse().map(t => `<div class="so"><b>${t.cn}</b><span>${t.v.map(x => `<img src="img/seal/${x.id}.webp" alt="">`).join('')}</span><em>${fmtP(t.rate)}</em></div>`).join('')}</div>
      <div class="rule">${RULE_HTML}<br>重复的卡化为星尘，${DUST_PER_TICKET} 星尘换 1 张抽卡券</div>`);
  }
  function openDust() {
    const can = Math.floor(S.dust / DUST_PER_TICKET);
    openSheet(`<h3 class="sh-h">星尘</h3>
      <div class="dust-box"><img src="img/icon3d/stardust.webp" alt=""><b>${S.dust}</b><span>${DUST_PER_TICKET} 星尘 = 1 张抽卡券</span></div>
      <div class="sh-acts"><button type="button" class="btn soft" id="duOne"${can ? '' : ' disabled'}>兑换 1 张</button><button type="button" class="btn dark" id="duAll"${can ? '' : ' disabled'}>全部兑换 · ${can} 张</button></div>`, root => {
      const ex = k => { if (!k) return; S.dust -= k * DUST_PER_TICKET; addTickets(k, 1); save(); closeSheet(); toast('兑换了 ' + k + ' 张抽卡券'); if (view === 'draw') renderDraw(); if (view === 'album') renderAlbum(); };
      root.querySelector('#duOne').addEventListener('click', () => ex(Math.min(1, can)));
      root.querySelector('#duAll').addEventListener('click', () => ex(can));
    });
  }

  /* ---------- 揭晓 ---------- */
  // 轻量彩纸（Canvas 2D，不依赖 Worker）
  const REDUCE = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  function confettiBurst(rank, cvSel, hostSel, yAt) {
    if (REDUCE) return;
    const c = $(cvSel || '#cf'), host = $(hostSel || '#reveal'), dpr = Math.min(2, window.devicePixelRatio || 1), W = window.innerWidth, H = window.innerHeight;
    c.width = W * dpr; c.height = H * dpr;
    const ctx = c.getContext('2d'); if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const colors = rank >= 6 ? ['#E9E6FF', '#D6DDFF', '#F9D6E6', '#FFFFFF', '#C9C3F5', '#F4DDA8'] : ['#F9C6DA', '#DCCBFA', '#BFDDF8', '#C9F2E2', '#FAE6BE', '#FFFFFF'];
    const ps = [];
    for (let i = 0; i < (rank >= 5 ? 130 : 80); i++) {
      const a = Math.random() * Math.PI * 2, sp = 4 + Math.random() * 9;
      ps.push({ x: W / 2, y: H * (yAt || .45), vx: Math.cos(a) * sp, vy: Math.sin(a) * sp - 5, s: 4 + Math.random() * 5, c: pick(colors), r: Math.random() * 6, vr: (Math.random() - .5) * .3, sq: Math.random() < .5, life: 0 });
    }
    const step = () => {
      ctx.clearRect(0, 0, W, H);
      let alive = 0;
      ps.forEach(p => {
        p.vy += .22; p.vx *= .985; p.vy *= .985; p.x += p.vx; p.y += p.vy; p.r += p.vr; p.life++;
        const al = 1 - p.life / 170;
        if (al <= 0 || p.y > H + 20) return;
        alive++;
        ctx.globalAlpha = al; ctx.fillStyle = p.c;
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r);
        if (p.sq) ctx.fillRect(-p.s / 2, -p.s / 3, p.s, p.s * .66); else { ctx.beginPath(); ctx.arc(0, 0, p.s / 2, 0, 6.283); ctx.fill(); }
        ctx.restore();
      });
      ctx.globalAlpha = 1;
      if (alive && !host.hidden) requestAnimationFrame(step); else ctx.clearRect(0, 0, W, H);
    };
    requestAnimationFrame(step);
  }
  function revealOpen(cls) {
    const r = $('#reveal'); r.hidden = false; r.className = 'ov dark bg-reveal ' + (cls || '');
    document.documentElement.classList.add('lock');
  }
  function revealClose() {
    $('#reveal').hidden = true; $('#rvBody').innerHTML = '';
    document.documentElement.classList.remove('lock');
    if (view === 'draw') renderDraw(); else if (view === 'album') renderAlbum(); else if (view === 'home') renderHome();
  }
  function revealOne(r) {
    const v = C.BY_ID[r.vid], t = TIER[r.tier], w = WORDS[r.k];
    revealOpen('t-' + r.tier + ' stage-pre');
    const nth = tierOwned(r.tier);
    $('#rvBody').innerHTML = `
      <div class="rtop"><button type="button" class="cl" id="rvX" aria-label="关闭">${icon('i-x')}</button><div class="tkt">${icon('i-ticket-f')}抽卡券<b>${ticketCount()}</b></div></div>
      <div class="orb"><i></i></div>
      <div class="rl"><div class="r">${r.tier === 'SECRET' ? 'S E C R E T' : r.tier} · ${t.cn}</div><div class="f">${esc(v.en)}</div><div class="c">${esc(v.cn)}</div></div>
      <div class="stage${v.land ? ' land' : ''}" id="rvStage"></div>
      <div class="rinfo">${t.cn} · ${SEAL[r.seal].tcn}「${SEAL[r.seal].cn}」${r.pity ? ' · ' + r.pity + ' 保底' : ''}<br>
        ${r.dup ? `重复获得 · 星尘 +${r.dust}` : r.newCard ? (r.rank >= 3 ? `这是你卡册里的第 <b>${nth}</b> 张${t.cn}` : `新卡 · 已放进卡册第 ${w.g} 页`) : `新蜡封 · ${SEAL[r.seal].tcn}「${SEAL[r.seal].cn}」`}</div>
      <div class="racts"><button type="button" class="btn ghost" id="rvShare">晒这张卡</button><button type="button" class="btn holo" id="rvOk">${ticketCount() ? '再抽一张' : '收进卡册'}</button></div>`;
    const stage = $('#rvStage');
    const made = CardKit.make(r.vid, w, { interactive: true, lit: true, seal: r.seal });
    stage.appendChild(made.el);
    CardKit.fit(stage, r.vid);
    $('#rvX').addEventListener('click', revealClose);
    $('#rvShare').addEventListener('click', () => shareCard(r.k, r.vid, r.seal));
    $('#rvOk').addEventListener('click', () => { if (ticketCount()) { revealClose(); doDraw(1); } else { revealClose(); show('album'); } });
    const hype = Math.max(r.rank, r.srank + 2);
    const delay = hype >= 4 ? 1500 : hype >= 3 ? 1100 : 700;
    if (hype >= 3) sfx('charge', hype >= 5 ? 1 : .8, (delay - 1050) / 1000);
    if (r.srank >= 1) sfx('stamp', .8, delay / 1000 + .5);
    setTimeout(() => {
      const ov = $('#reveal'); ov.classList.remove('stage-pre'); ov.classList.add('stage-on');
      sfxRare(hype);
      if (hype >= 3) confettiBurst(hype);
    }, delay);
  }
  function revealTen(list) {
    revealOpen('ten');
    const score = x => x.rank * 10 + x.srank;
    let best = list[0]; list.forEach(x => { if (score(x) > score(best)) best = x; });
    const fresh = list.filter(x => !x.dup).length, dust = list.reduce((a, x) => a + x.dust, 0);
    $('#rvBody').innerHTML = `
      <div class="rtop"><button type="button" class="cl" id="rvX" aria-label="关闭">${icon('i-x')}</button><div class="tkt">${icon('i-ticket-f')}抽卡券<b>${ticketCount()}</b></div></div>
      <div class="rl"><div class="r">DIX CARTES · 十连</div><div class="f">${esc(C.BY_ID[best.vid].en)}</div><div class="c">本次最佳 · ${best.tier} ${TIER[best.tier].cn} · ${SEAL[best.seal].tcn}</div></div>
      <div class="tgrid" id="tGrid"></div>
      <div class="rinfo">新卡 <b>${fresh}</b> 张${dust ? ` · 星尘 +${dust}` : ''}</div>
      <div class="racts"><button type="button" class="btn ghost" id="rvOk">收进卡册</button><button type="button" class="btn holo" id="rvAgain"${ticketCount() >= 10 ? '' : ' disabled'}>再来十连</button></div>`;
    const grid = $('#tGrid');
    list.forEach((r, i) => {
      const cell = document.createElement('button'); cell.type = 'button';
      cell.className = 'tc' + (r === best && r.rank >= 3 ? ' best' : '');
      cell.style.animationDelay = (i * 110) + 'ms';
      cell.appendChild(CardKit.mini(r.vid, WORDS[r.k], { seal: r.seal }));
      if (!r.dup) cell.insertAdjacentHTML('beforeend', '<i class="tc-new">NEW</i>');
      cell.addEventListener('click', () => openViewer(r.k, r.vid, r.seal));
      grid.appendChild(cell);
    });
    $('#rvX').addEventListener('click', revealClose);
    $('#rvOk').addEventListener('click', () => { revealClose(); show('album'); });
    $('#rvAgain').addEventListener('click', () => { revealClose(); doDraw(10); });
    const bh = Math.max(best.rank, best.srank + 2);
    list.forEach((x, i) => sfx('flick', .6, .15 + i * .11));
    if (bh >= 3) sfx('charge', .8, .15);
    setTimeout(() => { sfxRare(bh); if (bh >= 3) confettiBurst(bh); }, 1200);
  }

  /* ================= 卡片详情 ================= */
  let viewerCard = null;
  function openViewer(k, vid, seal) {
    const w = WORDS[k], owned = ownVids(k);
    if (!vid) vid = bestVid(k);
    if (!vid) return;
    if (!seal || ownSeals(k, vid).indexOf(seal) < 0) seal = bestSeal(k, vid);
    const seals = ownSeals(k, vid).sort((a, b) => SEAL[b].rank - SEAL[a].rank);
    const v = C.BY_ID[vid], t = TIER[v.tier];
    const vw = $('#viewer'); vw.hidden = false; vw.className = 'ov dark t-' + v.tier;
    document.documentElement.classList.add('lock');
    const chips = owned.slice().sort((a, b) => C.BY_ID[b].rank - C.BY_ID[a].rank).map(id => { const x = C.BY_ID[id]; return `<button type="button" class="vchip${id === vid ? ' on' : ''}" data-vid="${id}"><b>${x.tier}</b>${esc(x.cn)}${S.cards[k][id].n > 1 ? ' ×' + S.cards[k][id].n : ''}</button>`; }).join('');
    const schips = seals.map(id => `<button type="button" class="schip${id === seal ? ' on' : ''}" data-seal="${id}"><img src="img/seal/${id}.webp" alt="">${SEAL[id].tcn}·${esc(SEAL[id].cn)}</button>`).join('');
    $('#vwBody').innerHTML = `
      <div class="rtop"><button type="button" class="cl" id="vwX" aria-label="关闭">${icon('i-x')}</button><div class="tkt">${esc(v.tier)} · ${t.cn}</div></div>
      <div class="stage${v.land ? ' land' : ''}" id="vwStage"></div>
      <div class="vinfo"><div class="vw-w"><b>${esc(w.w)}</b><span>${esc(w.p)}</span><button type="button" class="spk sm" id="vwSay" aria-label="朗读">${icon('i-speaker-high')}</button></div>
        <div class="vw-m">${esc(short(w))}</div>
        ${owned.length > 1 ? `<div class="vchips">${chips}</div>` : ''}
        <div class="schips">${schips}</div></div>
      <div class="racts"><button type="button" class="btn ghost" id="vwWord">单词详情</button><button type="button" class="btn holo" id="vwShare">晒这张卡</button></div>`;
    if (viewerCard) { try { viewerCard.destroy(); } catch (e) { } }
    const made = CardKit.make(vid, w, { interactive: true, lit: true, seal });
    viewerCard = made.card;
    $('#vwStage').appendChild(made.el);
    CardKit.fit($('#vwStage'), vid);
    $('#vwX').addEventListener('click', closeViewer);
    $('#vwSay').addEventListener('click', () => speak(w.w));
    $('#vwShare').addEventListener('click', () => shareCard(k, vid, seal));
    $('#vwWord').addEventListener('click', () => { closeViewer(); openWord(k); });
    $$('#vwBody .vchip').forEach(b => b.addEventListener('click', () => openViewer(k, b.dataset.vid)));
    $$('#vwBody .schip').forEach(b => b.addEventListener('click', () => openViewer(k, vid, b.dataset.seal)));
  }
  function closeViewer() {
    if (viewerCard) { try { viewerCard.destroy(); } catch (e) { } viewerCard = null; }
    $('#viewer').hidden = true; $('#vwBody').innerHTML = '';
    if ($('#reveal').hidden) document.documentElement.classList.remove('lock');
  }

  /* ================= 卡册 ================= */
  let albumPage = null;
  function renderAlbum() {
    if (albumPage == null) albumPage = S.cur;
    const g = albumPage, ws = groupWords(g);
    const counts = ORDER.map(t => [t, tierOwned(t)]).reverse();
    const col = ws.filter(w => ownVids(w.k).length).length;
    $('#aBody').innerHTML = `
      <header class="bh"><h2>卡册</h2><span class="bh-c"><b>${collectedWords()}</b> / ${N} 词 · 卡面 <b>${collectedVariants()}</b> / 18 · 蜡封 <b>${Object.keys(sealsOwned()).length}</b> / ${Object.keys(SEAL).length}</span></header>
      <div class="rar">${counts.map(x => `<span class="gl ${tierCls(x[0])}"><i></i>${TIER[x[0]].cn} ${x[1]}</span>`).join('')}</div>
      <div class="pagec gl" id="aPage">
        <div class="pt"><span>第 ${g + 1} 组<small>No.${pad3(ws[0].i)}–${pad3(ws[ws.length - 1].i)}</small></span><span><b>${col}</b> / ${ws.length}</span></div>
        <div class="slots4" id="aSlots"></div>
        <div class="pager"><button type="button" class="ibtn" id="aPrev" aria-label="上一组"${g ? '' : ' disabled'}>${icon('i-caret-left')}</button><span>${pad2(g + 1)} / ${NG}</span><button type="button" class="ibtn" id="aNext" aria-label="下一组"${g < NG - 1 ? '' : ' disabled'}>${icon('i-caret-right')}</button></div>
      </div>
      <div class="bts">
        <button type="button" class="btn soft" data-act="gallery">${icon('i-cards-d')}图鉴</button>
        <button type="button" class="btn soft" data-act="odds">${icon('i-chart-bar')}概率与保底</button>
        <button type="button" class="btn soft" data-act="dust"><img src="img/icon3d/stardust.webp" alt="">星尘 ${S.dust}</button>
      </div>
      <button type="button" class="btn holo wide" data-act="draw">${icon('i-ticket-f')}去抽卡 · ${ticketCount()} 张</button>`;
    const slots = $('#aSlots');
    ws.forEach(w => {
      const s = document.createElement('button'); s.type = 'button'; s.className = 'sl';
      const vid = bestVid(w.k);
      if (vid) { s.appendChild(CardKit.mini(vid, w, { seal: bestSeal(w.k, vid) })); s.addEventListener('click', () => openViewer(w.k, vid)); }
      else { s.classList.add('e'); s.innerHTML = `<span>${pad3(w.i)}</span>`; s.addEventListener('click', () => openWord(w.k)); }
      slots.appendChild(s);
    });
    $('#aPrev').addEventListener('click', () => { albumPage = Math.max(0, albumPage - 1); renderAlbum(); });
    $('#aNext').addEventListener('click', () => { albumPage = Math.min(NG - 1, albumPage + 1); renderAlbum(); });
    swipe($('#aPage'), dir => { const n = albumPage + dir; if (n >= 0 && n < NG) { albumPage = n; renderAlbum(); } });
  }
  function swipe(el, fn) {
    let x0 = null, y0 = 0;
    el.addEventListener('touchstart', e => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
    el.addEventListener('touchend', e => {
      if (x0 == null) return;
      const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0; x0 = null;
      if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) fn(dx < 0 ? 1 : -1);
    }, { passive: true });
  }

  /* ================= 图鉴 ================= */
  const SAMPLE = { x1: 3, x2: 13, lr1: 2, lr2: 14, ur1: 18, ur2: 17, ssr1: 0, ssr2: 1, ssr3: 19, sr1: 7, sr2: 5, sr3: 11, r1: 8, r2: 4, r3: 12, n1: 9, n2: 10, n3: 15 };
  let galleryCards = [];
  function renderGallery() {
    galleryCards.forEach(c => { try { c.destroy(); } catch (e) { } }); galleryCards = [];
    const owned = {}; Object.keys(S.cards).forEach(k => ownVids(k).forEach(id => { if (!owned[id]) owned[id] = +k; }));
    const body = $('#gBody');
    body.innerHTML = `<div class="rtop"><button type="button" class="cl" data-act="back" aria-label="返回">${icon('i-arrow-left')}</button><div class="tkt">已解锁 <b>${Object.keys(owned).length}</b> / 18</div></div>
      <h1 class="gh">图鉴</h1><div class="gsub">Sept niveaux · dix-huit finitions</div><div id="gRows"></div>`;
    const rows = $('#gRows');
    C.TIERS.slice().reverse().forEach(t => {
      const row = document.createElement('div'); row.className = 'grow ' + tierCls(t.t);
      row.innerHTML = `<div class="glab"><b>${t.t}</b><span>${t.cn} · ${t.v.length} 款</span></div><div class="gcards"></div>`;
      const cs = row.querySelector('.gcards');
      t.v.forEach(v => {
        const cell = document.createElement('div'); cell.className = 'gcell' + (v.land ? ' land' : '');
        const box = document.createElement('div'); box.className = 'gbox';
        cell.appendChild(box);
        cell.insertAdjacentHTML('beforeend', `<p>${esc(v.en)}<span>${esc(v.cn)}</span></p>`);
        cs.appendChild(cell);
        if (owned[v.id] != null) {
          const made = CardKit.make(v.id, WORDS[owned[v.id]], { seal: bestSeal(owned[v.id], v.id) });
          galleryCards.push(made.card);
          box.appendChild(made.el);
          cell.addEventListener('click', () => openViewer(owned[v.id], v.id));
        } else {
          box.appendChild(CardKit.mini(v.id, null, { cls: 'locked' }));
          box.insertAdjacentHTML('beforeend', `<i class="lock">?</i>`);
          cell.addEventListener('click', () => toast(`${t.t} ${t.cn}「${v.cn}」还没抽到`));
        }
      });
      rows.appendChild(row);
    });
    const so = sealsOwned();
    rows.insertAdjacentHTML('beforeend', `<h2 class="gh2">蜡封图鉴<span>已收集 ${Object.keys(so).length} / ${Object.keys(SEAL).length}</span></h2><div class="gsub">Cachets de cire</div>` +
      SEAL_TIERS.slice().reverse().map(t => `<div class="grow"><div class="glab"><b>${t.cn}</b><span>${t.v.length} 款</span></div><div class="gseals">` +
        t.v.map(x => `<div class="gseal${so[x.id] ? '' : ' locked'}"><img src="img/seal/${x.id}.webp" alt=""><p>${esc(x.cn)}</p></div>`).join('') + '</div></div>').join(''));
    requestAnimationFrame(() => $$('#gRows .gcell').forEach(cell => { const box = cell.querySelector('.gbox'); const hc = box.querySelector('.holo-card'); if (hc) { const vid = Array.prototype.slice.call(hc.classList).filter(c => c.indexOf('v-') === 0)[0].slice(2); CardKit.fit(box, vid); } }));
  }

  /* ================= 词表 ================= */
  const BF = { q: '', f: 'all', g: -1, limit: 60 };
  function renderBook() {
    const cnt = { all: N, w: 0, l: 0, m: 0, new: 0 };
    WORDS.forEach(w => { cnt[status(w.k)]++; });
    $('#bChips').innerHTML = [['all', '全部'], ['w', '错词本'], ['l', '学习中'], ['m', '已掌握'], ['new', '未学']].map(x => `<button type="button" class="fchip" data-f="${x[0]}" aria-pressed="${BF.f === x[0]}">${x[1]}<em>${cnt[x[0]]}</em></button>`).join('');
    $('#bGroup').firstChild.textContent = BF.g < 0 ? '全部 35 组' : '第 ' + (BF.g + 1) + ' 组';
    renderList();
  }
  function filtered() {
    const q = BF.q.trim().toLowerCase();
    let ws = BF.g >= 0 ? groupWords(BF.g) : WORDS;
    if (BF.f !== 'all') ws = ws.filter(w => status(w.k) === BF.f);
    if (q) ws = ws.filter(w => w.w.toLowerCase().indexOf(q) >= 0 || w.alt.some(a => a.indexOf(q) >= 0) || w.cm.indexOf(q) >= 0 || w.s.some(s => s[1].indexOf(q) >= 0));
    return ws;
  }
  function renderList() {
    const ws = filtered();
    $('#bCount').textContent = '共 ' + ws.length + ' 词';
    const list = $('#bList');
    if (!ws.length) { list.innerHTML = `<div class="empty">${BF.f === 'w' ? '错词本是空的' : '没有找到'}</div>`; $('#bMore').hidden = true; return; }
    const st = { new: '', w: 'w', l: 'l', m: 'm' };
    list.innerHTML = ws.slice(0, BF.limit).map(w => {
      const vid = bestVid(w.k);
      return `<div class="row gl" data-k="${w.k}"><span class="no"><i class="st ${st[status(w.k)]}"></i>${w.i}</span>
        <div class="wd"><b>${esc(w.w)}</b><span>${esc(w.p)}</span><p>${esc(short(w))}</p></div>
        ${vid ? `<span class="own ${tierCls(C.BY_ID[vid].tier)}">${C.BY_ID[vid].tier}</span>` : ''}
        <button type="button" class="spk sm" data-spk aria-label="朗读">${icon('i-speaker-high')}</button></div>`;
    }).join('');
    $('#bMore').hidden = ws.length <= BF.limit;
  }
  let qT = null;
  $('#bQ').addEventListener('input', e => { clearTimeout(qT); qT = setTimeout(() => { BF.q = e.target.value; BF.limit = 60; renderList(); }, 160); });
  $('#bChips').addEventListener('click', e => { const b = e.target.closest('.fchip'); if (!b) return; BF.f = b.dataset.f; BF.limit = 60; $$('#bChips .fchip').forEach(x => x.setAttribute('aria-pressed', String(x === b))); renderList(); });
  $('#bMore').addEventListener('click', () => { BF.limit += 80; renderList(); });
  $('#bList').addEventListener('click', e => {
    const row = e.target.closest('.row'); if (!row) return;
    const k = +row.dataset.k;
    if (e.target.closest('[data-spk]')) { speak(WORDS[k].w); return; }
    openWord(k);
  });
  $('#bGroup').addEventListener('click', () => {
    let h = '<h3 class="sh-h">按分组查看</h3><div class="grps"><button type="button" class="g' + (BF.g < 0 ? ' on' : '') + '" data-g="-1"><b>全部</b><span>688 词</span></button>';
    for (let g = 0; g < NG; g++) { const ws = groupWords(g); h += `<button type="button" class="g${g === BF.g ? ' on' : ''}" data-g="${g}"><b>${pad2(g + 1)}</b><span>${ws[0].i}–${ws[ws.length - 1].i}</span></button>`; }
    openSheet(h + '</div>', root => root.querySelector('.grps').addEventListener('click', e => {
      const b = e.target.closest('[data-g]'); if (!b) return; BF.g = +b.dataset.g; BF.limit = 60; closeSheet(); renderBook();
    }));
  });

  function openWord(k) {
    const w = WORDS[k], owned = ownVids(k).sort((a, b) => C.BY_ID[b].rank - C.BY_ID[a].rank);
    const wr = inWrong(k), stl = { new: '未学', w: '错词本', l: '学习中', m: '已掌握' }[status(k)];
    openSheet(`<div class="wsh"><div class="wsh-h"><div><b>${esc(w.w)}</b><span>${esc(w.p)}</span></div><button type="button" class="spk gl" id="wsSay" aria-label="朗读">${icon('i-speaker-high')}</button></div>
      <div class="wsh-meta">No.${w.i} · 第 ${w.g} 组 · 考频 ${w.f} · ${stl}</div>
      <div class="fb-m">${w.s.map(x => `<div><i>${esc(x[0])}.</i>${esc(senses(x[1]).join('；'))}</div>`).join('')}</div>
      ${w.note ? `<div class="fb-n">${esc(w.note)}</div>` : ''}
      <div class="fb-l"><em>${esc(w.en)}</em><span>${esc(w.cn)}${w.src ? ' — ' + esc(w.src) : ''}</span></div>
      ${owned.length ? `<div class="wsh-cards"><h4>已收集的卡面</h4><div class="wsh-row" id="wsCards"></div></div>` : '<div class="wsh-empty">还没有这张卡</div>'}
      <div class="sh-acts"><button type="button" class="btn soft" id="wsWrong">${icon(wr ? 'i-star-f' : 'i-star')}${wr ? '移出错词本' : '加入错词本'}</button></div></div>`, root => {
      root.querySelector('#wsSay').addEventListener('click', () => speak(w.w));
      root.querySelector('#wsWrong').addEventListener('click', () => {
        const p = S.prog[k] || (S.prog[k] = { c: 0, w: 0, s: 0 }); p.m = wr ? 0 : 1; save(); closeSheet();
        toast(wr ? '已移出错词本' : '已加入错词本'); if (view === 'book') renderBook(); if (view === 'home') renderHome();
      });
      const row = root.querySelector('#wsCards');
      if (row) owned.forEach(id => { const b = document.createElement('button'); b.type = 'button'; b.className = 'wsc'; b.appendChild(CardKit.mini(id, w, { seal: bestSeal(k, id) })); b.addEventListener('click', () => { closeSheet(); openViewer(k, id); }); row.appendChild(b); });
    });
  }

  /* ================= 晒图（Canvas 2D 生成图片 → 存相册 / 发笔记） ================= */
  function loadImg(src) {
    return new Promise(res => { const im = new Image(); im.onload = () => res(im); im.onerror = () => res(null); im.src = src; });
  }
  async function fontsReady() {
    try {
      if (document.fonts && document.fonts.load) {
        await Promise.all(['400 40px "Instrument Serif"', 'italic 400 40px "Instrument Serif"', '600 30px "Noto Serif SC"', '300 30px "Noto Serif SC"'].map(f => document.fonts.load(f, 'Aa中')));
      }
    } catch (e) { }
  }
  function rr(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
  function cover(ctx, im, x, y, w, h, ax, ay) {
    if (!im) return;
    const s = Math.max(w / im.width, h / im.height), iw = im.width * s, ih = im.height * s;
    ctx.drawImage(im, x + (w - iw) * (ax == null ? .5 : ax), y + (h - ih) * (ay == null ? .5 : ay), iw, ih);
  }
  function wrap(ctx, text, maxW) {
    const out = []; let line = '';
    const cjk = /[　-鿿＀-￯]/.test(text);
    const parts = cjk ? text.split('') : text.split(' ');
    parts.forEach(p => {
      const t = line ? (cjk ? line + p : line + ' ' + p) : p;
      if (ctx.measureText(t).width > maxW && line) { out.push(line); line = p; } else line = t;
    });
    if (line) out.push(line);
    return out;
  }
  function spaced(ctx, text, x, y, sp, align) {
    const chars = text.split(''); let wsum = 0; chars.forEach(c => { wsum += ctx.measureText(c).width + sp; }); wsum -= sp;
    let cx = align === 'center' ? x - wsum / 2 : align === 'right' ? x - wsum : x;
    const a = ctx.textAlign; ctx.textAlign = 'left';
    chars.forEach(c => { ctx.fillText(c, cx, y); cx += ctx.measureText(c).width + sp; });
    ctx.textAlign = a;
  }
  const SE = '"Instrument Serif", Georgia, serif', SC = '"Noto Serif SC", "Songti SC", serif', SA = '-apple-system, "PingFang SC", sans-serif';
  async function drawCardTo(ctx, x, y, W, H, vid, w, imgs) {
    const v = C.BY_ID[vid], land = !!v.land, u = (land ? H : W) * 0.24;
    ctx.save();
    ctx.textAlign = 'left'; ctx.globalAlpha = 1; ctx.shadowColor = 'transparent';
    rr(ctx, x, y, W, H, W * .045); ctx.clip();
    ctx.fillStyle = '#eee'; ctx.fillRect(x, y, W, H);
    cover(ctx, imgs.art, x, y, W, H);
    if (imgs.line) { ctx.globalAlpha = .5; cover(ctx, imgs.line, x, y, W, H, land ? 1 : .5, land ? .5 : 0); ctx.globalAlpha = 1; }
    if (v.rank >= 2) {
      const g = ctx.createLinearGradient(x, y, x + W, y + H);
      ['#ff9ad5', '#fff3a8', '#9effd8', '#9ad7ff', '#d5a8ff', '#ff9ad5'].forEach((c, i) => g.addColorStop(i / 5, c));
      ctx.globalCompositeOperation = 'soft-light'; ctx.globalAlpha = v.rank >= 4 ? .55 : .4; ctx.fillStyle = g; ctx.fillRect(x, y, W, H);
      ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1;
    }
    const ink = v.id === 'ur2' ? '#5A2E3C' : v.id === 'x2' ? '#3B3560' : v.lt ? '#FFFFFF' : '#1F1C24';
    const gold = v.gold ? '#F4DDA8' : null;
    if (v.frame) {
      ctx.strokeStyle = v.frame === 3 ? (v.id === 'x2' ? '#B9B8E6' : '#F2D7A2') : 'rgba(255,255,255,.9)'; ctx.lineWidth = Math.max(1.5, W * .004);
      const fx = land ? W * .028 : W * .042, fy = land ? H * .042 : H * .028;
      rr(ctx, x + fx, y + fy, W - fx * 2, H - fy * 2, u * .16); ctx.stroke();
    }
    ctx.fillStyle = gold || ink; ctx.textBaseline = 'alphabetic';
    const L = land ? x + W * .052 : x + W * .08, R = land ? x + W * .948 : x + W * .92;
    ctx.font = `700 ${u * .17}px ${SA}`; spaced(ctx, v.tier, L, y + H * (land ? .07 : .052) + u * .17, u * .045, 'left');
    ctx.font = `italic 400 ${u * .27}px ${SE}`; ctx.globalAlpha = .85; ctx.fillText(v.en, L, y + H * (land ? .122 : .086) + u * .27); ctx.globalAlpha = 1;
    ctx.font = `300 ${u * .16}px ${SC}`; ctx.textAlign = 'right'; ctx.globalAlpha = .75; ctx.fillText(pad3(w.i) + ' / 688', R, y + H * (land ? .07 : .052) + u * .16); ctx.globalAlpha = 1; ctx.textAlign = 'left';
    // 单词
    ctx.fillStyle = v.id === 'x1' ? '#F6E2B4' : ink;
    ctx.font = `400 ${u * (land ? 1.08 : 1)}px ${SE}`;
    let ws = u * (land ? 1.08 : 1);
    const maxWW = land ? W * .6 : W * .86;
    while (ctx.measureText(w.w).width > maxWW && ws > u * .5) { ws *= .94; ctx.font = `400 ${ws}px ${SE}`; }
    if (land) ctx.fillText(w.w, L + W * .028, y + H * .27 + ws * .82);
    else { ctx.textAlign = 'center'; ctx.fillText(w.w, x + W / 2, y + H * .25 + ws * .82); }
    ctx.fillStyle = gold || ink;
    const cx = land ? L + W * .028 : x + W / 2;
    // 例句
    const lw = land ? W * .6 : W * .8;
    let ly = y + H * (land ? .5 : .46);
    const long = (w.en.length > 78 ? .78 : w.en.length > 58 ? .88 : 1) * (land ? .86 : 1);
    ly += u * .32;
    ctx.font = `italic 400 ${u * .27 * long}px ${SE}`;
    wrap(ctx, w.en, lw).forEach(l => { ly += u * .27 * long * 1.2; ctx.fillText(l, cx, ly); });
    ly += u * .12;
    ctx.font = `400 ${u * .165 * long}px ${SC}`; ctx.globalAlpha = .8;
    wrap(ctx, w.cn + (w.src ? ' — ' + w.src : ''), lw).forEach(l => { ly += u * .165 * long * 1.55; ctx.fillText(l, cx, ly); });
    ctx.globalAlpha = 1; ctx.textAlign = 'left';
    // 页脚
    ctx.font = `600 ${u * .155}px ${SC}`; ctx.globalAlpha = .8;
    if (land) spaced(ctx, v.cn, L, y + H * .93, u * .03, 'left');
    else spaced(ctx, v.cn, L, y + H * .95, u * .03, 'left');
    ctx.globalAlpha = 1; ctx.textAlign = 'left';
    if (imgs.seal) { const cs = u * (land ? 1.05 : 1.15); ctx.drawImage(imgs.seal, land ? x + W * .96 - cs : x + W * .955 - cs, land ? y + H * .88 - cs : y + H * .915 - cs, cs, cs); }
    ctx.restore();
  }
  function bgFill(ctx, W, H, im, dark) {
    ctx.fillStyle = dark ? '#16121F' : '#F6EEF3'; ctx.fillRect(0, 0, W, H);
    cover(ctx, im, 0, 0, W, H);
  }
  /* ---------- 海报里的 3D 卡片：平面卡面 → 透视投影（网格三角形贴图），带厚度、高光、倒影 ---------- */
  function projector(ry, rx, D) {
    const sy = Math.sin(ry), cy = Math.cos(ry), sx = Math.sin(rx), cx = Math.cos(rx);
    return (x, y, z) => {
      const y1 = y * cx - z * sx, z1 = y * sx + z * cx;
      const x2 = x * cy + z1 * sy, z2 = -x * sy + z1 * cy;
      const k = D / (D + z2);
      return [x2 * k, y1 * k];
    };
  }
  // 纹理三角形：把 src 里 (t0,t1,t2) 三角形仿射映射到屏幕 (p0,p1,p2)
  function texTri(ctx, src, p0, p1, p2, t0, t1, t2) {
    const mx = (p0[0] + p1[0] + p2[0]) / 3, my = (p0[1] + p1[1] + p2[1]) / 3;
    const inf = q => { const dx = q[0] - mx, dy = q[1] - my, l = Math.sqrt(dx * dx + dy * dy) || 1; return [q[0] + dx / l * .8, q[1] + dy / l * .8]; };
    const a = inf(p0), b = inf(p1), c = inf(p2);
    const u0 = t0[0], v0 = t0[1], u1 = t1[0], v1 = t1[1], u2 = t2[0], v2 = t2[1];
    const det = (u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0); if (!det) return;
    const ma = ((p1[0] - p0[0]) * (v2 - v0) - (p2[0] - p0[0]) * (v1 - v0)) / det;
    const mb = ((p1[1] - p0[1]) * (v2 - v0) - (p2[1] - p0[1]) * (v1 - v0)) / det;
    const mc = ((p2[0] - p0[0]) * (u1 - u0) - (p1[0] - p0[0]) * (u2 - u0)) / det;
    const md = ((p2[1] - p0[1]) * (u1 - u0) - (p1[1] - p0[1]) * (u2 - u0)) / det;
    const me = p0[0] - ma * u0 - mc * v0, mf = p0[1] - mb * u0 - md * v0;
    ctx.save();
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.lineTo(c[0], c[1]); ctx.closePath(); ctx.clip();
    ctx.transform(ma, mb, mc, md, me, mf);
    const x0 = Math.max(0, Math.min(u0, u1, u2) - 2), y0 = Math.max(0, Math.min(v0, v1, v2) - 2);
    const x1 = Math.min(src.width, Math.max(u0, u1, u2) + 2), y1 = Math.min(src.height, Math.max(v0, v1, v2) + 2);
    ctx.drawImage(src, x0, y0, x1 - x0, y1 - y0, x0, y0, x1 - x0, y1 - y0);
    ctx.restore();
  }
  function roundPts(w, h, r, n) {
    const pts = [], c = [[w / 2 - r, -h / 2 + r, -Math.PI / 2], [w / 2 - r, h / 2 - r, 0], [-w / 2 + r, h / 2 - r, Math.PI / 2], [-w / 2 + r, -h / 2 + r, Math.PI]];
    c.forEach(q => { for (let i = 0; i <= n; i++) { const a = q[2] + i / n * Math.PI / 2; pts.push([q[0] + Math.cos(a) * r, q[1] + Math.sin(a) * r]); } });
    return pts;
  }
  function path(ctx, pts) { ctx.beginPath(); pts.forEach((q, i) => i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1])); ctx.closePath(); }
  // 在 (X,Y) 处画一张立体卡。face：平面卡面画布（尺寸 = w*k × h*k）
  function card3D(ctx, face, X, Y, w, h, o) {
    const k = face.width / w, P = projector(o.ry, o.rx, o.D || 2200), T = o.depth || w * .018;
    const ra = (o.rot || 0) * Math.PI / 180, rc = Math.cos(ra), rsn = Math.sin(ra);
    const sp = (x, y, z) => { const q = P(x, y, z); return [X + q[0] * rc - q[1] * rsn, Y + q[0] * rsn + q[1] * rc]; };
    const rim = roundPts(w, h, w * .045, 6);
    const front = rim.map(q => sp(q[0], q[1], 0)), back = rim.map(q => sp(q[0], q[1], T));
    // 地面阴影
    const ys = front.map(q => q[1]), bot = Math.max.apply(null, ys);
    ctx.save(); ctx.shadowColor = o.shadow; ctx.shadowBlur = w * .12; ctx.shadowOffsetY = 3000;
    ctx.fillStyle = '#000'; ctx.beginPath(); ctx.ellipse ? ctx.ellipse(X, bot - 3000 + 8, w * .46, w * .05, 0, 0, Math.PI * 2) : ctx.arc(X, bot - 3000, w * .3, 0, Math.PI * 2); ctx.fill(); ctx.restore();
    // 外发光
    if (o.glow) { ctx.save(); ctx.shadowColor = o.glow; ctx.shadowBlur = w * .16; ctx.fillStyle = o.glow; path(ctx, front); ctx.fill(); ctx.restore(); }
    // 厚度：背面轮廓 + 侧面，正面再盖上去，只露出朝向镜头的那一侧
    const xs = front.map(q => q[0]), L = Math.min.apply(null, xs), R = Math.max.apply(null, xs);
    const eg = ctx.createLinearGradient(L, 0, R, 0);
    o.edge.forEach((c, i) => eg.addColorStop(i / (o.edge.length - 1), c));
    ctx.fillStyle = eg; path(ctx, back); ctx.fill();
    for (let i = 0; i < rim.length; i++) {
      const j = (i + 1) % rim.length;
      ctx.beginPath(); ctx.moveTo(front[i][0], front[i][1]); ctx.lineTo(front[j][0], front[j][1]); ctx.lineTo(back[j][0], back[j][1]); ctx.lineTo(back[i][0], back[i][1]); ctx.closePath(); ctx.fill();
    }
    // 正面：网格贴图
    ctx.save(); path(ctx, front); ctx.clip();
    const NX = 14, NY = Math.round(14 * h / w);
    for (let gy = 0; gy < NY; gy++) for (let gx = 0; gx < NX; gx++) {
      const xa = -w / 2 + w * gx / NX, xb = -w / 2 + w * (gx + 1) / NX, ya = -h / 2 + h * gy / NY, yb = -h / 2 + h * (gy + 1) / NY;
      const A = sp(xa, ya, 0), B = sp(xb, ya, 0), Cc = sp(xb, yb, 0), Dd = sp(xa, yb, 0);
      const ta = [(xa + w / 2) * k, (ya + h / 2) * k], tb = [(xb + w / 2) * k, (ya + h / 2) * k], tc = [(xb + w / 2) * k, (yb + h / 2) * k], td = [(xa + w / 2) * k, (yb + h / 2) * k];
      texTri(ctx, face, A, B, Cc, ta, tb, tc); texTri(ctx, face, A, Cc, Dd, ta, tc, td);
    }
    // 镜面高光 + 一道斜向的镭射反光
    const g0 = sp(-w * .22, -h * .3, 0);
    const gl = ctx.createRadialGradient(g0[0], g0[1], 0, g0[0], g0[1], w * .95);
    gl.addColorStop(0, 'rgba(255,255,255,.42)'); gl.addColorStop(.45, 'rgba(255,255,255,.08)'); gl.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.globalCompositeOperation = 'screen'; ctx.fillStyle = gl; ctx.fillRect(L - 10, Math.min.apply(null, ys) - 10, R - L + 20, bot - Math.min.apply(null, ys) + 20);
    const s0 = sp(-w * .5, -h * .1, 0), s1 = sp(w * .5, h * .25, 0);
    const sg = ctx.createLinearGradient(s0[0], s0[1], s1[0], s1[1]);
    [['rgba(255,255,255,0)', 0], ['rgba(255,190,230,.0)', .34], ['rgba(255,214,236,.22)', .42], ['rgba(220,240,255,.3)', .47], ['rgba(214,255,236,.2)', .52], ['rgba(255,255,255,0)', .62], ['rgba(255,255,255,0)', 1]].forEach(x => sg.addColorStop(x[1], x[0]));
    ctx.fillStyle = sg; ctx.fillRect(L - 10, Math.min.apply(null, ys) - 10, R - L + 20, bot - Math.min.apply(null, ys) + 20);
    ctx.restore();
    // 边缘的一圈受光
    ctx.save(); path(ctx, front); ctx.lineWidth = 2; ctx.strokeStyle = o.rim; ctx.stroke(); ctx.restore();
    return { bot: bot, L: L, R: R, top: Math.min.apply(null, ys) };
  }
  function star4(ctx, x, y, r) {
    ctx.beginPath(); ctx.moveTo(x, y - r);
    ctx.quadraticCurveTo(x, y, x + r, y); ctx.quadraticCurveTo(x, y, x, y + r);
    ctx.quadraticCurveTo(x, y, x - r, y); ctx.quadraticCurveTo(x, y, x, y - r); ctx.fill();
  }
  async function cardPoster(k, vid, safe, seal) {
    const v = C.BY_ID[vid], w = WORDS[k], t = TIER[v.tier];
    await fontsReady();
    const imgs = safe ? {} : {
      art: await loadImg('img/art/' + vid + '.webp'), seal: seal ? await loadImg('img/seal/' + seal + '.webp') : null,
      line: (window.LINEART || {})[vid] ? await loadImg(window.LINEART[vid]) : null
    };
    const bg = safe ? null : await loadImg('img/bg/' + (v.rank >= 5 || v.lt ? 'night' : v.rank >= 3 ? 'dusk' : 'sky') + '.webp');
    const W = 1080, H = 1440, dark = v.rank >= 5 || !!v.lt;
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const ctx = cv.getContext('2d');
    bgFill(ctx, W, H, bg, dark);
    const fg = dark ? '#FFFFFF' : '#1F1C24', sub = dark ? 'rgba(255,255,255,.7)' : 'rgba(31,28,36,.62)';
    // 卡面平面图（1.6 倍分辨率，投影后依然清晰）
    let cw, ch;
    if (v.land) { cw = 840; ch = cw * 250 / 386; } else { cw = 540; ch = cw * 386 / 250; }
    const KX = 1.6, face = document.createElement('canvas'); face.width = Math.round(cw * KX); face.height = Math.round(ch * KX);
    const fctx = face.getContext('2d'); fctx.scale(KX, KX);
    await drawCardTo(fctx, 0, 0, cw, ch, vid, w, imgs);
    const X = W / 2, Y = v.land ? 650 : 330 + ch / 2;
    // 背光：卡后面一团柔光 + 稀有卡的放射光
    const glow = dark ? 'rgba(170,150,255,' : 'rgba(255,255,255,';
    const rg = ctx.createRadialGradient(X, Y, 0, X, Y, W * .62);
    rg.addColorStop(0, glow + (dark ? '.42)' : '.75)')); rg.addColorStop(.5, glow + '.12)'); rg.addColorStop(1, glow + '0)');
    ctx.fillStyle = rg; ctx.fillRect(0, 0, W, H);
    if (v.rank >= 3) {
      ctx.save(); ctx.translate(X, Y); ctx.globalCompositeOperation = dark ? 'screen' : 'soft-light';
      for (let i = 0; i < 28; i++) {
        const a = i / 28 * Math.PI * 2 + .1, wd = .025 + (i % 3) * .012;
        const g = ctx.createLinearGradient(0, 0, Math.cos(a) * 900, Math.sin(a) * 900);
        g.addColorStop(0, glow + (dark ? '.13)' : '.42)')); g.addColorStop(.7, glow + '0)');
        ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.cos(a - wd) * 900, Math.sin(a - wd) * 900); ctx.lineTo(Math.cos(a + wd) * 900, Math.sin(a + wd) * 900); ctx.closePath(); ctx.fill();
      }
      ctx.restore();
    }
    // 标题
    ctx.fillStyle = sub; ctx.font = `500 26px ${SA}`; spaced(ctx, (v.tier === 'SECRET' ? 'SECRET' : v.tier) + ' · ' + t.cn, W / 2, 110, 10, 'center');
    ctx.fillStyle = fg; ctx.textAlign = 'center'; ctx.font = `italic 400 84px ${SE}`; ctx.fillText(v.en, W / 2, 200);
    ctx.font = `600 32px ${SC}`; spaced(ctx, v.cn, W / 2, 252, 14, 'center');
    // 立体卡：先画到一层上，好做倒影
    const layer = document.createElement('canvas'); layer.width = W; layer.height = H;
    const lctx = layer.getContext('2d');
    const gold = v.frame === 3 || v.gold;
    const box = card3D(lctx, face, X, Y, cw, ch, {
      ry: (v.land ? -14 : -20) * Math.PI / 180, rx: 8 * Math.PI / 180, D: 2200, depth: cw * .03,
      edge: gold ? ['#FFF3D6', '#E9C27E', '#B8873E', '#7A5626'] : v.lt ? ['#E4DBFF', '#9C8BD6', '#5B4C93', '#3A2E66'] : ['#FFFFFF', '#F1E8F2', '#D9CCE0', '#B7A8C2'],
      rim: gold ? 'rgba(255,236,200,.75)' : 'rgba(255,255,255,.7)',
      shadow: dark ? 'rgba(0,0,0,.7)' : 'rgba(90,60,120,.38)', glow: dark ? 'rgba(150,130,255,.35)' : null
    });
    // 倒影：翻转、渐隐
    const floor = box.bot + 4;
    const refl = document.createElement('canvas'); refl.width = W; refl.height = H;
    const rctx = refl.getContext('2d');
    rctx.save(); rctx.translate(0, floor * 2); rctx.scale(1, -1); rctx.drawImage(layer, 0, 0); rctx.restore();
    const fade = rctx.createLinearGradient(0, floor, 0, floor + 120);
    fade.addColorStop(0, 'rgba(0,0,0,' + (dark ? .26 : .2) + ')'); fade.addColorStop(1, 'rgba(0,0,0,0)');
    rctx.globalCompositeOperation = 'destination-in'; rctx.fillStyle = fade; rctx.fillRect(0, 0, W, H);
    ctx.drawImage(refl, 0, 0);
    ctx.drawImage(layer, 0, 0);
    // 星光
    let sd = vid.length * 97 + k;
    const rnd = () => { sd = (sd * 16807) % 2147483647; return sd / 2147483647; };
    ctx.fillStyle = dark ? '#FFFFFF' : '#FFFFFF';
    for (let i = 0; i < 16; i++) {
      const a = rnd() * Math.PI * 2, r = (v.land ? 470 : 360) + rnd() * 120;
      const x = X + Math.cos(a) * r * (v.land ? 1 : .95), y = Y + Math.sin(a) * r * (v.land ? .6 : 1.1);
      if (y < 290 || y > floor + 40) continue;
      ctx.globalAlpha = .45 + rnd() * .5; star4(ctx, x, y, 6 + rnd() * 16);
    }
    ctx.globalAlpha = 1;
    ctx.textAlign = 'center'; ctx.fillStyle = sub; ctx.font = `400 26px ${SA}`;
    const sl = seal && SEAL[seal];
    ctx.fillText(sl ? `${t.cn} · ${sl.tcn}「${sl.cn}」` : t.cn, W / 2, Math.min(H - 150, floor + 140));
    ctx.fillStyle = fg; ctx.font = `600 30px ${SC}`; ctx.fillText('单词手账 · 高考核心 688 词', W / 2, H - 70);
    return cv;
  }
  async function resultPoster(R, theme, safe) {
    await fontsReady();
    const W = 1080, H = 1440, dark = theme === 'night';
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const ctx = cv.getContext('2d');
    const bg = safe ? null : await loadImg('img/bg/' + theme + '.webp');
    bgFill(ctx, W, H, bg, dark);
    const fg = dark ? '#FFFFFF' : '#1F1C24', sub = dark ? 'rgba(255,255,255,.68)' : 'rgba(31,28,36,.6)';
    const d = R.date;
    ctx.fillStyle = sub; ctx.font = `300 34px ${SC}`; ctx.fillText(d.getFullYear() + '.' + pad2(d.getMonth() + 1) + '.' + pad2(d.getDate()), 90, 140);
    ctx.textAlign = 'right'; ctx.font = `600 30px ${SA}`; ctx.fillText('DAY ' + pad2(Math.max(1, streak())), W - 90, 140); ctx.textAlign = 'left';
    ctx.fillStyle = fg; ctx.font = `600 64px ${SC}`; ctx.fillText(R.kind === 'test' ? '全部测试' : R.label + ' · ' + (TYPE_NAME[R.mode] || ''), 90, 250);
    // 立体分数：先叠出厚度，再盖上渐变的正面
    ctx.font = `300 260px ${SC}`;
    const sw = ctx.measureText(String(R.right)).width;
    for (let i = 14; i >= 1; i--) { ctx.fillStyle = dark ? `rgba(${60 + i * 4},${40 + i * 3},${110 + i * 4},1)` : `rgba(${196 - i * 3},${170 - i * 3},${214 - i * 2},1)`; ctx.fillText(String(R.right), 80 + i * .9, 520 + i * 1.3); }
    const sg = ctx.createLinearGradient(80, 300, 80 + sw, 520);
    (dark ? ['#FFFFFF', '#E6DCFF', '#C9D9FF', '#FFE9F3'] : ['#2A2238', '#4A3A6A', '#2A2238', '#5A3E66']).forEach((c, i, a) => sg.addColorStop(i / (a.length - 1), c));
    ctx.fillStyle = sg; ctx.fillText(String(R.right), 80, 520);
    ctx.save(); ctx.globalCompositeOperation = 'screen'; const hl = ctx.createLinearGradient(0, 330, 0, 420); hl.addColorStop(0, 'rgba(255,255,255,.35)'); hl.addColorStop(1, 'rgba(255,255,255,0)'); ctx.fillStyle = hl; ctx.fillText(String(R.right), 80, 520); ctx.restore();
    ctx.fillStyle = fg;
    // 右侧：卡册里最稀有的三张，扇形立体展开
    if (!safe) {
      const own = [];
      Object.keys(S.cards).forEach(k => ownVids(+k).forEach(id => own.push(id)));
      const uniq = own.filter((x, i) => own.indexOf(x) === i && !C.BY_ID[x].land).sort((a, b) => C.BY_ID[b].rank - C.BY_ID[a].rank);
      const fan = (uniq.length >= 3 ? uniq.slice(0, 3) : ['sr1', 'ssr1', 'lr1']).reverse();
      const cw = 170, chh = cw * 386 / 250;
      for (let i = 0; i < fan.length; i++) {
        const id = fan[i], fv = C.BY_ID[id], art = await loadImg('img/art/' + id + '.webp');
        const f = document.createElement('canvas'); f.width = Math.round(cw * 2); f.height = Math.round(chh * 2);
        const fc = f.getContext('2d'); fc.scale(2, 2);
        rr(fc, 0, 0, cw, chh, cw * .05); fc.clip(); cover(fc, art, 0, 0, cw, chh);
        if (fv.rank >= 2) { const g = fc.createLinearGradient(0, 0, cw, chh); ['#ff9ad5', '#fff3a8', '#9effd8', '#9ad7ff', '#d5a8ff'].forEach((c, j) => g.addColorStop(j / 4, c)); fc.globalCompositeOperation = 'soft-light'; fc.globalAlpha = .5; fc.fillStyle = g; fc.fillRect(0, 0, cw, chh); fc.globalCompositeOperation = 'source-over'; fc.globalAlpha = 1; }
        if (fv.frame) { fc.strokeStyle = fv.frame === 3 ? '#F2D7A2' : 'rgba(255,255,255,.9)'; fc.lineWidth = 1.5; rr(fc, cw * .045, chh * .03, cw * .91, chh * .94, cw * .04); fc.stroke(); }
        fc.fillStyle = fv.lt ? '#fff' : '#1F1C24'; fc.font = `700 ${cw * .07}px ${SA}`; fc.fillText(fv.tier, cw * .1, cw * .14);
        fc.font = `italic 400 ${cw * .1}px ${SE}`; fc.globalAlpha = .85; fc.fillText(fv.en, cw * .1, cw * .26); fc.globalAlpha = 1;
        const ang = (i - 1) * 13;
        card3D(ctx, f, 800 + (i - 1) * 92, 410 + Math.abs(i - 1) * 16, cw, chh, {
          ry: (-14 - (i - 1) * 6) * Math.PI / 180, rx: 6 * Math.PI / 180, D: 1600, depth: cw * .035,
          edge: fv.frame === 3 ? ['#FFF3D6', '#E9C27E', '#B8873E'] : ['#FFFFFF', '#E7DDEC', '#B7A8C2'], rim: 'rgba(255,255,255,.7)',
          shadow: dark ? 'rgba(0,0,0,.6)' : 'rgba(90,60,120,.3)', glow: null, rot: ang
        });
      }
      ctx.textAlign = 'left';
    }
    ctx.fillStyle = sub; ctx.font = `300 70px ${SC}`; ctx.fillText('/ ' + R.total, 100 + sw, 520);
    const kv = [[R.pct + '%', '正确率'], [String(R.best), '最长连对'], [R.time, '用时'], ['+' + R.gain, '抽卡券']];
    kv.forEach((x, i) => {
      const xx = 90 + i * 230;
      ctx.fillStyle = fg; ctx.font = `300 60px ${SC}`; ctx.fillText(x[0], xx, 660);
      ctx.fillStyle = sub; ctx.font = `400 28px ${SA}`; ctx.fillText(x[1], xx, 708);
    });
    ctx.fillStyle = dark ? 'rgba(255,255,255,.18)' : 'rgba(31,28,36,.12)'; ctx.fillRect(90, 770, W - 180, 2);
    const list = (R.wrongs.length ? R.wrongs : R.words).slice(0, 4);
    ctx.fillStyle = sub; ctx.font = `500 28px ${SA}`; ctx.fillText(R.wrongs.length ? '要再看看的词' : '本轮的词', 90, 840);
    list.forEach((w, i) => {
      const yy = 920 + i * 92;
      ctx.fillStyle = fg; ctx.font = `400 58px ${SE}`; ctx.fillText(w.w, 90, yy);
      ctx.fillStyle = sub; ctx.font = `400 30px ${SC}`; ctx.textAlign = 'right'; ctx.fillText(short(w), W - 90, yy - 6); ctx.textAlign = 'left';
    });
    ctx.fillStyle = dark ? 'rgba(255,255,255,.1)' : 'rgba(255,255,255,.55)'; rr(ctx, 60, H - 200, W - 120, 130, 30); ctx.fill();
    ctx.fillStyle = fg; ctx.font = `600 36px ${SC}`; ctx.fillText('单词手账', 110, H - 128);
    ctx.fillStyle = sub; ctx.font = `italic 400 28px ${SE}`; ctx.fillText('688 high-frequency words', 110, H - 90);
    let bx = W - 110; for (let i = 0; i < 26; i++) { const bw = [3, 3, 6, 9][(i * 7 + R.right) % 4]; bx -= bw + 6; ctx.fillStyle = fg; ctx.fillRect(bx, H - 168, bw, 66); }
    return cv;
  }
  function toData(cv) { return cv.toDataURL('image/jpeg', .92); }
  async function makeImage(fn) {
    try { return toData(await fn(false)); }
    catch (e) { try { return toData(await fn(true)); } catch (e2) { return null; } }
  }
  async function shareCard(k, vid, seal) {
    const v = C.BY_ID[vid];
    openShare('晒这张卡', () => makeImage(safe => cardPoster(k, vid, safe, seal)), {
      title: v.rank >= 3 ? `抽到了${TIER[v.tier].cn}「${v.cn}」` : '单词手账的新卡片',
      content: `背单词抽到了 ${v.tier} ${TIER[v.tier].cn}「${v.cn}」✨ 单词：${WORDS[k].w}\n#单词手账 #高考英语 #背单词`
    });
  }
  function shareResult(R) {
    let theme = 'sky';
    const run = () => makeImage(safe => resultPoster(R, theme, safe));
    openShare('成绩卡', run, {
      title: R.kind === 'test' ? `全部测试 ${R.right}/${R.total}` : `${R.label}打卡`,
      content: `今天在单词手账答对 ${R.right}/${R.total}，正确率 ${R.pct}%，连续打卡 ${streak()} 天。\n#单词手账 #高考英语 #背单词打卡`
    }, [['sky', '晴'], ['dusk', '暮'], ['night', '夜']], t => { theme = t; });
  }
  let shareData = null;
  async function openShare(title, gen, note, themes, onTheme) {
    const box = $('#share'); box.hidden = false; document.documentElement.classList.add('lock');
    $('#shBody').innerHTML = `<div class="sh-top"><span>${esc(title)}</span><button type="button" class="cl" id="shX" aria-label="关闭">${icon('i-x')}</button></div>
      <div class="sh-img"><div class="sh-load">正在生成图片…</div><img id="shImg" alt="分享图" hidden></div>
      ${themes ? `<div class="tps" id="shThemes">${themes.map((x, i) => `<button type="button" data-t="${x[0]}" class="${i ? '' : 'on'}"><i class="tp-${x[0]}"></i>${x[1]}</button>`).join('')}</div>` : ''}
      <div class="sh-acts2"><button type="button" class="btn ghost" id="shSave">${icon('i-download-simple')}存到相册</button><button type="button" class="btn holo" id="shPost">${icon('i-share-network')}发笔记</button></div>`;
    const render = async () => {
      $('#shImg').hidden = true; $('.sh-load').hidden = false;
      shareData = await gen();
      if (!shareData) { $('.sh-load').textContent = '图片生成失败'; return; }
      $('#shImg').src = shareData; $('#shImg').hidden = false; $('.sh-load').hidden = true;
    };
    $('#shX').addEventListener('click', closeShare);
    if (themes) $('#shThemes').addEventListener('click', e => { const b = e.target.closest('[data-t]'); if (!b) return; $$('#shThemes button').forEach(x => x.classList.toggle('on', x === b)); onTheme(b.dataset.t); render(); });
    $('#shSave').addEventListener('click', () => saveImage());
    $('#shPost').addEventListener('click', () => postNote(note));
    render();
  }
  function closeShare() {
    $('#share').hidden = true; $('#shBody').innerHTML = ''; shareData = null;
    if ($('#reveal').hidden && $('#viewer').hidden) document.documentElement.classList.remove('lock');
  }
  async function tempPath(data) {
    const mt = miniTool();
    if (mt && typeof mt.writeTempFile === 'function') {
      try { const r = await mt.writeTempFile({ data }); if (r && r.filePath) return r.filePath; } catch (e) { }
    }
    return data;
  }
  async function saveImage() {
    if (!shareData) return;
    const mt = miniTool();
    if (!mt || typeof mt.saveImageToPhotosAlbum !== 'function') { toast('请在小红书 App 里使用，或截图保存'); return; }
    try { await mt.saveImageToPhotosAlbum({ filePath: await tempPath(shareData) }); toast('已保存到相册'); }
    catch (e) { toast('没有保存成功' + (e && e.errMsg && /auth|deny|permission/i.test(e.errMsg) ? '，请允许访问相册' : '')); }
  }
  async function postNote(note) {
    if (!shareData) return;
    const mt = miniTool();
    if (!mt || typeof mt.postNote !== 'function') { toast('请在小红书 App 里使用发笔记'); return; }
    try {
      await mt.postNote({ title: note.title.slice(0, 20), content: note.content.slice(0, 1000), pageType: 'photo_publish', mediaInfo: { image_resources: [{ url: await tempPath(shareData) }] } });
    } catch (e) { toast('没有打开发布页，可以先存到相册'); }
  }

  /* ================= 启动 ================= */
  function setAppHeight() { document.documentElement.style.setProperty('--app-h', window.innerHeight + 'px'); }
  window.addEventListener('resize', setAppHeight);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (!$('#modal').hidden) { $('#modal').hidden = true; return; }
    if (!$('#share').hidden) { closeShare(); return; }
    if (!$('#viewer').hidden) { closeViewer(); return; }
    if (!$('#sheet').hidden) { closeSheet(); return; }
  });
  async function boot() {
    setAppHeight();
    try { S = normalize(await loadState()); } catch (e) { S = normalize(null); }
    if (!S.welcome) {
      S.welcome = true;
      addTickets(10, 1);
      setTimeout(() => modal('单词手账', '送你 10 张抽卡券。', [{ label: '先去背词' }, { label: '去抽卡', cls: 'holo', fn: () => show('draw') }]), 400);
    }
    save();
    $('#boot').hidden = true; $('#app').hidden = false;
    show('home');
  }
  window.__danci = { get S() { return S; }, rates, multOf, drawOne, WORDS, cardPoster, resultPoster, show, revealOne, setLast(R) { LAST = R; show('result'); renderResult(); } }; // 自检用
  boot();
})();
