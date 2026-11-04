// 內建向量美術（ART 5.2、8、9.3、11.2；DEV_PLAN P8 量產第二輪）。全部用 SVG 畫，沒有圖檔。
// 角色徽章：版畫風，金線＋局部填色，24 px 也認得出輪廓（兜帽狼頭、裂面具、燈籠、水晶球、藥瓶、長弓）。
// 畫面主圖：每個畫面一張，同一頁只會有一張，所以漸層 id 不會重複。
// 動畫寫在 css/illus.css，只動 transform、opacity 和描線；舊手機掉幀與減少動態效果時關掉。
import { s } from '../dom.js';

const GOLD = '#c9a24a';
const LINE = { fill: 'none', stroke: GOLD, 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' };

/** 四角星點：預言家的星光、水晶球裡的星屑。 */
function star(x, y, r, i) {
  const d = `M${x} ${y - r}L${x + r * 0.3} ${y - r * 0.3}L${x + r} ${y}L${x + r * 0.3} ${y + r * 0.3}`
    + `L${x} ${y + r}L${x - r * 0.3} ${y + r * 0.3}L${x - r} ${y}L${x - r * 0.3} ${y - r * 0.3}Z`;
  return s('path', { class: 'art-twinkle', d, fill: '#f3ecff', style: `--i:${i}` });
}

// 解藥圓瓶貼「＋」、毒藥方高瓶貼「×」：紅綠色弱的人看兩瓶顏色差不多，要靠形狀和記號分（ART 3.5）
const FLASKS = {
  save: { body: 'M10 8H16V16Q22 20 21 29Q20 38 13 38Q6 38 5 29Q4 20 10 16Z', cork: 9, mark: 'M13 24V32M9 28H17' },
  poison: { body: 'M10 8H16V15L21 22V37Q21 40 18 40H8Q5 40 5 37V22L10 15Z', cork: 9, mark: 'M10 26L16 32M16 26L10 32' },
};

/** 藥瓶。用過的變成空瓶：只剩虛線輪廓。 */
function flask(kind, color, used) {
  const shape = FLASKS[kind];
  const glass = used
    ? { fill: 'rgba(232, 217, 181, .06)', stroke: '#8b93a0', 'stroke-dasharray': '3 3' }
    : { fill: color, stroke: GOLD };
  return [
    s('path', { d: shape.body, 'stroke-width': 2, 'stroke-linejoin': 'round', ...glass }),
    used ? null : s('path', { d: shape.mark, fill: 'none', stroke: '#f4ead2', 'stroke-width': 2.2, 'stroke-linecap': 'round' }),
    s('rect', { x: shape.cork, y: 4, width: 8, height: 5, rx: 1, fill: used ? 'none' : '#7a5532', stroke: used ? '#8b93a0' : 'none' }),
  ];
}

const EMBLEMS = {
  // 狼人：豎耳狼頭、血月紅眼
  wolf: () => [
    s('path', { d: 'M10 7L18 17H30L38 7L37 24Q36 34 24 42Q12 34 11 24Z', ...LINE, fill: '#2a1a12' }),
    s('path', { d: 'M13 12L17 17M35 12L31 17M21 34L24 37L27 34', ...LINE, 'stroke-width': 1.5 }),
    s('path', { d: 'M15 24L21 26.5L15.5 28Z M33 24L27 26.5L32.5 28Z', fill: '#e2483a' }),
  ],
  // 千面狼：裂開的白瓷面具，右眼洞裡是狼的金色豎瞳
  faceless: () => [
    s('path', { d: 'M12 9Q24 3 36 9Q38 30 24 43Q10 30 12 9Z', fill: '#e8e4dc', stroke: '#8d78d6', 'stroke-width': 2, 'stroke-linejoin': 'round' }),
    s('path', { d: 'M15 20Q19 17 22 21Q19 24 15 20Z M33 20Q29 17 26 21Q29 24 33 20Z', fill: '#2a2236' }),
    s('ellipse', { cx: 29.5, cy: 20.5, rx: 0.9, ry: 2, fill: '#e8c872' }),
    s('path', { d: 'M27 5L24.5 14L28 20L25 28L27 34', fill: 'none', stroke: '#3d2f4f', 'stroke-width': 1.5, 'stroke-linejoin': 'round' }),
    s('path', { d: 'M20 33Q24 35 28 33', fill: 'none', stroke: '#8d78d6', 'stroke-width': 1.5, 'stroke-linecap': 'round' }),
  ],
  // 村民：提燈，燈火輕輕搖晃
  villager: () => [
    s('path', { d: 'M24 3V9', ...LINE }),
    s('rect', { x: 16, y: 9, width: 16, height: 4, rx: 1, fill: '#7a5532', stroke: GOLD, 'stroke-width': 1.5 }),
    s('path', { d: 'M15 13Q12 25 15 37H33Q36 25 33 13Z', ...LINE, fill: 'rgba(255, 207, 122, .22)' }),
    s('ellipse', { class: 'art-flame', cx: 24, cy: 26, rx: 3.5, ry: 6, fill: '#ffcf7a' }),
    s('path', { d: 'M19.5 13Q17.5 25 19.5 37M28.5 13Q30.5 25 28.5 37', ...LINE, 'stroke-width': 1 }),
    s('rect', { x: 17, y: 37, width: 14, height: 4, rx: 1, fill: '#7a5532', stroke: GOLD, 'stroke-width': 1.5 }),
    s('path', { d: 'M24 41V46', ...LINE, stroke: '#b5373a' }),
  ],
  // 預言家：水晶球，裡面星點閃動
  seer: () => [
    s('circle', { cx: 24, cy: 21, r: 14, fill: '#3a2f5c', stroke: '#b9a6f0', 'stroke-width': 2 }),
    s('path', { d: 'M15 16Q17 10 23 9', fill: 'none', stroke: 'rgba(255,255,255,.55)', 'stroke-width': 2, 'stroke-linecap': 'round' }),
    star(27, 19, 3.5, 0), star(20, 26, 2.2, 1), star(30, 28, 1.6, 2),
    s('path', { d: 'M17 33H31L34 39H14Z', ...LINE, fill: '#7a5532' }),
    s('rect', { x: 11, y: 39, width: 26, height: 4, rx: 1, ...LINE, fill: '#5a3e24' }),
  ],
  // 女巫：紅解藥、綠毒藥
  witch: () => [
    s('g', { transform: 'translate(2 4)' }, flask('save', '#b5373a', false)),
    s('g', { transform: 'translate(22 2)' }, flask('poison', '#3f8f5a', false)),
  ],
  // 獵人：長弓搭箭（箭袋只剩最後一支）
  hunter: () => [
    s('path', { d: 'M15 5Q36 24 15 43', fill: 'none', stroke: '#a0733f', 'stroke-width': 3.5, 'stroke-linecap': 'round' }),
    s('path', { d: 'M15 5L15 43', fill: 'none', stroke: '#e8d9b5', 'stroke-width': 1 }),
    s('path', { d: 'M5 24H40', ...LINE }),
    s('path', { d: 'M44 24L37 19.5V28.5Z', fill: GOLD }),
    s('path', { d: 'M5 24L2 20M5 24L2 28M9 24L6 20M9 24L6 28', fill: 'none', stroke: '#e8d9b5', 'stroke-width': 1.5, 'stroke-linecap': 'round' }),
  ],
};

/** 角色徽章。size 是顯示的像素寬度；名字旁用 18、角色卡用 72。 */
export function roleEmblem(role, size = 18) {
  const draw = EMBLEMS[String(role ?? '').toLowerCase()];
  if (!draw) return null;
  return s('svg', {
    class: `emblem emblem--${String(role).toLowerCase()}`, viewBox: '0 0 48 48', width: size, height: size, 'aria-hidden': 'true',
  }, draw());
}

/** 卡背中央的二十面骰紋章（ART 5.3、7.5）。 */
export function d20Crest(extra = '') {
  return s('svg', { class: `crest ${extra}`.trim(), viewBox: '0 0 48 48', 'aria-hidden': 'true' },
    s('path', { d: 'M24 3L42 13.5V34.5L24 45L6 34.5V13.5Z', ...LINE, fill: 'rgba(201, 162, 74, .08)' }),
    s('path', { d: 'M24 14L35 32H13Z', ...LINE }),
    s('path', { d: 'M24 3V14M42 13.5L35 32M42 34.5L35 32M24 45L35 32M24 45L13 32M6 34.5L13 32M6 13.5L13 32M6 13.5L24 14M42 13.5L24 14',
      ...LINE, 'stroke-width': 1.2, opacity: '.75' }),
    s('path', { d: 'M5 40Q24 50 43 40', fill: 'none', stroke: '#8e1b1b', 'stroke-width': 2, 'stroke-linecap': 'round' }));
}

/** 柔和光暈：中心半透明、邊緣淡到沒有。 */
function halo(id, color, cx, cy, r) {
  return [
    s('defs', {}, s('radialGradient', { id },
      s('stop', { offset: '55%', 'stop-color': color, 'stop-opacity': '.45' }),
      s('stop', { offset: '100%', 'stop-color': color, 'stop-opacity': '0' }))),
    s('circle', { class: 'art-glow', cx, cy, r, fill: `url(#${id})` }),
  ];
}

/** 主圖外框：寬度跟著畫面，最高 150 px。 */
function hero(kind, children, state = '') {
  return s('svg', {
    class: `hero hero--${kind}${state ? ` hero--${state}` : ''}`, viewBox: '0 0 200 120', 'aria-hidden': 'true', testid: `hero-${kind}`,
  }, children);
}

/** 投票揭曉的銅幣（中間方孔）。i 決定第幾個落下。 */
export function coin(i) {
  return s('svg', { class: 'coin', viewBox: '0 0 24 24', style: `--i:${i}`, 'aria-hidden': 'true' },
    s('circle', { cx: 12, cy: 12, r: 10.5, fill: '#b8862e', stroke: '#e8c872', 'stroke-width': 1.5 }),
    s('circle', { cx: 12, cy: 12, r: 7.5, fill: 'none', stroke: '#7a5532', 'stroke-width': 1 }),
    s('rect', { x: 9, y: 9, width: 6, height: 6, fill: '#2b1d12' }));
}

/** S9 預言家：水晶球裡紫霧旋轉、星點閃；查到狼霧轉紅浮出狼頭，查到好人轉金浮出盾牌（ART 11.2）。 */
export function seerOrb(result = null) {
  const [inner, outer] = { wolf: ['#d0453a', '#3a0909'], good: ['#f2cf6b', '#4a3410'] }[result] ?? ['#8d78d6', '#1c1533'];
  return hero('seer', [
    s('defs', {},
      // 結果不同漸層也不同，id 要跟著分開，否則會沿用頁面上第一個同名漸層
      s('radialGradient', { id: `hero-orb-${result ?? 'idle'}`, cx: '40%', cy: '35%', r: '70%' },
        s('stop', { offset: '0%', 'stop-color': inner }),
        s('stop', { offset: '100%', 'stop-color': outer })),
      s('clipPath', { id: 'hero-orb-clip' }, s('circle', { cx: 100, cy: 54, r: 38 }))),
    halo(`hero-orb-halo-${result ?? 'idle'}`, inner, 100, 54, 56),
    s('circle', { cx: 100, cy: 54, r: 38, fill: `url(#hero-orb-${result ?? 'idle'})`, stroke: '#b9a6f0', 'stroke-width': 1.5 }),
    s('g', { 'clip-path': 'url(#hero-orb-clip)' },
      s('g', { class: 'art-swirl' },
        s('ellipse', { cx: 92, cy: 48, rx: 30, ry: 9, fill: 'rgba(255,255,255,.14)', transform: 'rotate(-20 100 54)' }),
        s('ellipse', { cx: 108, cy: 62, rx: 26, ry: 7, fill: 'rgba(255,255,255,.1)', transform: 'rotate(25 100 54)' })),
      result === 'wolf'
        ? s('g', { class: 'art-rise', transform: 'translate(76 30)' }, EMBLEMS.wolf())
        : result === 'good'
          ? s('path', { class: 'art-rise', d: 'M100 34L118 40V54Q118 68 100 76Q82 68 82 54V40Z', fill: 'rgba(255, 240, 200, .25)', stroke: '#fff3cf', 'stroke-width': 2.5, 'stroke-linejoin': 'round' })
          : [star(88, 44, 4, 0), star(112, 52, 3, 1), star(98, 68, 2.5, 2), star(117, 38, 2, 3), star(84, 62, 1.8, 4)]),
    s('path', { d: 'M78 36Q84 24 98 21', fill: 'none', stroke: 'rgba(255,255,255,.5)', 'stroke-width': 3, 'stroke-linecap': 'round' }),
    s('path', { d: 'M80 90H120L127 104H73Z', ...LINE, fill: '#5a3e24' }),
    s('rect', { x: 66, y: 104, width: 68, height: 7, rx: 2, ...LINE, fill: '#3d2a18' }),
    star(40, 30, 3, 5), star(160, 22, 2.5, 6), star(166, 70, 2, 7), star(30, 78, 2, 8),
  ], result);
}

/** S10 女巫：冒泡的小鍋＋兩瓶藥，用過的變空瓶（ART 8）。
 *  pouring 是這一步剛用的藥（'save' 或 'poison'）：那瓶倒向小鍋，鍋上冒出紅光或綠煙（ART 11.2）。 */
export function witchBrew(antidoteUsed, poisonUsed, pouring = null) {
  const bubble = (cx, r, i) => s('circle', { class: 'art-bubble', cx, cy: 66, r, fill: '#7fd39a', style: `--i:${i}` });
  const bottle = (kind, x, y, color, used) => (pouring === kind
    ? s('g', { transform: `translate(${x} ${y}) scale(1.6)` },
      s('g', { class: `art-pour art-pour--${kind}` }, flask(kind, color, false)))
    : s('g', { transform: `translate(${x} ${y}) scale(1.6)` }, flask(kind, color, used)));
  return hero('witch', [
    s('g', { class: 'art-steam', fill: 'none', stroke: 'rgba(200, 230, 210, .35)', 'stroke-width': 3, 'stroke-linecap': 'round' },
      s('path', { d: 'M88 54Q82 44 90 36Q98 28 92 18', pathLength: 1, style: '--i:0' }),
      s('path', { d: 'M110 54Q116 44 108 34Q100 26 106 16', pathLength: 1, style: '--i:1' })),
    bubble(86, 3, 0), bubble(100, 4, 1), bubble(114, 2.5, 2), bubble(94, 2, 3),
    s('path', { d: 'M60 70Q60 108 100 108Q140 108 140 70Z', fill: '#1d1a17', stroke: '#8b93a0', 'stroke-width': 2 }),
    s('ellipse', { cx: 100, cy: 70, rx: 42, ry: 7, fill: '#2f6b44', stroke: '#8b93a0', 'stroke-width': 2 }),
    s('path', { d: 'M70 108L64 116M130 108L136 116', ...LINE, stroke: '#8b93a0' }),
    bottle('save', 18, 50, '#b5373a', antidoteUsed),
    bottle('poison', 150, 48, '#3f8f5a', poisonUsed),
    pouring
      ? s('ellipse', {
        class: 'art-puff', cx: 100, cy: 58, rx: 34, ry: 16, fill: pouring === 'save' ? '#e2483a' : '#5fd08a',
      })
      : null,
  ], pouring ? `pour-${pouring}` : '');
}

/** S11 天亮：太陽從山後升起、光芒緩轉；平安夜時一群白鳥飛過（ART 11.2）。 */
export function dawnRise(peaceful = false) {
  // 只畫地平線以上的光芒（-75° 到 75°），轉動時也不會跑到山下
  const rays = Array.from({ length: 7 }, (_, i) => s('path', {
    d: 'M100 44V20', transform: `rotate(${(i - 3) * 25} 100 88)`,
  }));
  const bird = (x, y, i) => s('path', {
    class: 'art-bird', d: `M${x} ${y}q5 -5 10 0q5 -5 10 0`, style: `--i:${i}`,
  });
  return hero('dawn', [
    s('defs', {},
      s('radialGradient', { id: 'hero-sun' },
        s('stop', { offset: '0%', 'stop-color': '#fff3cf' }),
        s('stop', { offset: '60%', 'stop-color': '#e8c872' }),
        s('stop', { offset: '100%', 'stop-color': '#d9702b' }))),
    s('g', { class: 'art-sunrise' },
      s('g', { class: 'art-rays', stroke: 'rgba(232, 200, 114, .45)', 'stroke-width': 3, 'stroke-linecap': 'round' }, rays),
      s('circle', { cx: 100, cy: 88, r: 30, fill: 'url(#hero-sun)' })),
    s('path', { d: 'M0 96Q40 78 80 92Q120 104 150 86Q180 74 200 84V120H0Z', fill: '#2a1f14' }),
    s('path', { d: 'M0 106Q50 94 100 104Q150 114 200 100V120H0Z', fill: '#1a130c' }),
    peaceful
      ? s('g', { fill: 'none', stroke: '#f4ead2', 'stroke-width': 1.8, 'stroke-linecap': 'round' },
        bird(30, 34, 0), bird(52, 26, 1), bird(46, 44, 2))
      : null,
  ]);
}

/** S12 獵人：拉滿的長弓剪影橫過畫面上方，箭頭微微反光（ART 8）。
 *  shot：箭射出去飛離畫面、弓弦彈回；holster：箭慢慢收回、弓弦放鬆（ART 11.2）。 */
export function hunterBow(after = null) {
  const string = after ? 'M22 58L100 66L178 58' : 'M22 58L100 92L178 58';
  return hero('hunter', [
    s('path', { d: 'M22 58Q100 2 178 58', fill: 'none', stroke: '#a0733f', 'stroke-width': 6, 'stroke-linecap': 'round' }),
    s('path', { class: after ? 'art-string-release' : null, d: string, fill: 'none', stroke: '#e8d9b5', 'stroke-width': 1.5 }),
    s('g', { class: after ? `art-arrow art-arrow--${after}` : 'art-arrow' },
      s('path', { d: 'M100 92V14', ...LINE, 'stroke-width': 3 }),
      s('path', { class: 'art-glint', d: 'M100 4L93 18H107Z', fill: '#e8c872' }),
      s('path', { d: 'M100 92L92 104M100 92L108 104M100 84L92 96M100 84L108 96', fill: 'none', stroke: '#e8d9b5', 'stroke-width': 2, 'stroke-linecap': 'round' })),
    s('path', { d: 'M88 30Q100 26 112 30', fill: 'none', stroke: '#5a3e24', 'stroke-width': 8, 'stroke-linecap': 'round' }),
  ], after ?? '');
}

/** S17 出局：一支剛熄滅的蠟燭，青煙一縷縷升起（ART 8）。 */
export function snuffedCandle() {
  return hero('candle', [
    s('g', { class: 'art-smoke', fill: 'none', stroke: 'rgba(200, 205, 214, .45)', 'stroke-width': 2.5, 'stroke-linecap': 'round' },
      s('path', { d: 'M100 40Q92 30 100 22Q108 14 100 4', pathLength: 1, style: '--i:0' }),
      s('path', { d: 'M100 40Q108 32 102 24Q96 16 104 8', pathLength: 1, style: '--i:1' })),
    s('path', { d: 'M100 40V48', stroke: '#2b1d12', 'stroke-width': 2, 'stroke-linecap': 'round' }),
    s('circle', { class: 'art-ember', cx: 100, cy: 41, r: 1.6, fill: '#d9702b' }),
    s('path', { d: 'M86 48H114V98H86Z', fill: '#cdb98a', stroke: '#8a6d32', 'stroke-width': 1.5 }),
    s('path', { d: 'M86 54Q90 62 88 70M112 50Q110 58 113 64', fill: 'none', stroke: '#e8d9b5', 'stroke-width': 3, 'stroke-linecap': 'round' }),
    s('ellipse', { cx: 100, cy: 104, rx: 34, ry: 7, fill: '#3d2a18', stroke: GOLD, 'stroke-width': 1.5 }),
    s('path', { d: 'M78 98H122L126 104H74Z', fill: '#5a3e24', stroke: GOLD, 'stroke-width': 1.5 }),
  ]);
}

/** S18 結算：好人勝＝金色日出；狼人勝＝血月放大、山頭一匹狼仰天長嚎（ART 11.2）。 */
export function victory(winner) {
  if (winner !== 'wolf') return dawnRise(true);
  return hero('victory-wolf', [
    s('defs', {},
      s('radialGradient', { id: 'hero-bigmoon', cx: '40%', cy: '35%', r: '70%' },
        s('stop', { offset: '0%', 'stop-color': '#e2614c' }),
        s('stop', { offset: '60%', 'stop-color': '#8e1b1b' }),
        s('stop', { offset: '100%', 'stop-color': '#3a0909' }))),
    halo('hero-bigmoon-halo', '#c8322a', 100, 56, 56),
    s('circle', { class: 'art-moonrise', cx: 100, cy: 56, r: 44, fill: 'url(#hero-bigmoon)' }),
    s('path', { d: 'M0 120V104Q30 96 60 100Q90 88 110 92Q140 84 170 98Q186 102 200 98V120Z', fill: '#0c0a08' }),
    // 坐在山頭仰天長嚎的狼（剪影）
    s('path', {
      d: 'M104 97Q99 82 106 71Q111 61 116 53L119 41L115 29L122 34L126 32L135 21Q140 19 140 24L131 36Q127 45 128 53Q133 63 131 75L134 95L139 97Z'
        + 'M105 96Q91 95 88 85Q96 91 107 89Z',
      fill: '#0c0a08',
    }),
  ]);
}
