/* No content-script message bridge: only extension-owned pages may command the host. */
const api = globalThis.browser || chrome;
const HOST = 'org.teacher.video_downloader';
api.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== api.runtime.id || !sender.url?.startsWith(api.runtime.getURL('')) || sender.incognito || sender.tab?.incognito || message?.type !== 'native') return false;
  const allowed = ['status','enqueue','pause','resume','cancel','retry','doctor','resolve','reveal'];
  if (!allowed.includes(message.request?.op)) { respond({ok:false,error:'Unknown command'}); return false; }
  (async()=>{
    if(api.runtime.getManifest().browser_specific_settings?.gecko){
      const granted=await api.permissions.contains({data_collection:['browsingActivity','websiteContent']});
      if(!granted)return {ok:false,error:'Allow local companion access to view or manage the queue. Direct browser downloads remain available.'};
    }
    return await api.runtime.sendNativeMessage(HOST,message.request);
  })().then(respond).catch(() => respond({ok:false,error:'Local companion not connected. Direct file downloads still work in your browser. Open Help & setup to check the connection.',missingHost:true}));
  return true;
});
// Remove legacy captured links at startup; they are no longer collected.
api.runtime.onStartup.addListener(() => api.storage.local.remove('captured'));
