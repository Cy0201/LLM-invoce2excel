// 声音冒烟测试：三种环境下点一遍，统计真正发出的声音（Web Audio 的 BufferSource.start / <audio>.play）
//   normal  —— 普通 Chromium
//   ios     —— 模拟 iOS：AudioContext 只有在 touchend/click 里 resume() 才会真正跑起来
//   nowa    —— 容器里没有 Web Audio，只能用 <audio>
// 用法：node tools/audio_test.js   （先运行 build.py）
const path = require('path'), fs = require('fs'), http = require('http');
let chromium;
try { ({ chromium } = require('playwright')); } catch (e) { ({ chromium } = require('/opt/node-tools/node_modules/playwright')); }
const DIST = path.resolve(__dirname, '../dist');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.webp': 'image/webp', '.woff2': 'font/woff2' };

function serve() {
  return new Promise(res => {
    const s = http.createServer((q, r) => {
      const f = path.join(DIST, decodeURIComponent(q.url.split('?')[0]).replace(/\/$/, '/index.html'));
      if (!f.startsWith(DIST) || !fs.existsSync(f)) { r.writeHead(404); r.end(); return; }
      r.writeHead(200, { 'Content-Type': TYPES[path.extname(f)] || 'application/octet-stream' }); fs.createReadStream(f).pipe(r);
    }).listen(0, () => res(s));
  });
}

function hooks(mode) {
  window.__snd = [];
  const log = (k, d) => window.__snd.push([k, d, Math.round(performance.now())]);
  if (mode === 'nowa') { delete window.AudioContext; delete window.webkitAudioContext; window.AudioContext = undefined; window.webkitAudioContext = undefined; }
  if (mode === 'ios') {
    const Real = window.AudioContext;
    window.AudioContext = function () {
      const ac = new Real(); let st = 'suspended';
      Object.defineProperty(ac, 'state', { get: () => st });
      const realResume = ac.resume.bind(ac);
      ac.resume = function () { const ev = window.event; if (ev && (ev.type === 'touchend' || ev.type === 'click')) { st = 'running'; log('resume-ok', ev.type); } else log('resume-ignored', ev ? ev.type : 'none'); return realResume(); };
      return ac;
    };
  }
  if (window.AudioBufferSourceNode) {
    const s0 = AudioBufferSourceNode.prototype.start;
    AudioBufferSourceNode.prototype.start = function () {
      const ctx = this.context, d = this.buffer ? this.buffer.duration : 0;
      if (d > .05) log(ctx.state === 'running' ? 'wa' : 'wa-SILENT', d.toFixed(2));
      return s0.apply(this, arguments);
    };
  }
  const p0 = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    const src = this.src || '';
    const r = p0.apply(this, arguments);
    if (src.length > 2000) { log('media', src.length); if (r && r.then) r.then(() => log('media-ok', src.length), e => log('media-FAIL', String(e && e.name))); }
    return r;
  };
}

(async () => {
  const srv = await serve(), base = 'http://127.0.0.1:' + srv.address().port + '/';
  const b = await chromium.launch();
  let bad = 0;
  for (const mode of ['normal', 'ios', 'nowa']) {
    const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
    await ctx.addInitScript(`(${hooks})(${JSON.stringify(mode)})`);
    await ctx.addInitScript(() => { localStorage.setItem('danci-shouzhang-v3', JSON.stringify({ welcome: true })); });
    const p = await ctx.newPage();
    const errs = [];
    p.on('pageerror', e => errs.push(e.message));
    await p.goto(base + 'index.html'); await p.waitForTimeout(1200);
    const mark = async label => { const n = await p.evaluate(() => window.__snd.length); return { label, n }; };
    const steps = [];
    const since = async (m) => (await p.evaluate(n => window.__snd.slice(n), m.n));
    // 1. 答题页点喇叭（发音）
    let m = await mark('speak');
    await p.tap('[data-mode="en2zh"]'); await p.waitForTimeout(900);
    await p.tap('#qStage [data-say]'); await p.waitForTimeout(900);
    steps.push(['进题自动读 + 点喇叭', await since(m)]);
    // 2. 答对
    m = await mark();
    const j = await p.evaluate(() => { const it = document.querySelector('#qStage .qw').textContent; const W = window.__danci.WORDS.find(w => w.w === it); return Array.prototype.slice.call(document.querySelectorAll('#opts .op .t')).map(x => x.textContent).indexOf(W.cp + ' ' + W.cm); });
    await p.tap(`#opts .op[data-j="${j}"]`); await p.waitForTimeout(700);
    steps.push(['答对', await since(m)]);
    await p.tap('#qQuit'); await p.waitForTimeout(200); await p.tap('#modalActs .btn:last-child'); await p.waitForTimeout(300);
    // 3. 单抽（强制出隐藏款） + 十连
    await p.evaluate(() => { const S = window.__danci.S; S.tickets.push({ n: 30, m: 1 }); window.__danci.show('draw'); });
    await p.waitForTimeout(300);
    m = await mark();
    await p.evaluate(() => { const D = window.__danci; const r0 = Math.random; let k = 0; Math.random = () => (k++ < 2 ? 0.0001 : r0()); setTimeout(() => { Math.random = r0; }, 50); });
    await p.tap('#dOne'); await p.waitForTimeout(3200);
    steps.push(['单抽（隐藏款）', await since(m)]);
    await p.tap('#rvX'); await p.waitForTimeout(300);
    m = await mark();
    await p.tap('#dTen'); await p.waitForTimeout(3000);
    steps.push(['十连', await since(m)]);
    const all = await p.evaluate(() => window.__snd);
    console.log('\n== ' + mode + ' ==');
    steps.forEach(([k, v]) => {
      const heard = v.filter(x => x[0] === 'wa' || x[0] === 'media-ok').length;
      console.log(k.padEnd(12), heard ? 'OK  ' : 'MUTE', JSON.stringify(v.filter(x => x[0] !== 'media').map(x => x[0] + ':' + x[1])));
      if (!heard) bad++;
    });
    if (all.some(x => x[0] === 'wa-SILENT' || x[0] === 'media-FAIL')) { console.log('有静音播放：', JSON.stringify(all.filter(x => /SILENT|FAIL/.test(x[0])))); bad++; }
    if (errs.length) { console.log('errors', errs); bad++; }
    await ctx.close();
  }
  await b.close(); srv.close();
  console.log(bad ? '\nFAIL ' + bad : '\nALL OK');
  process.exit(bad ? 1 : 0);
})();
