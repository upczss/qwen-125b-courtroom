from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class GenerationSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reasoning_effort: Literal['none', 'low', 'medium', 'high'] = 'none'
    temperature: float = Field(default=0.7, ge=0, le=1.5, allow_inf_nan=False)

    def api_parameters(self):
        result = self.model_dump()
        if self.reasoning_effort != 'none':
            # Total output stays 2048 by default; reserve room for the final answer.
            result['reasoning_budget_tokens'] = {'low': 256, 'medium': 512, 'high': 1024}[self.reasoning_effort]
        return result
