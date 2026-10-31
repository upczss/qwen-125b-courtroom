"""Live account-isolation and concurrent generation acceptance; removes its own data."""
import concurrent.futures
import secrets
import threading
import time
import httpx
from backend.database import SessionLocal, User, Conversation

base = 'http://127.0.0.1:8000'
names = ['verify_' + secrets.token_hex(5) for _ in range(2)]
password = secrets.token_urlsafe(18)
clients = [httpx.Client(base_url=base, timeout=120, trust_env=False) for _ in names]
barrier = threading.Barrier(2)


def stream(pair):
    client, cid = pair
    barrier.wait()
    first = None
    done = False
    text = ''
    import json
    with client.stream('POST', f'/api/conversations/{cid}/messages/stream',
                       json={'content': '请详细分十节介绍企业系统架构。'}) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if not line.startswith('data: '):
                continue
            event = json.loads(line[6:])
            assert event['type'] != 'error', event
            if event['type'] == 'delta':
                first = first or time.perf_counter()
                text += event['content']
            if event['type'] == 'done':
                assert event['assistant_message']['content'] == text.strip()
                done = True
    end = time.perf_counter()
    assert done and first
    messages = client.get(f'/api/conversations/{cid}/messages').json()
    assert [m['role'] for m in messages] == ['user', 'assistant']
    assert messages[-1]['content'] == text.strip()
    return first, end


try:
    assert httpx.get(base + '/api/conversations').status_code == 401
    ids = []
    for client, name in zip(clients, names):
        response = client.post('/api/auth/register', json={'username': name, 'password': password})
        assert response.status_code == 201, response.text
        assert 'HttpOnly' in response.headers['set-cookie']
        assert client.get('/api/auth/me').json()['username'] == name
        ids.append(client.post('/api/conversations', json={'title': '验收临时会话'}).json()['id'])
    assert clients[0].post('/api/auth/register', json={'username': names[0], 'password': password}).status_code == 409
    for index, client in enumerate(clients):
        other = ids[1-index]
        assert {x['id'] for x in client.get('/api/conversations').json()} == {ids[index]}
        assert client.get(f'/api/conversations/{other}/messages').status_code == 404
        assert client.delete(f'/api/conversations/{other}').status_code == 404
        for suffix in ('messages', 'messages/stream'):
            assert client.post(f'/api/conversations/{other}/{suffix}', json={'content': '越权测试'}).status_code == 404
    assert clients[0].post('/api/conversations', json={}, headers={'Origin': 'https://evil.example'}).status_code == 403
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results = list(pool.map(stream, zip(clients, ids)))
    overlap = min(x[1] for x in results) - max(x[0] for x in results)
    assert overlap > 0
    for client, name in zip(clients, names):
        old = client.cookies.get('qwen_session')
        assert client.post('/api/auth/logout', json={}).status_code == 200
        assert client.get('/api/conversations').status_code == 401
        assert httpx.get(base+'/api/auth/me', headers={'Cookie': 'qwen_session='+old}).status_code == 401
        assert client.post('/api/auth/login', json={'username': name, 'password': 'incorrect_password'}).status_code == 401
        assert client.post('/api/auth/login', json={'username': name, 'password': password}).status_code == 200
        assert len(client.get('/api/conversations').json()) == 1
        client.post('/api/auth/logout', json={})
    print(f'PASS: registration/login/logout, cookie revocation, ownership, CSRF, PostgreSQL persistence; two-account output overlap={overlap:.2f}s')
finally:
    for client in clients:
        client.close()
    with SessionLocal() as db:
        users = db.query(User).filter(User.username.in_(names)).all()
        for user in users:
            for conversation in db.query(Conversation).filter(Conversation.user_id == user.id).all():
                db.delete(conversation)
            db.flush()
            db.delete(user)
        db.commit()
