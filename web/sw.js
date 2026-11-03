// 離線也打得開畫面（SPEC B1、DEV_PLAN P6）。只存畫面本身的檔案：
// server.json 每次開店都會換網址，伺服器的 /api、/ws、/media 是即時資料，都不經過這裡。
// 先上網拿新的，拿不到（或太久）才用存著的，所以發布新版後手機重開就是新版，不會在遊戲中被換掉。

const CACHE = 'bmt-static';
const SLOW_MS = 4000;
const LIVE = /\/(server\.json|api\/|ws|media\/)/;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

/** 存的時候拿掉 ?v= 版本號：同一個檔案只留最新一份，舊版不會越存越多。頁面本身一律存成同一份。 */
function keyOf(request) {
  if (request.mode === 'navigate') return new URL('./', self.registration.scope).href;
  const url = new URL(request.url);
  url.search = '';
  return url.href;
}

async function fromNetwork(request) {
  // 頁面本身要跳過瀏覽器快取，否則 GitHub Pages 的 10 分鐘快取會讓人拿到舊版
  const response = await fetch(request, request.mode === 'navigate' ? { cache: 'no-cache' } : {});
  if (response.ok && response.type === 'basic') {
    const copy = response.clone();
    caches.open(CACHE).then((cache) => cache.put(keyOf(request), copy)).catch(() => {});
  }
  return response;
}

async function fromCache(request) {
  const cache = await caches.open(CACHE);
  return cache.match(keyOf(request));
}

async function respond(request) {
  const network = fromNetwork(request);
  network.catch(() => {}); // 已經改用存著的檔案時，網路晚點失敗不用報錯
  const slow = new Promise((resolve) => { setTimeout(resolve, SLOW_MS, null); });
  try {
    const first = await Promise.race([network, slow]);
    if (first) return first;
    return (await fromCache(request)) ?? await network;
  } catch (error) {
    const cached = await fromCache(request);
    if (cached) return cached;
    throw error;
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin || LIVE.test(url.pathname)) return;
  event.respondWith(respond(request));
});
