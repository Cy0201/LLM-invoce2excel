/* 兑换码：离线校验，不联网。
 * 码 = 12 位 Crockford Base32（去掉 I L O U），显示成 XXXX-XXXX-XXXX，共 60 位：
 *   高 30 位：签名 24 位 | 张数 6 位
 *   低 30 位：批次 8 位 | 截止日 12 位（2026-01-01 起的天数，含当天）| 序号 10 位，再用签名派生的掩码打乱
 * 生成见 tools/gift_codes.py（读取这里的 K，改 K 会让已发出的码全部失效） */
(function () {
  'use strict';
  var K = 'iPKWV5ZufTrgvo6f9615KKsYUD0x';
  var AB = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
  var EPOCH = Date.UTC(2026, 0, 1);
  function h32(str, seed) {
    var h1 = 0xdeadbeef ^ seed, h2 = 0x41c6ce57 ^ seed;
    for (var i = 0; i < str.length; i++) {
      var ch = str.charCodeAt(i);
      h1 = Math.imul(h1 ^ ch, 2654435761); h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (h1 ^ h2) >>> 0;
  }
  // 输入宽容：大小写、空格、横线都行；O→0，I/L→1，U→V
  function clean(s) {
    return String(s || '').toUpperCase().replace(/[O]/g, '0').replace(/[IL]/g, '1').replace(/U/g, 'V').replace(/[^0-9A-Z]/g, '');
  }
  function fmt(s) { s = clean(s).slice(0, 12); return s.replace(/(.{4})(?=.)/g, '$1-'); }
  function today() { var d = new Date(); return Math.floor((Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) - EPOCH) / 864e5); }
  function dayStr(n) { var d = new Date(EPOCH + n * 864e5); return d.getUTCFullYear() + '.' + (d.getUTCMonth() + 1) + '.' + d.getUTCDate(); }
  /* 返回 {ok:true, n, batch, day, serial, code} 或 {ok:false, err:'format'|'sign'|'expired'} */
  function parse(input) {
    var s = clean(input);
    if (s.length !== 12) return { ok: false, err: 'format' };
    var hi = 0, lo = 0, i, v;
    for (i = 0; i < 6; i++) { v = AB.indexOf(s[i]); if (v < 0) return { ok: false, err: 'format' }; hi = hi * 32 + v; }
    for (i = 6; i < 12; i++) { v = AB.indexOf(s[i]); if (v < 0) return { ok: false, err: 'format' }; lo = lo * 32 + v; }
    var sig = Math.floor(hi / 64), n = hi % 64;
    lo = (lo ^ (h32(K + '#' + sig, 11) & 0x3FFFFFFF)) >>> 0;
    if ((h32(K + '|' + lo + '|' + n, 7) & 0xFFFFFF) !== sig || n < 1) return { ok: false, err: 'sign' };
    var batch = lo >>> 22, day = (lo >>> 10) & 0xFFF, serial = lo & 0x3FF;
    if (today() > day) return { ok: false, err: 'expired', day: day };
    return { ok: true, n: n, batch: batch, day: day, serial: serial, code: fmt(s) };
  }
  window.GiftCode = { parse: parse, fmt: fmt, clean: clean, dayStr: dayStr };
})();
