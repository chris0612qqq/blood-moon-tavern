// 倒數數字與倒數環（UI_RULES Q5、U6；ART 7.2）。app.js 的單一時鐘每影格呼叫 tickClocks，不另開計時器。
// 重繪時畫面也用同一個 ringState 算，重繪和下一影格的值一樣，環才不會閃。
import { t } from '../strings.js';

const WARN_S = 10;
const URGENT_S = 3;
const TOTALS_KEEP = 20;
const FRAC_STEP = 0.002; // 比這個小的變化不用重畫
// deadline → 第一次看到時剩幾秒。沒有 opens_at 的步驟只能這樣知道整段多長
const totals = new Map();

function totalOf(deadline, opens, left) {
  if (opens) return deadline - opens;
  if (!totals.has(deadline)) {
    if (totals.size > TOTALS_KEEP) totals.clear();
    totals.set(deadline, left);
  }
  return totals.get(deadline);
}

/** @returns {{frac: number, zone: 'calm'|'warn'|'urgent'|'paused'}} */
export function ringState(deadline, opens, now, paused = false) {
  if (paused) return { frac: 1, zone: 'paused' };
  if (!deadline || (opens && now < opens)) return { frac: 1, zone: 'calm' };
  const left = Math.max(0, deadline - now);
  const total = totalOf(deadline, opens, left);
  const frac = total > 0 ? Math.min(1, left / total) : 0;
  const zone = left <= URGENT_S ? 'urgent' : left <= WARN_S ? 'warn' : 'calm';
  return { frac, zone };
}

function tickRing(el, now) {
  const { frac, zone } = ringState(Number(el.dataset.ringDeadline), Number(el.dataset.ringOpens) || null, now);
  if (el.dataset.zone !== zone) el.dataset.zone = zone;
  const shown = Number(el.style.getPropertyValue('--frac'));
  if (Math.abs(shown - frac) > FRAC_STEP || (frac === 0 && shown !== 0)) el.style.setProperty('--frac', frac.toFixed(4));
}

// 掉幀偵測（ART 11.3）：連續 2 秒低於 45 fps 就關掉裝飾動畫，這次開著的期間不再打開
const SLOW_FRAME_MS = 1000 / 45;
const SLOW_WINDOW_MS = 2000;
let windowStart = 0;
let frames = 0;

export function watchFrames(ms) {
  if (document.hidden || document.documentElement.hasAttribute('data-lowfx')) {
    windowStart = 0;
    return;
  }
  if (!windowStart) {
    windowStart = ms;
    frames = 0;
    return;
  }
  frames += 1;
  const span = ms - windowStart;
  if (span < SLOW_WINDOW_MS) return;
  if (span / frames > SLOW_FRAME_MS) document.documentElement.setAttribute('data-lowfx', '');
  windowStart = ms;
  frames = 0;
}

export function tickClocks(now) {
  for (const el of document.querySelectorAll('[data-deadline]')) {
    const opens = Number(el.dataset.opens);
    let text;
    const waiting = Boolean(el.dataset.opens) && now < opens;
    if (el.hasAttribute('data-waiting') !== waiting) el.toggleAttribute('data-waiting', waiting);
    if (waiting) text = el.dataset.prep ?? t('prep');
    else {
      const left = Math.max(0, Math.ceil(Number(el.dataset.deadline) - now));
      text = el.dataset.clock === 'mmss'
        ? `${String(Math.floor(left / 60)).padStart(2, '0')}:${String(left % 60).padStart(2, '0')}`
        : String(left);
    }
    if (el.textContent !== text) el.textContent = text;
  }
  for (const el of document.querySelectorAll('[data-ring-deadline]')) tickRing(el, now);
}
