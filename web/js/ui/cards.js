// 字卡（使用者決定清單與順序，SPEC v4.20）：按了就發音，不看步驟、不影響流程。語音選單和廣播分頁共用。
// 新增字卡：這裡加一項，strings.js 加 card.<id>。之後的音效卡多帶 sound 欄位。
import { h } from '../dom.js';
import { t } from '../strings.js';

const CARD_GROUPS = Object.freeze([
  { id: 'compose', cards: [{ id: 'please' }, { id: 'you' }, { id: 'me' }, { id: 'say' }, { id: 'let' }, { id: 'no' }] },
  { id: 'control', cards: [{ id: 'hurry' }, { id: 'quiet' }, { id: 'gan' }] },
  { id: 'react', cards: [{ id: 'ha' }, { id: 'lol' }, { id: 'stunned' }] },
  { id: 'tease', cards: [{ id: 'great' }, { id: 'comfy' }, { id: 'rascal' }, { id: 'fairy' }, { id: 'handsome' }] },
]);

export const cardText = (card) => t(`card.${card.id}`);

export function cardGrid(onPress, disabled = false) {
  return h('div', { testid: 'sound-cards' }, CARD_GROUPS.map((group) => [
    h('div', { class: 'card-group', key: `title-${group.id}` }, t(`cardGroup.${group.id}`)),
    h('div', { class: 'grid', key: group.id }, group.cards.map((card) => h('button', {
      class: 'cell',
      key: card.id,
      testid: `card-${card.id}`,
      disabled,
      onclick: () => onPress(card),
    }, cardText(card)))),
  ]));
}
