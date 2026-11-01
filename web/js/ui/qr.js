// QR Code（ISO 18004）：位元組模式、糾錯等級 M、版本 1–10，邀請網址夠用（SPEC C4 S3）。
// 自己寫是因為前端不裝套件（CODING_RULES D5），網址也不該送去別人的服務產生圖片。

// 每個版本：每塊糾錯碼數、[塊數, 每塊資料碼數] 的分組（標準的 M 級表）
const BLOCKS = [
  null,
  [10, [1, 16]], [16, [1, 28]], [26, [1, 44]], [18, [2, 32]], [24, [2, 43]],
  [16, [4, 27]], [18, [4, 31]], [22, [2, 38], [2, 39]], [22, [3, 36], [2, 37]], [26, [4, 43], [1, 44]],
];
const ALIGN_LAST = [0, 0, 18, 22, 26, 30, 34, 38, 42, 46, 50];
const ALIGN_MID = { 7: 22, 8: 24, 9: 26, 10: 28 };
const MAX_VERSION = 10;
const FORMAT_POLY = 0x537;
const FORMAT_MASK = 0x5412;
const VERSION_POLY = 0x1f25;
const MODE_BYTE = 0b0100;
const PAD = [0xec, 0x11];
const MASKS = [
  (x, y) => (x + y) % 2,
  (x, y) => y % 2,
  (x) => x % 3,
  (x, y) => (x + y) % 3,
  (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2,
  (x, y) => (x * y) % 2 + (x * y) % 3,
  (x, y) => ((x * y) % 2 + (x * y) % 3) % 2,
  (x, y) => ((x + y) % 2 + (x * y) % 3) % 2,
];

const EXP = new Uint8Array(512);
const LOG = new Uint8Array(256);
for (let i = 0, v = 1; i < 255; i += 1) {
  EXP[i] = v;
  LOG[v] = i;
  v = v & 0x80 ? (v << 1) ^ 0x11d : v << 1;
}
for (let i = 255; i < 512; i += 1) EXP[i] = EXP[i - 255];

const gfMul = (a, b) => (a && b ? EXP[LOG[a] + LOG[b]] : 0);

function reedSolomon(data, degree) {
  let poly = [1];
  for (let i = 0; i < degree; i += 1) {
    const next = new Array(poly.length + 1).fill(0);
    poly.forEach((c, j) => {
      next[j] ^= c;
      next[j + 1] ^= gfMul(c, EXP[i]);
    });
    poly = next;
  }
  const rem = new Array(degree).fill(0);
  for (const byte of data) {
    const factor = byte ^ rem.shift();
    rem.push(0);
    for (let i = 0; i < degree; i += 1) rem[i] ^= gfMul(poly[i + 1], factor);
  }
  return rem;
}

const dataCapacity = (version) => BLOCKS[version].slice(1).reduce((sum, [n, size]) => sum + n * size, 0);

function chooseVersion(length) {
  for (let v = 1; v <= MAX_VERSION; v += 1) {
    const countBits = v < 10 ? 8 : 16;
    if (4 + countBits + length * 8 <= dataCapacity(v) * 8) return v;
  }
  return null;
}

function codewords(bytes, version) {
  const bits = [];
  const push = (value, n) => { for (let i = n - 1; i >= 0; i -= 1) bits.push((value >>> i) & 1); };
  const capacity = dataCapacity(version);
  push(MODE_BYTE, 4);
  push(bytes.length, version < 10 ? 8 : 16);
  bytes.forEach((b) => push(b, 8));
  push(0, Math.min(4, capacity * 8 - bits.length));
  push(0, (8 - (bits.length % 8)) % 8);
  const data = [];
  for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
  for (let i = 0; data.length < capacity; i += 1) data.push(PAD[i % 2]);
  const [degree, ...groups] = BLOCKS[version];
  const blocks = [];
  let at = 0;
  for (const [count, size] of groups) {
    for (let i = 0; i < count; i += 1) {
      const part = data.slice(at, at + size);
      at += size;
      blocks.push({ part, ec: reedSolomon(part, degree) });
    }
  }
  const out = [];
  const longest = Math.max(...blocks.map((b) => b.part.length));
  for (let i = 0; i < longest; i += 1) blocks.forEach((b) => { if (i < b.part.length) out.push(b.part[i]); });
  for (let i = 0; i < degree; i += 1) blocks.forEach((b) => out.push(b.ec[i]));
  return out;
}

function blank(version) {
  const size = version * 4 + 17;
  const dark = Array.from({ length: size }, () => new Array(size).fill(false));
  const fixed = Array.from({ length: size }, () => new Array(size).fill(false));
  const set = (x, y, on) => {
    if (x < 0 || y < 0 || x >= size || y >= size) return;
    dark[y][x] = on;
    fixed[y][x] = true;
  };
  for (const [cx, cy] of [[3, 3], [size - 4, 3], [3, size - 4]]) {
    for (let dy = -4; dy <= 4; dy += 1) {
      for (let dx = -4; dx <= 4; dx += 1) {
        const ring = Math.max(Math.abs(dx), Math.abs(dy));
        set(cx + dx, cy + dy, ring !== 2 && ring !== 4);
      }
    }
  }
  for (let i = 8; i < size - 8; i += 1) {
    set(i, 6, i % 2 === 0);
    set(6, i, i % 2 === 0);
  }
  const centers = version === 1 ? [] : [6, ...(ALIGN_MID[version] ? [ALIGN_MID[version]] : []), ALIGN_LAST[version]];
  const last = centers.length - 1;
  for (const [row, cy] of centers.entries()) {
    for (const [col, cx] of centers.entries()) {
      // 只有和定位圖案重疊的三個角不畫；壓在時序線上的要畫
      if ((row === 0 && col === 0) || (row === 0 && col === last) || (row === last && col === 0)) continue;
      for (let dy = -2; dy <= 2; dy += 1) {
        for (let dx = -2; dx <= 2; dx += 1) set(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
      }
    }
  }
  return { size, dark, fixed, set };
}

function drawFormat(q, mask) {
  const data = mask; // M 級的代碼是 00
  let rem = data;
  for (let i = 0; i < 10; i += 1) rem = (rem << 1) ^ ((rem >>> 9) * FORMAT_POLY);
  const bits = ((data << 10) | rem) ^ FORMAT_MASK;
  const bit = (i) => ((bits >>> i) & 1) === 1;
  for (let i = 0; i <= 5; i += 1) q.set(8, i, bit(i));
  q.set(8, 7, bit(6));
  q.set(8, 8, bit(7));
  q.set(7, 8, bit(8));
  for (let i = 9; i < 15; i += 1) q.set(14 - i, 8, bit(i));
  for (let i = 0; i < 8; i += 1) q.set(q.size - 1 - i, 8, bit(i));
  for (let i = 8; i < 15; i += 1) q.set(8, q.size - 15 + i, bit(i));
  q.set(8, q.size - 8, true);
}

function drawVersion(q, version) {
  if (version < 7) return;
  let rem = version;
  for (let i = 0; i < 12; i += 1) rem = (rem << 1) ^ ((rem >>> 11) * VERSION_POLY);
  const bits = (version << 12) | rem;
  for (let i = 0; i < 18; i += 1) {
    const on = ((bits >>> i) & 1) === 1;
    const a = q.size - 11 + (i % 3);
    const b = Math.floor(i / 3);
    q.set(a, b, on);
    q.set(b, a, on);
  }
}

function placeData(q, words) {
  let i = 0;
  for (let right = q.size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < q.size; vert += 1) {
      for (let j = 0; j < 2; j += 1) {
        const x = right - j;
        const y = ((right + 1) & 2) === 0 ? q.size - 1 - vert : vert;
        if (q.fixed[y][x]) continue;
        q.dark[y][x] = i < words.length * 8 && ((words[i >>> 3] >>> (7 - (i & 7))) & 1) === 1;
        i += 1;
      }
    }
  }
}

function applyMask(q, mask) {
  for (let y = 0; y < q.size; y += 1) {
    for (let x = 0; x < q.size; x += 1) {
      if (!q.fixed[y][x] && MASKS[mask](x, y) === 0) q.dark[y][x] = !q.dark[y][x];
    }
  }
}

/** 標準的四項扣分：連續同色、同色方塊、類似定位圖案、黑白比例。 */
function penalty({ size, dark }) {
  const line = (get) => {
    let score = 0;
    for (let a = 0; a < size; a += 1) {
      let run = 0;
      let last = null;
      let recent = 0;
      for (let b = 0; b < size; b += 1) {
        const on = get(a, b);
        run = on === last ? run + 1 : 1;
        last = on;
        if (run === 5) score += 3;
        else if (run > 5) score += 1;
        recent = ((recent << 1) | (on ? 1 : 0)) & 0x7ff;
        if (b >= 10 && (recent === 0b10111010000 || recent === 0b00001011101)) score += 40;
      }
    }
    return score;
  };
  let score = line((a, b) => dark[a][b]) + line((a, b) => dark[b][a]);
  let total = 0;
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      if (dark[y][x]) total += 1;
      if (x && y && dark[y][x] === dark[y][x - 1] && dark[y][x] === dark[y - 1][x] && dark[y][x] === dark[y - 1][x - 1]) score += 3;
    }
  }
  return score + Math.floor(Math.abs((total * 20) / (size * size) - 10)) * 10;
}

/** 回傳黑白矩陣（true＝黑）；文字太長回 null，呼叫端只顯示網址。 */
export function qrMatrix(text) {
  const bytes = [...new TextEncoder().encode(text)];
  const version = chooseVersion(bytes.length);
  if (version === null) return null;
  const words = codewords(bytes, version);
  let best = null;
  let bestScore = Infinity;
  for (let mask = 0; mask < MASKS.length; mask += 1) {
    const q = blank(version);
    drawVersion(q, version);
    drawFormat(q, mask); // 先佔位，資料才不會寫進格式區
    placeData(q, words);
    applyMask(q, mask);
    drawFormat(q, mask);
    const score = penalty(q);
    if (score < bestScore) {
      bestScore = score;
      best = q.dark;
    }
  }
  return best;
}

// 算一次要試 8 種遮罩，而畫面每次重繪都會問，記住上一次的結果（UI_RULES Q3）
let lastUrl = null;

/** SVG 的 data 網址，放進 <img> 就好。四周留 4 格白邊，相機才掃得到。 */
export function qrDataUrl(text) {
  if (lastUrl?.text !== text) lastUrl = { text, url: buildDataUrl(text) };
  return lastUrl.url;
}

function buildDataUrl(text) {
  const matrix = qrMatrix(text);
  if (!matrix) return null;
  const quiet = 4;
  const side = matrix.length + quiet * 2;
  let path = '';
  matrix.forEach((row, y) => row.forEach((on, x) => {
    if (on) path += `M${x + quiet} ${y + quiet}h1v1h-1z`;
  }));
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${side} ${side}" shape-rendering="crispEdges">`
    + `<rect width="${side}" height="${side}" fill="#fff"/><path d="${path}" fill="#000"/></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}
