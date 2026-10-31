"""Two authenticated SSE readers verify real local vLLM fanout and persisted answer."""
import asyncio,secrets,httpx,os,time
from sqlalchemy import delete
from backend.database import SessionLocal,User,CourtRoom,Conversation
from backend.auth import hasher,store,session_key

async def main():
    with SessionLocal() as db:
        users=[User(username='court_live_'+secrets.token_hex(4),password_hash=hasher.hash('Live-Preview-2026')) for _ in range(2)]
        db.add_all(users);db.commit();uids=[u.id for u in users];names=[u.username for u in users]
    rid=None
    clients=[httpx.AsyncClient(base_url=os.getenv('COURT_TEST_URL','http://127.0.0.1:8010'),trust_env=False,timeout=120) for _ in range(2)]
    try:
        for c,name in zip(clients,names):
            r=await c.post('/api/auth/login',json={'username':name,'password':'Live-Preview-2026'});r.raise_for_status()
        a,b=clients
        r=await a.post('/api/courts',json={'name':'双客户端实时流验收'});r.raise_for_status();room=r.json();rid=room['id'];base=f'/api/courts/{rid}'
        (await b.post('/api/courts/join',json={'code':room['invite_code']})).raise_for_status()
        (await a.post(base+'/phase',json={'phase':'ai'})).raise_for_status()
        import json
        async def watch(c):
            saw_ai=False
            partials=[]
            async with c.stream('GET',base+'/events') as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith('data: '):continue
                    state=json.loads(line[6:])
                    if state.get('ai'):
                        saw_ai=True
                        text=state['ai'].get('text','')
                        if text and (not partials or text!=partials[-1][1]):partials.append((time.monotonic(),text))
                    for m in state.get('messages',[]):
                        if m['kind']=='ai':return saw_ai,m['id'],m['content'],partials
        watchers=[asyncio.create_task(watch(c)) for c in clients]
        await asyncio.sleep(.3)
        (await a.post(base+'/ai',json={'content':'请简短解释模拟法庭讨论前为什么要明确争议焦点。用四条说明。'})).raise_for_status()
        results=await asyncio.wait_for(asyncio.gather(*watchers),120)
        assert results[0][1:3]==results[1][1:3] and all(r[0] for r in results),results
        assert all(len(r[3])>=3 and len(r[3][0][1])<len(r[2]) and r[3][-1][0]-r[3][0][0]>.1 for r in results), 'Output was buffered, not incremental'
        assert all('[97]' not in r[2] for r in results)
        print('PASS two authenticated SSE readers received shared AI state and identical saved real-vLLM answer',results[0][1],len(results[0][2]))
        print('Distinct partial outputs per reader:',[len(r[3]) for r in results])
    finally:
        for c in clients:
            token=c.cookies.get('qwen_session')
            if token:store.delete(session_key(token))
            await c.aclose()
        with SessionLocal() as db:
            if rid:db.execute(delete(CourtRoom).where(CourtRoom.id==rid))
            db.execute(delete(User).where(User.id.in_(uids)));db.commit()

if __name__=='__main__':asyncio.run(main())
