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
// 角色開場音效比旁白低 4 dB（ART 12.2）
const SFX_GAIN = 10 ** (-4 / 20);

let context = null;
let howlRecording = null;

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
  gain.connect(ac.destination);
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
  out.connect(ac.destination);
  out.connect(echo);
  echo.connect(feedback);
  feedback.connect(echo);
  feedback.connect(ac.destination);

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
