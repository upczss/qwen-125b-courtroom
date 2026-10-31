/* Shared court UI, using the existing personal chat renderer and theme. */
(() => {
    const $ = id => document.getElementById(id);
    const roles = {judge:'法官', admin:'管理员', plaintiff:'原告', defendant:'被告', pending:'待分配', observer:'旁听者', discussant:'历史讨论者'};
    let mode = 'personal', user = null, room = null, rooms = [], source = null;
    let seen = new Set(), preview = null, version = 0;
    let personalDraft = '', courtDraft = '';
    const modeBar = document.createElement('div');
    modeBar.className = 'mode-switch';
    modeBar.innerHTML = '<button id="personalMode" class="selected">个人对话</button><button id="courtMode">模拟法庭</button>';
    $('newChat').before(modeBar);
    const actions = document.createElement('div');
    actions.id = 'courtActions'; actions.hidden = true; actions.className = 'court-actions';
    actions.innerHTML = '<button id="createCourt" class="new-chat">＋ 创建法庭</button><button id="joinCourt" class="court-button">加入法庭</button>';
    $('newChat').after(actions);
    const toolbar = document.createElement('div');
    toolbar.id = 'courtToolbar'; toolbar.hidden = true;
    toolbar.innerHTML = '<span id="courtPhase" class="court-badge"></span><span id="courtRole" class="court-badge"></span><span id="courtLive"></span><div class="court-tools"><button id="courtMembers">成员</button><button id="courtPhaseToggle">切换阶段</button><button id="courtAI">申请AI回答</button><button id="courtLeave">退出法庭</button></div>';
    document.querySelector('.header').after(toolbar);
    const hint = document.createElement('div'); hint.id = 'courtHint'; hint.hidden = true;
    $('chatForm').before(hint);
    const modal = document.createElement('dialog'); modal.className = 'court-dialog';
    modal.innerHTML = '<form id="courtDialogForm"><h2 id="courtDialogTitle"></h2><div id="courtDialogBody"></div><p id="courtDialogError" role="alert"></p><div class="dialog-actions"><button type="button" id="courtDialogClose">关闭</button><button type="submit" id="courtDialogSubmit" class="auth-submit">确认</button></div></form>';
    document.body.append(modal);
    const safe = fn => async (...args) => {try {await fn(...args);} catch(e) {alert(e.message);}};
    const post = (url, body={}) => requestJson(url, {method:'POST', body:JSON.stringify(body)});
    function closeFeed() {if(source) source.close(); source=null; version++;}
    function manager() {return room && ['judge','admin'].includes(room.role);}
    function styleSpeaker(el, message) {
        const role=message.kind==='ai'?'ai':message.role;
        const left=['ai','judge','admin'].includes(role);
        el.wrapper.classList.remove('user','assistant');
        el.wrapper.classList.add(left?'assistant':'user','court-message','court-speaker-'+role);
        const own=message.user_id===user?.id?'（我）':'';
        el.wrapper.querySelector('.message-name').textContent=message.kind==='ai'?'AI助手':message.username+own+' · '+(roles[role]||'成员');
        const avatar=el.wrapper.querySelector('.avatar');
        avatar.textContent=role==='ai'?'AI':role==='judge'?'⚖':message.username.slice(0,2);
        const palette=['#6479a1','#7c73a5','#527f86','#8b778a'];
        avatar.style.setProperty('--court-avatar',palette[Math.abs(message.user_id||0)%palette.length]);
        // Human statements stay plain text even when positioned on the assistant's side.
        if(message.kind!=='ai')renderMessageContent(el.contentElement,message.content,'user');
    }
    function dialog(title, build, submit=null) {
        $('courtDialogTitle').textContent=title; $('courtDialogBody').replaceChildren(); $('courtDialogError').textContent='';
        $('courtDialogSubmit').hidden=!submit; build($('courtDialogBody'));
        $('courtDialogForm').onsubmit=async e=>{e.preventDefault(); if(!submit)return; $('courtDialogSubmit').disabled=true; try {await submit();modal.close();} catch(err){$('courtDialogError').textContent=err.message;} finally{$('courtDialogSubmit').disabled=false;}};
        modal.showModal();
    }
    $('courtDialogClose').onclick=()=>modal.close();
    function field(body, label, id, multiline=false) {
        const el=document.createElement('label'); el.textContent=label;
        const input=document.createElement(multiline?'textarea':'input'); input.id=id; input.className='auth-input'; input.required=true; input.maxLength=multiline?12000:100;
        el.append(input);body.append(el); return input;
    }
    async function refreshRooms() {rooms=await requestJson('/api/courts');if(mode==='court')renderRooms();}
    function renderRooms() {
        conversationList.replaceChildren();
        rooms.forEach(r=>{const row=document.createElement('div');row.className='conversation'+(room?.id===r.id?' active':'');const name=document.createElement('span');name.className='conversation-title';name.textContent='⚖ '+r.name;row.append(name);row.onclick=safe(()=>openRoom(r.id));conversationList.append(row);});
    }
    function emptyCourt() {
        headerTitle.textContent='模拟法庭';messagesElement.replaceChildren();
        const box=document.createElement('div');box.className='welcome';
        box.innerHTML='<div class="welcome-icon">⚖</div><h1>一起讨论，同步思考</h1><p>创建法庭并分享邀请码，或加入已有法庭。<br>每个法庭最多10人，成员共享讨论记录。</p><div class="court-empty-actions"><button class="court-button" id="emptyCreate">创建法庭</button><button class="court-button" id="emptyJoin">加入法庭</button></div>';
        messagesElement.append(box);$('emptyCreate').onclick=createDialog;$('emptyJoin').onclick=joinDialog;
        toolbar.hidden=true;messageInput.disabled=true;sendButton.disabled=true;hint.textContent='请先创建或加入法庭';
    }
    async function switchMode(next, restore=true) {
        if(isGenerating){alert('请等待个人对话回答结束后切换');return;}
        if(mode==='personal')personalDraft=messageInput.value;else courtDraft=messageInput.value;
        closeFeed(); mode=next; messageInput.value=mode==='personal'?personalDraft:courtDraft;resizeInput();
        $('personalMode').classList.toggle('selected',mode==='personal');$('courtMode').classList.toggle('selected',mode==='court');
        $('newChat').hidden=mode==='court';actions.hidden=mode!=='court';hint.hidden=mode!=='court';
        document.querySelector('.sidebar-label').textContent=mode==='court'?'我的法庭':'历史对话';
        if(mode==='personal') {toolbar.hidden=true;messageInput.disabled=false;sendButton.disabled=false;messageInput.placeholder='描述你的法律问题……';renderConversations();if(currentConversationId)await selectConversation(currentConversationId);else showWelcome();location.hash=currentConversationId?'chat/'+currentConversationId:'personal';}
        else {await refreshRooms(); if(restore&&room)await openRoom(room.id);else {emptyCourt();location.hash='courts';}}
    }
    async function openRoom(id) {
        closeFeed();const token=version;room=await requestJson('/api/courts/'+id);
        if(mode!=='court'||token!==version)return;
        seen=new Set();preview=null;messagesElement.replaceChildren(); apply(room);renderRooms();location.hash='court/'+id;
        source=new EventSource('/api/courts/'+id+'/events');
        source.onmessage=e=>{if(token===version&&mode==='court'){apply(JSON.parse(e.data));$('courtLive').textContent='● 已同步';}};
        source.addEventListener('ai_progress',e=>{if(token===version&&mode==='court'&&room){apply({...room,messages:[],ai:JSON.parse(e.data).ai});}});
        source.onerror=()=>{if(mode==='court')$('courtLive').textContent='连接中断，正在重连…';};
        source.addEventListener('access_lost',safe(async()=>{closeFeed();room=null;await refreshRooms();emptyCourt();await requestJson('/api/auth/me');}));
    }
    function apply(state) {
        room=state;toolbar.hidden=false;headerTitle.textContent=room.name;
        $('courtPhase').textContent=room.phase==='ai'?'AI阶段':'自由讨论';$('courtRole').textContent=roles[room.role];
        $('courtMembers').textContent='成员 '+room.members.length+'/10';$('courtLeave').hidden=room.role==='judge';
        $('courtPhaseToggle').hidden=!manager();$('courtAI').hidden=!manager();
        $('courtPhaseToggle').textContent=room.phase==='ai'?'返回自由讨论':'进入AI阶段';
        $('courtPhaseToggle').disabled=!!room.ai;$('courtAI').disabled=!!room.ai||room.phase!=='ai';
        const canSpeak=['judge','admin','plaintiff','defendant'].includes(room.role)&&(room.phase==='discussion'||manager());
        messageInput.disabled=!canSpeak;sendButton.disabled=!canSpeak;
        messageInput.placeholder=canSpeak?'发表你的讨论观点……':'当前身份或阶段不能发言';
        hint.textContent=['observer','pending'].includes(room.role)?(room.role==='pending'?'请等待法官分配身份，当前只能查看':'旁听者可查看消息，不能发言'):!canSpeak?'AI阶段仅法官和管理员可以发言':room.ai?'AI分析进行中；新发言留给下一次分析':'发言不会自动触发AI；由法官或管理员申请分析';
        for(const m of room.messages) {
            if(seen.has(m.id))continue;seen.add(m.id);
            if(m.kind==='system'){
                if(preview&&!room.ai&&m.content.startsWith('AI请求失败')){preview.wrapper.remove();preview=null;}
                const el=document.createElement('div');el.className='court-notice';el.textContent=m.content;
                messagesElement.insertBefore(el,preview?.wrapper||null);continue;
            }
            let el;
            if(m.kind==='ai'&&preview&&!room.ai){
                el=preview;if(el.thinking)el.thinking.remove();preview=null;
                renderMessageContent(el.contentElement,m.content);
                el.contentElement.classList.remove('streaming');
            }else{
                el=appendMessage(m.kind==='ai'?'assistant':'user',m.content);
                if(preview)messagesElement.insertBefore(el.wrapper,preview.wrapper);
            }
            styleSpeaker(el,m);
        }
        if(room.ai) {
            if(!preview){
                preview=appendMessage('assistant','',true);
                preview.wrapper.classList.add('court-ai-live');
                styleSpeaker(preview,{kind:'ai',role:'assistant',username:'AI助手',user_id:null});
            }
            if(room.ai.reasoning && !room.ai.text) {
                if(!preview.thinking){preview.thinking=document.createElement('div');preview.thinking.className='thinking-preview';preview.contentElement.before(preview.thinking);}
                preview.thinking.textContent=room.ai.reasoning;preview.thinking.scrollTop=preview.thinking.scrollHeight;
            } else if(preview.thinking){preview.thinking.remove();preview.thinking=null;}
            const nextText=room.ai.text||(room.ai.status==='thinking'?'':room.ai.status==='queued'?'等待生成名额…':'正在准备回答…');
            if(preview.lastText!==nextText){
                renderMessageContent(preview.contentElement,nextText);
                preview.lastText=nextText;
            }
            preview.wrapper.querySelector('.message-name').textContent='AI助手 · '+({queued:'排队中',preparing:'准备中',thinking:'思考中',generating:'生成中'}[room.ai.status]||'处理中')+' · 基于申请前的讨论';
            // Never reinsert the live bubble: reinsertion restarts the message entrance animation.
        }
        scrollToBottom();
    }
    function createDialog() {dialog('创建法庭',body=>field(body,'法庭名称','courtName'),async()=>{const r=await post('/api/courts',{name:$('courtName').value});await refreshRooms();await openRoom(r.id);});}
    function joinDialog() {dialog('加入法庭',body=>field(body,'输入邀请码','courtCode'),async()=>{const r=await post('/api/courts/join',{code:$('courtCode').value});await refreshRooms();await openRoom(r.id);});}
    function membersDialog() {
        dialog('成员与权限',body=>{
            if(room.invite_code){const code=document.createElement('p');code.textContent='邀请码：'+room.invite_code;body.append(code);}
            room.members.forEach(m=>{const row=document.createElement('div');row.className='court-member';const label=document.createElement('span');label.textContent=m.username+' · '+roles[m.role];row.append(label);
                if(room.role==='judge'&&m.role!=='judge') {const select=document.createElement('select');for(const role of ['admin','plaintiff','defendant','observer','pending']){const o=new Option(roles[role],role);select.add(o);}select.value=m.role;select.disabled=!!room.ai;select.onchange=async()=>{select.disabled=true;try{await post(`/api/courts/${room.id}/members/${m.user_id}/role`,{role:select.value});room=await requestJson('/api/courts/'+room.id);modal.close();membersDialog();}catch(e){alert(e.message);select.value=m.role;select.disabled=false;}};row.append(select);}
                body.append(row);
            });
        });
    }
    $('personalMode').onclick=safe(()=>switchMode('personal'));$('courtMode').onclick=safe(()=>switchMode('court'));
    $('createCourt').onclick=createDialog;$('joinCourt').onclick=joinDialog;$('courtMembers').onclick=membersDialog;
    $('courtPhaseToggle').onclick=safe(()=>post('/api/courts/'+room.id+'/phase',{phase:room.phase==='ai'?'discussion':'ai'}));
    $('courtAI').onclick=()=>dialog('申请AI分析',body=>field(body,'希望AI分析什么？','courtQuestion',true),()=>post('/api/courts/'+room.id+'/ai',{content:$('courtQuestion').value,generation:window.getGenerationSettings()}));
    $('courtLeave').onclick=safe(async()=>{if(!confirm('退出后将不再看到该法庭记录，是否继续？'))return;await post('/api/courts/'+room.id+'/leave');closeFeed();room=null;await refreshRooms();emptyCourt();location.hash='courts';});
    $('chatForm').addEventListener('submit',async e=>{
        if(mode!=='court')return;e.preventDefault();e.stopImmediatePropagation();const text=messageInput.value.trim();if(!text||messageInput.disabled)return;
        const target=room.id;sendButton.disabled=true;try{await post('/api/courts/'+target+'/messages',{content:text});messageInput.value='';resizeInput();}catch(err){alert(err.message);}finally{if(room?.id===target)sendButton.disabled=messageInput.disabled;}
    },true);
    window.courtUI={
        async signedIn(u){user=u;const hash=location.hash.slice(1);if(hash.startsWith('court')){await switchMode('court',false);const match=hash.match(/^court\/(\d+)$/);if(match)await safe(()=>openRoom(Number(match[1])))();}else if(hash.startsWith('chat/')){const id=Number(hash.split('/')[1]);if(conversations.some(c=>c.id===id))await selectConversation(id);}},
        reset(){closeFeed();room=null;rooms=[];user=null;mode='personal';modal.close();toolbar.hidden=true;actions.hidden=true;hint.hidden=true;$('newChat').hidden=false;messageInput.disabled=false;sendButton.disabled=false;$('personalMode').classList.add('selected');$('courtMode').classList.remove('selected');personalDraft='';courtDraft='';location.hash='personal';}
    };
})();
