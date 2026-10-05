// 合并词表（words_raw.js：序号/考频/单词/音标/释义/拼写变体/备注）与例句（sentences/*.txt），生成 src/js/data.js
const fs = require('fs'), path = require('path');
global.window = {};
eval(fs.readFileSync(path.join(__dirname, 'words_raw.js'), 'utf8').replace('const RAW=', 'global.RAW='));
const S = {};
for (const f of fs.readdirSync(path.join(__dirname, 'sentences')).sort()) {
  for (const line of fs.readFileSync(path.join(__dirname, 'sentences', f), 'utf8').split('\n')) {
    if (!line.trim()) continue;
    const p = line.split('|');
    if (p.length < 5) throw new Error('bad line ' + line);
    S[+p[0]] = { pos: p[1], m: p[2], en: p[3], cn: p[4], src: p[5] || '' };
  }
}
let bad = 0;
const out = RAW.map(r => {
  const s = S[r[0]];
  if (!s) { console.log('missing sentence', r[0], r[2]); bad++; return r; }
  const w = r[2].toLowerCase();
  const forms = [w, ...(r[5] || [])].map(x => x.toLowerCase());
  const stem = x => x.replace(/(e|y)$/, '').slice(0, Math.max(3, x.length - 2));
  const en = s.en.toLowerCase();
  if (!forms.some(f => en.includes(f) || en.includes(stem(f)))) { console.log('word not in sentence', r[0], w, '|', s.en); bad++; }
  // 统一音标外观：[ ] → / /
  const ipa = r[3].replace(/^\[/, '/').replace(/\]$/, '/');
  return [r[0], r[1], r[2], ipa, r[4], r[5] || [], r[6] || '', s.pos, s.m, s.en, s.cn, s.src];
});
const js = '/* 高考核心 688 词：[序号, 考频, 单词, 音标, 释义[[词性,释义]], 拼写变体, 备注, 卡面词性, 卡面释义, 例句, 例句译文, 出处] */\nwindow.WORDS_RAW=' + JSON.stringify(out) + ';\n';
fs.writeFileSync(path.join(__dirname, '../src/js/data.js'), js);
console.log('words', out.length, 'sentences', Object.keys(S).length, 'quotes', out.filter(x => x[11]).length, 'problems', bad, 'bytes', js.length);
