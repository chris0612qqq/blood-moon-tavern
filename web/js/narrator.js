// 旁白發聲。夜晚大家閉眼要靠聲音，灰盒試玩就需要；完整版（音效、優先序）在 P6。
// 不等 onend：iOS 常不觸發，流程也不依賴它（CODING_RULES E15）。
//
// iOS 只允許「手指點擊當下」開始第一次發聲，而旁白是收到伺服器訊息才念，不算點擊當下。
// 所以任何第一次點擊都先念一個無聲的字解鎖，之後伺服器叫念才念得出來（CODING_RULES V13）。

import { LIMITS } from './protocol.js';
import { HOWL_MS, wolfHowl } from './sfx.js';
import { changed, store } from './store.js';

const PITCH = 0.9;
// 電子音訊息（SPEC v4.24）：一般玩家正常音調；狼人身分很低又慢，一聽就分得出來
export const VOICE_STYLE = Object.freeze({
  normal: { pitch: 1.1, rate: 1.0 },
  wolf: { pitch: 0.5, rate: 0.8 },
});
const CANCEL_SETTLE_MS = 60;
const UNLOCK_TEXT = '。';
// 留住目前的語音物件：有些瀏覽器會把沒人參照的語音回收掉，念到一半就停
let current = null;
const queued = [];
const QUEUE_KEEP = 20;
// 角色開場音效。垂直切片只有狼人；其他角色量產時加進來（ART 12.4）
const OPENING_SFX = Object.freeze({ wolf_open: wolfHowl });
let openingPlayedAt = null;

store.voice = { supported: Boolean(window.speechSynthesis), unlocked: false, voices: 0, name: '', last: '' };

function report(last) {
  store.voice.last = last;
  changed();
}

function zhVoice() {
  const voices = window.speechSynthesis?.getVoices() ?? [];
  store.voice.voices = voices.length;
  for (const lang of ['zh-TW', 'zh-HK', 'zh-CN']) {
    const match = voices.find((v) => v.lang.replace('_', '-') === lang);
    if (match) return match;
  }
  return null;
}

function build(text, volume, style = null) {
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'zh-TW';
  utterance.rate = style?.rate ?? LIMITS.NARRATION_RATE;
  utterance.pitch = style?.pitch ?? PITCH;
  utterance.volume = volume;
  const voice = zhVoice();
  if (voice) {
    utterance.voice = voice;
    store.voice.name = voice.name;
  }
  return utterance;
}

/** 念一句。不支援或失敗都只是沒聲音，字幕照常（CODING_RULES E11）。 */
export function speak(text, style = null) {
  const synth = window.speechSynthesis;
  if (!synth) return false;
  try {
    const utterance = build(text, 1, style);
    utterance.onstart = () => {
      store.voice.unlocked = true;
      report('started');
    };
    utterance.onerror = (event) => report(`error:${event.error ?? ''}`);
    current = utterance;
    // 切到背景回來時可能卡在暫停狀態
    synth.resume();
    if (synth.speaking || synth.pending) {
      // iOS 取消後馬上念，這一句可能被吞掉，所以稍等一下
      synth.cancel();
      setTimeout(() => synth.speak(utterance), CANCEL_SETTLE_MS);
    } else {
      synth.speak(utterance);
    }
    report('requested');
    return true;
  } catch (err) {
    report(`error:${err}`);
    return false;
  }
}

/** 排在目前的話後面念，不打斷：字卡要能連按湊成一句（使用者決定）。 */
export function speakAfter(text) {
  const synth = window.speechSynthesis;
  if (!synth) return false;
  try {
    const utterance = build(text, 1);
    utterance.onstart = () => {
      store.voice.unlocked = true;
      report('started');
    };
    utterance.onerror = (event) => report(`error:${event.error ?? ''}`);
    queued.push(utterance);
    if (queued.length > QUEUE_KEEP) queued.shift();
    synth.resume();
    synth.speak(utterance);
    report('requested');
    return true;
  } catch (err) {
    report(`error:${err}`);
    return false;
  }
}

function unlockOnFirstTap() {
  if (store.voice.unlocked || !window.speechSynthesis) return;
  try {
    const utterance = build(UNLOCK_TEXT, 0);
    utterance.onstart = () => {
      store.voice.unlocked = true;
      changed();
    };
    current = utterance;
    window.speechSynthesis.speak(utterance);
  } catch {
    // 解鎖失敗就等下一次點擊
  }
}

for (const name of ['touchend', 'click']) {
  document.addEventListener(name, unlockOnFirstTap, { capture: true, passive: true });
}
// 語音清單是非同步載入的（CODING_RULES V14）
window.speechSynthesis?.addEventListener?.('voiceschanged', zhVoice);

/** 這支手機要不要念旁白：旁白主機、上帝主持人，或管理員選了「全部人」／指定到這支（SPEC v4.29）。 */
export function speaksHere(server) {
  if (server?.host) return true;
  const me = server?.me?.id;
  if (!me) return false;
  const narrator = server.narrator_id ?? server.room?.narrator_id;
  return narrator === me || Boolean(server.voices?.all) || Boolean(server.voices?.players.includes(me));
}

/** 收到 narrate 時呼叫：只有旁白主機或主持人手機發聲。 */
export function onNarrate(msg) {
  if (!msg.speak || !speaksHere(store.server)) return;
  // 狼人請睜眼之前先狼嚎（ART 12.4），嚎完才念；重念、催促時不再嚎
  const howl = OPENING_SFX[msg.line_id];
  const seq = store.server.step_seq;
  const played = howl && seq !== openingPlayedAt && howl();
  if (howl) openingPlayedAt = seq;
  // 主持人選了「我自己念」：繼續後的重念也只顯示字幕
  if (store.server.host && !store.ui.speakAloud) return;
  if (played) setTimeout(() => speak(msg.text), HOWL_MS);
  else speak(msg.text);
}

/** 收到定向廣播：伺服器只送給被指定的手機，所以不看是不是旁白主機。音效（msg.sound）P8 才接。 */
export function onBroadcast(msg) {
  if (msg.speak) speakAfter(msg.text);
}
