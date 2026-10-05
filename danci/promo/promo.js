/* 宣传片：20 秒，竖版。全部画面由 render(t) 按时间直接算出，便于逐帧截图。
 * 节拍 120 BPM（一拍 0.5 秒），转场都落在拍点上，与 music.py 的配乐对齐。 */
(function () {
  'use strict';
  var C = window.CATALOG, CK = window.CardKit;
  var WORDS = window.WORDS_RAW.map(function (r, k) { return { k: k, i: r[0], w: r[2], p: r[3], cp: r[7], cm: r[8], en: r[9], cn: r[10], src: r[11] }; });
  var W = function (w) { for (var i = 0; i < WORDS.length; i++) if (WORDS[i].w === w) return WORDS[i]; };
  var $ = function (s) { return document.querySelector(s); };
  var cl = function (x, a, b) { a = a == null ? 0 : a; b = b == null ? 1 : b; return Math.min(b, Math.max(a, x)); };
  var seg = function (t, a, b) { return cl((t - a) / (b - a)); };
  var lerp = function (a, b, x) { return a + (b - a) * x; };
  var E = {
    out3: function (x) { return 1 - Math.pow(1 - x, 3); },
    in3: function (x) { return x * x * x; },
    io3: function (x) { return x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; },
    outExpo: function (x) { return x >= 1 ? 1 : 1 - Math.pow(2, -10 * x); },
    outBack: function (x) { var c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); }
  };
  function rng(seed) { return function () { seed |= 0; seed = seed + 0x6D2B79F5 | 0; var t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  var PAL = ['#F9C6DA', '#DCCBFA', '#BFDDF8', '#C9F2E2', '#FAE6BE', '#FFFFFF', '#F2D7A2'];
  var pad3 = CK.pad3;
  function show(el, on) { el.style.display = on ? 'block' : 'none'; }

  /* ---------- 卡片 ---------- */
  function card(vid, word, seal, width, parent, cls, veil) {
    var wrap = document.createElement('div');
    if (cls) wrap.className = cls;
    var box = document.createElement('div');
    box.style.width = width + 'px';
    var land = C.BY_ID[vid].land;
    box.style.fontSize = (land ? width / 1.544 : width) * .24 + 'px';
    var m = CK.make(vid, W(word), { seal: seal });
    m.el.classList.remove('lit');
    box.appendChild(m.el); wrap.appendChild(box); parent.appendChild(wrap);
    var sl = m.el.querySelector('.cf-seal'), vl = null;
    // 隐藏款不完整展示：盖一层夜色面纱，只有一道光缝扫过时露出一窄条真卡面
    if (veil) {
      vl = document.createElement('div'); vl.className = 'veil';
      vl.innerHTML = '<b class="vt">SECRET</b><i class="vq">?</i><span class="vb">隐藏款</span>';
      var ov = m.el.querySelector('.cf-ov'); ov.insertBefore(vl, sl || null);
    }
    return { wrap: wrap, el: m.el, seal: sl, veil: vl };
  }
  // 手动设定 cards-css 的指针变量：px/py 为光点位置（%），o 为镭射强度，amp 为倾斜幅度
  function pose(el, px, py, o, amp) {
    var s = el.style, cx = px - 50, cy = py - 50;
    amp = amp == null ? 1 : amp;
    s.setProperty('--pointer-x', px + '%'); s.setProperty('--pointer-y', py + '%');
    s.setProperty('--pointer-from-center', String(cl(Math.sqrt(cx * cx + cy * cy) / 50)));
    s.setProperty('--pointer-from-top', String(py / 100)); s.setProperty('--pointer-from-left', String(px / 100));
    s.setProperty('--pointer-dx', String(cx / 50)); s.setProperty('--pointer-dy', String(cy / 50));
    s.setProperty('--card-opacity', String(o));
    s.setProperty('--rotate-x', (-cx / 3.5 * amp) + 'deg'); s.setProperty('--rotate-y', (cy / 2 * amp) + 'deg');
    s.setProperty('--background-x', lerp(37, 63, px / 100) + '%'); s.setProperty('--background-y', lerp(33, 67, py / 100) + '%');
  }
  function sealEl(id, parent) {
    var d = document.createElement('div');
    d.innerHTML = CK.sealHTML(id, 'ps');
    var el = d.firstChild; parent.appendChild(el); return el;
  }

  /* ---------- 场景元素 ---------- */
  var bgD = $('#bgD'), bgN = $('#bgN'), bgG = $('#bgG'), world = $('#world');
  var fx = $('#fx'), ctx0 = fx.getContext('2d'), ctx2 = $('#fx2').getContext('2d'), ctx = ctx0;
  // 底鼓时间（和 music.py 一致），画面随拍子轻轻一胀
  var KICKS = [];
  (function () { var i; for (i = 0; i < 8; i++) KICKS.push(3 + i * .5); for (i = 0; i < 11; i++) KICKS.push(8 + i * .5); KICKS.push(13.5, 14); for (i = 0; i < 5; i++) KICKS.push(14.5 + i * .5); KICKS.push(17.5); })();
  function pulse(t) { var v = 0; KICKS.forEach(function (k) { var a = t - k; if (a >= 0 && a < .6) v = Math.max(v, Math.exp(-a / .11)); }); return v; }
  var sA = $('#sA'), sB = $('#sB'), sC = $('#sC'), sD = $('#sD'), sE = $('#sE'), sF = $('#sF');

  // A：词流，越来越快，停在 still
  var A_WORDS = ['personal', 'tie', 'offer', 'cause', 'state', 'directly', 'wonder', 'present', 'complete', 'lead', 'recall', 'still'];
  var A_T = [0.45, 0.72, 0.95, 1.14, 1.3, 1.44, 1.56, 1.67, 1.78, 1.89, 2.02, 2.2];

  // B：答题。第一题慢，后面越答越快，抽卡券从 1 涨到 10
  var B_WORDS = ['still', 'wonder', 'offer', 'present', 'personal', 'lead', 'complete', 'state', 'cause', 'directly'];
  var B_T = [3.0, 4.5, 5.0, 5.5, 5.75, 6.0, 6.25, 6.375, 6.5, 6.625];
  var B_POS = [1, 3, 0, 2, 1, 0, 3, 2, 1, 0];
  var bR = rng(42), ROUNDS = B_WORDS.map(function (w, r) {
    var x = W(w), opts = [], used = {}; used[x.k] = 1;
    for (var j = 0; j < 4; j++) {
      if (j === B_POS[r]) { opts.push(x.cp + ' ' + x.cm); continue; }
      var y; do { y = WORDS[(bR() * 300) | 0]; } while (used[y.k] || y.cm.length > 9); used[y.k] = 1;
      opts.push(y.cp + ' ' + y.cm);
    }
    var t0 = B_T[r], dur = (B_T[r + 1] || 6.75) - t0;
    var pick = r === 0 ? 3.9 : t0 + dur * .45;
    return { w: x, opts: opts, t0: t0, pick: pick, fly: r === 0 ? .55 : Math.max(.3, Math.min(.45, dur * 1.6)) };
  });
  var opts = [];
  for (var oi = 0; oi < 4; oi++) {
    var o = document.createElement('div'); o.className = 'opt'; o.style.top = (402 + oi * 86) + 'px';
    o.innerHTML = '<i>' + 'ABCD'[oi] + '</i><span></span>'; $('#bOpts').appendChild(o); opts.push(o);
  }
  var tks = ROUNDS.map(function () { var im = document.createElement('img'); im.src = 'img/icon3d/ticket.webp'; im.className = 'tk'; $('#bFly').appendChild(im); return im; });

  // C：揭晓 LR 极光情书 still
  var cCard = card('lr1', 'still', 'aurora', 330, $('#cFront'));

  // D：七个等级依次滑入
  var D = [
    { v: 'n2', w: 'state', s: 'star', rate: '40%' }, { v: 'r1', w: 'cause', s: 'bow', rate: '30%' },
    { v: 'sr1', w: 'directly', s: 'diamond', rate: '18%' }, { v: 'ssr2', w: 'personal', s: 'pearl', rate: '8%' },
    { v: 'ur2', w: 'complete', s: 'crown', rate: '3%' }, { v: 'lr2', w: 'present', s: 'sunset', rate: '0.8%' },
    { v: 'x1', w: 'offer', s: 'moon', rate: '0.2%' }];
  D.forEach(function (d) { var c = card(d.v, d.w, d.s, 290, $('#dFlow'), 'dc', d.v === 'x1'); d.c = c; d.tier = C.BY_ID[d.v].tier; d.cn = C.TIERS[C.BY_ID[d.v].rank].cn; d.col = C.BY_ID[d.v].art; });
  var D_T0 = 10.5;

  // E：十枚蜡封
  var SE = ['star', 'bow', 'heart', 'diamond', 'pearl', 'sunset', 'crown', 'moon', 'aurora', 'midnight'];
  var seals = SE.map(function (id) { return { id: id, rank: C.SEAL[id].rank, el: sealEl(id, $('#eSeals')) }; });
  var ST = C.SEAL_TIERS;
  var bigSeal = sealEl('midnight', $('#bigSeal'));

  // F：收尾三张卡
  var fL = card('ssr1', 'personal', 'heart', 300, $('#fCards'), 'fc');
  var fR = card('lr1', 'still', 'aurora', 300, $('#fCards'), 'fc');
  var fC = card('x1', 'wonder', 'midnight', 300, $('#fCards'), 'fc', true);
  // 光缝位置：p 从 0 到 1 扫过整张卡
  function slit(c, p) { c.veil.style.setProperty('--s', lerp(-25, 125, p) + '%'); }

  /* ---------- 粒子（画布） ---------- */
  var STARS = (function () { var r = rng(7), a = []; for (var i = 0; i < 150; i++) a.push({ x: r() * 540, y: r() * 960, s: .5 + Math.pow(r(), 3) * 2.6, ph: r() * 6.28, sp: .8 + r() * 2.4, dr: .2 + r() * .8 }); return a; })();
  var MOTES = (function () { var r = rng(9), a = []; for (var i = 0; i < 34; i++) a.push({ x: r() * 540, y: r() * 960, s: 1.4 + r() * 3.2, ph: r() * 6.28, sp: 14 + r() * 26, c: PAL[(r() * 5) | 0] }); return a; })();
  function star4(x, y, r) {
    ctx.beginPath(); ctx.moveTo(x, y - r);
    ctx.quadraticCurveTo(x, y, x + r, y); ctx.quadraticCurveTo(x, y, x, y + r);
    ctx.quadraticCurveTo(x, y, x - r, y); ctx.quadraticCurveTo(x, y, x, y - r); ctx.fill();
  }
  function starfield(t, alpha) {
    if (alpha <= 0) return;
    ctx.fillStyle = '#fff';
    STARS.forEach(function (s) {
      var tw = .35 + .65 * (.5 + .5 * Math.sin(t * s.sp + s.ph));
      ctx.globalAlpha = alpha * tw * (s.s > 1.6 ? 1 : .7);
      var y = (s.y - t * 6 * s.dr + 960) % 960;
      if (s.s > 1.9) star4(s.x, y, s.s * 2.6); else { ctx.beginPath(); ctx.arc(s.x, y, s.s * .6, 0, 6.283); ctx.fill(); }
    });
    ctx.globalAlpha = 1;
  }
  function motes(t, alpha) {
    if (alpha <= 0) return;
    MOTES.forEach(function (m) {
      ctx.globalAlpha = alpha * (.4 + .6 * (.5 + .5 * Math.sin(t * 2 + m.ph)));
      ctx.fillStyle = m.c;
      var y = ((m.y - t * m.sp) % 960 + 960) % 960;
      star4(m.x + Math.sin(t + m.ph) * 8, y, m.s * 2);
    });
    ctx.globalAlpha = 1;
  }
  function burst(t, t0, x, y, n, seed, spd, life) {
    var a = t - t0; if (a < 0 || a > life) return;
    var r = rng(seed);
    for (var i = 0; i < n; i++) {
      var ang = r() * 6.283, v = spd * (.25 + r() * .9), k = 2.6, sz = 1.2 + r() * 3.4, col = PAL[(r() * PAL.length) | 0], shp = r(), sp = (r() - .5) * 12, lf = life * (.5 + r() * .5);
      if (a > lf) continue;
      var d = v * (1 - Math.exp(-k * a)) / k;
      var px = x + Math.cos(ang) * d, py = y + Math.sin(ang) * d + 40 * a * a;
      ctx.globalAlpha = Math.pow(1 - a / lf, 1.4); ctx.fillStyle = col;
      if (shp < .45) star4(px, py, sz * 2.2);
      else if (shp < .8) { ctx.save(); ctx.translate(px, py); ctx.rotate(sp * a); ctx.fillRect(-sz, -sz * .45, sz * 2, sz * .9); ctx.restore(); }
      else { ctx.beginPath(); ctx.arc(px, py, sz * .6, 0, 6.283); ctx.fill(); }
    }
    ctx.globalAlpha = 1;
  }
  // 横向光晕（镜头耀斑）
  function flare(t, t0, y, amp, col) {
    var a = t - t0; if (a < 0 || a > .7) return;
    var k = Math.exp(-a / .16) * amp, w = 540 * (.4 + E.outExpo(cl(a / .25)) * 1.4);
    var g = ctx.createLinearGradient(270 - w / 2, 0, 270 + w / 2, 0);
    g.addColorStop(0, 'rgba(255,255,255,0)'); g.addColorStop(.5, col || 'rgba(255,240,255,1)'); g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.globalAlpha = k; ctx.fillStyle = g;
    ctx.fillRect(270 - w / 2, y - 1.2, w, 2.4);
    ctx.globalAlpha = k * .35; ctx.fillRect(270 - w / 2, y - 7, w, 14);
    var rg = ctx.createRadialGradient(270, y, 0, 270, y, 120);
    rg.addColorStop(0, 'rgba(255,255,255,.9)'); rg.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.globalAlpha = k * .6; ctx.fillStyle = rg; ctx.fillRect(150, y - 120, 240, 240);
    ctx.globalAlpha = 1;
  }
  // 速度线：词流越来越快时从右往左掠过
  function streaks(t, t0, t1, dens) {
    var p = seg(t, t0, t1); if (p <= 0 || p >= 1) return;
    var r = rng(31);
    for (var i = 0; i < 46; i++) {
      var y = 300 + r() * 360, sp = 900 + r() * 1500, len = 60 + r() * 220, ph = r() * 3, col = PAL[(r() * 5) | 0];
      if (r() > dens(p)) continue;
      var x = 640 - ((t * sp + ph * 600) % 900);
      var g = ctx.createLinearGradient(x, 0, x + len, 0);
      g.addColorStop(0, col); g.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.globalAlpha = .55 * Math.sin(p * Math.PI); ctx.fillStyle = g; ctx.fillRect(x, y, len, 1.3);
    }
    ctx.globalAlpha = 1;
  }
  function twinkles(t, x, y, w, h, n, seed, alpha) {
    var r = rng(seed);
    ctx.fillStyle = '#fff';
    for (var i = 0; i < n; i++) {
      var px = x + r() * w, py = y + r() * h, ph = r() * 6.28, sp = 2 + r() * 4, sz = 3 + r() * 7;
      var tw = Math.pow(.5 + .5 * Math.sin(t * sp + ph), 6);
      ctx.globalAlpha = alpha * tw; star4(px, py, sz * (.6 + .4 * tw));
    }
    ctx.globalAlpha = 1;
  }
  function converge(t, t0, t1, x, y) {
    var p = seg(t, t0, t1); if (p <= 0 || p >= 1) return;
    var r = rng(77);
    ctx.lineCap = 'round';
    for (var i = 0; i < 80; i++) {
      var ang = r() * 6.283, r0 = 220 + r() * 300, delay = r() * .45, col = PAL[(r() * 5) | 0];
      var q = seg(p, delay, 1); if (q <= 0) continue;
      var e = Math.pow(q, 1.8), rr = r0 * (1 - e), rt = r0 * (1 - Math.pow(Math.max(0, q - .08), 1.8));
      ctx.globalAlpha = Math.sin(q * Math.PI) * .9; ctx.strokeStyle = col; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.moveTo(x + Math.cos(ang) * rt, y + Math.sin(ang) * rt); ctx.lineTo(x + Math.cos(ang) * rr, y + Math.sin(ang) * rr); ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  /* ---------- 时间线 ---------- */
  var cur = {};
  function setText(el, key, s) { if (cur[key] !== s) { cur[key] = s; el.textContent = s; } }
  function flashAt(t, t0, peak, dec) { var a = t - t0; return a < 0 ? 0 : peak * Math.exp(-a / dec) * (a < .02 ? a / .02 : 1); }
  function shake(t, t0, amp, dur) { var a = t - t0; if (a < 0 || a > dur) return [0, 0]; var k = amp * Math.pow(1 - a / dur, 2); return [Math.sin(a * 83) * k, Math.cos(a * 67) * k]; }
  var STAMP = { x: 0, y: 0 }, TKT = { x: 430, y: 67 };
  function TK_PATH(q, f) {
    var p = E.io3(cl(f)), sx = 400, sy = 402 + B_POS[q] * 86 + 35, tx = TKT.x, ty = TKT.y;
    var cx = (sx + tx) / 2 + 30, cy = Math.min(sy, ty) - 120;
    return [(1 - p) * (1 - p) * sx + 2 * (1 - p) * p * cx + p * p * tx, (1 - p) * (1 - p) * sy + 2 * (1 - p) * p * cy + p * p * ty];
  }

  function render(t) {
    ctx2.setTransform(2, 0, 0, 2, 0, 0); ctx2.clearRect(0, 0, 540, 960);
    ctx = ctx0;
    ctx.setTransform(2, 0, 0, 2, 0, 0); ctx.clearRect(0, 0, 540, 960);

    /* 背景 */
    var day = seg(t, 2.97, 3.0) * (1 - seg(t, 6.75, 7.0));
    bgD.style.opacity = day; bgD.style.transform = 'scale(' + (1.12 - .08 * seg(t, 3, 7)) + ')';
    bgN.style.opacity = 1 - day; bgN.style.transform = 'scale(' + (1.16 - .1 * seg(t, 0, 10.5)) + ')';
    bgG.style.opacity = seg(t, 10.3, 10.5) * (1 - day); bgG.style.transform = 'scale(' + (1.05 + .06 * seg(t, 10.5, 20)) + ') rotate(' + (seg(t, 10.5, 20) * 3) + 'deg)';
    $('#vig').style.opacity = lerp(1, .3, day);

    var night = 1 - day;
    starfield(t, night * (t < 3 ? seg(t, 0, .6) : 1));
    motes(t, day);

    /* 镜头震动 */
    var s1 = shake(t, 8.0, 9, .45), s2 = shake(t, 17.5, 7, .35), s3 = shake(t, 13.5, 5, .3);
    var pu = pulse(t), drift = Math.sin(t * .6) * .35;
    world.style.transform = 'translate(' + (s1[0] + s2[0] + s3[0]) + 'px,' + (s1[1] + s2[1] + s3[1]) + 'px) scale(' + (1 + pu * .012) + ') rotate(' + drift + 'deg)';
    bgN.style.filter = bgG.style.filter = 'brightness(' + (1 + pu * .12) + ')';

    streaks(t, .4, 2.35, function (p) { return .15 + .85 * p; });
    sceneA(t); sceneB(t); sceneC(t); sceneD(t); sceneF(t); sceneE(t);
    // 前景层：耀斑和贴在画面最上面的粒子
    ctx = ctx2;
    flare(t, 2.2, 444, .9); flare(t, 8.0, 522, 1.2); flare(t, 13.5, 460, .9, 'rgba(255,226,170,1)'); flare(t, 17.5, STAMP.y || 700, 1, 'rgba(255,226,170,1)');
    for (var fk = 1; fk < 7; fk++) flare(t, D_T0 + fk * .5, 470, .35);
    fgFX(t);
    ctx = ctx0;

    /* 转场：镭射色带扫过（A→B） */
    var wp = seg(t, 2.72, 3.28), wipe = $('#wipe');
    show(wipe, wp > 0 && wp < 1);
    if (wp > 0 && wp < 1) wipe.style.transform = 'translateX(' + lerp(-1400, 600, E.io3(wp)) + 'px) skewX(-14deg)';

    var fl = Math.max(flashAt(t, 8.0, .95, .16), flashAt(t, 17.5, .5, .14), flashAt(t, 10.5, .35, .12));
    for (var k = 1; k < 7; k++) fl = Math.max(fl, flashAt(t, D_T0 + k * .5, k === 6 ? .3 : .14, .1));
    $('#flash').style.opacity = cl(fl);
    $('#fade').style.opacity = Math.max(1 - seg(t, 0, .35), seg(t, 19.55, 20));
  }

  function fgFX(t) {
    // 点选正确选项：小爆发
    ROUNDS.forEach(function (Q, q) { if (t > 3 && t < 7) burst(t, Q.pick, 400, 402 + B_POS[q] * 86 + 35, 22, 50 + q, 260, .6); });
    // 抽卡券拖尾
    ROUNDS.forEach(function (Q, q) {
      var a = t - Q.pick; if (a < 0 || a > Q.fly + .25 || t > 6.9) return;
      for (var j = 1; j <= 6; j++) {
        var aa = a - j * .035; if (aa < 0 || aa > Q.fly) continue;
        var pp = TK_PATH(q, aa / Q.fly);
        ctx.globalAlpha = (1 - j / 7) * .8; ctx.fillStyle = PAL[j % 5]; star4(pp[0] + Math.sin(j * 7) * 4, pp[1] + Math.cos(j * 5) * 4, 4.5 - j * .5);
      }
      ctx.globalAlpha = 1;
    });
    burst(t, 8.0, 270, 522, 140, 3, 980, 1.7);
    burst(t, 13.5, 270, 470, 80, 13, 700, 1.3);
    if (t > 17.5) burst(t, 17.5, STAMP.x, STAMP.y, 90, 31, 560, 1.4);
    if (t > 17.7) twinkles(t, 90, 230, 360, 560, 22, 91, seg(t, 17.7, 18.2) * (1 - seg(t, 19.55, 20)));
    if (t > 8.3 && t < 10.4) twinkles(t, 80, 250, 380, 560, 16, 92, seg(t, 8.3, 8.8) * (1 - seg(t, 10.1, 10.4)));
  }

  function sceneA(t) {
    var on = t < 3.02; show(sA, on); if (!on) return;
    var ki = -1; for (var i = 0; i < A_T.length; i++) if (t >= A_T[i]) ki = i;
    var kick = $('#aKick'), line = $('#aLine'), word = $('#aWord'), ipa = $('#aIpa'), no = $('#aNo');
    var kp = E.out3(seg(t, .15, .9));
    kick.style.opacity = kp; kick.style.letterSpacing = lerp(1.1, .5, kp) + 'em';
    line.style.transform = 'scaleX(' + E.outExpo(seg(t, .1, .8)) + ')';
    if (ki < 0) { word.style.opacity = 0; ipa.style.opacity = 0; no.style.opacity = 0; return; }
    var w = W(A_WORDS[ki]), age = t - A_T[ki], last = ki === A_WORDS.length - 1;
    setText(word, 'aw', w.w); setText(no, 'an', pad3(w.i) + ' / 688'); setText(ipa, 'ai', w.p);
    var e = E.out3(seg(age, 0, last ? .3 : .12));
    word.style.opacity = e;
    word.style.filter = 'blur(' + ((1 - e) * 10) + 'px)';
    var sc = last ? lerp(1.3, 1, E.outBack(seg(age, 0, .4))) : lerp(1.08, 1, e);
    word.style.transform = 'translateY(' + ((1 - e) * 16) + 'px) scale(' + sc + ')';
    no.style.opacity = .4 + .6 * e;
    ipa.style.opacity = last ? E.out3(seg(age, .15, .45)) : 0;
    // 出场：随色带扫过淡出
    sA.style.opacity = 1 - seg(t, 2.85, 3.0);
  }

  function sceneB(t) {
    var on = t > 2.95 && t < 7.05; show(sB, on); if (!on) return;
    var r = 0; for (var i = 0; i < ROUNDS.length; i++) if (t >= ROUNDS[i].t0) r = i;
    var R = ROUNDS[r], age = t - R.t0;
    var panel = $('#bPanel');
    var ent = E.out3(seg(t, 3.0, 3.45));
    setText($('#bWord'), 'bw', R.w.w); setText($('#bIpa'), 'bi', R.w.p);
    setText($('#bLab'), 'bl', '全部测试 · ' + (r + 1) + ' / 25');
    var bump = r > 0 ? 1 + .04 * (1 - E.out3(seg(age, 0, .18))) : 1;
    panel.style.opacity = ent;
    panel.style.transform = 'perspective(900px) translateY(' + ((1 - ent) * 40) + 'px) rotateX(' + (3.5 * Math.sin(t * 2.1) + (1 - ent) * 25) + 'deg) rotateY(' + (5 * Math.sin(t * 1.5 + .8)) + 'deg) scale(' + bump + ')';
    var wordIn = r > 0 ? E.out3(seg(age, 0, .1)) : 1;
    $('#bWord').style.opacity = wordIn; $('#bWord').style.filter = 'blur(' + (1 - wordIn) * 6 + 'px)';
    var picked = t >= R.pick;
    opts.forEach(function (o, j) {
      setText(o.lastChild, 'bo' + j, R.opts[j]);
      var oe = E.out3(seg(t, 3.12 + j * .07, 3.5 + j * .07));
      var ok = picked && j === B_POS[r];
      o.classList.toggle('ok', ok);
      o.firstChild.textContent = ok ? '✓' : 'ABCD'[j];
      var pop = ok ? 1 + .05 * Math.sin(Math.PI * seg(t, R.pick, R.pick + .16)) : 1;
      o.style.opacity = oe * (picked && !ok ? .45 : 1);
      o.style.transform = 'translateY(' + ((1 - oe) * 30) + 'px) scale(' + pop + ')';
    });
    // 抽卡券飞向右上角
    var cnt = 0, lastArr = -9;
    ROUNDS.forEach(function (Q, q) {
      var a = t - Q.pick, im = tks[q];
      if (a >= Q.fly) { cnt++; lastArr = Math.max(lastArr, Q.pick + Q.fly); }
      if (a < 0 || a >= Q.fly) { im.style.display = 'none'; return; }
      im.style.display = 'block';
      var p = E.io3(a / Q.fly), xy = TK_PATH(q, a / Q.fly);
      var s = lerp(1.25, .5, p) * E.outBack(seg(a, 0, .12));
      im.style.transform = 'translate(' + xy[0] + 'px,' + xy[1] + 'px) rotate(' + lerp(-18, 8, p) + 'deg) scale(' + s + ')';
    });
    setText($('#bCnt'), 'bc', String(cnt));
    var pill = $('#bPill');
    pill.style.transform = 'scale(' + (1 + .12 * (1 - E.out3(seg(t - lastArr, 0, .2)))) + ')';
    pill.style.opacity = E.out3(seg(t, 3.05, 3.4));
    var cap = $('#bCap'), ce = E.out3(seg(t, 3.3, 3.75));
    cap.style.opacity = ce; cap.style.transform = 'translateY(' + (1 - ce) * 14 + 'px)';
    // 出场：冲进画面中心
    var ex = E.in3(seg(t, 6.72, 7.0));
    sB.style.transform = 'scale(' + (1 + ex * .7) + ')'; sB.style.opacity = 1 - ex; sB.style.filter = ex > 0 ? 'blur(' + ex * 10 + 'px)' : '';
  }

  function sceneC(t) {
    var on = t > 6.85 && t < 10.62; show(sC, on); if (!on) return;
    var cx = 270, cy = 268 + 509.5 / 2;
    var pre = seg(t, 6.95, 8.0), flipP = seg(t, 8.0, 8.6);
    // 翻面
    var ang = 180 * (1 - E.outBack(flipP));
    var sc = t < 8 ? lerp(.45, .66, E.out3(seg(t, 6.95, 7.4))) : lerp(.66, 1, E.outBack(seg(t, 8.0, 8.5)));
    var shk = t < 8 ? Math.sin(t * 70) * 3.2 * Math.pow(pre, 2.2) : 0;
    var flip = $('#cFlip');
    flip.style.transform = 'translateX(' + shk + 'px) translateY(' + (t < 8 ? (1 - E.out3(seg(t, 6.95, 7.4))) * 80 : 0) + 'px) scale(' + sc + ') rotateY(' + ang + 'deg)';
    flip.style.opacity = E.out3(seg(t, 6.95, 7.25));
    var front = Math.cos(ang * Math.PI / 180) > 0;
    $('#cFront').style.visibility = front ? 'visible' : 'hidden';
    $('#cBack').style.visibility = front ? 'hidden' : 'visible';
    var a8 = t - 8.0;
    var px = 50 + 30 * Math.sin(a8 * 2.6), py = 46 + 24 * Math.sin(a8 * 4.1 + .6);
    pose(cCard.el, t < 8 ? 50 : px, t < 8 ? 50 : py, t < 8 ? 0 : cl(.4 + a8 * 2), .55);
    // 光
    var rays = $('#cRays');
    rays.style.opacity = t < 8 ? pre * .5 : lerp(1, .55, seg(t, 8, 9));
    rays.style.transform = 'rotate(' + (t * 14) + 'deg) scale(' + (t < 8 ? .7 + pre * .2 : 1) + ')';
    var glow = $('#cGlow');
    glow.style.opacity = t < 8 ? pre * .7 : lerp(1, .5, seg(t, 8, 9.2));
    glow.style.transform = 'scale(' + (t < 8 ? .4 + pre * .5 + Math.sin(t * 18) * .03 * pre : lerp(1.3, 1, seg(t, 8, 9))) + ')';
    var ring = $('#cRing'), rp = seg(t, 8.0, 8.7);
    ring.style.opacity = rp > 0 && rp < 1 ? 1 - rp : 0; ring.style.transform = 'scale(' + (.3 + E.out3(rp) * 4.2) + ')';
    // 文字
    [['#cTier', 8.3], ['#cEn', 8.42], ['#cCn', 8.56], ['#cProb', 8.9]].forEach(function (x) {
      var el = $(x[0]), e = E.out3(seg(t, x[1], x[1] + .4));
      el.style.opacity = e; el.style.transform = 'translateY(' + (1 - e) * 16 + 'px)'; el.style.filter = e < 1 ? 'blur(' + (1 - e) * 6 + 'px)' : '';
    });
    converge(t, 7.0, 8.0, cx, cy);
    // 出场
    var ex = E.in3(seg(t, 10.28, 10.5));
    sC.style.opacity = 1 - ex; sC.style.transform = 'scale(' + (1 - ex * .12) + ')';
  }

  function sceneD(t) {
    var on = t > 10.4 && t < 14.75; show(sD, on); if (!on) return;
    var p = -(1 - E.outExpo(seg(t, D_T0, D_T0 + .4)));
    for (var k = 1; k < 7; k++) p += E.outExpo(seg(t, D_T0 + k * .5, D_T0 + k * .5 + .34));
    var ex = E.io3(seg(t, 14.15, 14.6));
    D.forEach(function (d, k) {
      var dd = k - p, ad = Math.abs(dd);
      var op = ad < 1 ? 1 - ad * .35 : Math.max(0, .65 - (ad - 1) * .55);
      var x = dd * 205 * (1 - ex), z = -ad * 240 - ex * 300, ry = cl(-dd * 42, -65, 65) * (1 - ex);
      d.c.wrap.style.transform = 'translate3d(' + x + 'px,' + (-ex * 40) + 'px,' + z + 'px) rotateY(' + ry + 'deg)';
      d.c.wrap.style.opacity = op * (1 - ex);
      d.c.wrap.style.zIndex = String(100 - Math.round(ad * 10));
      d.c.wrap.style.display = op * (1 - ex) > .01 ? 'block' : 'none';
      var lt = t - (D_T0 + k * .5);
      pose(d.c.el, 50 + 28 * Math.sin(lt * 4.4 + k), 44 + 22 * Math.cos(lt * 3.2 + k * 2), ad < .6 ? 1 : .35, .45);
      if (d.c.veil) slit(d.c, E.io3(seg(t, 13.55, 14.15)));
    });
    var ci = cl(Math.round(p), 0, 6), cd = D[ci], age = t - (D_T0 + ci * .5);
    var big = $('#dBig');
    setText(big, 'db', cd.tier);
    big.classList.toggle('gold', cd.tier === 'SECRET');
    big.style.fontSize = (cd.tier.length > 3 ? 132 : cd.tier.length === 3 ? 200 : 236) + 'px';
    var be = E.outExpo(seg(age, 0, .4));
    big.style.opacity = E.out3(seg(age, 0, .14)) * (1 - ex);
    big.style.transform = 'scale(' + lerp(1.3, 1, be) + ')';
    big.style.letterSpacing = lerp(.3, .04, be) + 'em';
    var ca = 1 - E.out3(seg(age, 0, .3));
    big.style.textShadow = ca > .01 ? (-10 * ca) + 'px 0 rgba(255,120,200,' + (.7 * ca) + '),' + (10 * ca) + 'px 0 rgba(120,220,255,' + (.7 * ca) + ')' : 'none';
    setText($('#dCn'), 'dc', cd.cn); setText($('#dRate'), 'dr', cd.rate);
    ['#dCn', '#dRate'].forEach(function (s, j) {
      var e = E.out3(seg(age, .04 + j * .05, .26 + j * .05)), el = $(s);
      el.style.opacity = e * (1 - ex); el.style.transform = 'translateY(' + (1 - e) * 12 + 'px)';
    });
    var g = $('#dGlow');
    g.style.background = 'radial-gradient(circle,' + cd.col[1] + ' 0,' + cd.col[0] + '66 30%,rgba(0,0,0,0) 66%)';
    g.style.opacity = (.42 + .2 * (1 - E.out3(seg(age, 0, .4)))) * (1 - ex);
  }

  function sceneE(t) {
    var on = t > 14.3 && t < 17.5; show(sE, on);
    var bs = $('#bigSeal');
    if (!on) { bs.style.display = 'none'; return; }
    var cap = $('#eCap'), ce = E.out3(seg(t, 14.6, 15.0));
    cap.style.opacity = ce * (1 - seg(t, 16.8, 17.1)); cap.style.transform = 'translateY(' + (1 - ce) * 14 + 'px)';
    cap.style.filter = ce < 1 ? 'blur(' + (1 - ce) * 6 + 'px)' : '';
    var ti = t >= 15 && t < 16.85 ? Math.min(3, Math.floor((t - 15) / .5)) : -1;
    var tAge = ti >= 0 ? t - (15 + ti * .5) : 0;
    var focus = E.io3(seg(t, 16.75, 17.12));
    var rot = (t - 14.4) * .9 + .6, cx = 270, cy = 590, rx = 205 + focus * 120, ry = 74 + focus * 40;
    seals.forEach(function (s, j) {
      var a = rot + j / 10 * 6.283, depth = (Math.sin(a) + 1) / 2;
      var x = cx + rx * Math.cos(a), y = cy + ry * Math.sin(a), size = 74 + 44 * depth;
      var st = 14.45 + j * .05, pop = E.outBack(seg(t, st, st + .32));
      var hot = ti >= 0 && s.rank === ti, k = ti < 0 ? 1 : hot ? 1.32 + .08 * Math.sin(Math.PI * seg(tAge, 0, .2)) : .9;
      var op = ti < 0 ? 1 : hot ? 1 : .38;
      if (s.id === 'midnight') { s.el.style.display = 'none'; return; }
      op *= 1 - focus;
      s.el.style.display = op > .01 && pop > 0 ? 'block' : 'none';
      s.el.style.opacity = op;
      s.el.style.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + (size / 100 * k * pop) + ')';
      s.el.style.zIndex = String(Math.round(depth * 100));
      s.el.style.setProperty('--lx', (50 - Math.cos(a) * 35) + '%'); s.el.style.setProperty('--ly', (30 - Math.sin(a) * 10) + '%');
      if (hot && op > .01) {
        var gr = ctx.createRadialGradient(x, y, 0, x, y, size * .9);
        gr.addColorStop(0, 'rgba(255,236,250,.55)'); gr.addColorStop(1, 'rgba(255,236,250,0)');
        ctx.globalAlpha = E.out3(seg(tAge, 0, .15)); ctx.fillStyle = gr; ctx.fillRect(x - size, y - size, size * 2, size * 2); ctx.globalAlpha = 1;
      }
    });
    // 午夜星月：环上 → 画面中央放大 → 盖到卡面上
    var mj = 9, ma = rot + mj / 10 * 6.283, md = (Math.sin(ma) + 1) / 2;
    var m0x = cx + (205) * Math.cos(ma), m0y = cy + 74 * Math.sin(ma), m0s = 74 + 44 * md;
    var mpop = E.outBack(seg(t, 14.45 + mj * .05, 14.45 + mj * .05 + .32));
    var mhot = ti === 3 ? 1.32 + .08 * Math.sin(Math.PI * seg(tAge, 0, .2)) : 1;
    var mop = ti < 0 || ti === 3 ? 1 : .38;
    var X = lerp(m0x, 270, focus), Y = lerp(m0y, 470, focus), S = lerp(m0s * mhot, 236, focus);
    var st2 = E.in3(seg(t, 17.18, 17.5));
    if (st2 > 0) { X = lerp(270, STAMP.x, st2); Y = lerp(470, STAMP.y, st2); S = lerp(236, STAMP.s, st2); }
    bs.style.display = 'block'; bs.style.zIndex = '50';
    bigSeal.style.opacity = mop + (1 - mop) * focus;
    bigSeal.style.width = bigSeal.style.height = S + 'px';
    bigSeal.style.transform = 'translate(' + (X - S / 2) + 'px,' + (Y - S / 2) + 'px) scale(' + mpop + ') rotate(' + (st2 * -8) + 'deg)';
    bigSeal.style.setProperty('--lx', lerp(15, 85, seg(t, 16.9, 17.4)) + '%'); bigSeal.style.setProperty('--ly', '28%');
    // 等级文字
    var eT = $('#eT');
    if (ti >= 0) {
      setText(eT.firstChild, 'et', ST[ti].cn); setText(eT.lastChild, 'er', ST[ti].rate + '%');
      var e = E.out3(seg(tAge, 0, .2));
      eT.style.opacity = e * (1 - focus); eT.style.transform = 'scale(' + lerp(1.2, 1, E.outExpo(seg(tAge, 0, .35))) + ')';
      eT.style.filter = e < 1 ? 'blur(' + (1 - e) * 8 + 'px)' : '';
    } else eT.style.opacity = 0;
    burst(t, 15 + 3 * .5, 270, 590, 40, 21, 420, .9);
  }

  function sceneF(t) {
    var on = t > 16.85; show(sF, on); if (!on) return;
    var ent = E.out3(seg(t, 16.9, 17.35));
    var sh = shake(t, 17.5, 5, .3);
    fC.wrap.style.opacity = ent;
    fC.wrap.style.zIndex = '10';
    fC.wrap.style.transform = 'translate3d(' + sh[0] + 'px,' + ((1 - ent) * 70 + sh[1]) + 'px,0) scale(' + (lerp(.9, 1, ent) * (t >= 17.5 ? 1 - .03 * Math.sin(Math.PI * seg(t, 17.5, 17.7)) : 1)) + ')';
    var a = t - 17.6;
    pose(fC.el, t < 17.6 ? 50 : 50 + 24 * Math.sin(a * 1.9), t < 17.6 ? 48 : 46 + 18 * Math.sin(a * 2.7 + .4), t < 17.4 ? .5 : 1, .5);
    if (fC.seal) fC.seal.style.opacity = t >= 17.5 ? 1 : 0;
    slit(fC, t < 18.6 ? E.io3(seg(t, 17.95, 18.6)) : E.io3(seg(t, 18.9, 19.5)));
    var fan = E.outBack(seg(t, 17.65, 18.25));
    [[fL, -1], [fR, 1]].forEach(function (x) {
      var c = x[0], sgn = x[1];
      c.wrap.style.zIndex = '5';
      c.wrap.style.display = fan > 0 ? 'block' : 'none';
      c.wrap.style.opacity = cl(fan) * .9;
      c.wrap.style.transform = 'translate3d(' + (sgn * 150 * fan) + 'px,' + (30 * fan) + 'px,' + (-140 * fan) + 'px) rotateZ(' + (sgn * 11 * fan) + 'deg) rotateY(' + (-sgn * 14 * fan) + 'deg)';
      pose(c.el, 50 - sgn * 18 + 10 * Math.sin(t * 2), 40 + 10 * Math.cos(t * 2.3), .8, .3);
    });
    [['#fTitle', 17.75, .5], ['#fSub', 18.05, .45], ['#fTease', 18.3, .45], ['#fFoot', 18.5, .45]].forEach(function (x) {
      var el = $(x[0]), e = E.out3(seg(t, x[1], x[1] + x[2]));
      el.style.opacity = e; el.style.filter = e < 1 ? 'blur(' + (1 - e) * 10 + 'px)' : '';
      el.style.transform = 'translateY(' + (1 - e) * 14 + 'px)';
    });
    $('#fTitle').style.backgroundPosition = (100 - seg(t, 17.75, 20) * 100) + '% 0';
  }

  window.render = render;
  window.DURATION = 20;
  // 预热：每个场景都画一遍，触发图片和分片字体加载
  window.warm = function () {
    for (var t = 0; t <= 20; t += .25) render(t);
    // 盖章落点：卡片落定时蜡封的位置
    render(3.6);
    var tr = $('#bTk').getBoundingClientRect(); TKT.x = tr.left + tr.width / 2; TKT.y = tr.top + tr.height / 2;
    render(17.45);
    var r = fC.seal.getBoundingClientRect(); STAMP.x = r.left + r.width / 2; STAMP.y = r.top + r.height / 2; STAMP.s = r.width;
    render(0);
  };
})();
