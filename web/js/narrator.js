// 旁白發聲。夜晚大家閉眼要靠聲音，灰盒試玩就需要，所以先做最小版；完整版在 P6。
// 不等 onend：iOS 常不觸發，流程也不依賴它（CODING_RULES E15）。

import { store } from './store.js';

const RATE = 0.9;
const PITCH = 0.9;
let unlocked = false;

function zhVoice() {
  const voices = window.speechSynthesis?.getVoices() ?? [];
  for (const lang of ['zh-TW', 'zh-HK', 'zh-CN']) {
    const match = voices.find((v) => v.lang.replace('_', '-') === lang);
    if (match) return match;
  }
  return null;
}

/** 念一句。不支援或失敗都只是沒聲音，字幕照常（CODING_RULES E11）。 */
export function speak(text) {
  try {
    if (!window.speechSynthesis) return false;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'zh-TW';
    utterance.rate = RATE;
    utterance.pitch = PITCH;
    const voice = zhVoice();
    if (voice) utterance.voice = voice;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
    return true;
  } catch {
    return false;
  }
}

/** iOS 要使用者點一下才能發聲。 */
export function unlockAudio(testText) {
  unlocked = speak(testText);
  store.audioUnlocked = unlocked;
  return unlocked;
}

function isNarrator(server) {
  if (server?.host) return true;
  return Boolean(server?.me && server.narrator_id === server.me.id);
}

/** 收到 narrate 時呼叫：只有旁白主機或主持人手機發聲。 */
export function onNarrate(msg) {
  if (msg.speak && isNarrator(store.server)) speak(msg.text);
}
