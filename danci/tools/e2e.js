// 端到端冒烟测试：模拟小红书容器（注入 window.xhs），把主要流程点一遍并截图到 tools/.shots/
// 用法：node tools/e2e.js   （先运行 build.py 生成 dist/）
const path = require('path'), fs = require('fs'), http = require('http');
let chromium;
try { ({ chromium } = require('playwright')); } catch (e) { ({ chromium } = require('/opt/node-tools/node_modules/playwright')); }
const DIST = path.resolve(__dirname, '../dist'), SHOTS = path.join(__dirname, '.shots');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.webp': 'image/webp', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' };

function serve() {
  return new Promise(res => {
    const s = http.createServer((q, r) => {
      const f = path.join(DIST, decodeURIComponent(q.url.split('?')[0]).replace(/\/$/, '/index.html'));
      if (!f.startsWith(DIST) || !fs.existsSync(f)) { r.writeHead(404); r.end(); return; }
      r.writeHead(200, { 'Content-Type': TYPES[path.extname(f)] || 'application/octet-stream' }); fs.createReadStream(f).pipe(r);
    }).listen(0, () => res(s));
  });
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const srv = await serve(), base = 'http://127.0.0.1:' + srv.address().port + '/';
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, hasTouch: true, isMobile: true });
  await ctx.addInitScript(() => {
    const store = {}; window.__calls = [];
    window.xhs = {
      launchOptions: { miniToolEnv: { buildVersion: 9492004, userDataPath: '/u' } },
      miniTool: {
        setStorage: async ({ key, data }) => { if (typeof data !== 'string') throw { errMsg: 'setStorage:fail' }; store[key] = data; return { errMsg: 'setStorage:ok' }; },
        getStorage: async ({ key }) => ({ errMsg: 'getStorage:ok', data: key in store ? store[key] : null }),
        getLaunchOptions: async () => window.xhs.launchOptions,
        writeTempFile: async ({ data }) => { window.__calls.push(['writeTempFile', data.length]); return { errMsg: 'ok', filePath: '/tmp/x.jpg' }; },
        saveImageToPhotosAlbum: async (o) => { window.__calls.push(['save', o.filePath]); return { errMsg: 'ok' }; },
        postNote: async (o) => { window.__calls.push(['postNote', o.title, o.mediaInfo.image_resources.length]); return { errMsg: 'ok' }; }
      }
    };
    window.__store = store;
  });
  const p = await ctx.newPage();
  const errs = [], reqs = [];
  p.on('pageerror', e => errs.push('pageerror: ' + e.message));
  p.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
  p.on('request', r => { if (!r.url().startsWith(base) && !r.url().startsWith('data:')) reqs.push(r.url()); });
  const shot = async n => { await p.waitForTimeout(350); await p.screenshot({ path: path.join(SHOTS, n + '.png') }); };
  const full = async n => { await p.waitForTimeout(350); await p.screenshot({ path: path.join(SHOTS, n + '.png'), fullPage: true }); };

  await p.goto(base + 'index.html');
  await p.waitForTimeout(900);
  await shot('01-welcome');
  await p.click('#modalActs .btn:first-child');
  await full('02-home');

  // 分组练习：英选中，全部答对
  await p.click('[data-mode="en2zh"]');
  for (let i = 0; i < 20; i++) {
    const right = await p.evaluate(() => {
      const it = document.querySelector('#qStage .qw') ? document.querySelector('#qStage .qw').textContent : null;
      const W = window.__danci.WORDS.find(w => w.w === it);
      const ops = Array.prototype.slice.call(document.querySelectorAll('#opts .op .t')).map(x => x.textContent);
      return ops.indexOf(W.cp + ' ' + W.cm);
    });
    if (i === 0) await shot('03-quiz-en2zh');
    await p.click(`#opts .op[data-j="${right < 0 ? 0 : right}"]`);
    if (i === 0) await shot('04-quiz-feedback');
    await p.click('#nextBtn');
    await p.waitForTimeout(80);
  }
  await full('05-result-group');

  // 全部测试：答错几题
  await p.click('[data-act="home"]');
  await p.click('#hTest');
  for (let i = 0; i < 25; i++) {
    await p.waitForTimeout(60);
    const kind = await p.evaluate(() => document.querySelector('#opts') ? 'mc' : document.querySelector('#spIn') ? 'spell' : 'other');
    if (kind === 'mc') {
      const j = await p.evaluate(i => {
        const qw = document.querySelector('#qStage .qw'), qcn = document.querySelector('#qStage .qcn');
        const ops = Array.prototype.slice.call(document.querySelectorAll('#opts .op .t')).map(x => x.textContent);
        const W = window.__danci.WORDS;
        let w = qw ? W.find(x => x.w === qw.textContent) : W.find(x => qcn.textContent === x.cp + x.cm);
        if (i % 9 === 4) return (ops.indexOf(qw ? w.cp + ' ' + w.cm : w.w) + 1) % 4;
        return ops.indexOf(qw ? w.cp + ' ' + w.cm : w.w);
      }, i);
      if (i === 1) await shot('06-test-mc');
      await p.click(`#opts .op[data-j="${j < 0 ? 0 : j}"]`);
    } else if (kind === 'spell') {
      const ans = await p.evaluate(() => { const c = document.querySelector('#qStage .qcn').textContent; const w = window.__danci.WORDS.find(x => c === x.cp + x.cm); return w.w; });
      await p.fill('#spIn', ans);
      if (!fs.existsSync(path.join(SHOTS, '07-test-spell.png'))) await shot('07-test-spell');
      await p.click('#checkBtn');
    }
    await p.click('#nextBtn');
  }
  await full('08-result-test');

  // 抽卡：单抽 + 十连
  await p.click('#rBody [data-act="draw"]');
  await shot('09-draw');
  await p.evaluate(() => { const S = window.__danci.S; S.tickets.push({ n: 30, m: 3 }); });
  await p.click('#dOne');
  await p.waitForTimeout(2300);
  await shot('10-reveal-one');
  await p.click('#rvShare');
  await p.waitForTimeout(1800);
  await shot('11-share-card');
  await p.click('#shSave'); await p.waitForTimeout(300);
  await p.click('#shPost'); await p.waitForTimeout(300);
  await p.click('#shX');
  await p.click('#rvX');
  await p.click('#dTen');
  await p.waitForTimeout(2600);
  await shot('12-reveal-ten');
  await p.click('#tGrid .tc');
  await p.waitForTimeout(900);
  await shot('13-viewer');
  await p.click('#vwX');
  await p.click('#rvOk');
  await full('14-album');
  await p.click('#aBody [data-act="gallery"]');
  await p.waitForTimeout(800);
  await full('15-gallery');
  await p.click('#gBody [data-act="back"]');
  await p.click('[data-tab-go="book"]');
  await full('16-book');
  await p.fill('#bQ', '珍贵'); await p.waitForTimeout(400);
  await p.click('#bList .row');
  await shot('17-word-sheet');
  await p.click('[data-close-sheet]', { position: { x: 20, y: 20 } }); await p.waitForTimeout(300);
  await p.click('[data-tab-go="home"]');
  await p.click('[data-mode="spell"]');
  await shot('18-quiz-spell');
  await p.click('#qQuit'); await p.click('#modalActs .btn:last-child');
  await p.click('[data-mode="flash"]');
  await shot('19-quiz-flash');
  await p.click('#flip'); await p.waitForTimeout(600); await shot('20-quiz-flash-back');
  await p.click('#qQuit'); await p.click('#modalActs .btn:last-child');
  await p.click('[data-act="settings"]'); await shot('21-settings');
  await p.click('[data-close-sheet]', { position: { x: 20, y: 20 } }); await p.waitForTimeout(300);
  await full('22-home-after');

  // 刷新后存档仍在（容器 Storage）
  const before = await p.evaluate(() => ({ t: window.__danci.S.tickets.reduce((a, b) => a + b.n, 0), c: Object.keys(window.__danci.S.cards).length, d: window.__danci.S.stat.draws }));
  await p.waitForTimeout(400);
  const stored = await p.evaluate(() => Object.keys(window.__store));
  const calls = await p.evaluate(() => window.__calls);
  console.log(JSON.stringify({ before, stored, calls, errs, external: reqs }, null, 1));
  await b.close(); srv.close();
})().catch(e => { console.error(e); process.exit(1); });
