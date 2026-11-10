// 共用元件灰盒版（DEV_PLAN P4）：ActionButton、CountdownRing、PickGrid、Avatar、確認框。
import { h } from '../dom.js';
import { send, serverNow } from '../net.js';
import { LIMITS } from '../protocol.js';
import { changed, store } from '../store.js';
import { uiSound } from '../sfx.js';
import { errorText, t } from '../strings.js';
import { ringState } from './clock.js';

const SUCCESS_MS = 1200;
const ERROR_MS = 2000;

/**
 * 送出按鈕（UI_RULES K1–K4）：點下即鎖，8 秒內一定有結果（net.js 保證）。
 * @param {object} o id、label、run（回傳 Promise<{ok,code}>）、disabled（原因文字）、kind、doneLabel
 */
export function actionButton(o) {
  const key = `${o.id}@${store.server?.step_seq ?? 0}`;
  const st = store.ui.buttons[key] ?? { state: 'idle' };
  const offline = store.server && store.conn !== 'online';
  const reason = o.disabled || (offline ? t('btn.connecting') : null);
  const classes = ['btn', o.kind ? `btn--${o.kind}` : '', st.state !== 'idle' ? `btn--${st.state}` : ''];
  if (o.small) classes.push('btn--small');
  let label = o.label;
  if (st.state === 'pending') label = t('btn.sending');
  else if (st.state === 'success') label = `✔ ${o.doneLabel ?? o.label}`;
  else if (st.state === 'error') label = st.message;
  const onclick = async () => {
    const current = store.ui.buttons[key]?.state ?? 'idle';
    if (current !== 'idle') return;
    if (o.confirm) {
      store.ui.dialog = {
        text: o.confirm,
        confirmLabel: o.label,
        onConfirm: () => press(key, o),
      };
      changed();
      return;
    }
    press(key, o);
  };
  return [
    h('button', { class: classes.join(' '), testid: o.id, disabled: Boolean(reason) || st.state !== 'idle', onclick }, label),
    reason ? h('div', { class: 'reason' }, reason) : null,
  ];
}

async function press(key, o) {
  if (store.ui.buttons[key]) return; // 確認框連點也只送一次（UI_RULES K1）
  store.ui.buttons[key] = { state: 'pending' };
  changed();
  const result = await o.run();
  if (result?.ok === false) {
    const message = result.code === null || result.code === undefined ? t('btn.timeout') : errorText(result.code);
    store.ui.buttons[key] = { state: 'error', message };
    uiSound('error');
    changed();
    setTimeout(() => {
      delete store.ui.buttons[key];
      changed();
    }, ERROR_MS);
    return;
  }
  store.ui.buttons[key] = { state: 'success' };
  uiSound('success');
  changed();
  setTimeout(() => {
    delete store.ui.buttons[key];
    changed();
  }, SUCCESS_MS);
}

/** 暫停和繼續共用同一顆按鈕，位置不變（使用者要求）。 */
export function pauseToggle(server) {
  const paused = server.paused;
  if (!paused) {
    return actionButton({ id: 'btn-pause', label: t('s16.pause'), kind: 'secondary', small: true, run: () => send('admin.pause') });
  }
  return actionButton({
    id: 'btn-resume',
    label: t('s16.resume'),
    kind: 'suggest',
    small: true,
    disabled: paused.resume_at ? t('s16.resuming') : null,
    run: () => send('admin.resume'),
  });
}

/** 普通按鈕（不送伺服器）。 */
export function button(label, onclick, o = {}) {
  const classes = ['btn', o.kind ? `btn--${o.kind}` : 'btn--secondary', o.small ? 'btn--small' : ''];
  return h('button', { class: classes.join(' '), testid: o.testid, disabled: o.disabled, onclick }, label);
}

/**
 * 倒數：不在這裡算秒數。節點帶 data-deadline，由 app.js 的單一時鐘每影格更新（UI_RULES U6、Q5）。
 */
export function countdown(server, hint) {
  return h('div', { class: 'center' }, clockNumber(server, 'count'), hint ? h('div', { class: 'hint' }, hint) : null);
}

function clockNumber(server, cls) {
  const paused = Boolean(server.paused);
  const notOpen = server.opens_at !== undefined && server.opens_at !== null;
  return h('div', {
    class: cls,
    testid: 'countdown',
    'data-deadline': paused ? null : (server.deadline ?? null),
    'data-opens': paused ? null : (notOpen ? server.opens_at : null),
    'data-prep': prepText(server),
    // 旁白還在念時顯示文字不是數字，倒數環裡要改用小字（clock.js 每影格同步）
    'data-waiting': !paused && notOpen && serverNow() < server.opens_at,
  }, paused ? '‖' : clockText(server));
}

const SPARKS = 5;

/** 倒數環（ART 7.2）：環隨時間變短，剩 10 秒轉火色冒火星，剩 3 秒數字跳動，暫停變灰。 */
export function countdownRing(server, hint) {
  const paused = Boolean(server.paused);
  const opens = server.opens_at ?? null;
  const { frac, zone } = ringState(server.deadline, opens, serverNow(), paused);
  return h('div', { class: 'center' },
    h('div', {
      class: 'ring',
      testid: 'countdown-ring',
      'data-ring-deadline': paused ? null : (server.deadline ?? null),
      'data-ring-opens': paused ? null : opens,
      'data-zone': zone,
      style: `--frac:${frac.toFixed(4)}`,
    },
    h('span', { class: 'ring__sparks', 'aria-hidden': 'true' }, Array.from({ length: SPARKS }, () => h('i'))),
    clockNumber(server, 'ring__num')),
    hint ? h('div', { class: 'hint' }, hint) : null);
}

// 角色步驟旁白念的時候就能選（SPEC A8.2），其他步驟要等念完
function prepText(server) {
  return t(['WOLF', 'SEER', 'WITCH', 'HUNTER'].includes(server.step) ? 'prep.canAct' : 'prep');
}

// 重繪時先放正確文字，時鐘下一影格才更新，避免數字閃掉
function clockText(server) {
  const now = serverNow();
  if (server.opens_at && now < server.opens_at) return prepText(server);
  return server.deadline ? String(Math.max(0, Math.ceil(server.deadline - now))) : '';
}

export function rosterRow(server, id) {
  return server.roster?.find((r) => r.id === id);
}

export function nameOf(server, id) {
  if (id === null || id === undefined) return t('s20.nobody');
  const row = server.players?.find((p) => p.id === id) ?? rosterRow(server, id);
  return row?.name ?? '';
}

/** 代號（SPEC v4.40）：爪痕、投票箭頭上用的一個字。 */
export function markOf(server, id) {
  const row = rosterRow(server, id);
  return row?.mark ?? graphemes(nameOf(server, id))[0] ?? '';
}

/** 頭像：沒有大頭貼就顯示代號。 */
export function avatar(server, id) {
  const row = rosterRow(server, id);
  const player = server.players?.find((p) => p.id === id);
  const dead = player && !player.alive;
  const name = player?.name ?? row?.name ?? '';
  return h('span', { class: `avatar ${dead ? 'avatar--dead' : ''}` },
    row?.avatar_url ? h('img', { src: row.avatar_url, alt: name, loading: 'lazy' }) : markOf(server, id));
}

/**
 * 選擇格（SPEC C8.1）：不可選的人不出現；一律 3 欄。extra 是空刀、棄票這類特殊格。
 * look 是整個格子區的外觀（例如 'grid--wolf'），stateOf(value) 回傳單格多加的 class（例如即將確認）。
 */
export function pickGrid({
  ids, server, selected, onPick, marks = null, extra = [], prefix = 'pick-cell', look = '', stateOf = () => '',
}) {
  const cells = ids.map((id) => {
    const row = server.players?.find((p) => p.id === id);
    return h('button', {
      class: `cell ${selected === id ? 'cell--on' : ''} ${stateOf(id)}`,
      key: id,
      testid: `${prefix}-${id}`,
      onclick: () => { uiSound('select'); onPick(id); },
    },
    avatar(server, id),
    h('div', { class: 'cell__name' },
      h('span', { class: 'cell__seat' }, row ? `#${row.seat} ` : ''),
      nameOf(server, id)),
    h('div', { class: 'cell__marks' }, marks?.[id] ?? ''));
  });
  const specials = extra.map((e) => h('button', {
    class: `cell cell--empty ${selected === e.value ? 'cell--on' : ''} ${stateOf(e.value)}`,
    key: `extra-${e.value}`,
    testid: `${prefix}-${e.value}`,
    onclick: () => { uiSound('select'); onPick(e.value); },
  }, h('div', { class: 'cell__name' }, e.label), h('div', { class: 'cell__marks' }, marks?.[e.value] ?? '')));
  return h('div', { class: `grid ${marks ? 'grid--marks' : ''} ${look}` }, cells, specials);
}

/** 點格子只是選取，再點一次取消（UI_RULES K7）。 */
export function selection(name) {
  const key = `${name}@${store.server?.step_seq ?? 0}`;
  return {
    value: store.ui.picks[key],
    set(value) {
      store.ui.picks[key] = store.ui.picks[key] === value ? undefined : value;
      changed();
    },
    clear() {
      delete store.ui.picks[key];
      changed();
    },
  };
}

/**
 * 複製文字，回傳是否成功（CODING_RULES E11）。
 * 非 HTTPS 的網址沒有 navigator.clipboard（iPhone 連區網就是這樣），改用隱藏輸入框選取後複製。
 */
export async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // 被瀏覽器拒絕就走下面的舊方法
    }
  }
  const area = document.createElement('textarea');
  area.value = text;
  // 字級 16px 才不會讓 iOS 自動放大畫面；放在畫面外不影響版面
  area.style.cssText = 'position:fixed;top:-100px;font-size:16px';
  document.body.append(area);
  try {
    area.focus();
    area.setSelectionRange(0, text.length);
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    area.remove();
  }
}

export function toast(key, params) {
  store.ui.toast = { key, params };
  changed();
}

// \u7570\u9ad4\u9078\u64c7\u5b57\u5143\u4e5f\u53bb\u6389\uff0c\u2665\ufe0f \u624d\u4e0d\u6703\u8b8a\u6210\u5f69\u8272\u5716\u6848\uff08\u548c\u4f3a\u670d\u5668 protocol.clean_text \u4e00\u81f4\uff09
const INVISIBLE = /[\u0000-\u001f\u007f\u200b-\u200f\u2028-\u202f\u2060\ufe0e\ufe0f\ufeff]/gu;
// \u4e09\u7a2e\u540d\u5b57\uff08SPEC v4.40\uff09\uff1a\u986f\u793a\u540d\u5b57\u591a\u6536\u6a19\u9ede\u8207\u7b26\u865f\uff1b\u8a9e\u97f3\u540d\u5b57\u3001\u4ee3\u865f\u53ea\u6536\u6587\u5b57\u8207\u6578\u5b57\uff1b\u90fd\u4e0d\u6536 emoji \u548c\u7a7a\u767d
const EMOJI = /[\p{Emoji_Presentation}\u{1F000}-\u{1FAFF}]/u;
const WORD_CHARS = /^[\p{L}\p{N}]*$/u;
const DISPLAY_CHARS = /^[\p{L}\p{N}\p{P}\p{S}]*$/u;
const segmenter = new Intl.Segmenter('zh-Hant', { granularity: 'grapheme' });

/** 字素：「👍🏽」算一個字，和伺服器的計法一樣。 */
const graphemes = (text) => [...segmenter.segment(text)].map((part) => part.segment);

/** 去掉前後空白與看不見的字元（UI_RULES K9），超過字數的部分不收。 */
export function cleanName(raw, limit) {
  return graphemes(raw.replace(INVISIBLE, '').trim()).slice(0, limit).join('');
}

export const nameIsValid = (name) => DISPLAY_CHARS.test(name) && !EMOJI.test(name);
export const wordIsValid = (text) => WORD_CHARS.test(text) && !EMOJI.test(text);
export const graphemeCount = (text) => graphemes(text).length;

/**
 * 自動帶入的語音名字：有漢字只留漢字和數字（Oo風花雪月oO → 風花雪月，玩1 → 玩1），
 * 否則留文字與數字。和伺服器 default_spoken 同規則。
 */
export function autoSpoken(name) {
  const chars = graphemes(name);
  const hasHan = chars.some((ch) => /^\p{Script=Han}$/u.test(ch));
  const keep = hasHan ? /^[\p{Script=Han}\p{Nd}]$/u : /^[\p{L}\p{N}]$/u;
  const words = chars.filter((ch) => keep.test(ch) && !EMOJI.test(ch));
  return words.slice(0, LIMITS.SPOKEN_MAX_CHARS).join('');
}

export const autoMark = (spoken) => graphemes(spoken)[0] ?? '';
const onlyDigits = (raw) => raw.replace(/\D/gu, '');

// 元素沒有 oncompositionend 屬性，只能這樣聽：Chrome 選完字後不會再發 input，補發一次才收得到
document.addEventListener('compositionend', (e) => {
  e.target.dispatchEvent(new Event('input', { bubbles: true }));
});

/**
 * 表單欄位：值存在 ui.form。o.clean 可清理輸入；數字欄位只收數字；o.oncommit 在使用者改值後呼叫。
 * 注音、倉頡組字中（K8）不清理也不更新畫面，否則打「ㄒㄧㄠˇ」就會被判超過字數。
 */
export function field(name, label, o = {}) {
  const form = store.ui.form;
  const clean = o.clean ?? (o.inputmode === 'numeric' ? onlyDigits : null);
  const commit = (input) => {
    let value = clean ? clean(input.value) : input.value;
    if (o.maxlength) value = value.slice(0, o.maxlength);
    if (value !== input.value) input.value = value;
    form[name] = value;
    o.oncommit?.(value);
    changed();
  };
  return h('label', { class: 'field' }, label,
    h('input', {
      class: o.error ? 'input--error' : '',
      testid: o.testid ?? `input-${name}`,
      value: form[name] ?? '',
      type: o.type ?? 'text',
      inputmode: o.inputmode,
      placeholder: o.placeholder,
      autocomplete: o.autocomplete ?? 'off',
      // iPhone 會把第一個字母自動變大寫、自動改字，帳號就對不上（使用者回報）
      autocapitalize: 'none',
      autocorrect: 'off',
      spellcheck: 'false',
      oninput: (e) => {
        if (!e.isComposing) commit(e.target);
      },
    }),
    o.hint ? h('div', { class: 'hint' }, o.hint) : null,
    o.error ? h('div', { class: 'error-text' }, `⚠ ${o.error}`) : null);
}

export function errorLine(name) {
  const message = store.ui.form[`${name}__error`];
  return message ? h('div', { class: 'error-text', testid: `error-${name}` }, `⚠ ${message}`) : null;
}

export function setFormError(name, code) {
  store.ui.form[`${name}__error`] = code === null ? t('btn.timeout') : errorText(code);
  changed();
}

export function clearFormError(name) {
  delete store.ui.form[`${name}__error`];
}

/** 出局後的共用角標（SPEC C8.5）。 */
export function deadTag(server) {
  if (server.phase !== 'game' || server.step === 'END') return null;
  if (server.me && !server.me.alive) return h('div', { class: 'banner' }, t('s17.title'));
  if (!server.me && !server.host) return h('div', { class: 'banner' }, t('s5.spectating'));
  return null;
}
