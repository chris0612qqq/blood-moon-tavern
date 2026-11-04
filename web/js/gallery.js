// 美術總覽頁（DEV_PLAN P8）：把內建向量美術全部排在一頁，不用開一局就能在手機上看。不連伺服器。
import { h, render } from './dom.js';
import { roleName } from './strings.js';
import {
  coin, d20Crest, dawnRise, hunterBow, roleEmblem, seerOrb, snuffedCandle, victory, witchBrew,
} from './ui/art.js';

const ROLES = ['wolf', 'faceless', 'villager', 'seer', 'witch', 'hunter'];

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
  scene('天亮', dawnRise()),
  scene('天亮：平安夜', dawnRise(true)),
  scene('獵人', hunterBow()),
  scene('出局', snuffedCandle()),
  scene('投票揭曉', h('div', { class: 'coins' }, [0, 1, 2, 3].map(coin))),
  scene('結算：好人勝', victory('village')),
  scene('結算：狼人勝', victory('wolf'))));
