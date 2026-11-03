// 唯一的狀態來源（UI_RULES U1、U8）。收到完整 state 就整個替換，其他訊息只做增量。

export const store = {
  /** 伺服器給的狀態；null 表示還沒連上房間。 */
  server: null,
  /** 連線：connecting / online / reconnecting / offline。 */
  conn: 'connecting',
  attempts: 0,
  /** 目前旁白字幕。 */
  subtitle: '',
  /** 公開的 /api/health 結果。 */
  health: null,
  healthFailed: false,
  /** 換裝置、關房等終止原因。 */
  ended: null,
  closesAt: null,
  lastReveal: null,
  /** 只影響這支手機的介面狀態（CODING_RULES V1）。 */
  ui: {
    tab: 'game',
    overlay: null,
    dialog: null,
    toast: null,
    buttons: {},
    picks: {},
    drafts: {},
    form: {},
    speakAloud: true,
    cardHeld: false,
    hostMoreOpen: false,
    witchStage: {},
    chatAs: 'self',
    /** 設定裡的「旁白要在哪些手機念」正在選人。 */
    voicesPicking: false,
    /** 哪些頻道已經翻到最舊。 */
    chatEnd: {},
    /** 按下載入舊訊息時的清單高度；收到後換到 chatRestore，重繪時補回捲動位置。 */
    chatHeight: null,
    chatRestore: null,
    /** 自己發的訊息一定要看得到，下次重繪捲到底。 */
    chatStick: false,
    /** 拖曳排座位中：{ id, order }。 */
    seatDrag: null,
    /** 各頻道沒看的訊息數。 */
    unread: {},
    /** 聊天分頁正在看哪個頻道；狼人頻道收在聊天分頁裡，下方不多一個分頁（使用者要求）。 */
    chatChannel: 'public',
    /** 廣播分頁選的對象與要不要念出來。 */
    broadcastTargets: [],
    broadcastSpeak: true,
  },
  version: 0,
};

const BROADCAST_SHOW_MS = 8000;
const listeners = new Set();
let scheduled = false;

export function subscribe(listener) {
  listeners.add(listener);
}

/** 通知重繪：同一影格內的多次改變只畫一次（UI_RULES U3）。背景分頁沒有 rAF，所以另有計時器。 */
export function changed() {
  store.version += 1;
  if (scheduled) return;
  scheduled = true;
  const flush = () => {
    if (!scheduled) return;
    scheduled = false;
    for (const listener of listeners) listener();
  };
  requestAnimationFrame(flush);
  setTimeout(flush, 100);
}

function patchMe(fields) {
  if (store.server?.me) store.server.me = { ...store.server.me, ...fields };
}

const HANDLERS = {
  state(msg) {
    const previous = store.server;
    store.server = msg;
    store.ui.chatEnd = {}; // 完整狀態只帶最近的訊息，舊的又可以往回翻
    if (msg.closes_at) store.closesAt = msg.closes_at;
    enterStep(previous?.step, msg.step);
  },
  step(msg) {
    const s = store.server;
    if (!s) return;
    const previous = s.step;
    Object.assign(s, msg);
    delete s.opens_at;
    delete s.deadline;
    delete s.suspect_picks;
    delete s.grace_until;
    s.announced = false;
    s.timed_out = false;
    enterStep(previous, msg.step);
  },
  timers(msg) {
    if (store.server) Object.assign(store.server, msg);
  },
  me(msg) {
    if (store.server) store.server.me = msg;
  },
  progress(msg) {
    if (!store.server) return;
    store.server.progress = { done: msg.done, total: msg.total };
    store.server.suspect_picks = msg.suspect_picks ?? {};
  },
  narrate(msg) {
    store.subtitle = msg.text;
  },
  death(msg) {
    const s = store.server;
    if (!s) return;
    for (const dead of msg.players) {
      const row = s.players.find((p) => p.id === dead.id);
      if (row) {
        row.alive = false;
        if (dead.public_role) row.public_role = dead.public_role;
        row.death_cause = dead.cause;
      }
      const history = historyRow(s);
      history.deaths.push(dead.id);
      history.causes = { ...history.causes, [dead.id]: dead.cause };
    }
  },
  revive(msg) {
    const row = store.server?.players.find((p) => p.id === msg.id);
    if (row) {
      row.alive = true;
      delete row.public_role;
    }
  },
  dawn(msg) {
    if (!store.server) return;
    store.server.announced = true;
    store.server.dawn_count = msg.count;
    historyRow(store.server).saved = msg.saved;
  },
  'vote.reveal'(msg) {
    store.lastReveal = msg;
    if (store.server) Object.assign(historyRow(store.server), msg);
  },
  'hunter.shot'(msg) {
    if (store.server) store.server.hunter_shot = msg;
  },
  'wolf.picks'(msg) {
    const pack = store.server?.me?.wolf_pack;
    if (pack) patchMe({ wolf_pack: { ...pack, ...msg } });
  },
  disguise(msg) {
    patchMe({ disguise_info: { target: msg.target, rounds_left: msg.rounds_left } });
  },
  paused(msg) {
    if (store.server) store.server.paused = { reason: msg.reason, resume_at: msg.resume_at };
  },
  roster(msg) {
    const s = store.server;
    if (!s) return;
    const old = s.roster?.find((r) => r.id === s.me?.id);
    const mine = msg.players.find((r) => r.id === s.me?.id);
    if (old && mine && old.seat !== mine.seat && s.phase === 'lobby') {
      store.ui.toast = { key: 'toast.seat', params: { seat: mine.seat } };
    }
    s.roster = msg.players;
  },
  'roster.narrator'(msg) {
    const s = store.server;
    if (!s) return;
    s.narrator_id = msg.player;
    if (s.room) s.room.narrator_id = msg.player;
  },
  voices(msg) {
    if (store.server) store.server.voices = { all: msg.all, players: msg.players };
  },
  'chat.msg'(msg) {
    const s = store.server;
    if (!s) return;
    s.chat = s.chat ?? [];
    if (!s.chat.some((m) => m.id === msg.id)) s.chat.push(msg);
    if (msg.mine) store.ui.chatStick = true;
    else if (store.ui.tab !== 'chat' || store.ui.chatChannel !== msg.channel) {
      store.ui.unread = { ...store.ui.unread, [msg.channel]: (store.ui.unread[msg.channel] ?? 0) + 1 };
    }
  },
  'media.url'(msg) {
    for (const m of store.server?.chat ?? []) {
      if (m.media_id === msg.media_id) m.media_url = msg.url;
    }
  },
  'chat.history'(msg) {
    const s = store.server;
    if (!s) return;
    const known = new Set((s.chat ?? []).map((m) => m.id));
    s.chat = [...msg.messages.filter((m) => !known.has(m.id)), ...(s.chat ?? [])];
    if (!msg.messages.length) store.ui.chatEnd = { ...store.ui.chatEnd, [msg.channel]: true };
    store.ui.chatRestore = store.ui.chatHeight;
    store.ui.chatHeight = null;
  },
  broadcast(msg) {
    store.ui.toast = { key: 'broadcast.show', params: { text: msg.text }, ms: BROADCAST_SHOW_MS };
  },
  'host.progress'(msg) {
    if (store.server) store.server.host = msg;
  },
  'card.reshow'() {
    store.ui.tab = 'role';
  },
  'room.closing'(msg) {
    store.closesAt = msg.at;
  },
  'room.closed'() {
    store.ended = 'closed';
    store.server = null;
  },
  replaced() {
    store.ended = 'replaced';
    store.server = null;
  },
};

function historyRow(s) {
  s.history = s.history ?? [];
  let row = s.history.find((h) => h.round_no === s.round_no);
  if (!row) {
    row = { round_no: s.round_no, deaths: [], causes: {}, saved: null };
    s.history.push(row);
  }
  return row;
}

// C9 #15：天黑時所有手機切到遊戲分頁；V6：日夜只有一個開關
function enterStep(previous, step) {
  if (previous === step) return;
  store.ui.picks = {};
  if (step === 'NIGHT_START') store.ui.tab = 'game';
  // 要投票的人如果還在聊天或看規則，會錯過投票（使用者要求）。已出局、旁觀、主持人不用投，不打擾
  if ((step === 'SUSPECT_VOTE' || step === 'VOTE') && store.server?.me?.alive) {
    store.ui.tab = 'game';
    store.ui.overlay = null;
  }
  store.ui.cardHeld = false;
}

/** 套用一則伺服器訊息。 */
export function applyMessage(msg) {
  const handler = HANDLERS[msg.t];
  if (handler) handler(msg);
  changed();
}

export function currentStepSeq() {
  return store.server?.step_seq ?? null;
}
