const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
const script = fs.readFileSync('site.js', 'utf8');
const release = JSON.parse(fs.readFileSync('downloads/release.json', 'utf8'));
for (const [id, url] of [['firefox-install', release.firefoxXpi], ['windows-companion', release.windowsInstaller]]) {
  assert(url && url.startsWith('https://github.com/MR-Gullo/teacher-video-downloader/releases/download/'));
  assert(html.includes(`id="${id}" class="button primary" href="${url}"`));
}
for (const removed of ['browser-note', 'release-state', 'platform-note', 'chrome-steps', 'firefox-pending', 'windows-pending', 'mac-install']) {
  assert(!html.includes(`id="${removed}"`));
}
function page(userAgent, savedTheme = null) {
  const elements = Object.fromEntries(['theme', 'windows-setup'].map(id => [id, {handlers: {}, setAttribute(k, v) {this[k] = v;}, addEventListener(k, fn) {this.handlers[k] = fn;}}]));
  const document = {documentElement: {dataset: {}}, querySelector: selector => elements[selector.slice(1)]};
  vm.runInNewContext(script, {document, navigator: {userAgent}, localStorage: {getItem: () => savedTheme, setItem() {}}});
  return {elements, document};
}
for (const browser of ['Firefox', 'Chrome', 'Edg']) {
  const p = page('Windows NT 10.0 Win64 x64 ' + browser);
  assert(p.elements['windows-setup'].open);
  assert.equal(p.document.documentElement.dataset.theme, 'light');
}
for (const ua of ['Macintosh Firefox', 'iPhone Safari', 'Windows ARM64 Firefox', 'Windows aarch64 Firefox']) {
  assert(!page(ua).elements['windows-setup'].open);
}
const p = page('Macintosh Firefox', 'dark');
assert.equal(p.document.documentElement.dataset.theme, 'dark');
p.elements.theme.handlers.click();
assert.equal(p.document.documentElement.dataset.theme, 'light');
console.log('PASS published download links, simplified setup, Windows disclosure and saved theme');
