import os
from time import perf_counter
from pathlib import Path
from threading import Event, Lock, Thread

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TextIteratorStreamer,
    StoppingCriteria,
    StoppingCriteriaList,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = Path(os.environ.get("QWEN_MODEL_PATH", str(PROJECT_ROOT / "models" / "Qwen3-4B")))
QUANTIZATION = os.environ.get("QWEN_QUANTIZATION", "nf4")
MAX_INPUT_TOKENS = int(os.environ.get("QWEN_MAX_INPUT_TOKENS", "6144"))
MAX_NEW_TOKENS = int(os.environ.get("QWEN_MAX_NEW_TOKENS", "2048"))


class MeasuredStreamer(TextIteratorStreamer):
    """Measure generated token IDs, rather than decoded text chunks."""
    def __init__(self, tokenizer):
        super().__init__(tokenizer, skip_prompt=True, skip_special_tokens=True, timeout=120.0)
        self.output_tokens = 0
        self.first_token_at = None
        self.last_token_at = None

    def put(self, value):
        if not (self.skip_prompt and self.next_tokens_are_prompt):
            now = perf_counter()
            if self.first_token_at is None:
                self.first_token_at = now
            self.last_token_at = now
            self.output_tokens += value.numel()
        super().put(value)


class CancelGeneration(StoppingCriteria):
    def __init__(self, event):
        self.event = event

    def __call__(self, input_ids, scores, **kwargs):
        return self.event.is_set()


class LocalModelService:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.generate_lock = Lock()
        self.model_name = MODEL_PATH.name
        self.quantization = QUANTIZATION
        self.max_input_tokens = MAX_INPUT_TOKENS
        self.max_new_tokens = MAX_NEW_TOKENS
        if self.max_input_tokens <= 0 or self.max_new_tokens <= 0:
            raise ValueError("输入和输出 token 上限必须大于 0")

    def load(self):
        if self.model is not None:
            return

        print(f"正在从本地加载模型：{MODEL_PATH}")

        if not MODEL_PATH.is_dir():
            raise FileNotFoundError(f"模型目录不存在：{MODEL_PATH}。请检查模型路径及本地权重是否完整")
        if QUANTIZATION == "int8":
            if not torch.cuda.is_available():
                raise RuntimeError("INT8 部署需要可用的 CUDA，请检查当前 Python 环境及 PyTorch")
            quantization_config = BitsAndBytesConfig(
                load_in_8bit=True,
                llm_int8_threshold=6.0,
                llm_int8_has_fp16_weight=False,
                llm_int8_enable_fp32_cpu_offload=False,
            )
        elif QUANTIZATION == "nf4":
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
            )
        else:
            raise ValueError(f"不支持的量化方式：{QUANTIZATION}，请选择 int8 或 nf4")

        self.tokenizer = AutoTokenizer.from_pretrained(
            MODEL_PATH,
            local_files_only=True,
        )
        self.tokenizer.truncation_side = "left"

        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH,
            quantization_config=quantization_config,
            device_map={"": 0} if QUANTIZATION == "int8" else "auto",
            dtype=torch.float16 if QUANTIZATION == "int8" else torch.bfloat16,
            local_files_only=True,
            low_cpu_mem_usage=True,
        )

        self.model.eval()
        context_limit = self.model.config.max_position_embeddings
        if self.max_input_tokens + self.max_new_tokens > context_limit:
            raise ValueError(f"输入与输出总预算超过模型上下文上限 {context_limit}")

        print("模型加载成功")
        print("模型设备：", self.model.device)
        print("量化方式：", QUANTIZATION)
        print(f"Token 预算：输入 {self.max_input_tokens}，输出 {self.max_new_tokens}")
        print(f"模型常驻占用：{self.model.get_memory_footprint() / 1024**3:.2f} GiB")

        if torch.cuda.is_available():
            memory = torch.cuda.memory_allocated() / 1024**3
            print(f"当前显存占用：{memory:.2f} GB")

    def chat(self, messages: list[dict], metrics: dict | None = None) -> str:
        return "".join(self.stream_chat(messages, metrics)).strip()

    def stream_chat(self, messages: list[dict], metrics: dict | None = None):
        if self.model is None or self.tokenizer is None:
            raise RuntimeError("模型尚未加载")
        stats = metrics if metrics is not None else {}
        queued_at = perf_counter()
        with self.generate_lock:
            acquired_at = perf_counter()
            stats["queue_seconds"] = acquired_at - queued_at
            device = self.model.device
            is_cuda = device.type == "cuda"
            if is_cuda:
                torch.cuda.synchronize(device)
                torch.cuda.reset_peak_memory_stats(device)
            prompt = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
            )
            raw_token_count = len(self.tokenizer.encode(prompt, add_special_tokens=False))
            inputs = self.tokenizer(
                prompt, return_tensors="pt", truncation=True,
                max_length=self.max_input_tokens,
            ).to(device)
            actual_token_count = inputs["input_ids"].shape[-1]
            stats.update(raw_input_tokens=raw_token_count, input_tokens=actual_token_count,
                         max_new_tokens=self.max_new_tokens)
            print(f"生成请求：原始 tokens={raw_token_count}，实际输入={actual_token_count}，输出上限={self.max_new_tokens}")
            streamer = MeasuredStreamer(self.tokenizer)
            cancel = Event()
            generation_kwargs = {
                **inputs, "streamer": streamer, "max_new_tokens": self.max_new_tokens,
                "do_sample": True, "temperature": 0.7, "top_p": 0.8, "top_k": 20,
                "repetition_penalty": 1.05, "pad_token_id": self.tokenizer.eos_token_id,
                "stopping_criteria": StoppingCriteriaList([CancelGeneration(cancel)]),
            }
            generation_errors = []
            result = {}
            generation_started_at = perf_counter()
            stats["prepare_seconds"] = generation_started_at - acquired_at

            def run_generation():
                try:
                    with torch.inference_mode():
                        ids = self.model.generate(**generation_kwargs)
                    result["tokens"] = ids[0, actual_token_count:].tolist()
                except Exception as exc:
                    generation_errors.append(exc)
                    streamer.on_finalized_text("", stream_end=True)
                finally:
                    result["finished_at"] = perf_counter()

            generation_thread = Thread(target=run_generation, daemon=True)
            generation_thread.start()
            exhausted = False
            try:
                for text_piece in streamer:
                    if text_piece:
                        yield text_piece
                exhausted = True
            finally:
                if not exhausted:
                    cancel.set()
                generation_thread.join()
                finished_at = result["finished_at"]
                output_ids = result.get("tokens", [])
                eos_ids = self.model.generation_config.eos_token_id
                eos_ids = eos_ids if isinstance(eos_ids, (list, tuple)) else [eos_ids]
                if generation_errors:
                    reason = "error"
                elif cancel.is_set():
                    reason = "cancelled"
                elif output_ids and output_ids[-1] in eos_ids:
                    reason = "stop"
                elif len(output_ids) >= self.max_new_tokens:
                    reason = "length"
                else:
                    reason = "stop"
                first = streamer.first_token_at
                last = streamer.last_token_at
                output_count = len(output_ids) if output_ids else streamer.output_tokens
                decode_seconds = last - first if first is not None and last is not None else 0.0
                stats.update(
                    output_tokens=output_count, finish_reason=reason,
                    ttft_seconds=first - generation_started_at if first is not None else None,
                    model_ttft_seconds=first - queued_at if first is not None else None,
                    generation_seconds=finished_at - generation_started_at,
                    decode_seconds=decode_seconds,
                    tokens_per_second=(output_count - 1) / decode_seconds if output_count > 1 and decode_seconds > 0 else None,
                    model_total_seconds=finished_at - queued_at,
                )
                if is_cuda:
                    free, total = torch.cuda.mem_get_info(device)
                    gib = 1024 ** 3
                    stats.update(
                        gpu_total_gib=total / gib,
                        gpu_used_gib=(total - free) / gib,
                        gpu_used_percent=100 * (total - free) / total,
                        allocated_gib=torch.cuda.memory_allocated(device) / gib,
                        reserved_gib=torch.cuda.memory_reserved(device) / gib,
                        peak_allocated_gib=torch.cuda.max_memory_allocated(device) / gib,
                        peak_reserved_gib=torch.cuda.max_memory_reserved(device) / gib,
                    )
                # Keep request data JSON serializable and readable.
                for key, value in stats.items():
                    if isinstance(value, float):
                        stats[key] = round(value, 4)
                print("生成统计：", stats, flush=True)
            if generation_errors:
                raise generation_errors[0]


model_service = LocalModelService()
