import concurrent.futures
import json
import threading
import time
from pathlib import Path
import httpx

BASE = 'http://127.0.0.1:8001'

def trial(n, long_input=False):
    prompt = '请分十节详细介绍企业系统架构，每节至少300字。'
    if long_input:
        prompt = '以下是参考材料：' + '系统需要用户隔离、可靠的数据保存、流式输出和并发调度。' * 100 + prompt
    barrier = threading.Barrier(n)
    def run(index):
        with httpx.Client(base_url=BASE, timeout=180, trust_env=False) as client:
            messages = [{'role': 'user', 'content': f'请求编号{index}。'+prompt}]
            count = client.post('/tokenize', json={'model':'qwen3-8b','messages':messages,'add_generation_prompt':True,'chat_template_kwargs':{'enable_thinking':False}}).json()['count']
            barrier.wait(timeout=30)
            started=time.perf_counter(); first=None; usage=None; reason=None
            with client.stream('POST','/v1/chat/completions',json={'model':'qwen3-8b','messages':messages,'max_tokens':512,'temperature':0,'stream':True,'stream_options':{'include_usage':True},'chat_template_kwargs':{'enable_thinking':False}}) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith('data: ') or line=='data: [DONE]':continue
                    event=json.loads(line[6:])
                    if event.get('error'):raise RuntimeError(event['error'])
                    if event.get('usage'):usage=event['usage']
                    for choice in event.get('choices',[]):
                        if choice.get('delta',{}).get('content'):first=first or time.perf_counter()
                        reason=choice.get('finish_reason') or reason
            ended=time.perf_counter()
            assert first and usage and reason in ('stop','length')
            return {'input_tokens':count,'output_tokens':usage['completion_tokens'],'ttft':round(first-started,3),'seconds':round(ended-started,3),'tokens_per_second':round(usage['completion_tokens']/(ended-started),2),'first':first,'end':ended}
    with concurrent.futures.ThreadPoolExecutor(n) as pool:
        results=list(pool.map(run,range(n)))
    overlap=min(r['end'] for r in results)-max(r['first'] for r in results)
    return {'concurrency':n,'long_input':long_input,'all_streams_overlap_seconds':round(overlap,3),'requests':results}

if __name__=='__main__':
    with httpx.Client(trust_env=False) as client:
        deadline=time.monotonic()+120
        while True:
            try:
                if client.get(BASE+'/health',timeout=2).status_code==200:break
            except httpx.HTTPError:pass
            if time.monotonic()>deadline:raise RuntimeError('Model not ready')
            time.sleep(3)
    results=[]
    for n,long_input in [(4,False),(5,False),(4,True),(5,True)]:
        result=trial(n,long_input); results.append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        Path(__file__).with_name('capacity-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
