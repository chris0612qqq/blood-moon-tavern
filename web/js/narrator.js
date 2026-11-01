// 旁白發聲。夜晚大家閉眼要靠聲音，灰盒試玩就需要；完整版（音效、優先序）在 P6。
// 不等 onend：iOS 常不觸發，流程也不依賴它（CODING_RULES E15）。
//
// iOS 只允許「手指點擊當下」開始第一次發聲，而旁白是收到伺服器訊息才念，不算點擊當下。
// 所以任何第一次點擊都先念一個無聲的字解鎖，之後伺服器叫念才念得出來（CODING_RULES V13）。

import { LIMITS } from './protocol.js';
import { changed, store } from './store.js';

const PITCH = 0.9;
const CANCEL_SETTLE_MS = 60;
const UNLOCK_TEXT = '。';
// 留住目前的語音物件：有些瀏覽器會把沒人參照的語音回收掉，念到一半就停
let current = null;

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

function build(text, volume) {
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'zh-TW';
  utterance.rate = LIMITS.NARRATION_RATE;
  utterance.pitch = PITCH;
  utterance.volume = volume;
  const voice = zhVoice();
  if (voice) {
    utterance.voice = voice;
    store.voice.name = voice.name;
  }
  return utterance;
}

/** 念一句。不支援或失敗都只是沒聲音，字幕照常（CODING_RULES E11）。 */
export function speak(text) {
  const synth = window.speechSynthesis;
  if (!synth) return false;
  try {
    const utterance = build(text, 1);
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

function isNarrator(server) {
  if (server?.host) return true;
  return Boolean(server?.me && server.narrator_id === server.me.id);
}

/** 收到 narrate 時呼叫：只有旁白主機或主持人手機發聲。 */
export function onNarrate(msg) {
  if (!msg.speak || !isNarrator(store.server)) return;
  // 主持人選了「我自己念」：繼續後的重念也只顯示字幕
  if (store.server.host && !store.ui.speakAloud) return;
  speak(msg.text);
}

/** 收到定向廣播：伺服器只送給被指定的手機，所以不看是不是旁白主機。音效（msg.sound）P8 才接。 */
export function onBroadcast(msg) {
  if (msg.speak) speak(msg.text);
}
