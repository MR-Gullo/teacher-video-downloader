/* No content-script message bridge: only extension-owned pages may command the host. */
const api = globalThis.browser || chrome;
const HOST = 'org.teacher.video_downloader';
const MEDIA = /\.(m3u8|mpd|mp4|webm|m4a|mp3)(?:[?#]|$)/i;
let observation = Promise.resolve();
api.webRequest.onBeforeRequest.addListener(details => {
  if (details.tabId < 0 || !MEDIA.test(details.url)) return;
  observation = observation.then(async () => {
    const { watched = [], captured = {} } = await api.storage.local.get(['watched', 'captured']);
    const tab = await api.tabs.get(details.tabId).catch(() => null);
    if (!tab || !watched.includes(new URL(tab.url).origin)) return;
    const key = String(details.tabId);
    const list = captured[key] || [];
    if (!list.some(x => x.url === details.url)) list.push({url: details.url, title: tab.title || 'Detected media', pageUrl: tab.url, kind: 'Detected stream'});
    captured[key] = list.slice(-40);
    const keys = Object.keys(captured); while (keys.length > 30) delete captured[keys.shift()];
    await api.storage.local.set({ captured });
  }).catch(() => {});
}, {urls: ['http://*/*', 'https://*/*']});
api.tabs.onRemoved.addListener(tabId => {
  observation = observation.then(async () => {
    const {captured = {}} = await api.storage.local.get('captured'); delete captured[String(tabId)];
    await api.storage.local.set({captured});
  }).catch(() => {});
});
api.tabs.onUpdated.addListener((tabId, change) => {
  if (!change.url) return;
  observation = observation.then(async () => {
    const {captured = {}} = await api.storage.local.get('captured'); delete captured[String(tabId)];
    await api.storage.local.set({captured});
  }).catch(() => {});
});
api.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== api.runtime.id || !sender.url?.startsWith(api.runtime.getURL('')) || message?.type !== 'native') return false;
  const allowed = ['status','enqueue','pause','resume','cancel','retry','doctor'];
  if (!allowed.includes(message.request?.op)) { respond({ok:false,error:'Unknown command'}); return false; }
  api.runtime.sendNativeMessage(HOST, message.request).then(respond).catch(() => respond({ok:false,error:'Local companion not connected. Direct file downloads still work in your browser. On Mac, see the setup guide to enable the queue and conversion.',missingHost:true}));
  return true;
});
// Tab IDs are not stable across browser launches; do not retain old signed URLs.
api.runtime.onStartup.addListener(() => api.storage.local.remove('captured'));
