// 运行时只需要 cards-css 的卡片部分（mesh-gradient 仅构建期预渲染使用，见 holokit-full.js）
import { createHoloCard } from './cards-css/dist/index.js';
window.HoloKit = { createHoloCard };
