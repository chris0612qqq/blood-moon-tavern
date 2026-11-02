// 聊天照片（SPEC A9、v4.24）：手機先縮小再上傳，重畫一次就順便去掉 EXIF（含拍攝位置）。
// 點小圖全螢幕放大，兩指縮放、一指拖曳。
import { h } from '../dom.js';
import { api, apiBase, send } from '../net.js';
import { loadTokens } from '../session.js';
import { changed, store } from '../store.js';
import { t } from '../strings.js';

const PHOTO_MAX_SIDE = 1600;
const PHOTO_QUALITY = 0.82;
const ZOOM_MAX = 4;

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('decode')); };
    img.src = url;
  });
}

/** 縮到長邊 1600 再存成 JPEG。瀏覽器畫圖時已經照 EXIF 轉正方向。 */
export async function compressPhoto(file) {
  const img = await loadImage(file);
  const scale = Math.min(1, PHOTO_MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(img.naturalWidth * scale);
  canvas.height = Math.round(img.naturalHeight * scale);
  canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', PHOTO_QUALITY));
}

/** 上傳後發到聊天；身分照目前選的（本人、假扮、狼人）。 */
export async function sendPhoto(file, fields) {
  store.ui.toast = { key: 'chat.uploading' };
  changed();
  try {
    const blob = await compressPhoto(file);
    const tokens = loadTokens();
    const auth = tokens.player ?? tokens.admin;  // 上帝主持人用管理員身分
    const res = await api('/api/media?kind=photo', { method: 'POST', auth, raw: blob });
    if (!res.ok) throw new Error(res.code ?? 'upload');
    const result = await send('chat.send', { ...fields, kind: 'photo', media_id: res.data.id });
    store.ui.toast = result.ok ? null : { key: 'chat.photoFailed' };
  } catch {
    store.ui.toast = { key: 'chat.photoFailed' };
  }
  changed();
}

export function photoSrc(msg) {
  return msg.media_url ? apiBase + msg.media_url : '';
}

export function photoBubble(msg) {
  const src = photoSrc(msg);
  return h('img', {
    class: 'chat-photo',
    testid: `chat-photo-${msg.id}`,
    src,
    alt: t('chat.photo'),
    onclick: () => { store.ui.lightbox = { src, scale: 1, x: 0, y: 0 }; changed(); },
    // 簽章網址一小時過期，壞掉就重取（CODING_RULES N21）
    onerror: () => { if (msg.media_id) send('media.refresh', { media_id: msg.media_id }); },
  });
}

let gesture = null;

function distance(touches) {
  return Math.hypot(touches[0].clientX - touches[1].clientX, touches[0].clientY - touches[1].clientY);
}

function onTouchStart(e) {
  const box = store.ui.lightbox;
  if (e.touches.length === 2) gesture = { dist: distance(e.touches), scale: box.scale };
  else if (e.touches.length === 1) gesture = { x: e.touches[0].clientX - box.x, y: e.touches[0].clientY - box.y };
}

function onTouchMove(e) {
  const box = store.ui.lightbox;
  if (!box || !gesture) return;
  e.preventDefault();
  if (e.touches.length === 2 && gesture.dist) {
    box.scale = Math.min(ZOOM_MAX, Math.max(1, gesture.scale * (distance(e.touches) / gesture.dist)));
  } else if (e.touches.length === 1 && gesture.x !== undefined && box.scale > 1) {
    box.x = e.touches[0].clientX - gesture.x;
    box.y = e.touches[0].clientY - gesture.y;
  }
  if (box.scale === 1) { box.x = 0; box.y = 0; }
  changed();
}

/** 全螢幕看照片。點黑色背景或關閉鈕就收起來。 */
export function lightboxLayer() {
  const box = store.ui.lightbox;
  if (!box) return null;
  const close = () => { store.ui.lightbox = null; gesture = null; changed(); };
  return h('div', { class: 'lightbox', testid: 'lightbox', onclick: (e) => { if (e.target === e.currentTarget) close(); } },
    h('img', {
      src: box.src,
      testid: 'lightbox-img',
      style: `transform: translate(${box.x}px, ${box.y}px) scale(${box.scale})`,
      ontouchstart: onTouchStart,
      ontouchmove: onTouchMove,
      ontouchend: () => { gesture = null; },
    }),
    h('button', { class: 'lightbox__close', testid: 'lightbox-close', onclick: close }, t('common.close')));
}
