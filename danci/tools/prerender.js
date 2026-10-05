// 构建期预渲染：用 mesh-gradient（WebGL）把 18 款卡面底图和页面背景画成静态图片，
// 小工具运行时只加载图片，不再创建 WebGL 上下文。
// 用法：node tools/prerender.js   （需要 Playwright + Chromium；输出 PNG 到 tools/.render/，再由 build.py 转 webp）
const path = require('path');
const fs = require('fs');
let chromium;
try { ({ chromium } = require('playwright')); } catch (e) { ({ chromium } = require('/opt/node-tools/node_modules/playwright')); }

const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(__dirname, '.render');

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const p = await b.newPage({ viewport: { width: 1200, height: 1200 } });
  p.on('pageerror', e => console.log('pageerror', e.message));
  await p.setContent('<!doctype html><html><body style="margin:0"></body></html>');
  await p.addScriptTag({ path: path.join(ROOT, 'tools/vendor/holokit-full.js') });
  await p.addScriptTag({ path: path.join(ROOT, 'src/js/catalog.js') });
  const jobs = await p.evaluate(() => {
    const out = [];
    CATALOG.TIERS.forEach(t => t.v.forEach(v => {
      const key = v.id;
      out.push({ name: 'art/' + v.id, c: v.art, s: key.length * 7 + key.charCodeAt(key.length - 1), w: v.land ? 463 : 300, h: v.land ? 300 : 463 });
    }));
    Object.keys(CATALOG.BG).forEach(k => { const g = CATALOG.BG[k]; out.push({ name: 'bg/' + k, c: g.c, s: g.s, w: g.w, h: g.h }); });
    return out;
  });
  for (const j of jobs) {
    const data = await p.evaluate(j => new Promise(res => {
      const c = document.createElement('canvas');
      c.style.cssText = `position:absolute;left:0;top:0;width:${j.w}px;height:${j.h}px`;
      document.body.appendChild(c);
      const g = new HoloKit.MeshGradient();
      g.init(c, { colors: j.c, seed: j.s, isStatic: true, pixelRatio: 2, appearance: 'default', webglContextAttributes: { preserveDrawingBuffer: true } });
      setTimeout(() => { const u = c.toDataURL('image/png'); try { g.destroy(); } catch (e) {} c.remove(); res(u); }, 450);
    }), j);
    const file = path.join(OUT, j.name + '.png');
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, Buffer.from(data.split(',')[1], 'base64'));
    console.log('rendered', j.name, j.w + 'x' + j.h);
  }
  await b.close();
})();
