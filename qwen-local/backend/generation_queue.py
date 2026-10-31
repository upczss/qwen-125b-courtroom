"""Single-worker FIFO admission; cancellation releases both running and waiting tickets."""
import asyncio
from collections import deque
import os
from fastapi import HTTPException

class GenerationQueue:
    def __init__(self):
        default_slots = '3' if os.getenv('INFERENCE_PROVIDER', 'strata').lower() == 'strata' else '5'
        self.limit = int(os.getenv('GENERATION_SLOTS', default_slots))
        self.max_waiting = int(os.getenv('GENERATION_QUEUE_SIZE', '5'))
        self.running = set()
        self.waiting = deque()
        self.tickets = {}
        self.users = {}

    def reserve(self, cid, uid):
        if cid in self.tickets:
            raise HTTPException(409, '该会话正在生成或排队')
        if uid in self.users.values():
            raise HTTPException(429, '你已有一个请求正在生成或排队')
        if len(self.running) >= self.limit and len(self.waiting) >= self.max_waiting:
            raise HTTPException(429, '等待队列已满，请稍后再试')
        event = asyncio.Event()
        self.tickets[cid] = event
        self.users[cid] = uid
        if len(self.running) < self.limit:
            self.running.add(cid)
            event.set()
        else:
            self.waiting.append(cid)

    def position(self, cid):
        return list(self.waiting).index(cid)+1 if cid in self.waiting else 0

    async def wait(self, cid):
        try:
            await asyncio.wait_for(self.tickets[cid].wait(), timeout=120)
        except asyncio.TimeoutError as exc:
            raise HTTPException(504, '排队超过120秒，请稍后再试') from exc

    def release(self, cid):
        self.tickets.pop(cid, None)
        self.users.pop(cid, None)
        self.running.discard(cid)
        if cid in self.waiting:
            self.waiting.remove(cid)
        while self.waiting and len(self.running)<self.limit:
            following=self.waiting.popleft()
            self.running.add(following)
            self.tickets[following].set()

    async def cleanup(self, cid, ticket):
        if self.tickets.get(cid) is ticket:
            self.release(cid)

queue = GenerationQueue()
