// S0 等待開局、S1 管理員登入、S2 管理員選單、S3 開房完成、S4 加入、S25 已移出。
// 這幾個畫面都在進遊戲之前，內容簡單，放同一檔的理由是它們共用登入流程。
import { h } from '../dom.js';
import { api, connect } from '../net.js';
import { LIMITS } from '../protocol.js';
import {
  clearAdminToken, clearPlayerToken, lastName, loadTokens, saveAdminToken, saveLastName, savePlayerToken,
} from '../session.js';
import { changed, store } from '../store.js';
import { deviceId } from '../storage.js';
import { t } from '../strings.js';
import {
  actionButton, button, clearFormError, copyText, errorLine, field, setFormError, toast,
} from '../ui/common.js';

const form = () => store.ui.form;
const adminToken = () => loadTokens().admin;

export function s0() {
  const closed = store.healthFailed;
  return h('div', { class: 'center' },
    h('h1', { testid: 'screen-s0' }, closed ? t('s0.closed') : t('s0.title')),
    closed ? h('p', { class: 'hint' }, t('s0.retry')) : null);
}

export function s1() {
  return [
    h('h1', { testid: 'screen-s1' }, t('s1.title')),
    field('admin_user', t('s1.username'), { autocomplete: 'username' }),
    field('admin_pass', t('s1.password'), { type: 'password', autocomplete: 'current-password' }),
    errorLine('login'),
    actionButton({
      id: 'btn-admin-login',
      label: t('s1.login'),
      disabled: !form().admin_user || !form().admin_pass ? ' ' : null,
      run: async () => {
        clearFormError('login');
        const res = await api('/api/admin/login', {
          method: 'POST',
          body: { username: form().admin_user, password: form().admin_pass, device_id: deviceId() },
        });
        if (!res.ok) {
          setFormError('login', res.code);
          return res;
        }
        saveAdminToken(res.data.token);
        form().admin_pass = '';
        store.ui.overlay = 'S2';
        await refreshAdminRoom();
        return res;
      },
    }),
    button(t('common.back'), () => { store.ui.overlay = null; changed(); }),
  ];
}

export async function refreshAdminRoom() {
  const res = await api('/api/admin/room', { auth: adminToken() });
  store.adminRoom = res.ok ? res.data : null;
  if (!res.ok && res.code === 'unauthorized') {
    clearAdminToken();
    store.ui.overlay = 'S1';
  }
  changed();
  return res;
}

export function s2() {
  const room = store.adminRoom;
  return [
    h('h1', { testid: 'screen-s2' }, t('s2.title')),
    room ? currentRoom(room) : openForm(),
    h('h2', {}, t('s2.changePassword')),
    field('old_pass', t('s2.oldPassword'), { type: 'password' }),
    field('new_pass', t('s2.newPassword'), { type: 'password' }),
    errorLine('change'),
    actionButton({
      id: 'btn-change-password',
      label: t('s2.changePassword'),
      kind: 'secondary',
      disabled: !form().old_pass || (form().new_pass ?? '').length < 8 ? ' ' : null,
      run: async () => {
        clearFormError('change');
        const res = await api('/api/admin/password', {
          method: 'POST',
          auth: adminToken(),
          body: { old_password: form().old_pass, new_password: form().new_pass },
        });
        if (!res.ok) setFormError('change', res.code);
        return res;
      },
    }),
    button(t('common.close'), () => { store.ui.overlay = null; changed(); }, { testid: 'btn-admin-close' }),
    button(t('s2.logout'), () => {
      clearAdminToken();
      store.adminRoom = null;
      store.ui.overlay = null;
      changed();
    }),
  ];
}

function openForm() {
  const f = form();
  const mode = f.room_mode ?? 'god';
  const choice = (value, label) => h('button', {
    class: `cell ${mode === value ? 'cell--on' : ''}`,
    style: 'width:100%;min-height:60px;margin:4px 0',
    testid: `mode-${value}`,
    onclick: () => { f.room_mode = value; changed(); },
  }, label);
  return [
    choice('god', t('s2.god')),
    choice('auto', t('s2.auto')),
    field('room_name', t('s2.roomName')),
    field('room_password', t('s2.roomPassword'), { inputmode: 'numeric', maxlength: LIMITS.ROOM_PASSWORD_DIGITS }),
    errorLine('open'),
    actionButton({
      id: 'btn-open-room',
      label: t('s2.open'),
      run: async () => {
        clearFormError('open');
        const body = { mode, name: (f.room_name ?? '').trim() || t('app.name'), settings: {} };
        if (f.room_password) body.password = f.room_password;
        const res = await api('/api/admin/room', { method: 'POST', auth: adminToken(), body });
        if (!res.ok) {
          setFormError('open', res.code);
          return res;
        }
        await refreshAdminRoom();
        // 不等下一次 5 秒輪詢，否則按「去加入」會短暫退回等待頁
        await store.refreshHealth();
        store.ui.overlay = 'S3';
        changed();
        return res;
      },
    }),
  ];
}

function currentRoom(room) {
  return [
    h('h2', {}, t('s2.current')),
    h('div', { class: 'panel' },
      h('div', {}, room.name),
      h('div', {}, `${t('s3.password')}：`, h('b', { testid: 'room-password' }, room.password)),
      h('div', { class: 'hint' }, t('s5.count', { n: room.roster?.length ?? 0, cap: room.capacity }))),
    button(t('s3.title'), () => { store.ui.overlay = 'S3'; changed(); }),
    room.mode === 'god' || !loadTokens().player
      ? button(t('s3.toHost'), () => {
        store.ui.overlay = null;
        connect(adminToken());
        changed();
      }, { testid: 'btn-to-control' })
      : null,
    actionButton({
      id: 'btn-reopen',
      label: t('s2.reopen'),
      kind: 'secondary',
      confirm: t('s2.closeConfirm'),
      run: async () => {
        const res = await api('/api/admin/room/reopen', { method: 'POST', auth: adminToken() });
        if (res.ok) {
          await refreshAdminRoom();
          await store.refreshHealth();
        }
        return res;
      },
    }),
    actionButton({
      id: 'btn-close-room',
      label: t('s2.closeRoom'),
      kind: 'danger',
      confirm: t('s2.closeConfirm'),
      run: async () => {
        const res = await api('/api/admin/room', { method: 'DELETE', auth: adminToken() });
        if (res.ok) {
          store.adminRoom = null;
          clearPlayerToken();
          await store.refreshHealth();
          changed();
        }
        return res;
      },
    }),
  ];
}

/** QR 網址帶房間密碼，放在 # 後面，不會進伺服器紀錄（SPEC C4 S3）。 */
function inviteUrl(room) {
  return `${location.origin}${location.pathname}#pw=${room.password}`;
}

export function s3() {
  const room = store.adminRoom;
  if (!room) return s2();
  const url = inviteUrl(room);
  return [
    h('h1', { testid: 'screen-s3' }, t('s3.title')),
    h('p', {}, t('s3.password')),
    h('div', { class: 'big center', testid: 'room-password' }, room.password),
    h('p', {}, t('s3.link')),
    h('div', { class: 'panel selectable', testid: 'invite-url', style: 'overflow-wrap:anywhere' }, url),
    button(t('s3.copy'), async () => {
      const copied = await copyText(t('s3.invite', { url }));
      toast(copied ? 'toast.copied' : 'toast.copyFailed');
    }, { testid: 'btn-copy-invite' }),
    room.mode === 'god'
      ? button(t('s3.toHost'), () => {
        store.ui.overlay = null;
        connect(adminToken());
        changed();
      }, { kind: 'suggest', testid: 'btn-to-control' })
      : button(t('s3.toJoin'), () => {
        store.ui.overlay = null;
        form().join_password = room.password;
        changed();
      }, { kind: 'suggest', testid: 'btn-to-join' }),
  ];
}

export function s4() {
  const f = form();
  const hash = new URLSearchParams(location.hash.slice(1));
  if (f.join_password === undefined && hash.get('pw')) f.join_password = hash.get('pw');
  if (f.join_name === undefined && lastName()) f.join_name = lastName();
  return f.rejoinMode ? rejoinForm() : joinForm();
}

function afterJoin(data, name) {
  savePlayerToken(data.token);
  saveLastName(name);
  form().join_pin = '';
  connect(data.token);
  changed();
}

function joinForm() {
  const f = form();
  const name = (f.join_name ?? '').trim();
  const left = LIMITS.NAME_GRAPHEMES - [...name].length;
  const pinOk = /^\d{4}$/.test(f.join_pin ?? '');
  return [
    h('h1', { testid: 'screen-s4' }, t('s4.title')),
    field('join_password', t('s4.password'), { inputmode: 'numeric', maxlength: LIMITS.ROOM_PASSWORD_DIGITS }),
    field('join_name', t('s4.name'), { hint: left > 0 ? t('s4.nameLeft', { n: left }) : null }),
    field('join_pin', t('s4.pin'), { inputmode: 'numeric', maxlength: LIMITS.PIN_DIGITS, type: 'password', hint: t('s4.pinHint') }),
    errorLine('join'),
    actionButton({
      id: 'btn-join',
      label: t('s4.join'),
      disabled: !f.join_password || !name || !pinOk ? ' ' : null,
      run: async () => {
        clearFormError('join');
        const res = await api('/api/join', {
          method: 'POST',
          auth: adminToken(),
          body: { password: f.join_password, name, pin: f.join_pin, device_id: deviceId() },
        });
        if (!res.ok) {
          setFormError('join', res.code);
          return res;
        }
        afterJoin(res.data, name);
        return res;
      },
    }),
    button(t('s4.rejoin'), () => { f.rejoinMode = true; changed(); }, { testid: 'btn-rejoin-mode' }),
  ];
}

function rejoinForm() {
  const f = form();
  const name = (f.join_name ?? '').trim();
  return [
    h('h1', { testid: 'screen-s4-rejoin' }, t('s4.rejoinTitle')),
    field('join_name', t('s4.name')),
    field('join_pin', t('s4.pin'), { inputmode: 'numeric', maxlength: LIMITS.PIN_DIGITS, type: 'password' }),
    errorLine('rejoin'),
    actionButton({
      id: 'btn-rejoin',
      label: t('s4.rejoin'),
      disabled: !name || !/^\d{4}$/.test(f.join_pin ?? '') ? ' ' : null,
      run: async () => {
        clearFormError('rejoin');
        const res = await api('/api/rejoin', {
          method: 'POST',
          body: { name, pin: f.join_pin, device_id: deviceId() },
        });
        if (!res.ok) {
          setFormError('rejoin', res.code);
          return res;
        }
        afterJoin(res.data, name);
        return res;
      },
    }),
    button(t('s4.back'), () => { f.rejoinMode = false; changed(); }),
  ];
}

export function s25() {
  const reason = store.ended;
  const text = reason === 'kicked' ? 's25.kicked' : (reason === 'replaced' ? 's25.replaced' : 's25.closed');
  return h('div', { class: 'center' },
    h('h1', { testid: 'screen-s25' }, t(text)),
    reason === 'closed' ? h('p', { class: 'hint' }, t('s25.wait')) : null,
    button(t('s25.again'), () => {
      if (reason !== 'replaced') clearPlayerToken();
      store.ended = null;
      store.server = null;
      store.restart?.();
      changed();
    }, { testid: 'btn-ended-home' }));
}

