"""Serve the lab's HTTPS tunnel; run instead of serve_vllm.py."""
import os
import uvicorn

if __name__ == '__main__':
    os.environ['ALLOWED_ORIGINS'] = 'https://zss.nat200.top'
    os.environ['COOKIE_SECURE'] = 'true'
    # The tunnel connects locally. Do not trust client-supplied forwarded IPs.
    uvicorn.run('backend.main:app', host='127.0.0.1', port=8000,
                workers=1, proxy_headers=False)
