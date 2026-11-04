'use strict';
const setupApi = globalThis.browser || globalThis.chrome;
if (setupApi?.storage?.local) {
  setupApi.storage.local.get('theme').then(({theme}) => {
    document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
  }).catch(() => {});
}
