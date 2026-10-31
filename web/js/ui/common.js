// 共用元件灰盒版（DEV_PLAN P4）：ActionButton、CountdownRing、PickGrid、Avatar、確認框。
import { h } from '../dom.js';
import { serverNow } from '../net.js';
import { changed, store } from '../store.js';
import { errorText, t } from '../strings.js';

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
  store.ui.buttons[key] = { state: 'pending' };
  changed();
  const result = await o.run();
  if (result?.ok === false) {
    const message = result.code === null || result.code === undefined ? t('btn.timeout') : errorText(result.code);
    store.ui.buttons[key] = { state: 'error', message };
    changed();
    setTimeout(() => {
      delete store.ui.buttons[key];
      changed();
    }, ERROR_MS);
    return;
  }
  store.ui.buttons[key] = { state: 'success' };
  changed();
  setTimeout(() => {
    delete store.ui.buttons[key];
    changed();
  }, SUCCESS_MS);
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
  const paused = Boolean(server.paused);
  const notOpen = server.opens_at !== undefined && server.opens_at !== null;
  return h('div', { class: 'center' },
    h('div', {
      class: 'count',
      testid: 'countdown',
      'data-deadline': paused ? null : (server.deadline ?? null),
      'data-opens': paused ? null : (notOpen ? server.opens_at : null),
    }, paused ? '‖' : clockText(server)),
    hint ? h('div', { class: 'hint' }, hint) : null);
}

// 重繪時先放正確文字，時鐘下一影格才更新，避免數字閃掉
function clockText(server) {
  const now = serverNow();
  if (server.opens_at && now < server.opens_at) return t('prep');
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

/** 頭像：沒有大頭貼就顯示名字第一個字。 */
export function avatar(server, id) {
  const row = rosterRow(server, id);
  const player = server.players?.find((p) => p.id === id);
  const dead = player && !player.alive;
  const name = player?.name ?? row?.name ?? '';
  return h('span', { class: `avatar ${dead ? 'avatar--dead' : ''}` },
    row?.avatar_url ? h('img', { src: row.avatar_url, alt: name, loading: 'lazy' }) : name.slice(0, 1));
}

/** 選擇格（SPEC C8.1）：不可選的人不出現；一律 3 欄。extra 是空刀、棄票這類特殊格。 */
export function pickGrid({ ids, server, selected, onPick, marks = {}, extra = [], prefix = 'pick-cell' }) {
  const cells = ids.map((id) => {
    const row = server.players?.find((p) => p.id === id);
    return h('button', {
      class: `cell ${selected === id ? 'cell--on' : ''}`,
      key: id,
      testid: `${prefix}-${id}`,
      onclick: () => onPick(id),
    },
    avatar(server, id),
    h('div', {}, nameOf(server, id)),
    h('div', { class: 'cell__seat' }, row ? `#${row.seat}` : ''),
    h('div', { class: 'cell__marks' }, marks[id] ?? ''));
  });
  const specials = extra.map((e) => h('button', {
    class: `cell cell--empty ${selected === e.value ? 'cell--on' : ''}`,
    key: `extra-${e.value}`,
    testid: `${prefix}-${e.value}`,
    onclick: () => onPick(e.value),
  }, e.label, h('div', { class: 'cell__marks' }, marks[e.value] ?? '')));
  return h('div', { class: 'grid' }, cells, specials);
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

export function toast(key, params) {
  store.ui.toast = { key, params };
  changed();
}

/** 表單欄位：值存在 ui.form。 */
export function field(name, label, o = {}) {
  const form = store.ui.form;
  return h('label', { class: 'field' }, label,
    h('input', {
      testid: o.testid ?? `input-${name}`,
      value: form[name] ?? '',
      type: o.type ?? 'text',
      inputmode: o.inputmode,
      maxlength: o.maxlength,
      autocomplete: o.autocomplete ?? 'off',
      oninput: (e) => {
        form[name] = e.target.value;
        changed();
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
