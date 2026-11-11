"""Persistent admin settings and transactional, user-bound access keys."""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from contextlib import contextmanager

DEFAULTS = dict(mode='balanced', max_sessions=int(os.getenv('MAX_BROWSER_SESSIONS', '2')),
    maintenance=False, maintenance_message='Maintenance. Please try again later.',
    final_url='', second_url='', second_delay=0, close_on_activation=False,
    completion_url='', close_delay=0, notes='', tutorial_url='',
    price='', instructions='', channel='', channel_link='', topup_instructions='',
    pinch_zoom=True)

class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'admin.sqlite3'
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS codes (code TEXT PRIMARY KEY, owner INTEGER, state TEXT NOT NULL DEFAULT 'new', created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, code TEXT, owner INTEGER, email TEXT, started REAL, ended REAL, status TEXT, review TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS media (id INTEGER PRIMARY KEY, path TEXT, name TEXT);
            CREATE TABLE IF NOT EXISTS extensions (id TEXT PRIMARY KEY, name TEXT, path TEXT, enabled INTEGER DEFAULT 1);
            ''')
            try:
                db.execute("ALTER TABLE operations ADD COLUMN fail_reason TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass        # already upgraded
    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
    def settings(self):
        with self.db() as db:
            row = db.execute('SELECT data FROM settings WHERE id=1').fetchone()
            return {**DEFAULTS, **(json.loads(row[0]) if row else {})}
    def save_settings(self, values):
        from urllib.parse import urlsplit
        if not isinstance(values, dict) or set(values) - set(DEFAULTS):
            raise ValueError('Unknown settings')
        data = {**self.settings(), **values}
        if data['mode'] not in ('fast', 'balanced', 'quality'):
            raise ValueError('Invalid display mode')
        for key, maximum in [('max_sessions', 50), ('second_delay', 3600), ('close_delay', 3600)]:
            if type(data[key]) is not int or not (1 if key == 'max_sessions' else 0) <= data[key] <= maximum:
                raise ValueError('Invalid ' + key)
        for key in ('maintenance', 'close_on_activation', 'pinch_zoom'):
            if type(data[key]) is not bool:
                raise ValueError('Invalid ' + key)
        for key in ('final_url', 'second_url', 'tutorial_url', 'completion_url'):
            value = data[key]
            if not isinstance(value, str) or len(value) > 2048:
                raise ValueError('Invalid URL')
            if value:
                url = urlsplit(value)
                if url.scheme != 'https' or not url.hostname or url.username or url.password:
                    raise ValueError('Use a full HTTPS URL: ' + key)
        if data['close_on_activation'] and not data['completion_url']:
            raise ValueError('Set completion URL before enabling automatic close')
        for key in ('notes', 'maintenance_message'):
            if not isinstance(data[key], str) or len(data[key]) > 4000:
                raise ValueError('Text is too long')
        if not isinstance(data['instructions'], str) or len(data['instructions']) > 3500:
            raise ValueError('Instructions are too long (maximum 3500 characters)')
        if not isinstance(data['topup_instructions'], str) or len(data['topup_instructions']) > 1500:
            raise ValueError('Top-up instructions are too long (maximum 1500 characters)')
        import re
        channel = data['channel'] = str(data['channel']).strip()
        if channel and not re.fullmatch(r'@[A-Za-z][A-Za-z0-9_]{3,31}|-100\d{5,}', channel):
            raise ValueError('Required Channel must be @channelname or a numeric id like -1001234567890')
        link = data['channel_link'] = str(data['channel_link']).strip()
        if link and not re.fullmatch(r'https://t\.me/[A-Za-z0-9_+/\-]{3,100}', link):
            raise ValueError('Join link must look like https://t.me/yourchannel or https://t.me/+AbCdEf')
        if not isinstance(data['price'], str):
            raise ValueError('Invalid price')
        if data['price'].strip():
            from store_link import parse_price
            data['price'] = f"{parse_price(data['price']) / 100:.2f}"   # e.g. "12.5" → "12.50"
        else:
            data['price'] = ''
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (1,?)', (json.dumps(data),))
        return data
    def generate(self, count):
        if type(count) is not int or not 1 <= count <= 500:
            raise ValueError('Count must be 1–500')
        keys = [''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(12)) for _ in range(count)]
        with self.db() as db:
            db.executemany('INSERT INTO codes(code,created) VALUES (?,?)', [(k, time.time()) for k in keys])
        return keys
    def claim(self, code, owner):
        code = code.strip().upper()
        with self.db() as db:
            row = db.execute('SELECT * FROM codes WHERE code=?', (code,)).fetchone()
            if not row or row['state'] not in ('new', 'bound') or row['owner'] not in (None, owner):
                raise ValueError('Invalid, used, revoked or already assigned code.')
            db.execute("UPDATE codes SET owner=?,state='bound' WHERE code=?", (owner, code))
        return code
    def begin(self, code, owner, operation, email):
        with self.db() as db:
            row = db.execute('SELECT * FROM codes WHERE code=?', (code,)).fetchone()
            if not row or row['owner'] != owner or row['state'] != 'bound':
                raise ValueError('Use /login T= with an available code first.')
            if db.execute("SELECT 1 FROM operations WHERE owner=? AND ended IS NULL", (owner,)).fetchone():
                raise ValueError('A browser is already running.')
            db.execute("INSERT INTO operations(id,code,owner,email,started,status) VALUES (?,?,?,?,?,'starting')", (operation,code,owner,email,time.time()))
    def consume(self, operation):
        with self.db() as db:
            row = db.execute('SELECT * FROM operations WHERE id=? AND ended IS NULL', (operation,)).fetchone()
            if row:
                code = db.execute('SELECT state FROM codes WHERE code=?', (row['code'],)).fetchone()
                if code and code['state'] == 'revoked':
                    return False
                db.execute("UPDATE codes SET state='used' WHERE code=?", (row['code'],))
                db.execute("UPDATE operations SET status='in_progress' WHERE id=?", (operation,))
        return True
    def finish(self, operation, status='closed', reason=''):
        with self.db() as db:
            db.execute('UPDATE operations SET status=?,ended=?,fail_reason=? WHERE id=? AND ended IS NULL', (status,time.time(),reason[:300],operation))
    def recover(self):
        with self.db() as db:
            db.execute("UPDATE operations SET status='interrupted',ended=?,fail_reason='Server restarted while this session was running' WHERE ended IS NULL", (time.time(),))
    def revoke(self, code):
        with self.db() as db:
            db.execute("UPDATE codes SET state='revoked' WHERE code=?", (code,))
    def snapshot(self):
        with self.db() as db:
            return {table: [dict(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY rowid DESC LIMIT 5000')] for table in ('codes','operations','extensions')}
    def extensions(self):
        with self.db() as db:
            return [r[0] for r in db.execute('SELECT path FROM extensions WHERE enabled=1')]

STORE = Store(os.getenv('DATA_DIR', '/data' if Path('/data').is_dir() else './data'))

def is_admin(user_id):
    return str(user_id) in {s.strip() for s in os.getenv('ADMIN_TELEGRAM_IDS','').split(',') if s.strip()}

def admin_ids():
    return [int(s.strip()) for s in os.getenv('ADMIN_TELEGRAM_IDS','').split(',') if s.strip().lstrip('-').isdigit()]
