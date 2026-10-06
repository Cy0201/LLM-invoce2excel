/* 兑换码：离线校验，不联网，也不在前端放任何能「造码」的密钥。
 * 所有码在 tools/gift_codes.py 里一次生成好（12 位随机 Crockford Base32，60 位熵），
 * 小工具里只放每个码的单向哈希（加盐 SHA-256 迭代 IT 次，取前 96 位），见 gift-db.js。
 * 看得到代码也推不出码；想撞出一个能用的码，需要的计算量远超个人设备。 */
(function () {
  'use strict';
  var EPOCH = Date.UTC(2026, 0, 1);
  var KTAB = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];
  var Wb = new Array(64);
  // SHA-256（字节数组 → 32 字节数组）
  function sha256(bytes) {
    var H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var l = bytes.length, n = ((l + 9 + 63) >> 6) << 6, m = new Array(n), i, j;
    for (i = 0; i < n; i++) m[i] = i < l ? bytes[i] : 0;
    m[l] = 0x80;
    var bits = l * 8;
    m[n - 4] = (bits >>> 24) & 255; m[n - 3] = (bits >>> 16) & 255; m[n - 2] = (bits >>> 8) & 255; m[n - 1] = bits & 255;
    for (var off = 0; off < n; off += 64) {
      for (j = 0; j < 16; j++) Wb[j] = (m[off + j * 4] << 24) | (m[off + j * 4 + 1] << 16) | (m[off + j * 4 + 2] << 8) | m[off + j * 4 + 3];
      for (j = 16; j < 64; j++) {
        var x = Wb[j - 15], y = Wb[j - 2];
        var s0 = ((x >>> 7) | (x << 25)) ^ ((x >>> 18) | (x << 14)) ^ (x >>> 3);
        var s1 = ((y >>> 17) | (y << 15)) ^ ((y >>> 19) | (y << 13)) ^ (y >>> 10);
        Wb[j] = (Wb[j - 16] + s0 + Wb[j - 7] + s1) | 0;
      }
      var a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
      for (j = 0; j < 64; j++) {
        var S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        var t1 = (h + S1 + ((e & f) ^ (~e & g)) + KTAB[j] + Wb[j]) | 0;
        var S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        var t2 = (S0 + ((a & b) ^ (a & c) ^ (b & c))) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      H[0] = (H[0] + a) | 0; H[1] = (H[1] + b) | 0; H[2] = (H[2] + c) | 0; H[3] = (H[3] + d) | 0;
      H[4] = (H[4] + e) | 0; H[5] = (H[5] + f) | 0; H[6] = (H[6] + g) | 0; H[7] = (H[7] + h) | 0;
    }
    var out = [];
    for (i = 0; i < 8; i++) out.push((H[i] >>> 24) & 255, (H[i] >>> 16) & 255, (H[i] >>> 8) & 255, H[i] & 255);
    return out;
  }
  function ascii(s) { var a = []; for (var i = 0; i < s.length; i++) a.push(s.charCodeAt(i) & 255); return a; }
  var B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  function b64(bytes) {
    var s = '';
    for (var i = 0; i < bytes.length; i += 3) {
      var v = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
      s += B64[(v >>> 18) & 63] + B64[(v >>> 12) & 63] + B64[(v >>> 6) & 63] + B64[v & 63];
    }
    return s;
  }
  // 码 → 16 个字符的指纹：SHA-256(盐:码)，再对 32 字节结果迭代 IT-1 次，取前 12 字节
  function digest(code, salt, it) {
    var h = sha256(ascii(salt + ':' + code));
    for (var i = 1; i < it; i++) h = sha256(h);
    return b64(h.slice(0, 12));
  }
  // 输入宽容：大小写、空格、横线都行；O→0，I/L→1，U→V
  function clean(s) {
    return String(s || '').toUpperCase().replace(/O/g, '0').replace(/[IL]/g, '1').replace(/U/g, 'V').replace(/[^0-9A-Z]/g, '');
  }
  function fmt(s) { s = clean(s).slice(0, 12); return s.replace(/(.{4})(?=.)/g, '$1-'); }
  function today() { var d = new Date(); return Math.floor((Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) - EPOCH) / 864e5); }
  function dayStr(n) { var d = new Date(EPOCH + n * 864e5); return (d.getUTCMonth() + 1) + ' 月 ' + d.getUTCDate() + ' 日'; }
  /* 返回 {ok:true, n, batch, code} 或 {ok:false, err:'format'|'sign'|'expired'|'early', from?} */
  function parse(input) {
    var s = clean(input), DB = window.GIFT_DB;
    if (s.length !== 12 || /[^0-9A-HJKMNP-TV-Z]/.test(s)) return { ok: false, err: 'format' };
    if (!DB || !DB.w) return { ok: false, err: 'sign' };
    var fp = digest(s, DB.s, DB.it), t = today();
    for (var i = 0; i < DB.w.length; i++) {
      var w = DB.w[i], list = w[4], p = list.indexOf(fp);
      while (p >= 0 && p % 16) p = list.indexOf(fp, p + 1);
      if (p < 0) continue;
      if (t < w[0]) return { ok: false, err: 'early', from: w[0] };
      if (t > w[1]) return { ok: false, err: 'expired' };
      return { ok: true, n: w[2], batch: w[3], code: fmt(s) };
    }
    return { ok: false, err: 'sign' };
  }
  window.GiftCode = { parse: parse, fmt: fmt, clean: clean, dayStr: dayStr, _digest: digest };
})();
