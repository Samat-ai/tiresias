const form=document.querySelector('#voice-form');
if(form){
 const status=document.querySelector('#status'),speed=document.querySelector('#speed'),output=document.querySelector('#speed-value'),audio=document.querySelector('#audio-preview');
 let audioURL;
 const companion=document.querySelector('#companion-avatar'),reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
 if(companion)companion.addEventListener('error',()=>{if(companion.getAttribute('src')!==companion.dataset.still)companion.src=companion.dataset.still});
 const showCompanion=()=>{if(companion)companion.src=(!audio.paused&&!audio.ended&&!reducedMotion.matches)?companion.dataset.speaking:companion.dataset.still};
 ['play','pause','ended','error'].forEach(event=>audio.addEventListener(event,showCompanion));
 reducedMotion.addEventListener('change',showCompanion);
 const preferences=()=>({voice_id:form.querySelector('[name=voice_id]:checked').value,tone:form.tone.value,speed:Number(speed.value)});
 const message=(text,error=false)=>{status.textContent=text;status.classList.toggle('error',error)};
 const send=async(url)=>{const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('#csrf').value},body:JSON.stringify(preferences())});if(!response.ok){let text='Something went wrong. Please try again.';try{const data=await response.json();if(typeof data.detail==='string')text=data.detail}catch{}throw new Error(text)}return response};
 speed.addEventListener('input',()=>{output.value=Number(speed.value).toFixed(2)+'×';message('You have unsaved changes.')});
 form.addEventListener('change',()=>message('You have unsaved changes.'));
 form.addEventListener('submit',async event=>{event.preventDefault();const button=document.querySelector('#save');button.disabled=true;message('Saving your preferences…');try{await send('/api/preferences');message('Saved. Your voice is ready for your next call.')}catch(error){message(error.message,true)}finally{button.disabled=false}});
 document.querySelector('#preview').addEventListener('click',async()=>{const button=document.querySelector('#preview');button.disabled=true;message('Preparing your voice preview…');try{const response=await send('/api/voice-preview');if(audioURL)URL.revokeObjectURL(audioURL);audioURL=URL.createObjectURL(await response.blob());audio.src=audioURL;audio.hidden=false;await audio.play();message('Previewing your selected voice. Save to keep these preferences.')}catch(error){message(error.message,true)}finally{button.disabled=false}});
 document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-filter]').forEach(item=>{item.classList.toggle('active',item===button);item.setAttribute('aria-pressed',String(item===button))});document.querySelectorAll('[data-gender]').forEach(item=>item.hidden=button.dataset.filter!=='all'&&item.dataset.gender!==button.dataset.filter)}));
}

const callerPanel=document.querySelector('#caller-link-panel');
if(callerPanel){
 const startForm=document.querySelector('#caller-start-form'),confirmForm=document.querySelector('#caller-confirm-form'),verifySection=document.querySelector('#caller-verify-section'),linkedText=document.querySelector('#caller-linked'),unlinkButton=document.querySelector('#caller-unlink'),notice=document.querySelector('#caller-message');
 let pending=null,pollTimer;
 const tell=(text,error=false)=>{notice.textContent=text;notice.classList.toggle('error',error)};
 const api=async(path,method='GET',body)=>{const response=await fetch(path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('#csrf').value},...(body?{body:JSON.stringify(body)}:{})});const data=await response.json();if(!response.ok)throw new Error(data.detail||data.message||'Please reload the page and try again.');return data};
 const refresh=async()=>{clearTimeout(pollTimer);try{const state=await api('/api/caller-link');pending=state.pending;linkedText.hidden=!state.linked;unlinkButton.hidden=!state.linked&&!pending;verifySection.hidden=!pending;if(state.linked)linkedText.textContent='Connected: '+state.linked.masked_handle+'. Your next calls will use your saved settings.';if(pending){tell(pending.ready?'Your call is connected. Enter the four digits Tiresias read to you.':'Ready for your setup call. Call from '+pending.masked_handle+'.');pollTimer=setTimeout(refresh,3000)}}catch(error){tell(error.message,true)}};
 const busy=async(form,action)=>{const button=form.querySelector('button');button.disabled=true;try{await action()}catch(error){tell(error.message,true)}finally{button.disabled=false}};
 startForm.addEventListener('submit',event=>{event.preventDefault();busy(startForm,async()=>{await api('/api/caller-link/request','POST',{handle:document.querySelector('#caller-handle').value});document.querySelector('#caller-code').value='';await refresh();verifySection.scrollIntoView({behavior:'smooth',block:'center'})})});
 confirmForm.addEventListener('submit',event=>{event.preventDefault();busy(confirmForm,async()=>{if(!pending)throw new Error('Start caller setup again.');await api('/api/caller-link/confirm','POST',{request_id:pending.request_id,code:document.querySelector('#caller-code').value});await refresh();tell('Connected. Future calls from this caller will load your saved voice automatically.')})});
 unlinkButton.addEventListener('click',async()=>{unlinkButton.disabled=true;try{await api('/api/caller-link','DELETE');clearTimeout(pollTimer);await refresh();tell('Caller disconnected. You can connect another number anytime.')}catch(error){tell(error.message,true)}finally{unlinkButton.disabled=false}});
 refresh();
}
