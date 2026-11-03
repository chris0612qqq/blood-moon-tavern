// 音效（ART 12）：內建版本用 Web Audio 即時合成（12.6），不用下載、沒有版權問題。
// 失敗或不支援都只是沒聲音，不影響遊戲（CODING_RULES E11）。

const HOWL_S = 1.8;
/** 狼嚎加回音的長度：旁白等這麼久再念（ART 12.2：開場音效播完才念）。 */
export const HOWL_MS = 2300;
const ECHO_S = 0.4;
const ECHO_FEEDBACK = 0.35;
const CLEANUP_MS = 5000;
// 角色開場音效比旁白低 4 dB（ART 12.2）
const SFX_GAIN = 10 ** (-4 / 20);

let context = null;

function audio() {
  if (!context) {
    const Context = window.AudioContext ?? window.webkitAudioContext;
    if (!Context) return null;
    context = new Context();
  }
  if (context.state === 'suspended') context.resume();
  return context;
}

// iOS 只在手指點擊當下允許打開聲音，所以第一次點擊就先開好
for (const name of ['touchend', 'click']) {
  document.addEventListener(name, () => { audio(); }, { capture: true, passive: true });
}

/** 狼嚎：兩支微微走音的鋸齒波，300→700→450 Hz 滑音、尾段加顫音，經低通濾波，最後回音。 */
export function wolfHowl() {
  try {
    const ac = audio();
    if (!ac) return false;
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
    return true;
  } catch {
    return false;
  }
}
