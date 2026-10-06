/* 逐帧截图：node promo/capture.js <输出目录> [fps] [起始秒] [结束秒] [并行数] [像素倍率]
 * 成片用 60fps × 3 倍渲染，再用 ffmpeg 两帧混合（动态模糊）+ 缩到 1080×1920（抗锯齿、减少闪烁）
 * 本地起一个静态服务：dist/ 为根，promo/ 和字体包挂在旁边 */
const path = require('path'), fs = require('fs'), http = require('http');
const { chromium } = require(process.env.PW || '/opt/node-tools/node_modules/playwright');
const ROOT = path.join(__dirname, '..');
const OUT = process.argv[2], FPS = +(process.argv[3] || 30), T0 = +(process.argv[4] || 0), T1 = +(process.argv[5] || 20), PAR = +(process.argv[6] || 3), DSF = +(process.argv[7] || 2);
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.webp': 'image/webp', '.woff2': 'font/woff2', '.woff': 'font/woff' };
function resolve(u) {
  if (u === '/' || u === '/index.html') return path.join(__dirname, 'index.html');
  if (u === '/promo.js' || u === '/promo.css') return path.join(__dirname, u);
  if (u.startsWith('/fs/')) return path.join(ROOT, 'tools/node_modules/@fontsource/noto-serif-sc', u.slice(4));
  return path.join(ROOT, 'dist', u);
}
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const srv = http.createServer((q, r) => {
    const f = resolve(decodeURIComponent(q.url.split('?')[0]));
    if (!fs.existsSync(f) || fs.statSync(f).isDirectory()) { r.writeHead(404); r.end(); return; }
    r.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' }); fs.createReadStream(f).pipe(r);
  }).listen(0);
  await new Promise(r => srv.on('listening', r));
  const url = 'http://127.0.0.1:' + srv.address().port + '/';
  const browser = await chromium.launch({ args: ['--force-color-profile=srgb', '--disable-lcd-text'] });
  const frames = [];
  for (let f = Math.round(T0 * FPS); f < Math.round(T1 * FPS); f++) frames.push(f);
  const chunk = Math.ceil(frames.length / PAR);
  const t0 = Date.now();
  await Promise.all(Array.from({ length: PAR }, async (_, w) => {
    const mine = frames.slice(w * chunk, (w + 1) * chunk); if (!mine.length) return;
    const ctx = await browser.newContext({ viewport: { width: 540, height: 960 }, deviceScaleFactor: DSF });
    const p = await ctx.newPage();
    p.on('pageerror', e => console.log('pageerror', e.message));
    p.on('requestfailed', r => console.log('requestfailed', r.url()));
    await p.goto(url); await p.waitForLoadState('networkidle');
    await p.evaluate(() => window.warm());
    await p.evaluate(() => document.fonts.ready);
    await p.waitForTimeout(1500);
    await p.evaluate(() => window.warm());
    await p.waitForTimeout(500);
    for (const f of mine) {
      await p.evaluate(t => window.render(t), f / FPS);
      await p.screenshot({ path: path.join(OUT, String(f).padStart(4, '0') + '.jpg'), type: 'jpeg', quality: 95 });
      if (f % 60 === 0) console.log('frame', f, ((Date.now() - t0) / 1000).toFixed(0) + 's');
    }
    await ctx.close();
  }));
  await browser.close(); srv.close();
})();
