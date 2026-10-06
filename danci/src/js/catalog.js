/* 卡面目录：7 个等级（纵向）× 18 款卡面（横向）。
 * art     —— 卡面底图配色（构建期预渲染为 img/art/<id>.webp，运行时不再用 WebGL）
 * eff     —— cards-css 镭射效果
 * slot    —— UR 及以上的人物线稿位（0–5，对应线稿拼图的格子；见 README「线稿位」）
 * dust    —— 重复获得时折算的星尘 */
(function () {
  'use strict';
  var PASTEL = { sunpillars: ['hsl(340,95%,82%)', 'hsl(268,90%,84%)', 'hsl(205,95%,82%)', 'hsl(160,80%,82%)', 'hsl(42,95%,84%)', 'hsl(310,90%,84%)'] };
  var ROSEGOLD = { sunpillars: ['hsl(350,80%,82%)', 'hsl(20,85%,80%)', 'hsl(35,90%,82%)', 'hsl(340,70%,78%)', 'hsl(25,80%,86%)', 'hsl(355,85%,84%)'], spectrum: ['#c9727f', '#f3c1a8', '#fff1e6', '#e79a9a', '#9b4f5a'], edge: 'hsl(20,80%,85%)', glow: 'hsl(350,90%,85%)' };
  var MOON = { sunpillars: ['hsl(230,60%,88%)', 'hsl(260,60%,90%)', 'hsl(200,60%,88%)', 'hsl(290,50%,90%)', 'hsl(220,40%,92%)', 'hsl(250,60%,90%)'], edge: 'hsl(240,60%,92%)', glow: 'hsl(240,80%,90%)' };
  var TIERS = [
    { t: 'N', cn: '素笺', rate: 40, dust: 1, v: [
      { id: 'n1', en: 'Papier Rosé', cn: '樱粉信笺', eff: 'none', art: ['#FBEFF2', '#F5D9E4', '#FDF6F1', '#F0E4F3'] },
      { id: 'n2', en: 'Papier Lilas', cn: '丁香信笺', eff: 'none', art: ['#F3EEFB', '#E3DAF6', '#F9F5FC', '#E7EAF9'] },
      { id: 'n3', en: 'Papier Ciel', cn: '晴空信笺', eff: 'none', art: ['#EDF5FC', '#DCEAF8', '#F8FAFC', '#E9F3EF'] }] },
    { t: 'R', cn: '微光', rate: 30, dust: 2, v: [
      { id: 'r1', en: 'Satin', cn: '缎光心跳', eff: 'reverse', art: ['#F6C9DA', '#E9D5F7', '#FCE6EC', '#F8DCCB'], vis: { brightness: .78 } },
      { id: 'r2', en: 'Perle', cn: '珍珠眼泪', eff: 'reverse', art: ['#EDE6F4', '#F7EDF1', '#DDE6F4', '#F4EFE6'], vis: { brightness: .8 }, pal: MOON },
      { id: 'r3', en: 'Velours', cn: '丝绒晚风', eff: 'radiant', art: ['#D9C9F4', '#F2C6DA', '#C9D9F4', '#EFD8F0'], vis: { brightness: .75 } }] },
    { t: 'SR', cn: '流光', rate: 18, dust: 5, v: [
      { id: 'sr1', en: 'Lumière', cn: '流光絮语', eff: 'holo', art: ['#C8B3F7', '#F7AECB', '#9FD0F4', '#F7DCA6'], vis: { brightness: .62, saturate: 1.1 } },
      { id: 'sr2', en: 'Paillettes', cn: '星屑告白', eff: 'glitter', art: ['#E9B9D8', '#C4B5F4', '#A9D3F2', '#F6D6E6'], vis: { brightness: .72 } },
      { id: 'sr3', en: 'Cristal', cn: '碎冰心事', eff: 'crystal', art: ['#B9C7F6', '#D7B6F2', '#A6DDF0', '#E8D7F7'], vis: { brightness: .72 } }] },
    { t: 'SSR', cn: '星辉', rate: 8, dust: 10, v: [
      { id: 'ssr1', en: 'Arc-en-ciel', cn: '彩虹私语', eff: 'rainbow', art: ['#A797F2', '#F29AC0', '#8DC8F2', '#9BE8D4'], vis: { brightness: .75 }, frame: 1 },
      { id: 'ssr2', en: 'Opale', cn: '人鱼眼泪', eff: 'oilslick', art: ['#8FB8F0', '#C49AF0', '#8FE0E0', '#F0A8D0'], vis: { brightness: .72 }, frame: 1 },
      { id: 'ssr3', en: 'Mosaïque', cn: '糖霜琉璃', eff: 'mosaic', art: ['#F2A9C8', '#C9A8F2', '#A8D4F2', '#F7D6A8'], vis: { brightness: .72 }, frame: 1 }] },
    { t: 'UR', cn: '璀璨', rate: 3, dust: 20, v: [
      { id: 'ur1', en: 'Prisme', cn: '棱镜之吻', eff: 'prism', art: ['#C8B3F7', '#F7AECB', '#9FD0F4', '#F7DCA6'], vis: { brightness: .6 }, frame: 2, slot: 0, ink: '#3E2F7A' },
      { id: 'ur2', en: 'Or Rosé', cn: '玫瑰金誓约', eff: 'radiant', art: ['#E9B7B9', '#C98A9A', '#F6D5C4', '#B87C93'], vis: { brightness: .62, glareOpacity: .6 }, pal: ROSEGOLD, top: 1, frame: 2, slot: 1, ink: '#6E2F45' }] },
    { t: 'LR', cn: '传说', rate: 0.8, dust: 40, v: [
      { id: 'lr1', en: 'Aurore', cn: '极光情书', eff: 'aurora', art: ['#2E2A7C', '#1E8FA6', '#7E4FC6', '#C96AA8'], vis: { brightness: .5, glareOpacity: .45 }, lt: 1, top: 1, frame: 2, slot: 2, ink: '#E8F4FF' },
      { id: 'lr2', en: 'Crépuscule', cn: '晚霞心动', eff: 'sunburst', art: ['#F08FA8', '#9B7FE6', '#F6B98A', '#5E5BC9'], vis: { brightness: .5, glareOpacity: .45 }, lt: 1, top: 1, frame: 2, slot: 3, ink: '#7A2E55' }] },
    { t: 'SECRET', cn: '隐藏款', rate: 0.2, dust: 80, v: [
      { id: 'x1', en: 'Minuit', cn: '午夜星河', eff: 'cosmos', art: ['#100D24', '#36246A', '#14305E', '#5E2160'], lt: 1, gold: 1, top: 1, frame: 3, slot: 4, ink: '#F4DDA8' },
      { id: 'x2', en: 'Clair de Lune', cn: '月光恋人', eff: 'holo', art: ['#D5D2F4', '#F1E1F0', '#B9C6EE', '#8E8CCB'], vis: { brightness: .55, saturate: .6 }, pal: MOON, land: 1, frame: 3, slot: 5, ink: '#3B3570' }] }
  ];
  // 火漆：与卡面等级独立抽取，稀有卡面 × 稀有火漆 = 更稀有的组合
  // hype：揭晓时的隆重程度（和卡面等级 0–6 同一把尺子）；hidden：图鉴里不留位置、概率表只写「？？？」，抽到才出现
  var SEAL_TIERS = [
    { t: 'basic', cn: '素漆', rate: 40, hype: 0, v: [{ id: 'star', cn: '薰衣草星' }, { id: 'bow', cn: '樱粉蝴蝶结' }, { id: 'heart', cn: '珠光爱心' }] },
    { t: 'fine', cn: '雅漆', rate: 24, hype: 2, v: [{ id: 'diamond', cn: '冰蓝钻石' }, { id: 'pearl', cn: '珍珠贝壳' }, { id: 'sunset', cn: '晚霞心' }] },
    { t: 'gold', cn: '金漆', rate: 14, hype: 3, v: [{ id: 'crown', cn: '玫瑰金王冠' }, { id: 'moon', cn: '月光新月' }] },
    { t: 'zodiac', cn: '星座漆', rate: 14, hype: 3, v: [{ id: 'aries', cn: '白羊座' }, { id: 'taurus', cn: '金牛座' }, { id: 'gemini', cn: '双子座' }, { id: 'cancer', cn: '巨蟹座' }, { id: 'leo', cn: '狮子座' }, { id: 'virgo', cn: '处女座' }, { id: 'libra', cn: '天秤座' }, { id: 'scorpio', cn: '天蝎座' }, { id: 'aquarius', cn: '水瓶座' }, { id: 'capricorn', cn: '摩羯座' }, { id: 'capricorn_gold', cn: '鎏金摩羯' }] },
    { t: 'secret', cn: '秘漆', rate: 5, hype: 4, v: [{ id: 'aurora', cn: '极光新月' }, { id: 'midnight', cn: '午夜星月' }, { id: 'sprig', cn: '橄榄枝' }] },
    { t: 'hidden', cn: '隐藏', rate: 2.4, hype: 5, hidden: 1, v: [{ id: 'sagittarius', cn: '星辉射手' }, { id: 'pisces', cn: '幻彩双鱼' }] },
    { t: 'mythic', cn: '超级隐藏', rate: 0.6, hype: 6, hidden: 1, v: [{ id: 'apple', cn: '伊甸禁果' }, { id: 'serpent', cn: '低语之蛇' }, { id: 'luna', cn: '深蓝弦月' }, { id: 'bloom2', cn: '金缕花信' }] }
  ];
  var SEAL = {};
  SEAL_TIERS.forEach(function (t, ti) { t.rank = ti; t.v.forEach(function (x) { x.tier = t.t; x.tcn = t.cn; x.rank = ti; x.hype = t.hype; x.hidden = !!t.hidden; x.p = t.rate / t.v.length; SEAL[x.id] = x; }); });
  var ORDER = TIERS.map(function (x) { return x.t; });
  var BY_ID = {};
  TIERS.forEach(function (t, ti) { t.rank = ti; t.v.forEach(function (v) { v.tier = t.t; v.rank = ti; BY_ID[v.id] = v; }); });
  // 页面背景（构建期预渲染为 img/bg/<key>.webp）
  var BG = {
    home: { c: ['#F7D3E1', '#E3D6FA', '#CFE3FA', '#FBE6CF'], s: 11, w: 390, h: 844 },
    quiz: { c: ['#E9DDFB', '#F8D9E6', '#D6E9FA', '#F6EBD8'], s: 23, w: 390, h: 844 },
    result: { c: ['#F4D5E6', '#E2D5FA', '#D2E6FA', '#F8E8D6'], s: 77, w: 390, h: 844 },
    album: { c: ['#F5E1EA', '#E6DDF8', '#DCEBF8', '#F7EEDF'], s: 53, w: 390, h: 844 },
    reveal: { c: ['#2C2A6A', '#5B4A9E', '#1A2550', '#15121C'], s: 31, w: 390, h: 844 },
    gallery: { c: ['#2A1F55', '#5A2F6E', '#1B2F5E', '#14111B'], s: 9, w: 390, h: 844 },
    test: { c: ['#4B2F9A', '#C24F94', '#2F5FB8', '#1C1530'], s: 4, w: 360, h: 180 },
    sky: { c: ['#F7CFE0', '#E0D2FA', '#C9E1FA', '#FBE3C9'], s: 61, w: 390, h: 520 },
    dusk: { c: ['#E0D2FA', '#F6C9C9', '#FBE3C9', '#C9B8F0'], s: 62, w: 390, h: 520 },
    night: { c: ['#3A2A6E', '#8A3F7E', '#1E3C78', '#15121C'], s: 63, w: 390, h: 520 }
  };
  window.CATALOG = { TIERS: TIERS, ORDER: ORDER, BY_ID: BY_ID, BG: BG, PASTEL: PASTEL, SEAL_TIERS: SEAL_TIERS, SEAL: SEAL };
})();
