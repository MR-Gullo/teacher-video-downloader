'use strict';
const root=document.documentElement, themeButton=document.querySelector('#theme');
function theme(value){root.dataset.theme=value;themeButton.textContent=value==='dark'?'Light theme':'Dark theme';themeButton.setAttribute('aria-label',`Switch to ${value==='dark'?'light':'dark'} theme`);}
try{const saved=localStorage.getItem('lessonshelf-theme');theme(saved==='dark'?'dark':'light');}catch{theme('light');}
themeButton.addEventListener('click',()=>{const value=root.dataset.theme==='dark'?'light':'dark';theme(value);try{localStorage.setItem('lessonshelf-theme',value);}catch{}});
function choose(browser){for(const button of document.querySelectorAll('[data-browser]'))button.setAttribute('aria-pressed',String(button.dataset.browser===browser));for(const name of ['chrome','firefox'])document.querySelector(`#${name}-steps`).hidden=name!==browser;}
for(const button of document.querySelectorAll('[data-browser]'))button.addEventListener('click',()=>choose(button.dataset.browser));
const ua=navigator.userAgent;if(/Firefox|Zen\//i.test(ua)){choose('firefox');document.querySelector('#browser-note').textContent='Zen or Firefox detected. Check the steps below.';}else if(/Chrome|Chromium/i.test(ua)&&!/Edg|OPR/i.test(ua)){choose('chrome');document.querySelector('#browser-note').textContent='Chrome detected. Check the steps below.';}else{choose('chrome');document.querySelector('#browser-note').textContent='Choose Chrome or Zen / Firefox for setup steps.';}

if(/Windows/i.test(navigator.userAgent))document.querySelector('#platform-note').textContent='Windows: direct file downloads use your browser. The optional companion is available on Mac only.';else if(!/Macintosh|Mac OS X/i.test(navigator.userAgent))document.querySelector('#platform-note').textContent='The browser preview is intended for Windows and Mac. The optional companion is Mac-only.';
