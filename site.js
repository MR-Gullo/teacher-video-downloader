"use strict";
const root=document.documentElement,themeButton=document.querySelector('#theme');
function theme(value){root.dataset.theme=value;themeButton.textContent=value==='dark'?'Light theme':'Dark theme';themeButton.setAttribute('aria-label',`Switch to ${value==='dark'?'light':'dark'} theme`)}
try{theme(localStorage.getItem('lessonshelf-theme')==='dark'?'dark':'light')}catch{theme('light')}
themeButton.addEventListener('click',()=>{const value=root.dataset.theme==='dark'?'light':'dark';theme(value);try{localStorage.setItem('lessonshelf-theme',value)}catch{}});
// Keep the required companion step visible for Windows testers.
const ua = navigator.userAgent;
document.querySelector('#windows-setup').open = /Windows/i.test(ua) && !/ARM64|aarch64/i.test(ua);
