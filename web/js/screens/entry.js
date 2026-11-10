// S0 等待開局、S1 管理員登入、S2 管理員選單、S3 開房完成、S4 加入、S25 已結束。
// 這幾個畫面都在進遊戲之前，內容簡單，放同一檔的理由是它們共用登入流程。
import { h } from '../dom.js';
import { api, connect } from '../net.js';
import { speak } from '../narrator.js';
import { LIMITS } from '../protocol.js';
import {
  clearAdminToken, clearPlayerToken, lastMark, lastName, lastSpoken, loadTokens, saveAdminToken, saveLastNames,
  savePlayerToken,
} from '../session.js';
import { changed, store } from '../store.js';
import { deviceId } from '../storage.js';
import { t } from '../strings.js';
import { qrDataUrl } from '../ui/qr.js';
import {
  actionButton, autoMark, autoSpoken, button, cleanName, clearFormError, copyText, errorLine, field,
  graphemeCount, nameIsValid, setFormError, toast, wordIsValid,
} from '../ui/common.js';

const form = () => store.ui.form;

/** 進房前測一次聲音就好，進房後第一次點擊會自動解鎖旁白（narrator.js）。 */
function soundCheck() {
  if (!store.voice.supported) return h('p', { class: 'error-text', testid: 'sound-unsupported' }, t('voice.unsupported'));
  return [
    button(t('sound.test'), () => { speak(t('sound.line')); }, { testid: 'btn-sound-test' }),
    h('p', { class: 'hint center' }, t('sound.hint')),
  ];
}
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

/** 關房或開新房後，這支手機不再屬於上一間房：清掉結束畫面、舊連線與舊玩家身分。 */
function resetForNewRoom() {
  clearPlayerToken();
  connect(null);
  store.activeToken = null;
  store.server = null;
  store.ended = null;
  store.closesAt = null;
  store.subtitle = '';
}

/** 無管理員模式的管理員也是玩家：一定要走加入，才有座位、角色，也才當得了旁白主機。 */
export function joinAsPlayerButton(room) {
  return button(t('s3.toJoin'), () => {
    store.ui.overlay = null;
    form().join_password = room.password;
    connect(null);
    store.activeToken = null;
    store.server = null;
    changed();
  }, { kind: 'suggest', testid: 'btn-to-join' });
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
        resetForNewRoom();
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

function currentRoomEntry(room) {
  const goToControl = () => {
    store.ui.overlay = null;
    connect(adminToken());
    changed();
  };
  if (room.mode === 'god') return button(t('s3.toHost'), goToControl, { testid: 'btn-to-control' });
  if (loadTokens().player) return null;
  // 大廳時要加入當玩家；遊戲已開始時（手機不在）才以操作身分進去按繼續（SPEC A11）
  return room.state === 'lobby'
    ? joinAsPlayerButton(room)
    : button(t('s3.toOperate'), goToControl, { testid: 'btn-to-control' });
}

function currentRoom(room) {
  return [
    h('h2', {}, t('s2.current')),
    h('div', { class: 'panel' },
      h('div', {}, room.name),
      h('div', {}, `${t('s3.password')}：`, h('b', { testid: 'room-password' }, room.password)),
      h('div', { class: 'hint' }, t('s5.count', { n: room.roster?.length ?? 0, cap: room.capacity }))),
    button(t('s3.title'), () => { store.ui.overlay = 'S3'; changed(); }),
    currentRoomEntry(room),
    actionButton({
      id: 'btn-reopen',
      label: t('s2.reopen'),
      kind: 'secondary',
      confirm: t('s2.closeConfirm'),
      run: async () => {
        const res = await api('/api/admin/room/reopen', { method: 'POST', auth: adminToken() });
        if (res.ok) {
          resetForNewRoom();
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
          resetForNewRoom();
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
  const qr = qrDataUrl(url);
  return [
    h('h1', { testid: 'screen-s3' }, t('s3.title')),
    h('p', {}, t('s3.password')),
    h('div', { class: 'big center', testid: 'room-password' }, room.password),
    qr ? h('img', { class: 'qr', src: qr, alt: t('s3.qr'), testid: 'invite-qr' }) : null,
    qr ? h('p', { class: 'hint center' }, t('s3.qr')) : null,
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
      : joinAsPlayerButton(room),
    soundCheck(),
  ];
}

export function s4() {
  const f = form();
  const hash = new URLSearchParams(location.hash.slice(1));
  if (f.join_password === undefined && hash.get('pw')) f.join_password = hash.get('pw');
  if (f.join_name === undefined && lastName()) {
    f.join_name = lastName();
    // 上次自己改過的語音名字、代號才帶入；和自動帶入一樣的就讓它繼續跟著名字變
    if (lastSpoken() && lastSpoken() !== autoSpoken(f.join_name)) {
      f.join_spoken = lastSpoken();
      f.spoken_edited = true;
    }
    if (lastMark() && lastMark() !== autoMark(f.join_spoken ?? autoSpoken(f.join_name))) {
      f.join_mark = lastMark();
      f.mark_edited = true;
    }
  }
  return f.rejoinMode ? rejoinForm() : joinForm();
}

/** names 是加入時的三種名字；回原位只打顯示名字，就不更新記住的名字。 */
function afterJoin(data, names = null) {
  savePlayerToken(data.token);
  if (names) saveLastNames(...names);
  form().join_pin = '';
  connect(data.token);
  changed();
}

const nameField = (o = {}) => field('join_name', t('s4.name'), {
  ...o,
  placeholder: t('s4.namePlaceholder'),
  clean: (raw) => cleanName(raw, LIMITS.NAME_MAX_CHARS),
});

/** 三種名字（SPEC v4.40）：語音名字、代號沒自己改過就跟著名字自動帶入。 */
function nameFields(f) {
  const name = f.join_name ?? '';
  if (!f.spoken_edited) f.join_spoken = autoSpoken(name);
  const spoken = f.join_spoken ?? '';
  if (!f.mark_edited) f.join_mark = autoMark(spoken);
  const mark = f.join_mark ?? '';
  const nameOk = graphemeCount(name) > 0 && nameIsValid(name);
  const spokenOk = graphemeCount(spoken) > 0 && wordIsValid(spoken);
  const markOk = graphemeCount(mark) === LIMITS.MARK_CHARS && wordIsValid(mark);
  const spokenError = spoken ? t('s4.wordChars') : name && t('s4.spokenEmpty');
  const fields = [
    nameField({
      hint: t('s4.nameHint'),
      error: nameIsValid(name) ? null : t('s4.nameChars'),
    }),
    field('join_spoken', t('s4.spoken'), {
      clean: (raw) => cleanName(raw, LIMITS.SPOKEN_MAX_CHARS),
      oncommit: () => { f.spoken_edited = true; },
      error: spokenOk ? null : spokenError || null,
    }),
    field('join_mark', t('s4.mark'), {
      clean: (raw) => cleanName(raw, LIMITS.MARK_CHARS),
      oncommit: () => { f.mark_edited = true; },
      error: markOk || !mark ? null : t('s4.wordChars'),
    }),
    // 預覽一直佔著位置、只換內容：中途插進來會讓下面的 PIN 欄被換掉，正在打的 PIN 會不見
    h('p', { class: 'hint', testid: 'name-preview', hidden: nameOk && spokenOk && markOk ? null : '' },
      nameOk && spokenOk && markOk ? t('s4.preview', { name, spoken, mark }) : ''),
  ];
  return { fields, ok: nameOk && spokenOk && markOk, names: [name, spoken, mark] };
}

function joinForm() {
  const f = form();
  const { fields, ok, names } = nameFields(f);
  const [name, spoken, mark] = names;
  const pinOk = /^\d{4}$/.test(f.join_pin ?? '');
  return [
    h('h1', { testid: 'screen-s4' }, t('s4.title')),
    field('join_password', t('s4.password'), { inputmode: 'numeric', maxlength: LIMITS.ROOM_PASSWORD_DIGITS }),
    fields,
    field('join_pin', t('s4.pin'), { inputmode: 'numeric', maxlength: LIMITS.PIN_DIGITS, type: 'password', hint: t('s4.pinHint') }),
    errorLine('join'),
    actionButton({
      id: 'btn-join',
      label: t('s4.join'),
      disabled: !f.join_password || !ok || !pinOk ? ' ' : null,
      run: async () => {
        clearFormError('join');
        const res = await api('/api/join', {
          method: 'POST',
          auth: adminToken(),
          body: { password: f.join_password, name, spoken, mark, pin: f.join_pin, device_id: deviceId() },
        });
        if (!res.ok) {
          setFormError('join', res.code);
          return res;
        }
        afterJoin(res.data, names);
        return res;
      },
    }),
    button(t('s4.rejoin'), () => { f.rejoinMode = true; changed(); }, { testid: 'btn-rejoin-mode' }),
    soundCheck(),
  ];
}

function rejoinForm() {
  const f = form();
  const name = f.join_name ?? '';
  return [
    h('h1', { testid: 'screen-s4-rejoin' }, t('s4.rejoinTitle')),
    nameField(),
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
        afterJoin(res.data);
        return res;
      },
    }),
    button(t('s4.back'), () => { f.rejoinMode = false; changed(); }),
    soundCheck(),
  ];
}

export function s25() {
  const reason = store.ended;
  const text = reason === 'replaced' ? 's25.replaced' : 's25.closed';
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

