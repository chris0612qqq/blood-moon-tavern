// 音效（ART 12）：錄音檔放 web/audio/，沒載到就用 Web Audio 即時合成（12.6）。
// 失敗或不支援都只是沒聲音，不影響遊戲（CODING_RULES E11）。
//
// audio/wolf_howl.wav：美國魚類及野生動物管理局錄的狼嚎（公有領域），取自 Wikimedia Commons
// 「File:Wolf howls.ogg」12.9–15.7 秒，濾掉低頻雜音與高頻嘶聲、前後淡入淡出。
// audio/rooster.wav：Wikimedia Commons「File:Medium rooster crowing.ogg」（alys，公有領域）2.75–4.97 秒，
// 只留長長的那一聲，後面兩小聲不要（使用者要求）。
// audio/win_village.wav：OpenGameArt「Just a random fanfare」（Spring Spring，CC0）前 8.6 秒、尾段淡出。
// audio/win_wolf.wav：OpenGameArt「String and piano horror stings」的 abyss.ogg（congusbongus，CC0）。
// audio/claw_swipe.wav、audio/bite.wav：Gravity Sound 錄製，CC BY 4.0（要標示出處），取自 Wikimedia Commons
// 「File:Sword Swipe (Gravity Sound).mp3」前 0.2 秒、「File:Big bite (Gravity Sound).wav」前 0.42 秒。
// audio/shield_clash.wav：同樣是 Gravity Sound（CC BY 4.0，Wikimedia Commons），
// 「File:Sword Clash (Gravity Sound).mp3」0.03–0.75 秒。守衛睜眼前的「鏘」（SPEC v4.44、v4.45）。
// 都轉成單聲道並把峰值調到 −1 dBFS（iPhone 舊版 Safari 不一定解得開 ogg，所以用 wav）。

import { WINNER } from './protocol.js';
import { load, save } from './storage.js';

const RECORDING_FILES = {
  howl: 'audio/wolf_howl.wav',
  rooster: 'audio/rooster.wav',
  win_village: 'audio/win_village.wav',
  win_wolf: 'audio/win_wolf.wav',
  slash: 'audio/claw_swipe.wav',
  bite: 'audio/bite.wav',
  shield: 'audio/shield_clash.wav',
};
const HOWL_S = 1.8;
// 守衛的「鏘」：伺服器預留 1.2 秒（server/balance.py SFX_SECONDS），錄音比較短也等滿再念
const GUARD_LEAD_MS = 1200;
/** 合成狼嚎加回音的長度。 */
const SYNTH_HOWL_MS = 2300;
const AFTER_RECORDING_MS = 300; // 錄音放完稍停一下再念旁白
const ECHO_S = 0.4;
const ECHO_FEEDBACK = 0.35;
const CLEANUP_MS = 5000;
// 原本比旁白低 4 dB（ART 12.2），使用者試聽後要再大聲三倍
const SFX_GAIN = 3 * 10 ** (-4 / 20);

// 下載逾時跟 net.js 一樣 8 秒（CODING_RULES E10、N7）；這裡不 import net.js，免得總覽頁也連伺服器
const FETCH_TIMEOUT_MS = 8000;

let context = null;
/** 已經解碼好的錄音；還沒載到或失敗就沒有這一項，改用合成的。 */
const recordings = {};
/** 要不要下載錄音：只有會出聲的旁白手機要，其他人省下約 1 MB 行動網路。 */
let wantRecordings = false;
let loading = null;

// iPhone 預設把 Web Audio 當「環境音」，側邊靜音鍵一開就沒聲音（旁白語音不受影響）；
// 改成「播放」類，像音樂一樣不理靜音鍵（Safari 17 起支援，舊版沒有就照舊）
try {
  if (navigator.audioSession) navigator.audioSession.type = 'playback';
} catch { /* 不支援就算了 */ }

/** 下載並解碼一段錄音；逾時、下載或解碼失敗就一直用合成的。 */
async function loadRecording(ac, name) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(RECORDING_FILES[name], { signal: controller.signal });
    if (!response.ok) return;
    const bytes = await response.arrayBuffer();
    // 舊版 Safari 的 decodeAudioData 只有回呼寫法
    recordings[name] = await new Promise((resolve, reject) => { ac.decodeAudioData(bytes, resolve, reject); });
  } catch { /* 用合成的 */ } finally {
    clearTimeout(timer);
  }
}

function startLoading(ac) {
  loading ??= Promise.all(Object.keys(RECORDING_FILES).map((name) => loadRecording(ac, name)));
}

/** 這支手機會念旁白：聲音一開就下載錄音（app.js 每次重畫告訴這裡，重複呼叫沒關係）。 */
export function preloadRecordings() {
  wantRecordings = true;
  if (context) startLoading(context);
}

/** 錄音都下載完（或失敗）時完成；還沒開始下載就立刻完成（測試、試聽用）。 */
export const recordingsReady = () => loading ?? Promise.resolve();

function audio() {
  if (!context) {
    const Context = window.AudioContext ?? window.webkitAudioContext;
    if (!Context) return null;
    context = new Context();
    if (wantRecordings) startLoading(context);
  }
  if (context.state === 'suspended') context.resume();
  return context;
}

let limiter = null;
/** 音效都接到這裡：放大三倍後錄音會超過上限，用限幅器壓住，免得破音。 */
function sfxOut(ac) {
  if (!limiter) {
    limiter = ac.createDynamicsCompressor();
    limiter.threshold.value = -3;
    limiter.knee.value = 0;
    limiter.ratio.value = 20;
    limiter.attack.value = 0.002;
    limiter.release.value = 0.1;
    limiter.connect(ac.destination);
  }
  return limiter;
}

// iOS 只在手指點擊當下允許打開聲音，所以第一次點擊就先開好
for (const name of ['touchend', 'click']) {
  document.addEventListener(name, () => { audio(); }, { capture: true, passive: true });
}

/** 狼嚎（ART 12.4）。回傳要等幾毫秒再念旁白；沒播出來回傳 0。 */
export function wolfHowl() {
  try {
    const ac = audio();
    if (!ac) return 0;
    if (recordings.howl) return playRecording(ac, recordings.howl);
    synthHowl(ac);
    return SYNTH_HOWL_MS;
  } catch {
    return 0;
  }
}

/** 音效的總音量節點，已接到限幅器。 */
function sfxGain(ac) {
  const gain = ac.createGain();
  gain.gain.value = SFX_GAIN;
  gain.connect(sfxOut(ac));
  return gain;
}

/** 放一段錄音，接到 out（預設新開一個音效音量）。回傳放完再稍停一下的毫秒數。 */
function playRecording(ac, buffer, { at = ac.currentTime, out = sfxGain(ac) } = {}) {
  const source = ac.createBufferSource();
  source.buffer = buffer;
  source.connect(out);
  source.start(at);
  return Math.round(buffer.duration * 1000) + AFTER_RECORDING_MS;
}

// 結算勝利音效：前奏先響，旁白念「好人／狼人獲勝」時壓低，讓字聽得清楚，之後放完
const WIN_LEAD_MS = 2500;
const WIN_DUCK = 0.35;
const WIN_DUCK_RAMP_S = 0.3;
const WOLF_STING_AT_S = 1.2; // 狼嚎響到一半，低沉弦樂進來

/** 勝利音效（ART 12.4）。錄音沒載到就合成：好人是明亮的號角琶音，狼人是狼嚎＋低沉和弦。 */
function victorySound(ac, at, { winner = null } = {}) {
  const isWolf = winner === WINNER.WOLF;
  const music = recordings[isWolf ? 'win_wolf' : 'win_village'];
  const out = ac.createGain();
  const duckAt = at + WIN_LEAD_MS / 1000;
  out.gain.setValueAtTime(SFX_GAIN, at);
  out.gain.setValueAtTime(SFX_GAIN, duckAt - WIN_DUCK_RAMP_S);
  out.gain.linearRampToValueAtTime(SFX_GAIN * WIN_DUCK, duckAt);
  out.connect(sfxOut(ac));
  if (isWolf) {
    if (recordings.howl) playRecording(ac, recordings.howl, { at, out });
    else synthHowl(ac, out);
  }
  const musicAt = isWolf ? at + WOLF_STING_AT_S : at;
  if (music) playRecording(ac, music, { at: musicAt, out });
  else (isWolf ? synthWolfChord : synthFanfare)(ac, musicAt, out);
  return WIN_LEAD_MS;
}

/** 合成好人勝利：C 大調號角琶音往上，最後一個和弦拉長。 */
function synthFanfare(ac, at, out) {
  [523, 659, 784].forEach((freq, i) => {
    tone(ac, { freq, type: 'sawtooth', at: at + i * 0.18, decay: 0.3, peak: 0.12, out });
  });
  for (const freq of [523, 659, 784, 1047]) {
    tone(ac, { freq, type: 'sawtooth', at: at + 0.6, decay: 2.4, peak: 0.08, attack: 0.05, out });
  }
}

/** 合成狼人勝利：低音小三和弦慢慢浮出來。 */
function synthWolfChord(ac, at, out) {
  for (const freq of [55, 65.4, 82.4]) {
    tone(ac, { freq, type: 'sawtooth', at, decay: 3, peak: 0.2, attack: 0.6, out });
  }
}

/** 合成狼嚎：兩支微微走音的鋸齒波，300→700→450 Hz 滑音、尾段加顫音，經低通濾波，最後回音。 */
function synthHowl(ac, dest = sfxGain(ac)) {
  const t0 = ac.currentTime + 0.05;
  const end = t0 + HOWL_S;

  const out = ac.createGain();
  const echo = ac.createDelay(1);
  echo.delayTime.value = ECHO_S;
  const feedback = ac.createGain();
  feedback.gain.value = ECHO_FEEDBACK;
  out.connect(dest);
  out.connect(echo);
  echo.connect(feedback);
  feedback.connect(echo);
  feedback.connect(dest);

  const envelope = ac.createGain();
  envelope.gain.setValueAtTime(0.0001, t0);
  envelope.gain.exponentialRampToValueAtTime(0.5, t0 + 0.35);
  envelope.gain.setValueAtTime(0.5, t0 + 1.2);
  envelope.gain.exponentialRampToValueAtTime(0.0001, end);
  envelope.connect(out);

  const filter = ac.createBiquadFilter();
  filter.type = 'lowpass';
  filter.Q.value = 4;
  filter.frequency.setValueAtTime(900, t0);
  filter.frequency.linearRampToValueAtTime(1800, t0 + 0.6);
  filter.frequency.linearRampToValueAtTime(800, end);
  filter.connect(envelope);

  const vibrato = ac.createOscillator();
  vibrato.frequency.value = 5.5;
  const depth = ac.createGain();
  depth.gain.setValueAtTime(0, t0);
  depth.gain.linearRampToValueAtTime(12, t0 + 1.0);
  vibrato.connect(depth);
  vibrato.start(t0);
  vibrato.stop(end);

  for (const detune of [-8, 8]) {
    const osc = ac.createOscillator();
    osc.type = 'sawtooth';
    osc.detune.value = detune;
    osc.frequency.setValueAtTime(300, t0);
    osc.frequency.exponentialRampToValueAtTime(700, t0 + 0.6);
    osc.frequency.setValueAtTime(700, t0 + 1.0);
    osc.frequency.exponentialRampToValueAtTime(450, end);
    depth.connect(osc.frequency);
    osc.connect(filter);
    osc.start(t0);
    osc.stop(end + 0.05);
  }
  // 回音是個迴圈，聲音停了也不會自己斷開，要手動拆掉
  setTimeout(() => {
    out.disconnect();
    feedback.disconnect();
  }, CLEANUP_MS);
}

// ── 其他流程音效（ART 12.4、12.6），全部即時合成 ──────────────────────────

let noise = null;
/** 一秒白噪音，鼓聲、骰子、冒泡、風聲共用。 */
function noiseBuffer(ac) {
  if (!noise) {
    noise = ac.createBuffer(1, ac.sampleRate, ac.sampleRate);
    const data = noise.getChannelData(0);
    for (let i = 0; i < data.length; i += 1) data[i] = Math.random() * 2 - 1;
  }
  return noise;
}

/** 一個音：起音很快，之後指數衰減到幾乎無聲。給了 out 就接到它（它已經含音效音量）。 */
function tone(ac, { freq, type = 'sine', at, decay, peak = 0.3, attack = 0.005, out = null }) {
  const osc = ac.createOscillator();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, at);
  const gain = ac.createGain();
  gain.gain.setValueAtTime(0.0001, at);
  gain.gain.exponentialRampToValueAtTime(out ? peak : peak * SFX_GAIN, at + attack);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + attack + decay);
  osc.connect(gain);
  gain.connect(out ?? sfxOut(ac));
  osc.start(at);
  osc.stop(at + attack + decay + 0.05);
  return osc;
}

/** 一小段濾過的噪音：敲擊、骰子、泡泡、風。 */
function burst(ac, { at, dur, freq, q = 1, type = 'bandpass', peak = 0.4, attack = 0.002 }) {
  const source = ac.createBufferSource();
  source.buffer = noiseBuffer(ac);
  const filter = ac.createBiquadFilter();
  filter.type = type;
  filter.frequency.value = freq;
  filter.Q.value = q;
  const gain = ac.createGain();
  gain.gain.setValueAtTime(0.0001, at);
  gain.gain.exponentialRampToValueAtTime(peak * SFX_GAIN, at + attack);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + dur);
  source.connect(filter);
  filter.connect(gain);
  gain.connect(sfxOut(ac));
  source.start(at, Math.random() * 0.5, dur + 0.05);
}

/** 鐘：基音加兩個泛音，高的衰減得快（ART 12.6）。 */
function bell(ac, at, base, decay) {
  tone(ac, { freq: base, at, decay, peak: 0.45 });
  tone(ac, { freq: base * 2.01, at, decay: decay * 0.6, peak: 0.25 });
  tone(ac, { freq: base * 3.03, at, decay: decay * 0.35, peak: 0.15 });
}

const SOUNDS = {
  // 天黑請閉眼之前：一聲低沉的鐘＋夜風灌入
  night_start(ac, at) {
    bell(ac, at, 110, 2.4);
    burst(ac, { at: at + 0.2, dur: 1.6, freq: 500, q: 0.7, type: 'lowpass', peak: 0.12, attack: 0.8 });
    return 2200;
  },
  // 狼人請閉眼之前：低吼漸弱
  wolf_close(ac, at) {
    burst(ac, { at, dur: 1.1, freq: 160, q: 3, type: 'lowpass', peak: 0.6, attack: 0.15 });
    const growl = tone(ac, { freq: 72, type: 'sawtooth', at, decay: 1.0, peak: 0.18, attack: 0.15 });
    growl.frequency.linearRampToValueAtTime(58, at + 1.1);
    return 1300;
  },
  // 守衛請睜眼之前：盾牌「鏘」一聲。有錄音用錄音（SPEC v4.44），沒有就合成：撞擊雜音＋不和諧的金屬泛音
  // take 是美術總覽試聽用：'synth' 放合成版來比較
  guard_open(ac, at, { take = 'clash' } = {}) {
    if (take !== 'synth' && recordings.shield) {
      playRecording(ac, recordings.shield, { at });
      return GUARD_LEAD_MS;
    }
    burst(ac, { at, dur: 0.08, freq: 3000, q: 1.2, peak: 0.6 });
    [420, 1093, 1785].forEach((freq, i) => {
      tone(ac, { freq, at, decay: 1.0 - i * 0.25, peak: 0.28 - i * 0.07 });
    });
    return 1200;
  },
  // 預言家請睜眼之前：水晶風鈴由低到高閃爍
  seer_open(ac, at) {
    [1200, 1500, 1800, 2250, 2700, 3000].forEach((freq, i) => {
      tone(ac, { freq, at: at + i * 0.07 + Math.random() * 0.03, decay: 0.7, peak: 0.16 });
    });
    return 1200;
  },
  // 女巫請睜眼之前：鍋子咕嘟冒泡＋玻璃瓶「叮」
  witch_open(ac, at) {
    for (let i = 0; i < 9; i += 1) {
      burst(ac, { at: at + i * 0.11 + Math.random() * 0.05, dur: 0.07, freq: 300 + Math.random() * 600, q: 8, peak: 0.7 });
    }
    tone(ac, { freq: 2637, at: at + 1.0, decay: 0.5, peak: 0.2 });
    return 1500;
  },
  // 天亮請睜眼之前：一聲雞鳴。錄音沒載到才用合成的（方波階梯滑音＋顫音）
  dawn(ac, at) {
    if (recordings.rooster) return playRecording(ac, recordings.rooster, { at });
    const osc = ac.createOscillator();
    osc.type = 'square';
    osc.frequency.setValueAtTime(600, at);
    osc.frequency.linearRampToValueAtTime(1100, at + 0.25);
    osc.frequency.setValueAtTime(1100, at + 0.7);
    osc.frequency.linearRampToValueAtTime(800, at + 1.1);
    const wobble = ac.createOscillator();
    wobble.frequency.value = 18;
    const depth = ac.createGain();
    depth.gain.value = 35;
    wobble.connect(depth);
    depth.connect(osc.frequency);
    const filter = ac.createBiquadFilter();
    filter.type = 'bandpass';
    filter.frequency.value = 1200;
    filter.Q.value = 1.2;
    const gain = ac.createGain();
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(0.2 * SFX_GAIN, at + 0.05);
    gain.gain.setValueAtTime(0.2 * SFX_GAIN, at + 0.9);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + 1.15);
    osc.connect(filter);
    filter.connect(gain);
    gain.connect(sfxOut(ac));
    for (const node of [osc, wobble]) {
      node.start(at);
      node.stop(at + 1.2);
    }
    return 1500;
  },
  // 平安夜：柔和豎琴往上撥
  peaceful(ac, at) {
    [523, 659, 784, 1047, 1319].forEach((freq, i) => {
      tone(ac, { freq, type: 'triangle', at: at + i * 0.12, decay: 1.1, peak: 0.22 });
    });
    return 1300;
  },
  // 公布死者：寺廟喪鐘低鳴；有人被狼咬死，就在他那列翻開、爪痕劃下時放咬的聲音（SPEC v4.37）
  deaths(ac, at, { bites = [] } = {}) {
    if (!bites.length) bell(ac, at, 98, 2.6);
    for (const order of bites) biteSound(ac, at + order * REVEAL_EACH_S + BITE_AT_S);
    return 1800;
  },
  // 獵人請發動技能：弓弦慢慢拉緊的吱嘎聲
  hunter(ac, at) {
    for (let i = 0; i < 6; i += 1) {
      burst(ac, { at: at + i * 0.13, dur: 0.06, freq: 900 + i * 120, q: 12, peak: 0.5 });
    }
    return 1000;
  },
  // 請投票：驚堂木「啪」＋低頻一下
  suspect_vote(ac, at) {
    burst(ac, { at, dur: 0.06, freq: 2000, q: 0.8, peak: 0.9 });
    tone(ac, { freq: 120, at, decay: 0.25, peak: 0.5 });
    return 500;
  },
};
SOUNDS.vote = SOUNDS.suspect_vote;

// 和畫面上死者一列列翻開對齊：css/tokens.css --dur-reveal-each、--dur-bite-at
const REVEAL_EACH_S = 1.5;
const BITE_AT_S = 0.6;
const BITE_CRUNCH_S = 0.12; // 爪子揮過去，緊接著咬下去

/** 咬死：爪子劃過的破風聲＋一口咬下的悶響。有錄音用錄音，沒有就合成。 */
function biteSound(ac, at) {
  if (recordings.slash) playRecording(ac, recordings.slash, { at });
  else burst(ac, { at, dur: 0.18, freq: 2400, q: 0.7, type: 'highpass', peak: 0.5, attack: 0.04 });
  const crunch = at + BITE_CRUNCH_S;
  if (recordings.bite) {
    playRecording(ac, recordings.bite, { at: crunch });
    return;
  }
  tone(ac, { freq: 85, at: crunch, decay: 0.25, peak: 0.6 });
  for (let i = 0; i < 4; i += 1) {
    burst(ac, { at: crunch + i * 0.03, dur: 0.04, freq: 1200 + Math.random() * 1500, q: 3, peak: 0.7 });
  }
}
// 結算：依勝方放不同的音樂（SPEC v4.36）
SOUNDS.win = victorySound;

// 伺服器有替這幾句預留音效時間（server/balance.py SFX_SECONDS）：放完才念。
// 結算（win）沒有預留，但它是最後一句，後面沒有句子會打斷，所以也等前奏。
// 其他句子沒有預留，等的話下一句會來打斷，所以音效和旁白一起出來。
const LEAD_LINES = new Set(['night_start', 'guard_open', 'wolf_open', 'seer_open', 'witch_open', 'dawn', 'win']);

/**
 * 旁白念這一句之前的音效（ART 12.4）。回傳要等幾毫秒再念；不用等或沒播出來回傳 0。
 * extra 是這句需要的狀態：結算 {winner}、公布死者 {bites}（被咬死的人在死者名單第幾個）。
 */
export function openingSound(lineId, extra = {}) {
  if (lineId === 'wolf_open') return wolfHowl();
  const play = SOUNDS[lineId];
  if (!play) return 0;
  try {
    const ac = audio();
    if (!ac || ac.state !== 'running') return 0;
    const ms = play(ac, ac.currentTime + 0.03, extra);
    return LEAD_LINES.has(lineId) ? ms : 0;
  } catch {
    return 0;
  }
}

/** 發牌：二十面骰在木桌上滾，越滾越慢，最後「喀」一聲停下（ART 12.4 sfx_deal_roll）。 */
export function diceRoll() {
  try {
    const ac = audio();
    if (!ac || ac.state !== 'running') return;
    const at = ac.currentTime + 0.3; // 配合畫面上骰子落下
    let t = 0;
    for (let i = 0; i < 7; i += 1) {
      burst(ac, { at: at + t, dur: 0.035, freq: 2200 + Math.random() * 1200, q: 4, peak: 0.55 });
      t += 0.07 + i * 0.03;
    }
    burst(ac, { at: at + t + 0.05, dur: 0.05, freq: 1500, q: 3, peak: 0.9 });
  } catch { /* 沒聲音不影響遊戲 */ }
}

/** 投票揭曉：每一票一枚銅幣落桌，間隔和畫面上的銅幣一樣 0.4 秒（ART 12.4 sfx_vote_reveal）。 */
export function coinDrops(count) {
  try {
    const ac = audio();
    if (!ac || ac.state !== 'running') return;
    for (let i = 0; i < count; i += 1) {
      const at = ac.currentTime + 0.35 + i * 0.4;
      tone(ac, { freq: 2600 + Math.random() * 300, type: 'square', at, decay: 0.05, peak: 0.08 });
      tone(ac, { freq: 3900, at, decay: 0.25, peak: 0.1 });
    }
  } catch { /* 沒聲音不影響遊戲 */ }
}

// ── 個人設定：每支手機自己決定要不要環境音、介面音效（ART 12.3、12.5「可關」）──────

export const soundPrefs = {
  get ambience() { return load('sound_ambience', true); },
  set ambience(on) { save('sound_ambience', on); },
  get ui() { return load('sound_ui', true); },
  set ui(on) { save('sound_ui', on); },
};

let night = false;
/** 夜晚介面音效對所有手機一律靜音，只留畫面回饋（ART 12.5、SPEC A8.2）。app.js 每次重畫告訴這裡。 */
export function setNight(value) {
  night = value;
}

const UI_SOUNDS = {
  // 選中格子：木牌翻起的輕響
  select(ac, at) { burst(ac, { at, dur: 0.04, freq: 1800, q: 5, peak: 0.25 }); },
  // 送出成功：蠟封蓋章「啵」＋小鈴
  success(ac, at) {
    tone(ac, { freq: 180, at, decay: 0.08, peak: 0.25 });
    tone(ac, { freq: 1568, at: at + 0.06, decay: 0.35, peak: 0.1 });
  },
  // 送出失敗：低沉木頭「咚」＋短促否定音
  error(ac, at) {
    tone(ac, { freq: 140, at, decay: 0.18, peak: 0.3 });
    tone(ac, { freq: 220, type: 'square', at: at + 0.12, decay: 0.12, peak: 0.05 });
  },
  // 短提示：紙卷展開「沙」
  toast(ac, at) { burst(ac, { at, dur: 0.18, freq: 3500, q: 0.6, type: 'highpass', peak: 0.12, attack: 0.05 }); },
  // 對話框：較長的卷軸展開聲
  dialog(ac, at) { burst(ac, { at, dur: 0.35, freq: 2500, q: 0.6, type: 'highpass', peak: 0.12, attack: 0.12 }); },
  // 聊天送出：羽毛筆劃過紙面
  chat(ac, at) { burst(ac, { at, dur: 0.22, freq: 5000, q: 1.5, peak: 0.12, attack: 0.08 }); },
  // 倒數剩 10 秒：沙漏翻轉（木頭輕碰＋沙子流）
  countdown(ac, at) {
    burst(ac, { at, dur: 0.05, freq: 900, q: 4, peak: 0.35 });
    burst(ac, { at: at + 0.08, dur: 0.6, freq: 6000, q: 0.5, type: 'highpass', peak: 0.05, attack: 0.1 });
  },
  // 暫停：大鐘停擺「鏗」
  pause(ac, at) { bell(ac, at, 330, 0.9); },
  // 輪到你發言：清脆小銅鈴兩下；下一個是你：一下、較輕
  turn(ac, at) {
    tone(ac, { freq: 2093, at, decay: 0.4, peak: 0.18 });
    tone(ac, { freq: 2093, at: at + 0.22, decay: 0.5, peak: 0.18 });
  },
  next(ac, at) { tone(ac, { freq: 2093, at, decay: 0.35, peak: 0.1 }); },
  // 千面狼換臉（只在他手機、只在白天）：瓷面具碎裂「喀啦」＋布料翻動
  swap(ac, at) {
    for (let i = 0; i < 6; i += 1) {
      burst(ac, { at: at + i * 0.035 + Math.random() * 0.02, dur: 0.03, freq: 3000 + Math.random() * 2500, q: 6, peak: 0.6 });
    }
    burst(ac, { at: at + 0.3, dur: 0.5, freq: 900, q: 0.8, peak: 0.2, attack: 0.15 });
  },
};

/** 介面與個人提醒音效。夜晚、或這支手機關掉介面音效時不出聲。 */
export function uiSound(name) {
  if (night || !soundPrefs.ui) return;
  const play = UI_SOUNDS[name];
  try {
    const ac = context; // 還沒點過畫面就不要開聲音（iOS 也不允許）
    if (!play || !ac || ac.state !== 'running') return;
    play(ac, ac.currentTime + 0.01);
  } catch { /* 沒聲音不影響遊戲 */ }
}

// ── 環境音（ART 12.3）：循環的底噪＋不定時的點綴，比旁白低 18 dB，旁白念的時候再壓低 ──────

const AMB_GAIN = 0.07;
const AMB_DUCK = 0.3; // 旁白念的時候環境音剩三成（約 −10 dB，ART 12.2）
const AMB_TICK_MS = 250;
let ambience = null; // { kind, bed, gain, timer, next }

/** 一直循環的濾波噪音：火堆的低鳴、夜風、竹林風。 */
function bedOf(ac, kind) {
  const source = ac.createBufferSource();
  source.buffer = noiseBuffer(ac);
  source.loop = true;
  const filter = ac.createBiquadFilter();
  filter.type = kind === 'tavern' ? 'lowpass' : 'bandpass';
  filter.frequency.value = { tavern: 220, night: 420, day: 900 }[kind];
  filter.Q.value = kind === 'tavern' ? 0.7 : 0.9;
  const gain = ac.createGain();
  gain.gain.value = 0;
  source.connect(filter);
  filter.connect(gain);
  gain.connect(ac.destination);
  source.start();
  // 風聲要一陣一陣：用很慢的低頻震盪推動音量
  let gust = null;
  if (kind !== 'tavern') {
    gust = ac.createOscillator();
    gust.frequency.value = 0.13;
    const depth = ac.createGain();
    depth.gain.value = AMB_GAIN * 0.4;
    gust.connect(depth);
    depth.connect(gain.gain);
    gust.start();
  }
  return { source, gain, gust };
}

/** 不定時的點綴：柴火劈啪與酒杯、貓頭鷹、鳥叫。回傳下一次要等幾秒。 */
const ACCENTS = {
  tavern(ac, at) {
    if (Math.random() < 0.85) {
      for (let i = 0; i < 1 + Math.floor(Math.random() * 3); i += 1) {
        burst(ac, { at: at + i * 0.06, dur: 0.02, freq: 2500 + Math.random() * 2000, q: 2, peak: 0.05 });
      }
      return 0.4 + Math.random() * 1.2;
    }
    tone(ac, { freq: 2794, at, decay: 0.5, peak: 0.03 }); // 遠處酒杯碰一下
    tone(ac, { freq: 3322, at: at + 0.02, decay: 0.4, peak: 0.02 });
    return 3 + Math.random() * 4;
  },
  night(ac, at) {
    // 遠處貓頭鷹「咕—咕」
    tone(ac, { freq: 410, at, decay: 0.35, peak: 0.05, attack: 0.06 });
    tone(ac, { freq: 380, at: at + 0.55, decay: 0.5, peak: 0.05, attack: 0.06 });
    return 14 + Math.random() * 12;
  },
  day(ac, at) {
    const chirps = 2 + Math.floor(Math.random() * 3);
    for (let i = 0; i < chirps; i += 1) {
      const osc = tone(ac, { freq: 2600 + Math.random() * 900, at: at + i * 0.14, decay: 0.09, peak: 0.03 });
      osc.frequency.exponentialRampToValueAtTime(3800 + Math.random() * 600, at + i * 0.14 + 0.08);
    }
    return 4 + Math.random() * 6;
  },
};

function stopAmbience() {
  if (!ambience) return;
  clearInterval(ambience.timer);
  const { bed } = ambience;
  try {
    const ac = context;
    bed.gain.gain.setTargetAtTime(0, ac.currentTime, 0.3);
    setTimeout(() => {
      bed.source.stop();
      bed.gust?.stop();
    }, 1500);
  } catch { /* 已經停了 */ }
  ambience = null;
}

/** 目前在放哪一種環境音（測試與設定頁用）。 */
export const ambienceKind = () => ambience?.kind ?? null;

/** 切換環境音：'tavern' 大廳與結算、'night' 夜晚、'day' 白天，null 停止。同一種重複呼叫不重開。 */
export function setAmbience(kind) {
  const want = kind && soundPrefs.ambience ? kind : null;
  if ((ambience?.kind ?? null) === want) return;
  stopAmbience();
  if (!want) return;
  ambience = { kind: want, bed: null, timer: null, next: 0 };
  const state = ambience;
  state.timer = setInterval(() => {
    const ac = context;
    if (!ac || ac.state !== 'running') return; // 還沒點過畫面，等聲音開了才開始
    try {
      if (!state.bed) state.bed = bedOf(ac, want);
      const target = AMB_GAIN * (window.speechSynthesis?.speaking ? AMB_DUCK : 1);
      state.bed.gain.gain.setTargetAtTime(target, ac.currentTime, 0.25);
      if (ac.currentTime >= state.next) {
        const at = ac.currentTime + 0.05;
        state.next = at + ACCENTS[want](ac, at);
      }
    } catch { /* 沒聲音不影響遊戲 */ }
  }, AMB_TICK_MS);
}
