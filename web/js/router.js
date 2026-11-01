// 畫面由狀態決定（CODING_RULES V1）：重連、回前景、回上一步後都不會停在錯的畫面。
import { STEP } from './protocol.js';
import { loadTokens } from './session.js';

const NIGHT_ACTOR_SCREENS = { [STEP.WOLF]: 'S8', [STEP.SEER]: 'S9', [STEP.WITCH]: 'S10' };
const PUBLIC_SCREENS = {
  [STEP.DAWN]: 'S11',
  [STEP.HUNTER]: 'S12',
  [STEP.LAST_WORDS]: 'S22',
  [STEP.DAY_SPEAK]: 'S13',
  [STEP.SUSPECT_VOTE]: 'S14',
  [STEP.DEFENSE]: 'S13',
  [STEP.VOTE]: 'S14',
  [STEP.REVEAL]: 'S15',
};

/** @returns {string} 畫面代號 */
export function resolveScreen(store) {
  const { server, ui, health, ended } = store;
  if (ui.overlay) return ui.overlay;
  if (ended) return 'S25';
  const tokens = loadTokens();
  if (!server) {
    if (!health?.room) return 'S0';
    // 有 token 代表正在連線；無管理員模式的管理員還要自己加入，所以看加入頁
    const connecting = tokens.player || (tokens.admin && health.room.mode === 'god');
    return connecting ? 'S0' : 'S4';
  }
  if (server.phase === 'lobby') {
    if (!server.room) return 'S0';
    // 無管理員模式的管理員沒加入前也看大廳；只有上帝主持人進控制台
    return !server.me && server.is_admin && server.room.mode === 'god' ? 'S20' : 'S5';
  }
  if (server.step === STEP.END) return 'S18';
  if (server.host) return 'S20';
  return gameScreen(server);
}

function gameScreen(server) {
  const { step, me } = server;
  if (step === STEP.DEAL) return me ? 'S6' : 'S7';
  if (PUBLIC_SCREENS[step]) return PUBLIC_SCREENS[step];
  if (me && !me.alive) return 'S17';
  if (me?.is_actor && NIGHT_ACTOR_SCREENS[step]) return NIGHT_ACTOR_SCREENS[step];
  if (me?.wolf_pack && step === STEP.WOLF_END) return 'S8';
  return 'S7';
}
