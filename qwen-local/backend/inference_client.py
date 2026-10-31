import json
import os
from time import perf_counter

import httpx


class InferenceClient:
    def __init__(self):
        self.provider = os.getenv('INFERENCE_PROVIDER', 'strata').lower()
        if self.provider not in {'strata', 'vllm'}:
            raise ValueError('INFERENCE_PROVIDER 必须为 strata 或 vllm')
        strata = self.provider == 'strata'
        self.model_name = os.getenv('INFERENCE_MODEL', 'strata' if strata else os.getenv('VLLM_MODEL', 'qwen3-8b'))
        self.base_url = os.getenv('INFERENCE_BASE_URL', 'http://127.0.0.1:8080' if strata else os.getenv('VLLM_BASE_URL', 'http://127.0.0.1:8001')).rstrip('/')
        if self.base_url.endswith('/v1'):
            self.base_url = self.base_url[:-3]
        self.max_input_tokens = int(os.getenv('INFERENCE_MAX_INPUT_TOKENS', '32768' if strata else '3072'))
        self.max_new_tokens = int(os.getenv('INFERENCE_MAX_NEW_TOKENS', '2048' if strata else '1024'))
        self.quantization = os.getenv('INFERENCE_QUANTIZATION', 'IQ2_XS' if strata else 'FP16')
        if min(self.max_input_tokens, self.max_new_tokens) <= 0:
            raise ValueError('输入和输出 token 上限必须大于 0')

    async def open(self):
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={'Authorization': 'Bearer ' + os.getenv('INFERENCE_API_KEY', 'none')},
            timeout=httpx.Timeout(300, connect=5), trust_env=False,
        )
        if self.provider == 'strata':
            try:
                response = await self.client.get('/health', timeout=5)
                response.raise_for_status()
                context = int(response.json()['max_context'])
                if self.max_input_tokens + self.max_new_tokens > context:
                    raise ValueError(f'输入与输出预算超过 Strata 上下文上限 {context}')
            except BaseException:
                await self.client.aclose()
                raise

    async def close(self):
        await self.client.aclose()

    async def healthy(self):
        try:
            response = await self.client.get('/health', timeout=5)
            if response.status_code != 200:
                return False
            if self.provider == 'strata':
                data = response.json()
                return data.get('status') == 'ok' and data.get('loaded') is True
            return True
        except (httpx.HTTPError, ValueError):
            return False

    async def count_tokens(self, messages, settings=None):
        if self.provider == 'strata':
            # Count with the same model/template, with thinking disabled on both APIs.
            system = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
            payload = {'model': self.model_name, 'system': system,
                       'messages': [m for m in messages if m['role'] != 'system'],
                       'thinking': {'type': 'disabled'} if not settings or settings['reasoning_effort'] == 'none' else {'type': 'enabled', 'budget_tokens': {'low': 1024, 'medium': 4096, 'high': 8192}[settings['reasoning_effort']]}}
            response = await self.client.post('/v1/messages/count_tokens', json=payload)
            field = 'input_tokens'
        else:
            response = await self.client.post('/tokenize', json={
                'model': self.model_name, 'messages': messages,
                'add_generation_prompt': True,
                'chat_template_kwargs': {'enable_thinking': bool(settings and settings['reasoning_effort'] != 'none')},
            })
            field = 'count'
        response.raise_for_status()
        return int(response.json()[field])

    async def prepare(self, messages, settings=None):
        messages = list(messages)
        system = [m for m in messages[:-1] if m['role'] == 'system']
        current = messages[-1:]
        history = [m for m in messages[:-1] if m['role'] != 'system']
        # Each user message starts a turn, including unanswered/cancelled turns.
        # Never leave an assistant reply without its preceding user message.
        turns = []
        for message in history:
            if message['role'] == 'user':
                turns.append([message])
            elif turns:
                turns[-1].append(message)
        def build(start):
            return system + [m for turn in turns[start:] for m in turn] + current
        return await self.fit_history(len(turns), build, settings)

    async def fit_history(self, size, build, settings=None):
        """Find a recent suffix using exact counts and logarithmic API calls."""
        full = build(0)
        if await self.count_tokens(full, **({'settings': settings} if settings else {})) <= self.max_input_tokens:
            return full
        minimum = build(size)
        if await self.count_tokens(minimum, **({'settings': settings} if settings else {})) > self.max_input_tokens:
            raise ValueError('当前问题超过输入预算，请缩短问题后重试')
        low, high = 0, size
        best = minimum
        while low + 1 < high:
            middle = (low + high) // 2
            candidate = build(middle)
            if await self.count_tokens(candidate, **({'settings': settings} if settings else {})) <= self.max_input_tokens:
                high, best = middle, candidate
            else:
                low = middle
        return best

    async def prepare_transcript(self, system, heading, entries, question, settings=None):
        # A court statement is indivisible, even when it contains multiple lines.
        def build(start):
            transcript = '\n'.join(entries[start:])
            return [{'role': 'system', 'content': system},
                    {'role': 'user', 'content': f'{heading}\n{transcript}\n{question}'}]
        # Use prepare for counting so existing mock inference can exercise court orchestration.
        async def fits(start):
            try:
                return await self.prepare(build(start), **({'settings': settings} if settings else {}))
            except ValueError:
                return None
        full = await fits(0)
        if full is not None:
            return full
        best = await fits(len(entries))
        if best is None:
            raise ValueError('当前问题超过输入预算，请缩短问题后重试')
        low, high = 0, len(entries)
        while low + 1 < high:
            middle = (low + high) // 2
            candidate = await fits(middle)
            if candidate is not None:
                high, best = middle, candidate
            else:
                low = middle
        return best

    async def stream_chat(self, messages, metrics, settings=None):
        started = perf_counter()
        first = None
        finished = False
        async with self.client.stream('POST', '/v1/chat/completions', json={
            'model': self.model_name, 'messages': messages,
            'max_tokens': self.max_new_tokens, 'temperature': 0.7,
            **(settings or {}),
            'stream': True, 'stream_options': {'include_usage': True},
            'chat_template_kwargs': {'enable_thinking': bool(settings and settings['reasoning_effort'] != 'none')},
        }) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith('data: '):
                    continue
                if line == 'data: [DONE]':
                    finished = True
                    break
                event = json.loads(line[6:])
                if 'error' in event:
                    raise RuntimeError('推理服务返回错误')
                if event.get('usage'):
                    metrics.update(input_tokens=event['usage']['prompt_tokens'],
                                   output_tokens=event['usage']['completion_tokens'])
                for choice in event.get('choices', []):
                    if choice.get('finish_reason'):
                        metrics['finish_reason'] = choice['finish_reason']
                    delta = choice.get('delta', {})
                    reasoning = delta.get('reasoning_content')
                    if reasoning and settings and settings['reasoning_effort'] != 'none':
                        # Transient event; consumers remove it before saving metrics.
                        metrics['_reasoning_delta'] = reasoning
                        yield ''
                        metrics.pop('_reasoning_delta', None)
                    text = delta.get('content')
                    if text:
                        if first is None:
                            first = perf_counter()
                        yield text
        if not finished or 'finish_reason' not in metrics:
            raise RuntimeError('推理连接提前结束，请重试')
        elapsed = perf_counter() - started
        metrics.update(max_new_tokens=self.max_new_tokens,
                       model_ttft_seconds=first-started if first else None,
                       generation_seconds=elapsed,
                       tokens_per_second=metrics['output_tokens']/elapsed if 'output_tokens' in metrics else None,
                       metrics_source=self.provider + '_proxy',
                       reasoning_effort=(settings or {}).get('reasoning_effort', 'none'),
                       temperature=(settings or {}).get('temperature', 0.7),
                       throughput_definition='output_tokens / upstream_total_seconds')


model_service = InferenceClient()
