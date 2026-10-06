// 兑换码福利海报：SSR 立体卡上印本周兑换码，直接拿去发笔记。
// 用法（先 python3 tools/build.py）：
//   node tools/gift_posters.js                     # 本周，两个 SSR 模板各一张
//   node tools/gift_posters.js --week w03          # 指定周
//   node tools/gift_posters.js --all               # 全年 52 周一次出完
//   node tools/gift_posters.js --code XXXX-XXXX-XXXX --tickets 5 --from 10.20 --to 10.23   # 临时码
//   --vid ssr1,ssr2,ssr3 选模板（默认 ssr1 彩虹私语、ssr2 人鱼眼泪）
// 码从 gift-codes/全年周码_*.csv 里取每周第一个；图片输出到 gift-codes/posters/（不进仓库）。
const path = require('path'), fs = require('fs'), http = require('http');
let chromium;
try { ({ chromium } = require('playwright')); } catch (e) { ({ chromium } = require('/opt/node-tools/node_modules/playwright')); }
const ROOT = path.resolve(__dirname, '..'), DIST = path.join(ROOT, 'dist'), CODES = path.join(ROOT, 'gift-codes'), OUT = path.join(CODES, 'posters');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.webp': 'image/webp', '.woff2': 'font/woff2' };
const STYLE = { ssr1: { seal: 'crown', line: 'A little gift, sealed for you.' }, ssr2: { seal: 'pearl', line: 'Something rare is waiting this week.' }, ssr3: { seal: 'aurora', line: 'Open it before the week ends.' } };

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i < 0 ? d : (process.argv[i + 1] && !process.argv[i + 1].startsWith('--') ? process.argv[i + 1] : true); };
const md = s => { const p = s.split('-'); return +p[1] + '.' + p[2]; };

function jobs() {
  if (arg('code')) return [{ code: arg('code'), tickets: +arg('tickets', 10), from: arg('from', ''), to: arg('to', ''), week: '', tag: 'extra' }];
  const csv = fs.readdirSync(CODES).filter(f => /^全年周码_.*\.csv$/.test(f))[0];
  if (!csv) throw new Error('找不到 gift-codes/全年周码_*.csv，先运行 python3 tools/gift_codes.py --year');
  const rows = fs.readFileSync(path.join(CODES, csv), 'utf8').replace(/^﻿/, '').trim().split('\n').slice(1).map(l => l.split(','));
  const first = {};
  rows.forEach(r => { if (!first[r[0]]) first[r[0]] = { batch: r[0], from: r[1], to: r[2], tickets: +r[3], code: r[4] }; });
  let list = Object.values(first);
  if (arg('week')) list = list.filter(x => x.batch === arg('week'));
  else if (!arg('all')) { const today = new Date().toISOString().slice(0, 10); list = list.filter(x => x.from <= today && today <= x.to).slice(-1); }
  return list.map(x => ({ code: x.code, tickets: x.tickets, from: md(x.from), to: md(x.to), week: String(+x.batch.slice(1)).padStart(2, '0'), tag: x.batch }));
}

(async () => {
  const list = jobs();
  if (!list.length) { console.log('没有匹配的周'); return; }
  const vids = String(arg('vid', 'ssr1,ssr2')).split(',');
  fs.mkdirSync(OUT, { recursive: true });
  const srv = http.createServer((q, r) => {
    const f = path.join(DIST, decodeURIComponent(q.url.split('?')[0]));
    if (!fs.existsSync(f) || fs.statSync(f).isDirectory()) { r.writeHead(404); r.end(); return; }
    r.writeHead(200, { 'Content-Type': TYPES[path.extname(f)] || 'application/octet-stream' }); fs.createReadStream(f).pipe(r);
  }).listen(0);
  await new Promise(r => srv.on('listening', r));
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 400, height: 800 } });
  await ctx.addInitScript(() => { localStorage.setItem('danci-shouzhang-v3', JSON.stringify({ welcome: true })); });
  const p = await ctx.newPage();
  p.on('pageerror', e => console.log('pageerror', e.message));
  await p.goto('http://127.0.0.1:' + srv.address().port + '/index.html');
  await p.waitForTimeout(800);
  for (const j of list) {
    for (const vid of vids) {
      const o = Object.assign({ vid }, STYLE[vid] || {}, j);
      const url = await p.evaluate(async o => (await window.__danci.giftPoster(o)).toDataURL('image/jpeg', .92), o);
      const file = path.join(OUT, `${j.tag}_${vid}_${j.code}.jpg`);
      fs.writeFileSync(file, Buffer.from(url.split(',')[1], 'base64'));
      console.log(path.relative(ROOT, file));
    }
  }
  await b.close(); srv.close();
})();
