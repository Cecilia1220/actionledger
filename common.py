import hashlib
import json
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name('.env'))
DATA = Path(os.getenv('DATA_DIR', Path(__file__).with_name('data')))
DATA.mkdir(parents=True, exist_ok=True)
AGENT_KEY = os.getenv('AGENT_KEY', 'local-demo-agent')
TRACKER_KEY = os.getenv('TRACKER_KEY', 'local-demo-tracker')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def connect(name):
    db = sqlite3.connect(DATA / name, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    return db
