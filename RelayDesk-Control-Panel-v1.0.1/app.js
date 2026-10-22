const $=s=>document.querySelector(s);let loginId=null,relayId=null,relayEnabled=false;
const API_URL=(window.RELAYDESK_API_URL||'').replace(/\/$/,'');
let panelUser=localStorage.getItem('relaydesk_user')||'';
let panelPass=localStorage.getItem('relaydesk_pass')||'';
if(!panelUser) panelUser=prompt('Control-panel username','admin')||'';
if(!panelPass) panelPass=prompt('Control-panel password')||'';
localStorage.setItem('relaydesk_user',panelUser);localStorage.setItem('relaydesk_pass',panelPass);
const toast=m=>{const t=$('#toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3200)};
async function api(path,options={}){const r=await fetch(API_URL+path,{headers:{'Content-Type':'application/json','Authorization':'Basic '+btoa(panelUser+':'+panelPass),...(options.headers||{})},...options});const data=await r.json().catch(()=>({detail:'Unexpected server response'}));if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:Array.isArray(data.detail)?data.detail.map(x=>x.msg).join('; '):'Request failed');return data}
async function refresh(){try{const d=await api('/api/status');const tg=d.telegram;const destinations=$('#messageDestination');const chosen=destinations.value;const options=d.relays.map(r=>({id:String(r.id),label:r.name+' → '+r.destination_link}));const signature=JSON.stringify(options);if(destinations.dataset.signature!==signature){destinations.replaceChildren(...options.map(r=>new Option(r.label,r.id)));destinations.dataset.signature=signature;if(options.some(r=>r.id===chosen))destinations.value=chosen;}$('#connectionBadge').classList.toggle('live',tg.connected);$('#connectionBadge span').textContent=tg.connected?(tg.profile?.name||tg.profile?.username||'Telegram connected'):'Telegram not connected';$('#telegramSetup').classList.toggle('connected',tg.connected);const relay=d.relays[0];if(relay){relayId=relay.id;relayEnabled=!!relay.enabled;$('#relayName').value=relay.name;$('#sourceLink').value=relay.source_link;$('#destinationLink').value=relay.destination_link;$('#toggleRelay').textContent=relayEnabled?'Stop relay':'Start relay';$('#toggleRelay').classList.toggle('danger',relayEnabled)}$('#deliveredCount').textContent=d.stats.delivered||0;$('#failedCount').textContent=d.stats.failed||0;$('#relayCount').textContent=d.relays.length;const job=relayId&&tg.jobs?.[relayId];const importing=!!job?.running;$('#jobProgress').classList.toggle('hidden',!job);$('#cancelImport').classList.toggle('hidden',!importing);$('#importAll').disabled=importing;$('#importTest').disabled=importing;if(job)$('#jobProgress b').textContent=job.message+` · ${job.delivered} delivered · ${job.failed} failed · ${job.skipped||0} skipped`;await loadActivity()}catch(e){toast(e.message)}}
$('#sendCode').onclick=async()=>{try{const d=await api('/api/auth/request-code',{method:'POST',body:JSON.stringify({api_id:+$('#apiId').value,api_hash:$('#apiHash').value.trim(),phone:$('#phone').value.trim()})});loginId=d.login_id;$('#verifyBox').classList.remove('hidden');toast('Telegram sent your verification code')}catch(e){toast(e.message)}};
$('#confirmCode').onclick=async()=>{try{const d=await api('/api/auth/confirm',{method:'POST',body:JSON.stringify({login_id:loginId,code:$('#loginCode').value.trim()||null,password:$('#twoFactor').value||null})});if(d.needs_password){$('#passwordWrap').classList.remove('hidden');toast('Enter your Telegram two-step password');return}toast('Telegram connected successfully');await refresh()}catch(e){toast(e.message)}};
function pair(){return{source_link:$('#sourceLink').value.trim(),destination_link:$('#destinationLink').value.trim()}}
$('#checkLinks').onclick=async()=>{try{const d=await api('/api/groups/check',{method:'POST',body:JSON.stringify(pair())});$('#pairResult').innerHTML=`✓ Found <b>${d.source.title}</b> → <b>${d.destination.title}</b>`;$('#pairResult').classList.remove('hidden');toast('Both Telegram groups are reachable')}catch(e){toast(e.message)}};
$('#saveRelay').onclick=async()=>{try{const d=await api('/api/relays',{method:'POST',body:JSON.stringify({id:relayId,name:$('#relayName').value.trim()||'My relay',...pair(),import_media:true})});relayId=d.id;toast('Group connection saved');await refresh()}catch(e){toast(e.message)}};
async function startImport(limit){if(!relayId){toast('Save the group connection first');return}if(limit===0&&!confirm('Import every visible old post now? Large groups can take time.'))return;try{await api(`/api/relays/${relayId}/import`,{method:'POST',body:JSON.stringify({limit})});toast('Historical import started');await refresh()}catch(e){toast(e.message)}}
$('#importAll').onclick=()=>startImport(0);$('#importTest').onclick=()=>startImport(Math.max(1,+$('#testCount').value||10));
$('#cancelImport').onclick=async()=>{if(!relayId)return;try{const d=await api(`/api/relays/${relayId}/import/stop`,{method:'POST'});toast(d.message);await refresh()}catch(e){toast(e.message)}};
$('#newOnly').onclick=async()=>{if(!relayId){toast('Save the group connection first');return}if(!confirm('Stop importing old posts, skip everything already in the old group, and monitor only posts made after now?'))return;try{const d=await api(`/api/relays/${relayId}/new-only`,{method:'POST'});toast(d.message);await refresh()}catch(e){toast(e.message)}};
$('#toggleRelay').onclick=async()=>{if(!relayId){toast('Save the group connection first');return}try{await api(`/api/relays/${relayId}/${relayEnabled?'stop':'start'}`,{method:'POST'});toast(relayEnabled?'Relay stopped':'24/7 relay started');await refresh()}catch(e){toast(e.message)}};
async function loadActivity(){const d=await api('/api/activity?limit=100');const box=$('#activityList');if(!d.items.length){box.innerHTML='<p class="empty">No delivery activity yet.</p>';return}const icon={text:'✎',photo:'▧',video:'▶',voice:'◉',file:'▤',system:'⚙'};box.innerHTML=d.items.map(x=>`<div class="activity-item ${x.status==='delivered'?'ok':x.status==='skipped'?'skipped':'fail'}"><span class="type">${icon[x.kind]||'⌁'}</span><p><b>${escapeHtml(x.relay_name)} · ${escapeHtml(x.kind)}</b><small>Source post #${x.source_message_id}${x.error?' · '+escapeHtml(x.error):''}</small></p><time>${x.status}</time></div>`).join('')}
function escapeHtml(v){const d=document.createElement('div');d.textContent=v;return d.innerHTML}
$('#refresh').onclick=refresh;refresh();setInterval(refresh,5000);

$('#sendOwnerMessage').onclick=async()=>{
 const id=$('#messageDestination').value,text=$('#ownerMessage').value;
 if(!id){toast('Save a group connection first');return}
 if(!text.trim()){toast('Write your message first');return}
 const button=$('#sendOwnerMessage');button.disabled=true;button.textContent='Sending…';
 $('#ownerMessageStatus').textContent='Sending to the selected group…';
 try{const d=await api(`/api/relays/${id}/message`,{method:'POST',body:JSON.stringify({text})});$('#ownerMessageStatus').textContent=d.message;$('#ownerMessage').value='';toast(d.message)}
 catch(e){$('#ownerMessageStatus').textContent='Delivery could not be confirmed. Check your group before sending again. '+e.message}
 finally{button.disabled=false;button.textContent='Send to group'}
};

function formatSettings(){return {
 enabled:$('#formatEnabled').checked,default_sport:$('#formatSport').value,
 source_timezone:$('#formatTimezone').value.trim(),stake_high:$('#formatStakeHigh').checked,
 promo_platform:$('#promoPlatform').value,promo_code:$('#promoCode').value.trim(),
 crash_promo_code:$('#crashPromoCode').value.trim()
}}
async function loadPostFormat(){
 try{
  const {settings:s}=await api('/api/post-format');
  $('#formatEnabled').checked=s.enabled;$('#formatSport').value=s.default_sport;
  $('#formatTimezone').value=s.source_timezone;$('#formatStakeHigh').checked=s.stake_high;
  $('#promoPlatform').value=s.promo_platform;$('#promoCode').value=s.promo_code;
  $('#crashPromoCode').value=s.crash_promo_code;
  $('#formatStatus').textContent=s.enabled?'Category formatting is on. '+(s.promo_code||s.crash_promo_code?'Your saved promo settings are active.':'No promo code is added until you save your own.'):'Category formatting is off.';
  $('#savePostFormat').disabled=false;$('#previewPostFormat').disabled=false;
 }catch(e){$('#formatStatus').textContent='Could not load post format: '+e.message;}
}
$('#savePostFormat').onclick=async()=>{
 const b=$('#savePostFormat');b.disabled=true;
 try{const d=await api('/api/post-format',{method:'PUT',body:JSON.stringify(formatSettings())});$('#formatStatus').textContent=d.message;toast(d.message)}
 catch(e){$('#formatStatus').textContent='Not saved: '+e.message}
 finally{b.disabled=false}
};
$('#previewPostFormat').onclick=async()=>{
 const text=$('#formatSource').value.trim();if(!text){toast('Paste a post or choose an example first');return}
 const b=$('#previewPostFormat');b.disabled=true;$('#formatWarnings').textContent='Preparing preview…';$('#formatPreview').replaceChildren();
 try{
  const time=$('#formatPostedAt').value;
  const d=await api('/api/post-format/preview',{method:'POST',body:JSON.stringify({text,settings:formatSettings(),posted_at:time?new Date(time).toISOString():null})});
  $('#formatWarnings').textContent=[d.action==='skipped'?'This post would be skipped: '+d.reason:d.action==='unchanged'?'No betting details detected. Normal link filtering applies.':'Preview only — nothing has been sent.',...(d.warnings||[])].join(' ');
  if(d.cards?.length){for(const card of d.cards){const item=document.createElement('div');item.innerHTML=card.html;item.querySelectorAll('a').forEach(a=>{a.target='_blank';a.rel='noopener noreferrer'});$('#formatPreview').appendChild(item)}}
  else if(d.plain_text){const item=document.createElement('blockquote');item.textContent=d.plain_text;$('#formatPreview').appendChild(item)}
 }catch(e){$('#formatWarnings').textContent='Could not preview: '+e.message}
 finally{b.disabled=false}
};
const formatExamples={
 football:'Football combo banker on Stake\nSTAKE HIGH!\nPlay and win 1.3 million\nBet code > 674761481\nBet link https://stake.com/sports/home?iid=sport%3A674761481&source=link_shared&modal=bet\nBet code 2 > 674761233\nBet link 2 https://stake.com/sports/home?iid=sport%3A674761233&source=link_shared&modal=bet\nCreate an Account on STAKE\nhttps://stake.com/?offer=example\nUse Promo code SOURCEPROMO to get a bonus',
 table_tennis:'Table tennis on Stake\nMatch time: 6:30 pm WAT\nBet code > DEMO123\nUse Promo code SOURCEPROMO',
 crash:'CRASH SIGNAL 2\nPlatform: Stake\nGet in at 9:10 am tomorrow\nCashout at 1.30 odds\nCreate an Account on STAKE\nhttps://stake.com/?offer=example\nUse Promo code SOURCEPROMO'
};
document.querySelectorAll('[data-format-example]').forEach(button=>{button.onclick=()=>{
 $('#formatSource').value=formatExamples[button.dataset.formatExample];$('#formatPostedAt').value='';
 $('#formatWarnings').textContent='Example text only. Football codes come from the supplied screenshot; the table-tennis code is a demonstration.';
 $('#formatPreview').replaceChildren();
}});
loadPostFormat();
