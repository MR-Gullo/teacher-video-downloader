'use strict';
const api=globalThis.browser||chrome;
const $=id=>document.getElementById(id);
const privateMode=Boolean(api.extension?.inIncognitoContext);
const firefox=Boolean(api.runtime.getManifest?.().browser_specific_settings?.gecko);
const dataPermissions={data_collection:['browsingActivity','websiteContent']};
const settingIds=['quality','audio','captions','copy','course'];
let source=null,players=[],pageSnapshot=null,consent=!firefox,busy=false,polling=false,lastJobId=null,lastDownload=null,lastRenderedJobs='';
function setStatus(text){$('status').textContent=text||'';}
function validURL(value){const u=new URL(value);if(!['http:','https:'].includes(u.protocol)||u.username||u.password)throw new Error('Enter an HTTP or HTTPS link without credentials.');return u.href;}
function safeSite(value){try{return new URL(value).hostname}catch{return ''}}
function durationText(n){if(!Number.isFinite(n)||n<=0)return '';let s=Math.round(n);return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;}
function setTheme(value){document.documentElement.dataset.theme=value;$('theme').textContent=value==='dark'?'☀':'☾';$('theme').setAttribute('aria-label',`Switch to ${value==='dark'?'light':'dark'} theme`);}
function syncConsent(){const need=firefox&&!consent;$('consent-note').hidden=!need;$('download').textContent=need?'Allow and download':'Download video';}
function selectedPlayer(){if(players.length===1)return players[0];const v=$('player-choice').value;return v===''?null:players[Number(v)]||null;}
function showSource(){
  const pasted=$('paste-area').hidden?'':$('url').value.trim();
  let url=pasted||source?.url||'';const p=pasted?null:selectedPlayer();
  $('current-title').textContent=pasted?'Video link':source?.title||'Open a video page';$('current-domain').textContent=safeSite(url);$('current-duration').textContent=p?durationText(p.duration):'';
  $('download').disabled=busy||!url||(!pasted&&players.length>1&&!p);
  const direct=Boolean(pasted&&/\.(mp4|webm|mp3|m4a|wav)(?:[?#]|$)/i.test(pasted));$('direct-download').hidden=!direct;$('direct-note').hidden=!direct;
}
function inspectPage(){
  const nodes=[...document.querySelectorAll('video')];
  const videos=nodes.map((v,i)=>({index:i,duration:Number.isFinite(v.duration)?v.duration:0,playing:!v.paused&&!v.ended,src:v.currentSrc||v.src||'',label:v.getAttribute('aria-label')||v.getAttribute('title')||`Video ${i+1}`}));
  const resources=performance.getEntriesByType('resource').map(x=>x.name).filter(u=>/^https?:/i.test(u)&&/\.(m3u8|mpd)(?:[?#]|$)/i.test(u)).slice(-24);
  return {url:location.href,documentStamp:performance.timeOrigin,videos,resources};
}
async function scanCurrent(){
  if(privateMode)return;const tabs=await api.tabs.query({active:true,currentWindow:true});const tab=tabs[0];
  if(!tab||tab.incognito||!/^https?:/i.test(tab.url||'')){source=null;players=[];showSource();return;}
  source={id:tab.id,url:tab.url,title:tab.title||'Current video'};players=[];pageSnapshot=null;
  try{
    const result=await api.scripting.executeScript({target:{tabId:tab.id},func:inspectPage});const snap=result[0]?.result;
    if(!snap||snap.url!==tab.url)throw new Error('The page changed. Reopen LessonShelf.');
    pageSnapshot=snap;const playing=snap.videos.filter(v=>v.playing);
    players=playing.length===1?playing:snap.videos.length===1?snap.videos:[];
    if(!players.length&&snap.videos.length>1){players=snap.videos;$('player-choice').replaceChildren();const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='Choose a video';placeholder.disabled=true;placeholder.selected=true;$('player-choice').append(placeholder);for(const [i,v] of players.entries()){const o=document.createElement('option');o.value=String(i);o.textContent=`${v.label}${v.duration?' · '+durationText(v.duration):''}`;$('player-choice').append(o)}$('player-choice-label').hidden=false;}
    else $('player-choice-label').hidden=true;
  }catch{setStatus('Could not inspect this page. You can still try its link.');}
  showSource();
}
async function verifyPage(){
  const tab=await api.tabs.get(source.id);if(!tab||tab.incognito||tab.url!==source.url)throw new Error('The video page changed. Reopen LessonShelf.');
  if(!pageSnapshot)return null;
  const r=await api.scripting.executeScript({target:{tabId:source.id},func:inspectPage});const now=r[0]?.result;
  if(!now||now.url!==pageSnapshot.url||now.documentStamp!==pageSnapshot.documentStamp)throw new Error('The video page changed. Reopen LessonShelf.');return now;
}
function askConsent(){if(!firefox||consent)return Promise.resolve(true);return api.permissions.request(dataPermissions);}
async function native(request){const result=await api.runtime.sendMessage({type:'native',request:{requestId:crypto.randomUUID(),...request}});if(!result?.ok)throw new Error(result?.error||'The local downloader did not respond.');return result;}
function resolveWithinLimit(request){let timer;return Promise.race([native(request),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('The local downloader did not respond. Check Help & setup, then try again.')),45000)})]).finally(()=>clearTimeout(timer));}
function settings(){const course=$('course').value.trim();if(course&&(/[\\/]|^\.{1,2}$/.test(course)))throw new Error('Use a course name without slashes.');return {quality:$('quality').value,audio:$('audio').value==='audio',captions:$('captions').value==='english',copy:$('copy').value,course,engine:'auto'};}
function beginDownload(){
  if(privateMode||busy)return;
  let options,url,pasted;try{options=settings();pasted=!$('paste-area').hidden&&Boolean($('url').value.trim());url=validURL(pasted?$('url').value.trim():source?.url||'');}catch(e){setStatus(e.message||'Enter a valid video link.');return;}
  busy=true;$('download').disabled=true;setStatus('Preparing video…');
  let permission;try{permission=askConsent()}catch(e){permission=Promise.reject(e)}
  (async()=>{
    if(!await permission){setStatus('Permission was not granted. You can try again.');return;}
    consent=true;syncConsent();let verifiedManifest=false;
    if(!pasted){const now=await verifyPage();const player=selectedPlayer();if(now&&player){const live=now.videos.find(v=>v.index===player.index);if(!live||Math.abs((live.duration||0)-(player.duration||0))>2)throw new Error('The video changed. Reopen LessonShelf.');
      if(/^https?:/i.test(live.src)&&/\.(mp4|webm|m3u8|mpd)(?:[?#]|$)/i.test(live.src))url=validURL(live.src);
      else if(now.resources.length&&live.duration>0){setStatus('Finding this video…');const found=await resolveWithinLimit({op:'resolve',candidates:now.resources,duration:live.duration,quality:options.quality});if(found.url){url=validURL(found.url);verifiedManifest=true;}}
    }}
    const r=await native({op:'enqueue',jobs:[{url,pageUrl:pasted?url:source.url,title:pasted?'Video':source.title,...options,verifiedManifest}]});
    lastJobId=r.jobIds?.[0]||null;if(lastJobId&&!pasted&&pageSnapshot){lastDownload={id:lastJobId,tabId:source.id,stamp:pageSnapshot.documentStamp};await api.storage.local.set({lastDownload})}setStatus('Added to downloads.');renderJobs(r.jobs||[]);
  })().catch(e=>setStatus(e.message||'Could not start the download.')).finally(()=>{busy=false;showSource();syncConsent()});
}
function renderJobs(jobs=[]){
  const signature=JSON.stringify(jobs);if(signature===lastRenderedJobs||$('jobs').contains?.(document.activeElement))return;lastRenderedJobs=signature;
  $('jobs').replaceChildren();if(!jobs.length){const p=document.createElement('p');p.className='empty';p.textContent='No downloads yet.';$('jobs').append(p);return;}
  for(const job of jobs){const card=document.createElement('div');card.className='job';const head=document.createElement('div');head.className='job-header';const title=document.createElement('span');title.className='job-title';title.textContent=job.title||'Video';const badge=document.createElement('span');badge.className='badge';badge.textContent=String(job.status||'').replaceAll('-',' ');head.append(title,badge);card.append(head);
    if(['running','queued','retrying','processing'].includes(job.status)){const progress=document.createElement('progress');progress.max=100;progress.value=Number(job.progress)||0;progress.setAttribute('aria-label',`Progress for ${title.textContent}`);card.append(progress)}
    const msg=document.createElement('div');msg.className='job-message';msg.textContent=job.message||'';card.append(msg);const acts=document.createElement('div');acts.className='job-actions';let ops=[];if(['running','queued','retrying','processing'].includes(job.status))ops=['pause','cancel'];else if(job.status==='paused')ops=['resume','cancel'];else if(['failed','cancelled'].includes(job.status))ops=['retry'];
    for(const op of ops){const button=document.createElement('button');button.textContent=op[0].toUpperCase()+op.slice(1);button.setAttribute('aria-label',`${button.textContent} ${title.textContent}`);button.addEventListener('click',()=>{button.disabled=true;native({op,id:job.id}).then(r=>renderJobs(r.jobs||[])).catch(e=>{$('queue-access').textContent=e.message;button.disabled=false})});acts.append(button)}card.append(acts);if(Array.isArray(job.files)&&job.files.length){const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Saved files';details.append(summary);for(const path of job.files){const item=document.createElement('div');item.className='job-message';item.textContent=path;details.append(item)}card.append(details)}$('jobs').append(card);
  }
  const latest=jobs.find(x=>x.id===lastJobId);if(latest&&!busy&&$('queue-view').hidden)setStatus(`${latest.message||latest.status}${latest.progress&&latest.status==='running'?` (${Math.round(latest.progress)}%)`:''}`);
}
async function refreshStatus(){if(privateMode||!consent||polling)return;polling=true;try{const r=await native({op:'status'});$('queue-access').textContent='';renderJobs(r.jobs||[])}catch(e){$('queue-access').textContent=e.message;$('jobs').replaceChildren();lastRenderedJobs='';if(!$('queue-view').hidden)setStatus('');}finally{polling=false}}
function allowQueue(){if(privateMode)return;let request;try{request=askConsent()}catch(e){request=Promise.reject(e)}Promise.resolve(request).then(ok=>{if(!ok){$('queue-access').textContent='Permission was not granted. You can try again.';return}consent=true;syncConsent();$('queue-allow').hidden=true;return refreshStatus()}).catch(e=>{$('queue-access').textContent=e.message})}
$('download').addEventListener('click',beginDownload);
$('theme').addEventListener('click',()=>{const t=document.documentElement.dataset.theme==='dark'?'light':'dark';setTheme(t);api.storage.local.set({theme:t})});
$('paste').addEventListener('click',()=>{$('paste-area').hidden=!$('paste-area').hidden;if(!$('paste-area').hidden)$('url').focus();showSource()});$('url').addEventListener('input',showSource);$('player-choice').addEventListener('change',showSource);
$('downloads').addEventListener('click',()=>{if(privateMode)return;$('video-view').hidden=true;$('queue-view').hidden=false;if(!consent){$('queue-access').textContent='Allow access to view your downloads.';$('queue-allow').hidden=false;$('jobs').replaceChildren()}else refreshStatus()});$('back').addEventListener('click',()=>{if(privateMode)return;$('queue-view').hidden=true;$('video-view').hidden=false});$('queue-allow').addEventListener('click',allowQueue);
$('direct-download').addEventListener('click',async()=>{if(privateMode)return;try{const url=validURL($('url').value.trim());await api.downloads.download({url,saveAs:false});setStatus('Browser download started. Original quality.') }catch(e){setStatus(e.message||'The browser download could not start.')}});
$('reconnect').addEventListener('click',()=>{if(privateMode)return;let request;try{request=askConsent()}catch(e){request=Promise.reject(e)}Promise.resolve(request).then(ok=>{if(!ok)throw new Error('Permission was not granted.');consent=true;syncConsent();return refreshStatus()}).then(()=>setStatus('Reconnected.')).catch(e=>setStatus(e.message))});
$('doctor').addEventListener('click',()=>{if(privateMode)return;let request;try{request=askConsent()}catch(e){request=Promise.reject(e)}Promise.resolve(request).then(ok=>{if(!ok)throw new Error('Permission was not granted.');consent=true;syncConsent();return native({op:'doctor'})}).then(r=>{$('doctor-result').textContent=['yt-dlp','ffmpeg','ffprobe','N_m3u8DL-RE'].map(k=>`${k}: ${r.doctor?.[k]?.available?'available':'not found'}`).join('\n')}).catch(e=>{$('doctor-result').textContent=e.message})});
for(const id of settingIds)$(id).addEventListener('change',()=>{const saved={};for(const key of settingIds)saved[key]=$(key).value;api.storage.local.set({settings:saved})});
(async()=>{if(privateMode){$('video-view').hidden=true;$('queue-view').hidden=false;$('queue-access').textContent='LessonShelf is unavailable in private browsing. Open a regular window.';$('back').hidden=true;$('queue-allow').hidden=true;return}const {theme='light',settings:saved={},lastDownload:stored=null}=await api.storage.local.get(['theme','settings','lastDownload']);lastDownload=stored;setTheme(theme);for(const id of settingIds)if(saved[id]!==undefined&&[...($(id).options||[])].some(o=>o.value===saved[id])||id==='course'&&saved[id]!==undefined)$(id).value=saved[id];if(firefox){try{consent=await api.permissions.contains(dataPermissions)}catch{consent=false}}syncConsent();await scanCurrent();if(lastDownload&&source&&pageSnapshot&&lastDownload.tabId===source.id&&lastDownload.stamp===pageSnapshot.documentStamp)lastJobId=lastDownload.id;if(consent)refreshStatus();setInterval(refreshStatus,2000)})().catch(()=>setStatus('Could not open LessonShelf. Try again.'));
