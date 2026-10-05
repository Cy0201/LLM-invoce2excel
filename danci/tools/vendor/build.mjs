// 打包 cards-css → src/js/holokit.js（ES2017、IIFE、去掉陀螺仪：容器禁用 DeviceOrientation）
// 用法：cd tools/vendor && npm i esbuild && node build.mjs
import * as esbuild from 'esbuild';
const stub = { name: 'stub-orientation', setup(b) {
  b.onResolve({ filter: /orientation\.js$/ }, () => ({ path: 'orient-stub', namespace: 'stub' }));
  b.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({ contents: 'export const resetBaseOrientation=()=>{};export const subscribeOrientation=()=>()=>{};export const requestOrientationPermission=async()=>false;', loader: 'js' }));
} };
await esbuild.build({ entryPoints: ['entry.js'], bundle: true, format: 'iife', target: 'es2017', minify: true, outfile: '../../src/js/holokit.js', plugins: [stub], legalComments: 'inline' });
