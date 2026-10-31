"""Start the existing FastAPI application with Qwen3-8B LLM.int8()."""
import os
import sys
import socket
from pathlib import Path

os.environ["QWEN_MODEL_PATH"] = str(Path(__file__).resolve().parent / "models" / "Qwen3-8B")
os.environ["QWEN_QUANTIZATION"] = "int8"

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 8000))
    except OSError as exc:
        listener.close()
        if exc.winerror == 10048 or exc.errno == 98:
            print("8000 端口已被占用，请打开 http://127.0.0.1:8000 或先停止已有服务。")
            sys.exit(1)
        raise
    import uvicorn

    try:
        config = uvicorn.Config("backend.main:app", host="127.0.0.1", port=8000, workers=1)
        uvicorn.Server(config).run(sockets=[listener])
    finally:
        listener.close()
