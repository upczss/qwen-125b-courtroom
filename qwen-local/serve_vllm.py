"""Start the web backend; inference defaults to Strata, or INFERENCE_PROVIDER=vllm."""
import uvicorn

if __name__ == '__main__':
    uvicorn.run('backend.main:app', host='127.0.0.1', port=8000, workers=1)
