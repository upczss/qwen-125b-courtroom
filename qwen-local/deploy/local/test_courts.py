"""Integration checks on PostgreSQL; fake inference isolates room orchestration."""
import asyncio
import secrets
import httpx
from fastapi import Request
from sqlalchemy import delete
from backend.main import app
from backend.auth import current_user
from backend.database import SessionLocal, User, CourtRoom, CourtMember, CourtMessage
from backend import courts
from backend.generation_queue import queue

async def main():
    prefix='court_test_'+secrets.token_hex(4)
    with SessionLocal() as db:
        users=[User(username=f'{prefix}_{i}',password_hash='test-only-no-login') for i in range(12)]
        db.add_all(users);db.commit();uids=[u.id for u in users]
    def actor(request: Request):
        with SessionLocal() as db:
            u=db.get(User,int(request.headers['x-test-user']));db.expunge(u);return u
    app.dependency_overrides[current_user]=actor
    original_prepare=courts.model_service.prepare
    original_stream=courts.model_service.stream_chat
    async def prepare(messages):return messages
    async def stream(messages,metrics):
        for text in ['共同','讨论','总结']:
            await asyncio.sleep(.15);yield text
    courts.model_service.prepare=prepare
    courts.model_service.stream_chat=stream
    rid=None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        async def call(i,method,path,body=None,expected=200):
            if method == 'POST' and body is None:
                body = {}
            r=await c.request(method,path,headers={'x-test-user':str(uids[i])},json=body)
            assert r.status_code==expected,(method,path,r.status_code,r.text)
            return r.json()
        try:
            # Personal conversations continue to work and remain private.
            private=await call(0,'POST','/api/conversations',{})
            await call(1,'GET',f'/api/conversations/{private["id"]}/messages',expected=404)
            room=await call(0,'POST','/api/courts',{'name':'权限与并发验收法庭'})
            rid=room['id'];base=f'/api/courts/{rid}'
            assert len(room['members'])==1 and room['role']=='judge'
            responses=await asyncio.gather(*[c.post('/api/courts/join',headers={'x-test-user':str(uid)},json={'code':room['invite_code']}) for uid in uids[1:]])
            assert sum(r.status_code==200 for r in responses)==9
            assert sum(r.status_code==409 for r in responses)==2
            state=await call(0,'GET',base)
            assert len(state['members'])==10
            memberids=[m['user_id'] for m in state['members'] if m['role']!='judge']
            admin=uids.index(memberids[0]);discussant=uids.index(memberids[1]);observer=uids.index(memberids[2]);defendant=uids.index(memberids[3])
            outsider=next(i for i,uid in enumerate(uids) if uid not in [m['user_id'] for m in state['members']])
            await call(outsider,'GET',base,expected=404)
            await call(outsider,'POST',base+'/messages',{'content':'越权'},expected=404)
            await call(outsider,'GET',base+'/events',expected=404)
            await call(discussant,'POST',base+'/messages',{'content':'待分配不能发言'},expected=403)
            await call(0,'POST',f'{base}/members/{uids[discussant]}/role',{'role':'plaintiff'})
            await call(0,'POST',f'{base}/members/{uids[defendant]}/role',{'role':'defendant'})
            await call(defendant,'POST',base+'/messages',{'content':'被告发言'})
            await call(0,'POST',f'{base}/members/{uids[admin]}/role',{'role':'admin'})
            await call(0,'POST',f'{base}/members/{uids[observer]}/role',{'role':'observer'})
            await call(admin,'POST',f'{base}/members/{uids[discussant]}/role',{'role':'admin'},expected=403)
            await call(0,'POST',f'{base}/members/{uids[0]}/role',{'role':'observer'},expected=400)
            await call(discussant,'POST',base+'/messages',{'content':'讨论者发言'})
            await call(observer,'POST',base+'/messages',{'content':'不应允许'},expected=403)
            await call(discussant,'POST',base+'/phase',{'phase':'ai'},expected=403)
            await call(admin,'POST',base+'/ai',{'content':'分析'},expected=409)
            await call(admin,'POST',base+'/phase',{'phase':'ai'})
            await call(discussant,'POST',base+'/messages',{'content':'AI阶段违规发言'},expected=403)
            await call(defendant,'POST',base+'/messages',{'content':'被告AI阶段违规'},expected=403)
            await call(defendant,'POST',base+'/ai',{'content':'无权限申请'},expected=403)
            await call(admin,'POST',base+'/messages',{'content':'管理员补充问题'})
            await call(observer,'POST',base+'/ai',{'content':'分析'},expected=403)
            await call(admin,'POST',base+'/ai',{'content':'归纳争议'})
            await call(0,'POST',base+'/ai',{'content':'重复'},expected=409)
            await call(0,'POST',base+'/phase',{'phase':'discussion'},expected=409)
            await call(0,'POST',f'{base}/members/{uids[observer]}/role',{'role':'plaintiff'},expected=409)
            # All members see the same live job; feed survives requester disconnect.
            a=await call(0,'GET',base);b=await call(observer,'GET',base)
            assert a['ai']==b['ai'] and 'prompt' not in a['ai']
            task=courts.jobs[rid]['task']
            await asyncio.sleep(.2)
            mid=await call(observer,'GET',base)
            assert mid['ai']['text']=='共同'
            await call(admin,'POST',base+'/messages',{'content':'生成时仍可补充'})
            await task
            final=await call(observer,'GET',base)
            assert final['ai'] is None and any(m['kind']=='ai' and m['content']=='共同讨论总结' for m in final['messages'])
            assert -rid not in queue.tickets
            # Global GPU admission is shared with personal chat; a full queue leaves no stuck room job.
            keys = list(range(900000, 900010))
            try:
                for index, key in enumerate(keys):
                    queue.reserve(key, 900000 + index)
                await call(admin,'POST',base+'/ai',{'content':'队列满时申请'},expected=429)
                assert rid not in courts.jobs
            finally:
                for key in keys:
                    queue.release(key)
            async def failed_stream(messages, metrics):
                yield '不完整内容'
                await asyncio.sleep(.1)
                raise RuntimeError('test upstream failure')
            courts.model_service.stream_chat = failed_stream
            await call(admin,'POST',base+'/ai',{'content':'失败释放验证'})
            await courts.jobs[rid]['task']
            failed = await call(observer,'GET',base)
            assert failed['ai'] is None and -rid not in queue.tickets
            assert not any(m['kind']=='ai' and m['content']=='不完整内容' for m in failed['messages'])
            assert any('AI请求失败' in m['content'] for m in failed['messages'])
            await call(admin,'POST',base+'/phase',{'phase':'discussion'})
            await call(observer,'POST',base+'/leave')
            await call(observer,'GET',base,expected=404)
            await call(outsider,'POST','/api/courts/join',{'code':room['invite_code']})
            await call(0,'POST',base+'/leave',expected=400)
            print('PASS: private chat isolation, concurrent 10-person limit, roles, stages, shared AI partial/completion, member leave and slot release')
        finally:
            if rid in courts.jobs:
                courts.jobs[rid]['task'].cancel();await asyncio.gather(courts.jobs[rid]['task'],return_exceptions=True)
            app.dependency_overrides.clear()
            courts.model_service.prepare=original_prepare;courts.model_service.stream_chat=original_stream
            with SessionLocal() as db:
                if rid:
                    db.execute(delete(CourtRoom).where(CourtRoom.id==rid))
                from backend.database import Conversation
                db.execute(delete(Conversation).where(Conversation.user_id.in_(uids)))
                db.execute(delete(User).where(User.id.in_(uids)))
                db.commit()

if __name__=='__main__':asyncio.run(main())
