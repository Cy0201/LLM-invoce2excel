/* 卡片渲染：完整镭射卡（cards-css）与轻量缩略卡。
 * 依赖：holokit.js（cards-css，MIT）、catalog.js；线稿配置 window.LINEART（lineart.js，可为空） */
(function () {
  'use strict';
  var C = window.CATALOG;
  var LINEART = window.LINEART || {};
  var REDUCE = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function pad3(n) { return ('00' + n).slice(-3); }
  function lenClass(w) {
    var n = (w.en || '').length;
    return n > 78 ? ' xl' : n > 58 ? ' lg' : '';
  }
  function tierLabel(t) { return t; }

  // w: {i,w,p,cp,cm,en,cn,src,g}
  function overlayHTML(v, w, withWord) {
    var wd = '<div class="cf-w">' + esc(w.w) + '</div>';
    return (v.frame ? '<div class="cf-frame"></div>' : '') + (withWord ? wd : '') +
      '<div class="cf-tier">' + tierLabel(v.tier) + '</div><div class="cf-name">' + esc(v.en) + '</div>' +
      '<div class="cf-no">' + pad3(w.i) + ' / 688</div>' +
      '<div class="cf-pm"><span class="cf-ipa">' + esc(w.p) + '</span><b><i>' + esc(w.cp) + '</i>' + esc(w.cm) + '</b></div>' +
      (w.en ? '<div class="cf-line' + lenClass(w) + '"><i class="cf-rule"></i><em>' + esc(w.en) + '</em><span class="cf-cn">' + esc(w.cn) + '</span>' + (w.src ? '<span class="cf-src">— ' + esc(w.src) + '</span>' : '') + '</div>' : '') +
      '<div class="cf-foot"><span>' + esc(v.cn) + '</span><span>第 ' + w.g + ' 组</span></div>' +
      (v.charm ? '<img class="cf-charm" src="img/charm/' + v.charm + '.webp" alt="">' : '');
  }

  /* 完整卡。opt: {interactive, glow, lit} 返回 {el, card} */
  function make(vid, w, opt) {
    opt = opt || {};
    var v = C.BY_ID[vid], land = !!v.land;
    var art = LINEART[vid];
    var top = !!(v.top || art);
    var face = document.createElement('div');
    face.className = 'cf-face' + (v.lt ? ' lt' : '') + (land ? ' land' : '');
    if (!top) face.innerHTML = '<div class="cf-w">' + esc(w.w) + '</div>';
    var ov = document.createElement('div');
    ov.className = 'cf-ov' + (v.lt ? ' lt' : '') + (v.gold ? ' gold' : '') + (land ? ' land' : '') + (v.frame ? ' fr' + v.frame : '');
    ov.innerHTML = overlayHTML(v, w, top);
    var layers;
    if (art) {
      layers = [{ image: art, className: 'cf-art cf-art-' + vid, opacity: v.lt ? .5 : .55, parallax: 6, size: 'cover', position: land ? 'right center' : 'center top' }];
    }
    var pal = v.pal || (v.eff === 'holo' || v.eff === 'reverse' || v.eff === 'radiant' ? C.PASTEL : undefined);
    var card = HoloKit.createHoloCard({
      image: 'img/art/' + vid + '.webp', effect: v.eff, textureSeed: 7,
      aspectRatio: land ? 386 / 250 : 250 / 386, gyroscope: false,
      interactive: !!opt.interactive, content: face, overlay: ov, layers: layers,
      visual: v.vis || {}, palette: pal, glow: opt.glow,
      // 可交互的卡：自动缓慢扫光，手指一碰就跟手；静态展示的卡用固定光位（.lit）
      showcase: opt.interactive && !REDUCE ? { delay: 400, loop: true, speed: .03, intensity: 14 } : false
    });
    var el = card.element;
    el.classList.add('t-' + v.tier, 'v-' + vid, 'hc');
    if (land) el.classList.add('is-land');
    if (art) el.classList.add('has-art');
    if (!opt.interactive || REDUCE) el.classList.add('lit');
    return { el: el, card: card };
  }

  /* 按容器宽度设定卡面字号（排版都以 em 为单位） */
  function fit(box, v) {
    var wpx = box.clientWidth || box.getBoundingClientRect().width;
    var land = C.BY_ID[v] && C.BY_ID[v].land;
    box.style.fontSize = (land ? wpx / 1.544 : wpx) * 0.24 + 'px';
  }

  /* 轻量缩略卡：一张底图 + 少量文字，用在卡册、首页、十连等需要同时显示很多张的地方 */
  function mini(vid, w, opt) {
    opt = opt || {};
    var v = C.BY_ID[vid];
    var d = document.createElement('div');
    d.className = 'mc t-' + v.tier + ' v-' + vid + (v.lt ? ' lt' : '') + (opt.cls ? ' ' + opt.cls : '');
    d.innerHTML = '<div class="mc-in" style="background-image:url(img/art/' + vid + '.webp)">' +
      (v.rank >= 2 ? '<i class="mc-foil"></i>' : '') + (v.frame ? '<i class="mc-frame"></i>' : '') +
      '<b class="mc-t">' + v.tier + '</b>' +
      (w ? '<span class="mc-w">' + esc(w.w) + '</span>' : '') +
      (v.charm && opt.charm !== false ? '<img class="mc-ch" src="img/charm/' + v.charm + '.webp" alt="">' : '') +
      '</div>';
    return d;
  }

  window.CardKit = { make: make, mini: mini, fit: fit, esc: esc, pad3: pad3 };
})();
