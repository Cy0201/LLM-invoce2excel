// 分享图用的卡面：把 app 里真实的镭射卡（闪粉、条纹、高光都在）在固定光位下拍成图片，
// 不含文字和蜡封（分享图里再按单词画上去），输出 src/img/face/<卡面>.webp。
// 用法：python3 tools/build.py 之后运行 node tools/faces.js，再重新 build 打包。
const path = require('path'), fs = require('fs'), http = require('http'), { execFileSync } = require('child_process');
let chromium;
try { ({ chromium } = require('playwright')); } catch (e) { ({ chromium } = require('/opt/node-tools/node_modules/playwright')); }
const ROOT = path.resolve(__dirname, '..'), DIST = path.join(ROOT, 'dist'), TMP = path.join(__dirname, '.render', 'face'), OUT = path.join(ROOT, 'src', 'img', 'face');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.webp': 'image/webp', '.woff2': 'font/woff2' };
const W = 620;   // 竖版卡宽（横版卡取同样的高）

(async () => {
  fs.mkdirSync(TMP, { recursive: true }); fs.mkdirSync(OUT, { recursive: true });
  const srv = http.createServer((q, r) => {
    const f = path.join(DIST, decodeURIComponent(q.url.split('?')[0]));
    if (!fs.existsSync(f) || fs.statSync(f).isDirectory()) { r.writeHead(404); r.end(); return; }
    r.writeHead(200, { 'Content-Type': TYPES[path.extname(f)] || 'application/octet-stream' }); fs.createReadStream(f).pipe(r);
  }).listen(0);
  await new Promise(r => srv.on('listening', r));
  const b = await chromium.launch({ args: ['--force-color-profile=srgb', '--run-all-compositor-stages-before-draw'] });
  const ctx = await b.newContext({ viewport: { width: 1100, height: 1100 }, deviceScaleFactor: 1 });
  await ctx.addInitScript(() => { localStorage.setItem('danci-shouzhang-v3', JSON.stringify({ welcome: true })); });
  const p = await ctx.newPage();
  p.on('pageerror', e => console.log('pageerror', e.message));
  await p.goto('http://127.0.0.1:' + srv.address().port + '/index.html');
  await p.waitForTimeout(800);
  const ids = await p.evaluate(() => Object.keys(window.CATALOG.BY_ID));
  await p.addStyleTag({ content: `
    #facebox{position:fixed;left:40px;top:40px;z-index:9999;background:transparent}
    /* 只要底图、线稿和镭射层：文字、外框、蜡封都由分享图自己画 */
    #facebox .cf-face{display:none!important}
    #facebox .cf-ov>*:not(.cf-art){display:none!important}
    /* 固定光位（右上角，避开单词所在的位置），卡面本身不倾斜，投影交给分享图 */
    #facebox .holo-card.lit{--rotate-x:0deg!important;--rotate-y:0deg!important;--card-scale:1!important;--translate-x:0px!important;--translate-y:0px!important;
      --pointer-x:78%!important;--pointer-y:16%!important;--pointer-from-center:.72!important;--pointer-from-left:.78!important;--pointer-from-top:.16!important;
      --background-x:58%!important;--background-y:38%!important;--card-opacity:.82!important}
    #facebox .holo-card{--card-glow:transparent!important}
    #facebox .holo-card__rotator{box-shadow:none!important}` });
  for (const id of ids) {
    const land = await p.evaluate(id => !!window.CATALOG.BY_ID[id].land, id);
    const w = land ? Math.round(W * 386 / 250) : W;
    await p.evaluate(({ id, w }) => {
      let box = document.getElementById('facebox'); if (box) box.remove();
      box = document.createElement('div'); box.id = 'facebox'; box.style.width = w + 'px';
      document.body.appendChild(box);
      const m = CardKit.make(id, { i: 1, w: '', en: '', cn: '', src: '' }, {});
      box.appendChild(m.el); CardKit.fit(box, id);
    }, { id, w });
    await p.waitForTimeout(500);
    const el = await p.$('#facebox .holo-card__rotator');
    const png = path.join(TMP, id + '.png');
    await el.screenshot({ path: png, omitBackground: true });
    execFileSync('python3', ['-c', `
from PIL import Image
im = Image.open(${JSON.stringify(png)}).convert('RGBA')
im.save(${JSON.stringify(path.join(OUT, id + '.webp'))}, quality=84, method=6)
print(${JSON.stringify(id)}, im.size)`], { stdio: 'inherit' });
  }
  await b.close(); srv.close();
})();
