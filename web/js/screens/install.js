// S23 安裝引導、S24 準備檢查（SPEC C4）。都跟「這支手機準備好了沒」有關，放同一檔。
import { h } from '../dom.js';
import { PLATFORM, STANDALONE, confirmScreenManual, promptInstall, screenStaysOn, skipInstallGuide } from '../pwa.js';
import { changed, store } from '../store.js';
import { t } from '../strings.js';
import { button } from '../ui/common.js';

// iPhone 分享按鈕的樣子：方框加向上箭頭
const SHARE_ICON = 'data:image/svg+xml,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#6fa3b8" stroke-width="2"'
  + ' stroke-linecap="round" stroke-linejoin="round"><path d="M8 10H6v11h12V10h-2"/><path d="M12 15V3M8 7l4-4 4 4"/></svg>',
);

function steps() {
  if (PLATFORM === 'ios') {
    return [
      [t('s23.ios1'), h('img', { class: 'install__icon', src: SHARE_ICON, alt: t('s23.shareAlt') })],
      [t('s23.ios2')],
      [t('s23.open')],
    ];
  }
  return [[t('s23.android1')], [t('s23.android2')], [t('s23.open')]];
}

export function s23() {
  const fromSettings = store.ui.overlay === 'S23';
  const password = new URLSearchParams(location.hash.slice(1)).get('pw');
  return [
    h('h1', { testid: 'screen-s23' }, t('s23.title')),
    h('p', {}, t('s23.why')),
    store.installPrompt ? button(t('s23.installNow'), promptInstall, { kind: 'suggest', testid: 'btn-install' }) : null,
    h('ol', { class: 'install__steps' }, steps().map(([text, icon]) => h('li', { class: 'install__step' }, text, icon ?? null))),
    password ? h('p', { class: 'big center selectable', testid: 'install-password' }, t('s23.password', { pw: password })) : null,
    h('p', { class: 'hint' }, t('s23.warn')),
    fromSettings
      ? button(t('common.close'), () => { store.ui.overlay = null; changed(); }, { testid: 'btn-install-close' })
      : button(t('s23.skip'), skipInstallGuide, { kind: 'secondary', testid: 'btn-install-skip' }),
  ];
}

function prepCard(done, testid, title, ...more) {
  return h('div', { class: `prep ${done ? 'prep--done' : ''}`, testid },
    h('div', { class: 'prep__title' }, `${done ? '✔' : '☐'} ${title}`),
    done ? null : more);
}

/** S24：保持螢幕亮著、從主畫面打開。電腦開的不用加主畫面，只看螢幕那張。 */
export function prepCards() {
  const screenOn = screenStaysOn();
  return h('div', { class: 'prep-list' },
    prepCard(screenOn, 'prep-wake', screenOn ? t('s24.wakeOk') : t('s24.wake'),
      h('p', { class: 'hint', testid: 'wake-hint' }, t('wake.manual')),
      button(t('s24.wakeDone'), confirmScreenManual, { small: true, testid: 'btn-wake-done' })),
    PLATFORM ? prepCard(STANDALONE, 'prep-pwa', STANDALONE ? t('s24.pwaOk') : t('s24.pwa'),
      h('p', { class: 'hint' }, t('s24.pwaLater')),
      button(t('s24.pwaHow'), () => { store.ui.overlay = 'S23'; changed(); }, { small: true, testid: 'btn-pwa-how' }))
      : null);
}

/** 設定裡可以再看一次教學。 */
export function installGuideButton() {
  return PLATFORM && !STANDALONE
    ? button(t('s21.install'), () => { store.ui.overlay = 'S23'; changed(); }, { testid: 'btn-install-guide' })
    : null;
}
