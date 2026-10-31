"""Budget boundaries, turn integrity and multiline court history."""
import unittest
from backend.inference_client import InferenceClient


class HistoryBudgetTest(unittest.IsolatedAsyncioTestCase):
    def client(self, budget):
        service = InferenceClient()
        service.max_input_tokens = budget
        async def count(messages):
            return sum(len(m['content']) for m in messages)
        service.count_tokens = count
        return service

    async def test_more_than_twenty_messages(self):
        messages = [{'role': 'system', 'content': 'S'}]
        for _ in range(30):
            messages += [{'role': 'user', 'content': 'U'}, {'role': 'assistant', 'content': 'A'}]
        messages += [{'role': 'user', 'content': 'Q'}]
        self.assertEqual(await self.client(62).prepare(messages), messages)
        kept = await self.client(8).prepare(messages)
        self.assertEqual(len(kept), 8)
        self.assertEqual([m['role'] for m in kept], ['system', 'user', 'assistant', 'user', 'assistant', 'user', 'assistant', 'user'])
        self.assertEqual(messages[1]['content'], 'U')

    async def test_orphan_and_cancelled_turns(self):
        messages = [{'role': 'system', 'content': 'S'}, {'role': 'assistant', 'content': 'orphan'},
                    {'role': 'user', 'content': 'cancelled'}, {'role': 'user', 'content': 'U'},
                    {'role': 'assistant', 'content': 'A'}, {'role': 'user', 'content': 'Q'}]
        kept = await self.client(4).prepare(messages)
        self.assertEqual([m['content'] for m in kept], ['S', 'U', 'A', 'Q'])
        with self.assertRaises(ValueError):
            await self.client(1).prepare(messages)

    async def test_court_whole_entries_and_request(self):
        service = self.client(13)
        kept = await service.prepare_transcript('S', 'H', ['old\nlong statement', 'new\ntext'], 'Q')
        self.assertEqual(kept[1]['content'], 'H\nnew\ntext\nQ')
        entries = ['x'] * 70
        kept = await self.client(1000).prepare_transcript('S', 'H', entries, 'Q')
        self.assertEqual(kept[1]['content'].count('x'), 70)
        with self.assertRaises(ValueError):
            await self.client(2).prepare_transcript('S', 'H', entries, 'Q')


if __name__ == '__main__':
    unittest.main()
