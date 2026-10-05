// 交付前检查：每个 JS 都能按 ES2017（Chrome 61）解析，且没有调用 Chrome 61 之后才有的常见 API
const fs = require('fs');
const acorn = require('acorn'), walk = require('acorn-walk');
const NEWER = ['replaceAll', 'at', 'hasOwn', 'structuredClone', 'flat', 'flatMap', 'fromEntries', 'matchAll', 'allSettled', 'any', 'trimStart', 'trimEnd', 'findLast', 'findLastIndex', 'toSorted'];
let bad = 0;
for (const f of process.argv.slice(2)) {
  const src = fs.readFileSync(f, 'utf8');
  try {
    const ast = acorn.parse(src, { ecmaVersion: 2017, sourceType: 'script' });
    walk.simple(ast, {
      MemberExpression(n) {
        if (!n.computed && n.property.type === 'Identifier' && NEWER.includes(n.property.name) && n.object.type !== 'ThisExpression') {
          console.log('WARN', f, '使用了较新的 API .' + n.property.name, '@', n.start); bad++;
        }
      }
    });
    console.log('ES2017 OK', f.split('/').slice(-2).join('/'), (src.length / 1024).toFixed(1) + ' KB');
  } catch (e) { console.log('ES2017 解析失败', f, e.message); bad++; }
}
process.exit(bad ? 1 : 0);
