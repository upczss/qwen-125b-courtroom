"""Check first-token overlap for two simultaneous streaming requests."""
import concurrent.futures
import json
import threading
import time
import urllib.request

barrier = threading.Barrier(2)


def run_request(number):
    payload = {
        'model': 'qwen3-8b',
        'messages': [{'role': 'user', 'content': f'测试{number}：请写一篇详细介绍企业信息系统架构的中文文章，至少八个部分。'}],
        'max_tokens': 256,
        'temperature': 0,
        'stream': True,
        'chat_template_kwargs': {'enable_thinking': False},
    }
    request = urllib.request.Request(
        'http://127.0.0.1:8001/v1/chat/completions',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
    )
    barrier.wait(timeout=30)
    start = time.perf_counter()
    first = None
    parts = []
    reason = None
    with urllib.request.urlopen(request, timeout=300) as response:
        for raw in response:
            line = raw.decode().strip()
            if not line.startswith('data: '):
                continue
            if line == 'data: [DONE]':
                break
            event = json.loads(line[6:])
            if 'error' in event:
                raise RuntimeError(event['error'])
            for choice in event.get('choices', []):
                content = choice.get('delta', {}).get('content')
                if content:
                    if first is None:
                        first = time.perf_counter()
                    parts.append(content)
                reason = choice.get('finish_reason') or reason
    end = time.perf_counter()
    if first is None or reason not in ('stop', 'length'):
        raise RuntimeError(f'Request {number} incomplete: {reason}')
    return dict(request=number, start=start, first=first, end=end,
                ttft_seconds=round(first-start, 3), total_seconds=round(end-start, 3),
                finish_reason=reason, characters=len(''.join(parts)))


if __name__ == '__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run_request, (1, 2)))
    overlap = min(r['end'] for r in results) - max(r['first'] for r in results)
    print(json.dumps({'requests': results, 'stream_overlap_seconds': round(overlap, 3),
                      'passed': overlap > 0}, ensure_ascii=False, indent=2))
    if overlap <= 0:
        raise SystemExit('No observable overlap between response streams')
