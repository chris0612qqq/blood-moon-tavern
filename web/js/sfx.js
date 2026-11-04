// 音效（ART 12）：錄音檔放 web/audio/，沒載到就用 Web Audio 即時合成（12.6）。
// 失敗或不支援都只是沒聲音，不影響遊戲（CODING_RULES E11）。
//
// audio/wolf_howl.wav：美國魚類及野生動物管理局錄的狼嚎（公有領域），取自 Wikimedia Commons
// 「File:Wolf howls.ogg」12.9–15.7 秒，濾掉低頻雜音與高頻嘶聲、前後淡入淡出。

const HOWL_FILE = 'audio/wolf_howl.wav';
const HOWL_S = 1.8;
/** 合成狼嚎加回音的長度。 */
const SYNTH_HOWL_MS = 2300;
const AFTER_RECORDING_MS = 300; // 錄音放完稍停一下再念旁白
const ECHO_S = 0.4;
const ECHO_FEEDBACK = 0.35;
const CLEANUP_MS = 5000;
// 原本比旁白低 4 dB（ART 12.2），使用者試聽後要再大聲三倍
const SFX_GAIN = 3 * 10 ** (-4 / 20);

let context = null;
let howlRecording = null;

// iPhone 預設把 Web Audio 當「環境音」，側邊靜音鍵一開就沒聲音（旁白語音不受影響）；
// 改成「播放」類，像音樂一樣不理靜音鍵（Safari 17 起支援，舊版沒有就照舊）
try {
  if (navigator.audioSession) navigator.audioSession.type = 'playback';
} catch { /* 不支援就算了 */ }

/** 第一次開聲音時順便下載錄音；下載或解碼失敗就一直用合成的。 */
async function loadHowl(ac) {
  try {
    const response = await fetch(HOWL_FILE);
    if (!response.ok) return;
    const bytes = await response.arrayBuffer();
    // 舊版 Safari 的 decodeAudioData 只有回呼寫法
    howlRecording = await new Promise((resolve, reject) => { ac.decodeAudioData(bytes, resolve, reject); });
  } catch {
    howlRecording = null;
  }
}

function audio() {
  if (!context) {
    const Context = window.AudioContext ?? window.webkitAudioContext;
    if (!Context) return null;
    context = new Context();
    loadHowl(context);
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
    if (howlRecording) return playRecording(ac, howlRecording);
    synthHowl(ac);
    return SYNTH_HOWL_MS;
  } catch {
    return 0;
  }
}

function playRecording(ac, buffer) {
  const source = ac.createBufferSource();
  source.buffer = buffer;
  const gain = ac.createGain();
  gain.gain.value = SFX_GAIN;
  source.connect(gain);
  gain.connect(sfxOut(ac));
  source.start();
  return Math.round(buffer.duration * 1000) + AFTER_RECORDING_MS;
}

/** 合成狼嚎：兩支微微走音的鋸齒波，300→700→450 Hz 滑音、尾段加顫音，經低通濾波，最後回音。 */
function synthHowl(ac) {
  const t0 = ac.currentTime + 0.05;
  const end = t0 + HOWL_S;

  const out = ac.createGain();
  out.gain.value = SFX_GAIN;
  const echo = ac.createDelay(1);
  echo.delayTime.value = ECHO_S;
  const feedback = ac.createGain();
  feedback.gain.value = ECHO_FEEDBACK;
  const master = sfxOut(ac);
  out.connect(master);
  out.connect(echo);
  echo.connect(feedback);
  feedback.connect(echo);
  feedback.connect(master);

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

/** 一個音：起音很快，之後指數衰減到幾乎無聲。 */
function tone(ac, { freq, type = 'sine', at, decay, peak = 0.3, attack = 0.005 }) {
  const osc = ac.createOscillator();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, at);
  const gain = ac.createGain();
  gain.gain.setValueAtTime(0.0001, at);
  gain.gain.exponentialRampToValueAtTime(peak * SFX_GAIN, at + attack);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + attack + decay);
  osc.connect(gain);
  gain.connect(sfxOut(ac));
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
  // 天亮請睜眼之前：一聲雞鳴（方波階梯滑音＋顫音）
  dawn(ac, at) {
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
  // 公布死者：寺廟喪鐘低鳴
  deaths(ac, at) {
    bell(ac, at, 98, 2.6);
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

// 伺服器有替這幾句預留音效時間（server/balance.py SFX_SECONDS）：放完才念。
// 其他句子沒有預留，等的話下一句會來打斷，所以音效和旁白一起出來。
const LEAD_LINES = new Set(['night_start', 'wolf_open', 'seer_open', 'witch_open', 'dawn']);

/** 旁白念這一句之前的音效（ART 12.4）。回傳要等幾毫秒再念；不用等或沒播出來回傳 0。 */
export function openingSound(lineId) {
  if (lineId === 'wolf_open') return wolfHowl();
  const play = SOUNDS[lineId];
  if (!play) return 0;
  try {
    const ac = audio();
    if (!ac || ac.state !== 'running') return 0;
    const ms = play(ac, ac.currentTime + 0.03);
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
