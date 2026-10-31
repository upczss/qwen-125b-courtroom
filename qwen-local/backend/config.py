import os
from pathlib import Path
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[1]
local = ROOT / 'deploy/local/.env'
settings = {}
if local.exists():
    for line in local.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            settings[key] = value
DATABASE_URL = os.getenv('DATABASE_URL') or URL.create(
    'postgresql+psycopg', username='qwen',
    password=settings.get('POSTGRES_PASSWORD'), host='127.0.0.1', port=5432, database='qwen',
)
REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
ALLOWED_ORIGINS = {
    item.strip().rstrip('/') for item in os.getenv(
        'ALLOWED_ORIGINS', 'http://127.0.0.1:8000,http://localhost:8000'
    ).split(',') if item.strip()
}
