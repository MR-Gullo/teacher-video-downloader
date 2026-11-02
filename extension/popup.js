'use strict';
const api = globalThis.browser || chrome;
const $ = id => document.getElementById(id);
const privateMode=Boolean(api.extension?.inIncognitoContext);
let candidates = [], selected = new Set(), current = null, busy = false, polling = false, connected = false, watchedOrigins = [];
function applyTheme(theme) { document.documentElement.dataset.theme=theme; $('theme').textContent=theme==='dark'?'Light theme':'Dark theme'; $('theme').setAttribute('aria-label',`Switch to ${theme==='dark'?'light':'dark'} theme`); }
const settingsIds = ['quality','audio','captions','course','copy','engine'];
function feedback(message) { $('feedback').textContent = message; $('feedback').hidden = !message; }
function httpURL(raw) { const url = new URL(raw); if (!['http:','https:'].includes(url.protocol) || url.username || url.password) throw new Error('Use an HTTP or HTTPS link without embedded credentials.'); return url.href; }
function parseInput(raw) { return [...new Set(raw.split(/(?:\s+|,\s*(?=https?:\/\/|[\w-]{11}(?:[\s,]|$)))/).filter(Boolean).map(s => httpURL(/^[\w-]{11}$/.test(s) ? `https://www.youtube.com/watch?v=${s}` : s)))]; }
function shortURL(url) { try { const u = new URL(url); return u.hostname + (u.pathname === '/' ? '' : u.pathname); } catch { return 'Unavailable page'; } }
function mediaLabel(url) { try { const u=new URL(url),match=u.pathname.match(/\.(m3u8|mpd|mp4|webm|mp3|m4a|wav)$/i),ext=match?.[1].toLowerCase(),type=ext==='m3u8'?'HLS':ext==='mpd'?'DASH':ext?.toUpperCase()||'media';return `${u.hostname} · ${type}`; } catch { return 'Media link'; } }
function addCandidate(item) { try { item.url = httpURL(item.url); } catch { return; } if (!candidates.some(x => x.url === item.url)) candidates.push(item); }
function renderCandidates() {
  $('candidates').replaceChildren();
  if (!candidates.length) { const p=document.createElement('p');p.className='empty';p.textContent='No web tabs found. Paste a video link below.';$('candidates').append(p); }
  candidates.forEach(item => {
    const label=document.createElement('label');label.className='candidate';
    const input=document.createElement('input');input.type='checkbox';input.checked=selected.has(item.url);input.setAttribute('aria-label',`Select ${item.title || shortURL(item.url)}`);
    input.addEventListener('change',()=>{input.checked?selected.add(item.url):selected.delete(item.url);updateCount();});
    const text=document.createElement('div'), title=document.createElement('strong'),sub=document.createElement('small');
    title.textContent=item.title || shortURL(item.url);sub.textContent=`${item.kind || 'Web page'} · ${['Page media','Detected stream'].includes(item.kind)?mediaLabel(item.url):shortURL(item.url)}`;
    text.append(title,sub);label.append(input,text);$('candidates').append(label);
  }); updateCount();
}
function updateCount() { const n=candidates.filter(x=>selected.has(x.url)).length;$('selected-count').textContent=`${n} selected`;$('select-all').checked=n>0&&n===candidates.length;$('select-all').indeterminate=n>0&&n<candidates.length; }
async function loadTabs(initial=false) {
  try {
    const tabs=(await api.tabs.query({currentWindow:true})).filter(t=>!t.incognito);
    const active=tabs.find(t=>t.active && /^https?:/.test(t.url || ''));
    current=active || null;
    candidates=[];tabs.filter(t=>/^https?:/.test(t.url || '')).forEach(t=>addCandidate({url:t.url,title:t.title,pageUrl:t.url,kind:t.id===current?.id?'Current page':'Open tab'}));
    const {captured={}}=await api.storage.local.get('captured');
    for(const t of tabs) for(const item of captured[String(t.id)]||[]) addCandidate(item);
    if(initial&&current) selected.add(current.url);
    selected=new Set([...selected].filter(u=>candidates.some(c=>c.url===u)));
    $('current-title').textContent=current?.title || 'No active web page';$('current-domain').textContent=current?shortURL(current.url):'Open a video page, or paste a link.';
    $('scan').disabled=!current;$('observe').disabled=!current;
    const {watched=[]}=await api.storage.local.get('watched');watchedOrigins=watched;
    $('observe').textContent=current&&watched.includes(new URL(current.url).origin)?'Disable stream detection for this site':'Enable stream detection for this site';
    renderCandidates();
  }catch(e){feedback('Could not read tabs. '+e.message);}
}
async function scan() {
  if(!current)return; $('scan').disabled=true;feedback('');
  try{
    const result=await api.scripting.executeScript({target:{tabId:current.id},func:()=>{const media=[...document.querySelectorAll('video,audio')],links=[...document.querySelectorAll('video,audio,video source,audio source,a[href]')].map(e=>e.currentSrc||e.src||e.href).filter(u=>/^https?:/.test(u)&&(/\.(m3u8|mpd|mp4|webm|mp3|m4a)(?:[?#]|$)/i.test(u)||media.some(v=>v.currentSrc===u)));const manifests=performance.getEntriesByType('resource').map(e=>e.name).filter(u=>/^https?:/.test(u)&&/\.(m3u8|mpd)(?:[?#]|$)/i.test(u));return [...new Set([...links,...manifests])].slice(0,40);}});
    const urls=[...new Set(result.flatMap(x=>x.result||[]))];urls.forEach((url,i)=>addCandidate({url,title:`${current.title || 'Video'} · media ${i+1}`,pageUrl:current.url,kind:'Page media'}));if(urls.length){selected.delete(current.url);for(const url of urls)if(/\.(mp4|webm|mp3|m4a|wav)$/i.test(new URL(url).pathname))selected.add(url);}renderCandidates();
    feedback(urls.length?`Found ${urls.length} media link(s). Select a link to download; direct files are preselected.`:'No direct media links found. Try the page URL with yt-dlp, or enable stream detection and play the video. Blob and protected media cannot be downloaded directly.');
  }catch{feedback('This tab does not allow scanning yet. Open the extension from the video tab, or enable site access and try again.');}
  finally{$('scan').disabled=false;}
}
async function observe() {
  if(!current)return;const origin=new URL(current.url).origin;const watched=watchedOrigins;
  if(watched.includes(origin)){const {captured={}}=await api.storage.local.get('captured');for(const key of Object.keys(captured)){captured[key]=captured[key].filter(item=>{try{return new URL(item.pageUrl).origin!==origin;}catch{return false;}});if(!captured[key].length)delete captured[key];}await api.storage.local.set({watched:watched.filter(x=>x!==origin),captured});await api.permissions.remove({origins:[origin+'/*']});}
  else {const granted=await api.permissions.request({origins:[origin+'/*']});if(!granted){feedback('Site access was not granted. You can still paste a media URL.');return;}await api.storage.local.set({watched:[...watched,origin].slice(-40)});feedback('Stream detection enabled for this site. Play the video, then Refresh tabs. Cross-origin CDN requests may not be visible without separate permission.');}
  await loadTabs();
}
async function requestNativeConsent(){if(!api.runtime.getManifest?.().browser_specific_settings?.gecko)return;const accepted=await api.permissions.request({data_collection:['browsingActivity','websiteContent']});if(!accepted)throw new Error('Local companion access was not granted. Direct file downloads in the browser remain available.');}
async function native(request) {
  const r=await api.runtime.sendMessage({type:'native',request:{requestId:crypto.randomUUID(),...request}});
  if(!r?.ok)throw new Error(r?.error||'The local companion did not respond.');return r;
}
function renderJobs(jobs=[]) {
  $('jobs').replaceChildren();if(!jobs.length){const p=document.createElement('p');p.className='empty';p.textContent='No downloads yet. Choose a video to get started.';$('jobs').append(p);return;}
  for(const job of [...jobs].reverse()){
    const card=document.createElement('article');card.className='job';const head=document.createElement('div');head.className='job-header';
    const title=document.createElement('div');title.className='job-title';title.textContent=job.title||shortURL(job.url||'');const badge=document.createElement('span');badge.className='badge';badge.textContent=job.status;head.append(title,badge);card.append(head);
    const progress=document.createElement('progress');progress.max=100;const n=Number(job.progress);if(Number.isFinite(n))progress.value=Math.min(100,Math.max(0,n));progress.setAttribute('aria-label',`Progress for ${title.textContent}`);card.append(progress);
    const message=document.createElement('div');message.className='job-message';message.textContent=job.message||({'queued':'Waiting to start','done':'Saved locally','complete':'Saved locally','paused':'Partial files kept','cancelled':'Stopped; partial files kept'}[job.status]||'Working locally…');card.append(message);
    if(Array.isArray(job.files)&&job.files.length){const files=document.createElement('div');files.className='job-message';files.textContent='Saved: '+job.files.join(' · ');card.append(files);}
    const actions=document.createElement('div');actions.className='job-actions';let ops=[];
    if(['queued','running','downloading','retrying','processing'].includes(job.status))ops=['pause','cancel'];
    if(job.status==='paused')ops=['resume','cancel'];
    if(['failed','error','cancelled','interrupted'].includes(job.status))ops=['retry'];
    for(const op of ops){const b=document.createElement('button');b.textContent=job.engine==='n'&&['resume','retry'].includes(op)?'Restart':op[0].toUpperCase()+op.slice(1);b.setAttribute('aria-label',`${b.textContent} ${title.textContent}`);b.addEventListener('click',async()=>{b.disabled=true;try{if(['resume','retry'].includes(op))await requestNativeConsent();const result=await native({op,id:job.id});renderJobs(result.jobs);}catch(e){feedback(e.message);b.disabled=false;}});actions.append(b);}card.append(actions);$('jobs').append(card);
  }
}
async function refreshStatus(){if(polling)return;polling=true;try{const r=await native({op:'status'});connected=true;$('connection').className='notice connected';$('connection').textContent='Companion connected · Downloads stay on this computer';renderJobs(r.jobs);}catch(e){connected=false;$('connection').className='notice';$('connection').textContent=e.message;}finally{polling=false;}}
function settings(){return {quality:$('quality').value,audio:$('audio').value==='audio',captions:$('captions').value==='english',course:$('course').value.trim(),copy:$('copy').value,engine:$('engine').value};}
function hints(){$('copy-hint').textContent=$('audio').value==='audio'?'Audio-only output; extra video copy settings do not apply.':$('copy').value==='av1'?'Keeps the original. AV1 is less compatible; only retain a validated copy if at least 15% smaller.':$('copy').value==='none'?'Preserves the downloaded source without an additional video encode.':'Keeps the original. Makes a compatible projector copy; encoding takes time.';$('engine-hint').textContent=$('engine').value==='n'?'Advanced: use a direct HLS (.m3u8) or DASH (.mpd) manifest, not a page. N keeps temporary data, but cross-process resume is not guaranteed; Retry may re-download segments.':'yt-dlp preserves partial files and retries interrupted downloads. Signed links may expire and need refreshing.';}
async function enqueue(){if(busy)return;feedback('');let jobs;try{const opts=settings();if(opts.course&&(/[\\/]|^\.{1,2}$/.test(opts.course)))throw new Error('Use a course name without slashes or path traversal.');const items=candidates.filter(x=>selected.has(x.url));for(const url of parseInput($('urls').value))if(!items.some(x=>x.url===url))items.push({url,title:'',pageUrl:''});if(!items.length)throw new Error('Select a page or media link, or paste a URL first.');if(items.length>50)throw new Error('Please queue at most 50 links at a time.');if(opts.engine==='n'&&items.some(x=>!/\.(m3u8|mpd)(?:[?#]|$)/i.test(x.url)))throw new Error('N_m3u8DL-RE needs direct .m3u8 or .mpd manifest URLs. Deselect page URLs or use yt-dlp.');jobs=items.map(x=>({...x,...opts}));}catch(e){feedback(e.message);return;}
  busy=true;$('download').disabled=true;$('download').textContent='Adding to your local queue…';try{await requestNativeConsent();const r=await native({op:'enqueue',jobs});renderJobs(r.jobs);feedback('Added to your local queue. Duplicate jobs are not started twice.');$('urls').value='';}catch(e){feedback(e.message);}finally{busy=false;$('download').disabled=false;$('download').textContent='Download selected';}
}
async function downloadDirect(){
  feedback('');const button=$('direct-download');let urls;
  try{const pasted=parseInput($('urls').value);urls=[...new Set(pasted.length?pasted:candidates.filter(x=>selected.has(x.url)).map(x=>x.url))];
    if(!urls.length)throw new Error('Select or paste a direct file link first.');
    if(urls.length>50)throw new Error('Choose at most 50 files at a time.');
    if(urls.some(url=>!/\.(mp4|webm|mp3|m4a|wav)$/i.test(new URL(url).pathname)))throw new Error('Browser download needs direct MP4, WebM, MP3, M4A or WAV links. Deselect pages or use the companion.');
  }catch(e){feedback(e.message);return;}
  button.disabled=true;let started=0;
  try{for(const url of urls){await api.downloads.download({url});started++;}feedback(`${started} file(s) sent to browser downloads. Check your browser for progress.`);$('urls').value='';}
  catch(e){feedback(`${started} file(s) started. Browser download failed: ${e.message}`);}finally{button.disabled=false;}
}
$('direct-download').addEventListener('click',downloadDirect);
$('theme').addEventListener('click',async()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';applyTheme(theme);await api.storage.local.set({theme});});
$('refresh').addEventListener('click',()=>loadTabs());$('scan').addEventListener('click',scan);$('observe').addEventListener('click',()=>observe().catch(e=>feedback(e.message)));$('select-all').addEventListener('change',e=>{selected=e.target.checked?new Set(candidates.map(x=>x.url)):new Set();renderCandidates();});$('clear').addEventListener('click',()=>{selected.clear();renderCandidates();});$('download').addEventListener('click',enqueue);$('reconnect').addEventListener('click',async()=>{try{await requestNativeConsent();await refreshStatus();}catch(e){feedback(e.message);}});$('expand').addEventListener('click',()=>api.tabs.create({url:api.runtime.getURL('popup.html')}));$('doctor').addEventListener('click',async()=>{try{$('doctor-result').textContent='Checking…';await requestNativeConsent();const r=await native({op:'doctor'});$('doctor-result').textContent=JSON.stringify(r.doctor||r,null,2);}catch(e){$('doctor-result').textContent=e.message;}});
for(const id of settingsIds)$(id).addEventListener('change',async()=>{hints();const saved={};for(const key of settingsIds)saved[key]=$(key).value;await api.storage.local.set({settings:saved});});
(async()=>{if(privateMode){for(const child of document.querySelector('main').children)if(child.id!=='connection'&&!child.classList.contains('privacy'))child.hidden=true;$('connection').textContent='LessonShelf is unavailable in private browsing. Open a regular window to use it.';return;}const {theme='light'}=await api.storage.local.get('theme');applyTheme(theme);const {settings:saved={}}=await api.storage.local.get('settings');for(const id of settingsIds)if(saved[id]!==undefined)$(id).value=saved[id];hints();await loadTabs(true);await refreshStatus();setInterval(refreshStatus,2000);})();
