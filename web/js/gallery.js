// 美術總覽頁（DEV_PLAN P8）：把內建向量美術全部排在一頁，不用開一局就能在手機上看。不連伺服器。
import { h, render } from './dom.js';
import { roleName } from './strings.js';
import {
  coin, d20Crest, dawnRise, guardShield, hunterBow, roleEmblem, seerOrb, snuffedCandle, victory, witchBrew,
} from './ui/art.js';
import { openingSound, preloadRecordings } from './sfx.js';
import { s11 } from './screens/day.js';

// 總覽頁可以試聽錄音，所以也要下載
preloadRecordings();

const DAWN_DEMO = {
  round_no: 1,
  announced: true,
  history: [{ round_no: 1, deaths: ['p1', 'p2'], causes: { p1: 'bite', p2: 'poison' } }],
  players: [
    { id: 'p1', name: '小美', alive: false, death_cause: 'bite' },
    { id: 'p2', name: '阿志', alive: false, death_cause: 'poison', public_role: 'wolf' },
  ],
};

const ROLES = ['wolf', 'faceless', 'villager', 'seer', 'witch', 'guard', 'hunter'];

const scene = (title, ...art) => h('section', { class: 'gallery__scene' }, h('h2', {}, title), art);

render(document.getElementById('app'), h('div', { class: 'main' },
  h('h1', { class: 'center' }, '美術總覽'),
  scene('角色徽章',
    h('div', { class: 'gallery__roles' }, ROLES.map((role) => h('div', { class: 'gallery__role' },
      roleEmblem(role, 64), h('div', {}, roleName(role))))),
    h('p', { class: 'center' }, ROLES.map((role) => h('span', { class: 'badge' }, roleEmblem(role), roleName(role))))),
  scene('卡背', h('div', { class: 'card' }, d20Crest(), '長按看角色')),
  scene('預言家：查驗中', seerOrb()),
  scene('預言家：查到狼人', seerOrb('wolf')),
  scene('預言家：查到好人', seerOrb('good')),
  scene('女巫：兩瓶都在', witchBrew(false, false)),
  scene('女巫：解藥用過', witchBrew(true, false)),
  scene('女巫：救人（倒紅藥）', witchBrew(true, false, 'save')),
  scene('女巫：下毒（倒綠藥）', witchBrew(false, true, 'poison')),
  scene('守衛：選人中', guardShield()),
  scene('守衛：已守護（盾牌亮起）', guardShield(true)),
  scene('天亮', dawnRise()),
  scene('天亮：平安夜', dawnRise(true)),
  scene('獵人', hunterBow()),
  scene('獵人：開弓', hunterBow('shot')),
  scene('獵人：收弓', hunterBow('holster')),
  scene('出局', snuffedCandle()),
  scene('投票揭曉', h('div', { class: 'coins' }, [0, 1, 2, 3].map(coin))),
  scene('千面狼面板：換臉（點一下重播）',
    h('div', {
      class: 'panel disguise disguise--swap',
      onclick: (e) => {
        const panel = e.currentTarget;
        panel.classList.remove('disguise--swap');
        requestAnimationFrame(() => panel.classList.add('disguise--swap'));
      },
    }, roleEmblem('faceless', 28), h('span', { class: 'disguise__text' }, '本期假扮：小明，剩 2 回合'))),
  // 天亮公布：小美被咬死、阿志被毒死（SPEC v4.37）。點一下重播動畫並放音效
  scene('天亮：被狼咬死（點一下重播）', h('div', { testid: 'dawn-demo', onclick: (e) => {
    const box = e.currentTarget;
    box.replaceChildren();
    render(box, s11(DAWN_DEMO));
    openingSound('deaths', { bites: [0] });
  } }, s11(DAWN_DEMO))),
  scene('結算：好人勝', victory('village')),
  scene('結算：狼人勝', victory('wolf')),
  // 錄音在第一次點畫面時才下載，所以按第二下才會是錄音版
  scene('試聽錄音（第一下載入，再按一次）',
    h('p', { class: 'center' }, [
      ['雞鳴', () => openingSound('dawn')],
      ['好人勝', () => openingSound('win', { winner: 'village' })],
      ['狼人勝', () => openingSound('win', { winner: 'wolf' })],
      ['狼嚎', () => openingSound('wolf_open')],
      ['咬死', () => openingSound('deaths', { bites: [0] })],
      ['守衛：刀劍鏘', () => openingSound('guard_open', { take: 'clash' })],
      ['守衛：金屬敲', () => openingSound('guard_open', { take: 'hit' })],
      ['守衛：合成', () => openingSound('guard_open', { take: 'synth' })],
    ].map(([label, play], i) => h('button', {
      class: 'btn btn--secondary btn--small', testid: `listen-${i}`, onclick: play,
    }, label))))));
