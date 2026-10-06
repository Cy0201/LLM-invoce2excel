/* 不止单词 · 运营工具（只自己扫码预览用，绝不上架：里面有全年兑换码）
 * 打开自动定位本周 → 生成 SSR 福利海报 → 存相册 / 一键打开发笔记页（图片、标题、正文已填好，你点发布） */
(function () {
  'use strict';
  var D = window.OPS_CODES || [], T = [['ssr1', '彩虹私语'], ['ssr2', '人鱼眼泪']];
  var STYLE = { ssr1: { seal: 'crown', line: 'A little gift, sealed for you.' }, ssr2: { seal: 'pearl', line: 'Something rare is waiting this week.' } };
  var wi = 0, ti = 0, img = null;
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function today() { var d = new Date(); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function md(s) { var p = s.split('-'); return +p[1] + '.' + +p[2]; }
  D.forEach(function (w, i) { if (w.from <= today() && today() <= w.to) wi = i; });
  var el = document.createElement('div'); el.id = 'ops';
  el.innerHTML = '<div class="op-h"><b>不止单词 · 运营</b><span>只自己用，不要上架</span></div>' +
    '<div class="op-w"><button type="button" id="opPrev">‹</button><div><b id="opWeek"></b><span id="opDate"></span></div><button type="button" id="opNext">›</button></div>' +
    '<div class="op-code" id="opCode"></div>' +
    '<div class="op-t" id="opTpl"></div>' +
    '<div class="op-img"><img id="opImg" alt=""><p id="opLoad">生成中…</p></div>' +
    '<div class="op-note"><b id="opTitle"></b><pre id="opText"></pre></div>' +
    '<div class="op-a"><button type="button" id="opSave">存到相册</button><button type="button" id="opPost">发笔记</button></div>' +
    '<p class="op-tip" id="opTip"></p>';
  document.body.appendChild(el);
  var $ = function (id) { return document.getElementById(id); };
  T.forEach(function (t, i) { var b = document.createElement('button'); b.type = 'button'; b.textContent = t[1]; b.onclick = function () { ti = i; render(); }; $('opTpl').appendChild(b); });
  function note() {
    var w = D[wi];
    return {
      title: '本周福利｜送你' + w.tickets + '张抽卡券🎟️',
      content: '长按「不止单词」首页的火漆，输入兑换码\n' + w.codes[0] + '\n' + md(w.from) + ' – ' + md(w.to) + ' 有效，每台手机限领一次 ✨\n\n#不止单词 #高考英语 #背单词 #抽卡'
    };
  }
  function tip(s) { $('opTip').textContent = s; clearTimeout(tip.t); tip.t = setTimeout(function () { $('opTip').textContent = ''; }, 2600); }
  async function render() {
    var w = D[wi]; if (!w) { $('opWeek').textContent = '没有码'; return; }
    $('opWeek').textContent = '第 ' + pad(w.week) + ' 周' + (w.from <= today() && today() <= w.to ? ' · 本周' : '');
    $('opDate').textContent = md(w.from) + ' – ' + md(w.to) + ' · 每码 ' + w.tickets + ' 张';
    $('opCode').textContent = w.codes[0];
    Array.prototype.forEach.call($('opTpl').children, function (b, i) { b.className = i === ti ? 'on' : ''; });
    var n = note(); $('opTitle').textContent = n.title; $('opText').textContent = n.content;
    $('opImg').style.opacity = .3; $('opLoad').hidden = false;
    var vid = T[ti][0], my = render.n = (render.n || 0) + 1;
    try {
      var cv = await window.__danci.giftPoster(Object.assign({ vid: vid, code: w.codes[0], tickets: w.tickets, from: md(w.from), to: md(w.to), week: pad(w.week) }, STYLE[vid]));
      if (my !== render.n) return;
      img = cv.toDataURL('image/jpeg', .92); $('opImg').src = img; $('opImg').style.opacity = 1; $('opLoad').hidden = true;
    } catch (e) { $('opLoad').textContent = '生成失败'; }
  }
  function mt() { return window.xhs && window.xhs.miniTool; }
  async function file() {
    var m = mt();
    if (m && m.writeTempFile) { try { var r = await m.writeTempFile({ data: img }); if (r && r.filePath) return r.filePath; } catch (e) { } }
    return img;
  }
  $('opPrev').onclick = function () { if (wi > 0) { wi--; render(); } };
  $('opNext').onclick = function () { if (wi < D.length - 1) { wi++; render(); } };
  $('opSave').onclick = async function () {
    var m = mt(); if (!img) return;
    if (!m || !m.saveImageToPhotosAlbum) { tip('请在小红书 App 里扫码打开'); return; }
    try { await m.saveImageToPhotosAlbum({ filePath: await file() }); tip('已保存到相册'); } catch (e) { tip('没有保存成功，请允许访问相册'); }
  };
  $('opPost').onclick = async function () {
    var m = mt(); if (!img) return;
    if (!m || !m.postNote) { tip('请在小红书 App 里扫码打开'); return; }
    var n = note();
    try { await m.postNote({ title: n.title.slice(0, 20), content: n.content.slice(0, 1000), pageType: 'photo_publish', mediaInfo: { image_resources: [{ url: await file() }] } }); }
    catch (e) { tip('没有打开发布页，可以先存到相册'); }
  };
  // 等 app 启动、字体就绪后再画
  setTimeout(render, 600);
})();
