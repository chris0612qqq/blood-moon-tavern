// 連線狀態機（UI_RULES U7、CODING_RULES E10、M1、M4、N2、N3、N5、N6）。

import { PROTOCOL_VERSION } from './protocol.js';
import { applyMessage, changed, currentStepSeq, store } from './store.js';
import { onBroadcast, onNarrate } from './narrator.js';
import { randomId } from './storage.js';

const TIMEOUT_MS = 8000;
const PING_MS = 5000;
const BACKOFF_MS = [1000, 2000, 4000, 8000];
const BACKOFF_MAX_MS = 10000;
const OFFLINE_AFTER_ATTEMPTS = 6;
const SAMPLE_COUNT = 5;

const params = new URLSearchParams(location.search);
export const apiBase = params.get('server') ?? '';

let socket = null;
let token = null;
let retryTimer = null;
let pingTimer = null;
let lastSeq = 0;
const pending = new Map();
const samples = [];

/** 校正後的伺服器時間（CODING_RULES M1）：取往返最短的那次。 */
let offset = 0;
export const serverNow = () => performance.now() / 1000 + offset;

function updateOffset(serverTs, sentAt) {
  const now = performance.now() / 1000;
  const rtt = sentAt === null ? 0.2 : now - sentAt;
  samples.push({ rtt, value: serverTs - (now - rtt / 2) });
  if (samples.length > SAMPLE_COUNT) samples.shift();
  offset = samples.reduce((best, s) => (s.rtt < best.rtt ? s : best)).value;
}

/** HTTP 呼叫，8 秒逾時（CODING_RULES E10）。失敗回 {ok:false, code}。 */
export async function api(path, { method = 'GET', body, auth, raw } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const headers = {};
    if (auth) headers.Authorization = `Bearer ${auth}`;
    if (body && !raw) headers['Content-Type'] = 'application/json';
    const res = await fetch(apiBase + path, {
      method,
      headers,
      body: raw ?? (body ? JSON.stringify(body) : undefined),
      signal: controller.signal,
    });
    const data = await res.json().catch(() => ({}));
    return res.ok ? { ok: true, data } : { ok: false, code: data.error ?? 'internal_error' };
  } catch {
    return { ok: false, code: null };
  } finally {
    clearTimeout(timer);
  }
}

function wsUrl() {
  const origin = apiBase || location.origin;
  return `${origin.replace(/^http/, 'ws')}/ws`;
}

/** 用這個 token 連線。token=null 表示斷開（例如登出）。 */
export function connect(newToken) {
  token = newToken;
  clearTimeout(retryTimer);
  if (socket) {
    const old = socket;
    socket = null;
    old.onclose = null;
    old.close();
  }
  if (token) open();
}

function open() {
  store.conn = store.attempts ? 'reconnecting' : 'connecting';
  changed();
  const ws = new WebSocket(wsUrl());
  socket = ws;
  lastSeq = 0;
  ws.onopen = () => {
    ws.send(JSON.stringify({ t: 'auth', token, client_version: PROTOCOL_VERSION }));
  };
  ws.onmessage = (event) => onMessage(ws, event);
  ws.onclose = (event) => onClose(ws, event);
  ws.onerror = () => {};
}

function onMessage(ws, event) {
  const msg = JSON.parse(event.data);
  if (msg.server_ts !== undefined) {
    const wait = msg.msg_id ? pending.get(msg.msg_id) : null;
    updateOffset(msg.server_ts, wait?.sentAt ?? null);
  }
  // N5：seq 跳號代表漏收，取完整狀態，不嘗試自己補
  if (msg.seq !== undefined) {
    if (lastSeq && msg.seq !== lastSeq + 1) send('state.request');
    lastSeq = msg.seq;
  }
  if (msg.t === 'state') {
    store.attempts = 0;
    store.conn = 'online';
    startPing();
  }
  if (msg.t === 'ack' || msg.t === 'error') settle(msg);
  if (msg.t === 'error' && !msg.msg_id) failAuth(msg.code);
  applyMessage(msg);
  if (msg.t === 'narrate') onNarrate(msg);
  if (msg.t === 'broadcast') onBroadcast(msg);
}

function failAuth(code) {
  if (code === 'unauthorized') {
    store.onUnauthorized?.();
  } else if (code === 'version_mismatch') {
    store.ui.dialog = { kind: 'version' };
  }
  connect(null);
}

function settle(msg) {
  const wait = pending.get(msg.msg_id);
  if (!wait) return;
  pending.delete(msg.msg_id);
  clearTimeout(wait.timer);
  // UI_RULES U10：回應到的時候步驟已換，不把畫面改回舊步驟
  wait.resolve(msg.t === 'ack' ? { ok: true } : { ok: false, code: msg.code });
}

function onClose(ws, event) {
  if (socket !== ws) return;
  socket = null;
  clearInterval(pingTimer);
  failPending();
  if (store.ended || event.code === 4401 || event.code === 4426) {
    changed();
    return;
  }
  scheduleRetry();
}

function failPending() {
  for (const [id, wait] of pending) {
    clearTimeout(wait.timer);
    wait.resolve({ ok: false, code: null });
    pending.delete(id);
  }
}

function scheduleRetry() {
  store.attempts += 1;
  store.conn = store.attempts >= OFFLINE_AFTER_ATTEMPTS ? 'offline' : 'reconnecting';
  changed();
  const base = BACKOFF_MS[store.attempts - 1] ?? BACKOFF_MAX_MS;
  // N2：加隨機抖動，避免熱點恢復時全部手機同一秒重連
  retryTimer = setTimeout(() => {
    if (token) open();
  }, base + Math.random() * 1000);
}

export function retryNow() {
  if (!token || (socket && socket.readyState <= WebSocket.OPEN)) return;
  clearTimeout(retryTimer);
  open();
}

function startPing() {
  clearInterval(pingTimer);
  pingTimer = setInterval(() => send('ping'), PING_MS);
}

/** 送意圖，回傳 Promise：{ok, code}。斷線時不排隊（CODING_RULES N6）；8 秒必有結果（K2）。 */
export function send(type, fields = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    return Promise.resolve({ ok: false, code: null });
  }
  const msgId = randomId();
  socket.send(JSON.stringify({ t: type, msg_id: msgId, step_seq: currentStepSeq(), ...fields }));
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      pending.delete(msgId);
      resolve({ ok: false, code: null });
    }, TIMEOUT_MS);
    pending.set(msgId, { resolve, timer, sentAt: performance.now() / 1000 });
  });
}

// M4、N3：回前景與網路恢復時立刻重新同步
function resync() {
  if (!token) return;
  if (socket?.readyState === WebSocket.OPEN) send('state.request');
  else retryNow();
}

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) resync();
});
window.addEventListener('pageshow', resync);
window.addEventListener('online', () => {
  if (socket) {
    socket.onclose = null;
    socket.close();
    socket = null;
  }
  store.attempts = Math.max(store.attempts, 1);
  if (token) open();
});
