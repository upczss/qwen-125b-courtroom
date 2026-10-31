"""Three real website requests; temporary users are removed after verification."""
import concurrent.futures
import json
import secrets
import subprocess
import threading
import time
from pathlib import Path

import httpx
from backend.database import SessionLocal, User, Conversation


def main():
    clients = []
    names = []
    results = []
    monitor_stop = threading.Event()
    gpu_samples = []

    def monitor():
        while not monitor_stop.is_set():
            try:
                raw = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used',
                                               '--format=csv,noheader,nounits'], text=True)
                gpu_samples.append(int(raw.strip().splitlines()[0]))
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            monitor_stop.wait(1)

    try:
        status = httpx.get('http://127.0.0.1:8080/v1/status', trust_env=False).json()
        health = httpx.get('http://127.0.0.1:8000/api/health', trust_env=False).json()
        assert status['concurrency']['serving'] == health['generation_slots'] == 3
        for index in range(3):
            name = 'parallel3_' + secrets.token_hex(6)
            names.append(name)
            client = httpx.Client(base_url='http://127.0.0.1:8000', timeout=300, trust_env=False)
            clients.append(client)
            response = client.post('/api/auth/register', json={'username': name, 'password': secrets.token_urlsafe(20)})
            response.raise_for_status()

        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        for round_number in range(2):
            barrier = threading.Barrier(3)

            def generate(index):
                client = clients[index]
                response = client.post('/api/conversations', json={'title': 'parallel verification'})
                response.raise_for_status()
                cid = response.json()['id']
                topics = ['database transactions', 'distributed caching', 'HTTP streaming']
                prompt = f'Explain {topics[index]} in English in about 400 words, with practical examples. Round {round_number}.'
                barrier.wait()
                started = time.perf_counter()
                first = None
                done = None
                text = ''
                queued = False
                with client.stream('POST', f'/api/conversations/{cid}/messages/stream', json={'content': prompt}) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line.startswith('data: '):
                            continue
                        event = json.loads(line[6:])
                        assert event['type'] != 'error', event
                        if event['type'] == 'queued':
                            queued = True
                        if event['type'] == 'delta':
                            first = first or time.perf_counter()
                            text += event['content']
                        if event['type'] == 'done':
                            done = event
                ended = time.perf_counter()
                assert done and first and text
                assert done['assistant_message']['content'] == text.strip()
                saved = client.get(f'/api/conversations/{cid}/messages')
                saved.raise_for_status()
                assert [m['role'] for m in saved.json()] == ['user', 'assistant']
                return dict(index=index, started=started, first=first, ended=ended,
                            ttft_seconds=first-started, total_seconds=ended-started,
                            queued=queued, metrics=done['metrics'])

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                rows = list(pool.map(generate, range(3)))
            overlap = min(row['ended'] for row in rows) - max(row['first'] for row in rows)
            assert overlap > 0, rows
            results.append(dict(round=round_number+1, overlap_seconds=overlap, requests=rows))
            print(f'PASS round {round_number+1}: three streams overlap {overlap:.2f}s', flush=True)
        report = dict(strata_concurrency=status['concurrency'], website_slots=health['generation_slots'],
                      sampled_peak_gpu_mib=max(gpu_samples) if gpu_samples else None, rounds=results)
        Path(__file__).with_name('strata-three-results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2), flush=True)
    finally:
        monitor_stop.set()
        for client in clients:
            try:
                client.post('/api/auth/logout', json={})
            finally:
                client.close()
        with SessionLocal() as db:
            for user in db.query(User).filter(User.username.in_(names)).all():
                for conversation in db.query(Conversation).filter_by(user_id=user.id).all():
                    db.delete(conversation)
                db.flush()
                db.delete(user)
            db.commit()


if __name__ == '__main__':
    main()
