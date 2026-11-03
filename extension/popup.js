'use strict';
const api=globalThis.browser||chrome;
const $=id=>document.getElementById(id);
const privateMode=Boolean(api.extension?.inIncognitoContext);
const firefox=Boolean(api.runtime.getManifest?.().browser_specific_settings?.gecko);
const dataPermissions={data_collection:['browsingActivity','websiteContent']};
const settingIds=['quality','audio','captions','copy','course','output-format'];
let source=null,players=[],pageSnapshot=null,consent=!firefox,busy=false,polling=false,lastJobId=null,lastDownload=null,lastDownloads=[],lastRenderedJobs='',currentJob=null,lastJobs=[],pasteBinding=null,jobStatusText='';
function setStatus(text){$('status').textContent=text||'';}
function validURL(value){const u=new URL(value);if(!['http:','https:'].includes(u.protocol)||u.username||u.password)throw new Error('Enter an HTTP or HTTPS link without credentials.');return u.href;}
function safeSite(value){try{return new URL(value).hostname}catch{return ''}}
function shortTitle(value){const parts=String(value||'').split(/\s+(?:[|]|[-–—])\s+/);const seen=new Set();return parts.filter(part=>{const key=part.trim().toLocaleLowerCase();if(seen.has(key))return false;seen.add(key);return true}).join(' · ');}
function jobMessage(job){const raw=job.message||'';if(job.status==='complete')return 'Saved.';if(job.status!=='complete-warning')return raw;const text=raw.replace(/The source video has no audio\./i,'Saved without sound.').replace(/No embedded English captions were found; no automatic cloud transcription was attempted\./i,"English captions weren't saved.").replace(/English captions could not be fetched because of rate limiting\./i,"English captions weren't saved because the site asked us to wait.");return text.startsWith('Saved')?text:'Saved. '+text;}

function durationText(n){if(!Number.isFinite(n)||n<=0)return '';let s=Math.round(n);return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;}
function setTheme(value){document.documentElement.dataset.theme=value;$('theme').textContent=value==='dark'?'☀':'☾';$('theme').setAttribute('aria-label',`Switch to ${value==='dark'?'light':'dark'} theme`);}
function jobLabel(job){if(!job)return '';return ({queued:'Waiting to download',running:'Downloading',retrying:'Waiting to retry',processing:'Saving file',paused:'Paused',failed:'Failed',cancelled:'Cancelled',complete:'Saved','complete-warning':'Saved with warning'})[job.status]||job.status||'';}
function syncConsent(){const need=firefox&&!consent;$('consent-note').hidden=!need;const job=boundJob();$('download').textContent=busy?'Finding video…':job&&activeStatuses.includes(job.status)?jobLabel(job)+'…':job?.status==='paused'?'Resume download':job&&['failed','cancelled'].includes(job.status)?'Retry download':need?'Allow and download':'Download video';}
function selectedPlayer(){if(players.length===1)return players[0];const v=$('player-choice').value;return v===''?null:players[Number(v)]||null;}
const activeStatuses=['running','queued','retrying','processing'];
function boundJob(){return currentJob;}
function showSource(){
  const pasteMode=!$('paste-area').hidden;const pasted=pasteMode?$('url').value.trim():'';
  let url=pasteMode?pasted:source?.url||'';const p=pasteMode?null:selectedPlayer();
  $('current-title').textContent=pasteMode?(pasted?(safeSite(pasted)||'Video link'):'Paste a video link'):(p?.label&&!/^Video(?: \d+)?$/i.test(p.label)?shortTitle(p.label):shortTitle(source?.title||'Open a video page'));$('player-choice-label').hidden=pasteMode||players.length<=1;$('current-domain').textContent=safeSite(url);$('current-duration').textContent=p?durationText(p.duration):'';
  const job=boundJob();syncConsent();if(job&&['complete','complete-warning'].includes(job.status)&&job.files?.length)$('download').textContent='Show in Finder';let valid=false;try{valid=Boolean(url)&&Boolean(validURL(url))}catch{}$('download').disabled=busy||Boolean(job&&activeStatuses.includes(job.status))||!valid||(!pasteMode&&players.length>1&&!p);$('paste').textContent=pasteMode?'Use current video':'Paste link';$('show-file').hidden=true;
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
    pageSnapshot=snap;const videos=snap.videos.filter((v,i,all)=>!v.src||all.findIndex(x=>x.src===v.src&&Math.abs((x.duration||0)-(v.duration||0))<1)===i);const playing=videos.filter(v=>v.playing);
    players=playing.length===1?playing:videos.length===1?videos:[];
    if(!players.length&&videos.length>1){players=videos;$('player-choice').replaceChildren();const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='Choose a video';placeholder.disabled=true;placeholder.selected=true;$('player-choice').append(placeholder);for(const [i,v] of players.entries()){const o=document.createElement('option');o.value=String(i);o.textContent=`${v.label}${v.duration?' · '+durationText(v.duration):''}`;$('player-choice').append(o)}$('player-choice-label').hidden=false;}
    else $('player-choice-label').hidden=true;
  }catch{setStatus('Could not inspect this page. You can still try its link.');}
  showSource();
}
async function verifyPage(capturedSource=source,capturedPage=pageSnapshot){
  const tab=await api.tabs.get(capturedSource.id);if(!tab||tab.incognito||tab.url!==capturedSource.url)throw new Error('The video page changed. Reopen LessonShelf.');
  if(!capturedPage)return null;
  const r=await api.scripting.executeScript({target:{tabId:capturedSource.id},func:inspectPage});const now=r[0]?.result;
  if(!now||now.url!==capturedPage.url||now.documentStamp!==capturedPage.documentStamp)throw new Error('The video page changed. Reopen LessonShelf.');return now;
}
function askConsent(){if(!firefox||consent)return Promise.resolve(true);return api.permissions.request(dataPermissions);}
async function native(request){const result=await api.runtime.sendMessage({type:'native',request:{requestId:crypto.randomUUID(),...request}});if(!result?.ok)throw new Error(result?.error||'The local downloader did not respond.');return result;}
function resolveWithinLimit(request){let timer;return Promise.race([native(request),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('The local downloader did not respond. Check Help & setup, then try again.')),45000)})]).finally(()=>clearTimeout(timer));}
function settings(){const course=$('course').value.trim();if(course&&(/[\\/]|^\.{1,2}$/.test(course)))throw new Error('Use a course name without slashes.');return {quality:$('quality').value,audio:$('audio').value==='audio',captions:$('captions').value==='english',copy:$('copy').value,course,engine:'auto',outputFormat:$('output-format').value||'standard'};}
function beginDownload(){
  if(privateMode||busy||(boundJob()&&activeStatuses.includes(boundJob().status)))return;
  const selectedSource=source&&{...source},selectedPage=pageSnapshot&&{...pageSnapshot},selectedVideo=selectedPlayer()&&{...selectedPlayer()};
  const retryJob=boundJob()&&['paused','failed','cancelled'].includes(boundJob().status)?boundJob():null;
  let options,url,pasted;try{options=settings();pasted=!$('paste-area').hidden;url=validURL(pasted?$('url').value.trim():selectedSource?.url||'');}catch(e){setStatus(e.message||'Enter a valid video link.');return;}
  busy=true;setStatus('Preparing video…');renderCurrent(lastJobs);
  let permission;try{permission=askConsent()}catch(e){permission=Promise.reject(e)}
  (async()=>{
    if(!await permission){setStatus('Permission was not granted. You can try again.');return;}
    consent=true;syncConsent();let verifiedManifest=false;
    if(retryJob){if(!pasted)await verifyPage(selectedSource,selectedPage);const action=retryJob.status==='paused'?'resume':'retry';const result=await native({op:action,id:retryJob.id});setStatus(action==='resume'?'Resuming download…':'Retrying download…');renderJobs(result.jobs||[]);return}
    if(!pasted){const now=await verifyPage(selectedSource,selectedPage);const player=selectedVideo;if(now&&player){const live=now.videos.find(v=>v.index===player.index);if(!live||Math.abs((live.duration||0)-(player.duration||0))>2)throw new Error('The video changed. Reopen LessonShelf.');
      if(/^https?:/i.test(live.src)&&/\.(mp4|webm|m3u8|mpd)(?:[?#]|$)/i.test(live.src))url=validURL(live.src);
      else if(now.resources.length&&live.duration>0){setStatus('Finding this video…');const found=await resolveWithinLimit({op:'resolve',candidates:now.resources,duration:live.duration,quality:options.quality});if(found.url){url=validURL(found.url);verifiedManifest=true;}}
    }}
    const r=await native({op:'enqueue',jobs:[{url,pageUrl:pasted?url:selectedSource.url,title:pasted?(safeSite(url)||'Video'):selectedSource.title,...options,verifiedManifest}]});
    lastJobId=r.jobIds?.[0]||null;if(pasted)pasteBinding=lastJobId?{id:lastJobId,url}:null;if(lastJobId&&!pasted&&selectedPage){lastDownload={id:lastJobId,tabId:selectedSource.id,stamp:selectedPage.documentStamp,playerIndex:selectedVideo?.index??null};lastDownloads=[lastDownload,...lastDownloads.filter(x=>!(x.tabId===lastDownload.tabId&&x.stamp===lastDownload.stamp&&x.playerIndex===lastDownload.playerIndex))].slice(0,50);await api.storage.local.set({lastDownload,lastDownloads})}setStatus('Added to downloads.');renderJobs(r.jobs||[]);
  })().catch(e=>setStatus(e.message||'Could not start the download.')).finally(()=>{busy=false;renderCurrent(lastJobs);if(consent)refreshStatus()});
}
function renderCurrent(jobs){
  lastJobs=jobs;
  const selected=selectedPlayer();const bound=lastDownload&&source&&pageSnapshot&&lastDownload.tabId===source.id&&lastDownload.stamp===pageSnapshot.documentStamp&&(lastDownload.playerIndex===undefined?players.length<=1:lastDownload.playerIndex===(selected?.index??null));
  const previous=currentJob,usingPaste=!$('paste-area').hidden;let pastedURL='';try{if(usingPaste)pastedURL=validURL($('url').value.trim())}catch{}
  if(usingPaste)currentJob=pasteBinding&&pasteBinding.url===pastedURL?jobs.find(x=>x.id===pasteBinding.id)||null:null;
  else currentJob=bound?jobs.find(x=>x.id===lastDownload.id)||null:null;
  if(previous&&!currentJob&&!busy&&$('status').textContent===jobStatusText){setStatus('');jobStatusText=''}
  const job=boundJob(),progress=$('download-progress');
  progress.hidden=!(busy||(job&&activeStatuses.includes(job.status)));
  if(!progress.hidden){const known=!busy&&job&&job.status==='running'&&job.message==='Downloading'&&Number.isFinite(job.progress);if(known){progress.value=Math.max(0,Math.min(100,job.progress));}else progress.removeAttribute('value');}
  if(job&&!busy&&$('queue-view').hidden){let message=jobMessage(job)||jobLabel(job);if(activeStatuses.includes(job.status)){message=jobLabel(job);if(!progress.hidden&&progress.hasAttribute?.('value'))message+=` (${Math.round(job.progress)}%)`;}setStatus(message);jobStatusText=message}
  showSource();
}
function renderJobs(jobs=[]){
  renderCurrent(jobs);
  const signature=JSON.stringify(jobs);if(signature===lastRenderedJobs)return;lastRenderedJobs=signature;const focused=$('jobs').contains?.(document.activeElement)?document.activeElement?.getAttribute?.('aria-label'):null;const openIds=new Set([...($('jobs').querySelectorAll?.('.job')||[])].filter(row=>row.querySelector?.('details')?.open).map(row=>row.dataset.jobId));const scroll=$('jobs').scrollTop;
  $('jobs').replaceChildren();if(!jobs.length){const p=document.createElement('p');p.className='empty';p.textContent='No downloads yet.';$('jobs').append(p);return;}
  for(const job of jobs){const card=document.createElement('div');card.className='job';if(card.dataset)card.dataset.jobId=job.id;const head=document.createElement('div');head.className='job-header';const title=document.createElement('span');title.className='job-title';title.textContent=job.title||'Video';const badge=document.createElement('span');badge.className='badge';badge.textContent=jobLabel(job);head.append(title,badge);card.append(head);
    if(activeStatuses.includes(job.status)){const progress=document.createElement('progress');progress.max=100;if(job.status==='running'&&job.message==='Downloading'&&Number.isFinite(job.progress))progress.value=Math.max(0,Math.min(100,job.progress));progress.setAttribute('aria-label',`Progress for ${title.textContent}`);card.append(progress)}
    const msg=document.createElement('div');msg.className='job-message';msg.textContent=jobMessage(job);card.append(msg);const acts=document.createElement('div');acts.className='job-actions';let ops=[];if(['running','queued','retrying','processing'].includes(job.status))ops=['pause','cancel'];else if(job.status==='paused')ops=['resume','cancel'];else if(['failed','cancelled'].includes(job.status))ops=['retry'];if(['complete','complete-warning'].includes(job.status)&&job.files?.length)ops.push('reveal');
    for(const op of ops){const button=document.createElement('button');button.textContent=op==='reveal'?'Show in Finder':op[0].toUpperCase()+op.slice(1);button.setAttribute('aria-label',`${button.textContent} ${title.textContent}`);button.addEventListener('click',()=>{button.disabled=true;native({op,id:job.id}).then(r=>{button.disabled=false;renderJobs(r.jobs||[])}).catch(e=>{$('queue-access').textContent=e.message;button.disabled=false})});acts.append(button)}card.append(acts);if(Array.isArray(job.files)&&job.files.length){const details=document.createElement('details'),summary=document.createElement('summary');details.open=openIds.has(job.id);summary.textContent='Saved files';details.append(summary);for(const path of job.files){const item=document.createElement('div');item.className='job-message';item.textContent=path;details.append(item)}card.append(details)}$('jobs').append(card);
  }
  if(scroll!==undefined)$('jobs').scrollTop=scroll;if(focused){const target=[...($('jobs').querySelectorAll?.('button')||[])].find(x=>x.getAttribute('aria-label')===focused);target?.focus();}
}
function bindCurrent(){lastDownload=lastDownloads.find(x=>source&&pageSnapshot&&x.tabId===source.id&&x.stamp===pageSnapshot.documentStamp&&(x.playerIndex===undefined?players.length<=1:x.playerIndex===(selectedPlayer()?.index??null)))||null;lastJobId=lastDownload?.id||null;renderCurrent(lastJobs)}
async function refreshStatus(){if(privateMode||!consent||polling)return false;polling=true;try{const r=await native({op:'status'});$('queue-access').textContent='';renderJobs(r.jobs||[]);$('queue-check').hidden=true;return true}catch(e){$('queue-access').textContent=e.message;$('queue-check').hidden=false;$('jobs').replaceChildren();lastRenderedJobs='';if(!$('queue-view').hidden)setStatus('');return false;}finally{polling=false}}
function allowQueue(){if(privateMode)return;let request;try{request=askConsent()}catch(e){request=Promise.reject(e)}Promise.resolve(request).then(ok=>{if(!ok){$('queue-access').textContent='Permission was not granted. You can try again.';return}consent=true;syncConsent();$('queue-allow').hidden=true;return refreshStatus()}).catch(e=>{$('queue-access').textContent=e.message})}
$('download').addEventListener('click',()=>{const job=boundJob();if(job&&['complete','complete-warning'].includes(job.status)&&job.files?.length){native({op:'reveal',id:job.id}).catch(e=>setStatus(e.message));return}beginDownload()});
$('show-file').addEventListener('click',()=>{if(privateMode||!boundJob())return;native({op:'reveal',id:boundJob().id}).catch(e=>setStatus(e.message))});
$('theme').addEventListener('click',()=>{const t=document.documentElement.dataset.theme==='dark'?'light':'dark';setTheme(t);api.storage.local.set({theme:t})});
$('paste').addEventListener('click',()=>{$('paste-area').hidden=!$('paste-area').hidden;if(!$('paste-area').hidden){$('url').focus()}else $('url').value='';setStatus('');renderCurrent(lastJobs)});$('url').addEventListener('input',()=>renderCurrent(lastJobs));$('player-choice').addEventListener('change',()=>{bindCurrent();refreshStatus()});
$('downloads').addEventListener('click',()=>{if(privateMode)return;$('video-view').hidden=true;$('queue-view').hidden=false;$('queue-title').focus();if(!consent){$('queue-access').textContent='Allow access to view your downloads.';$('queue-allow').hidden=false;$('jobs').replaceChildren()}else refreshStatus()});$('back').addEventListener('click',()=>{if(privateMode)return;$('queue-view').hidden=true;$('video-view').hidden=false;$('downloads').focus()});$('queue-allow').addEventListener('click',allowQueue);
$('direct-download').addEventListener('click',async()=>{if(privateMode)return;try{const url=validURL($('url').value.trim());await api.downloads.download({url,saveAs:false});setStatus('Browser download started. Original quality.') }catch(e){setStatus(e.message||'The browser download could not start.')}});
$('reconnect').addEventListener('click',()=>{if(privateMode)return;let request;try{request=askConsent()}catch(e){request=Promise.reject(e)}Promise.resolve(request).then(ok=>{if(!ok)throw new Error('Permission was not granted.');consent=true;syncConsent();return refreshStatus()}).then(ok=>setStatus(ok?'Connected.':'Could not connect. Check Help & setup.')).catch(e=>setStatus(e.message))});
$('queue-check').addEventListener('click',()=>refreshStatus());
$('doctor').addEventListener('click',()=>{if(privateMode)return;let request;try{request=askConsent()}catch(e){request=Promise.reject(e)}Promise.resolve(request).then(ok=>{if(!ok)throw new Error('Permission was not granted.');consent=true;syncConsent();return native({op:'doctor'})}).then(r=>{$('doctor-result').textContent=['yt-dlp','ffmpeg','ffprobe','N_m3u8DL-RE'].map(k=>`${k}: ${r.doctor?.[k]?.available?(k==='N_m3u8DL-RE'?'available; checked per video':'available'):'not found'}`).join('\n')}).catch(e=>{$('doctor-result').textContent=e.message})});
function updateAudioControls(){const audio=$('audio').value==='audio';$('quality').disabled=audio;$('output-format').disabled=audio;$('quality-hint').hidden=audio||$('quality').value==='best';}
for(const id of settingIds)$(id).addEventListener('change',()=>{updateAudioControls();const saved={};for(const key of settingIds)saved[key]=$(key).value;api.storage.local.set({settings:saved})});
(async()=>{if(privateMode){$('video-view').hidden=true;$('queue-view').hidden=false;$('queue-access').textContent='LessonShelf is unavailable in private browsing. Open a regular window.';$('back').hidden=true;$('queue-allow').hidden=true;return}const {theme='light',settings:saved={},lastDownload:stored=null,lastDownloads:storedList=[]}=await api.storage.local.get(['theme','settings','lastDownload','lastDownloads']);lastDownloads=Array.isArray(storedList)?storedList:[];if(stored&&!lastDownloads.some(x=>x.id===stored.id))lastDownloads.push(stored);setTheme(theme);for(const id of settingIds)if(saved[id]!==undefined&&[...($(id).options||[])].some(o=>o.value===saved[id])||id==='course'&&saved[id]!==undefined)$(id).value=saved[id];updateAudioControls();if(firefox){try{consent=await api.permissions.contains(dataPermissions)}catch{consent=false}}syncConsent();await scanCurrent();bindCurrent();if(consent)refreshStatus();setInterval(refreshStatus,2000)})().catch(()=>setStatus('Could not open LessonShelf. Try again.'));
