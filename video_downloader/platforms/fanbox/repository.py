"""Transactional archive index and durable work, scheduler and traffic ledger.

All workers in an archive share one conservative credential slot. Session
rotation must not reset limits. No authentication material is stored here.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time as day_time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import time
import uuid
from zoneinfo import ZoneInfo

from .errors import FanboxError


class Repository:
    VERSION = 1

    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > self.VERSION:
                raise FanboxError('database_version', '归档数据库来自更高版本')
            if version == 0:
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise FanboxError('database_version', '无法识别归档数据库结构')
                db.executescript('''
                    BEGIN IMMEDIATE;
                    CREATE TABLE jobs(id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                        status TEXT NOT NULL, updated REAL NOT NULL, state TEXT NOT NULL);
                    CREATE TABLE assets(key TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        state TEXT NOT NULL);
                    CREATE TABLE lanes(kind TEXT PRIMARY KEY, next REAL NOT NULL DEFAULT 0);
                    CREATE TABLE leases(token TEXT PRIMARY KEY, kind TEXT NOT NULL,
                        expires REAL NOT NULL, held INTEGER NOT NULL DEFAULT 0, capacity INTEGER NOT NULL DEFAULT 1);
                    CREATE TABLE traffic(bucket INTEGER PRIMARY KEY, bytes INTEGER NOT NULL);
                    CREATE TABLE cooldown(id INTEGER PRIMARY KEY CHECK(id=1), until REAL NOT NULL);
                    INSERT INTO cooldown VALUES(1,0);
                    PRAGMA user_version=1;
                    COMMIT;
                ''')
            db.execute('PRAGMA journal_mode=WAL')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=10000')
        db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def save_job(self, state):
        with self.transaction() as db:
            previous = db.execute('SELECT version FROM jobs WHERE id=?', (state['id'],)).fetchone()
            state['version'] = (previous['version'] if previous else 0) + 1
            state['updated_at'] = self.clock()
            db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?)',
                       (state['id'], state['version'], state['status'], state['updated_at'],
                        json.dumps(state, ensure_ascii=False)))

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT state FROM jobs WHERE id=?', (job_id,)).fetchone()
            return json.loads(row['state']) if row else None

    def jobs(self, limit=100):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT state FROM jobs ORDER BY updated DESC LIMIT ?', (limit,))]

    def allocate(self, key, candidate, *, conflict='uniquify', exists=lambda p: False):
        """Freeze paths in SQL before IO; never steal another asset's filename."""
        with self.transaction() as db:
            old = db.execute('SELECT path FROM assets WHERE key=?', (key,)).fetchone()
            if old:
                return old['path']
            path = Path(candidate)
            for number in range(10000):
                name = path if not number else path.with_name(f'{path.stem} ({number}){path.suffix}')
                taken = db.execute('SELECT key FROM assets WHERE path=? COLLATE NOCASE', (name.as_posix(),)).fetchone()
                occupied = exists(name.as_posix())
                if taken or (occupied and conflict == 'uniquify'):
                    continue
                if occupied and conflict=='skip':
                    raise FanboxError('file_skipped','已按冲突策略跳过现有文件')
                if occupied and conflict=='prompt':
                    raise FanboxError('conflict_required', '目标文件已存在，请调整冲突策略')
                db.execute('INSERT INTO assets VALUES(?,?,?)', (key, name.as_posix(), '{}'))
                return name.as_posix()
            raise FanboxError('path_conflict', '无法分配唯一文件名')

    def asset(self, key):
        with self.connect() as db:
            row = db.execute('SELECT path,state FROM assets WHERE key=?', (key,)).fetchone()
            return dict(json.loads(row['state']), path=row['path']) if row else None

    def save_asset(self, key, state):
        with self.transaction() as db:
            db.execute('UPDATE assets SET state=? WHERE key=?', (json.dumps(state), key))

    def acquire(self, kind, *, limit=1, interval=0, ttl=120):
        now, token = self.clock(), uuid.uuid4().hex
        with self.transaction() as db:
            db.execute('DELETE FROM leases WHERE expires<=?', (now,))
            until = db.execute('SELECT until FROM cooldown WHERE id=1').fetchone()[0] if kind in {'api','file'} else 0
            lane = db.execute('SELECT next FROM lanes WHERE kind=?', (kind,)).fetchone()
            wait = max(0, until-now, (lane[0]-now) if lane else 0)
            occupied = db.execute('SELECT COUNT(*),MIN(capacity) FROM leases WHERE kind=?', (kind,)).fetchone()
            effective = min(limit,occupied[1]) if occupied[1] is not None else limit
            if wait or occupied[0] >= effective:
                return None, max(.05, wait)
            db.execute('INSERT INTO leases VALUES(?,?,?,0,?)', (token, kind, now+ttl,limit))
            db.execute('INSERT OR REPLACE INTO lanes VALUES(?,?)', (kind, now+interval))
        return token, 0

    def release(self, token, *, interval=0):
        with self.transaction() as db:
            row = db.execute('SELECT kind FROM leases WHERE token=?', (token,)).fetchone()
            if row and interval:
                db.execute('UPDATE lanes SET next=MAX(next,?) WHERE kind=?', (self.clock()+interval, row[0]))
            db.execute('DELETE FROM leases WHERE token=?', (token,))

    def heartbeat(self, token):
        with self.transaction() as db:
            if not db.execute('UPDATE leases SET expires=? WHERE token=? AND expires>?',
                              (self.clock()+120, token, self.clock())).rowcount:
                raise FanboxError('lease_expired', '工作租约已失效，请继续任务')

    def defer(self, seconds):
        with self.transaction() as db:
            db.execute('UPDATE cooldown SET until=MAX(until,?) WHERE id=1', (self.clock()+seconds,))

    def cooldown_remaining(self):
        with self.connect() as db:
            return max(0,db.execute('SELECT until FROM cooldown WHERE id=1').fetchone()[0]-self.clock())

    @staticmethod
    def _day(now, zone):
        current = datetime.fromtimestamp(now, timezone.utc).astimezone(ZoneInfo(zone))
        start = datetime.combine(current.date(), day_time(), current.tzinfo)
        return int(start.timestamp()//60), int((start+timedelta(days=1)).timestamp()//60)

    def _usage(self, db, zone):
        start, end = self._day(self.clock(), zone)
        return db.execute('SELECT COALESCE(SUM(bytes),0) FROM traffic WHERE bucket>=? AND bucket<?', (start,end)).fetchone()[0]

    def reserve(self, token, quota, expected):
        with self.transaction() as db:
            db.execute('DELETE FROM leases WHERE expires<=?', (self.clock(),))
            row = db.execute('SELECT held FROM leases WHERE token=?', (token,)).fetchone()
            if row is None:
                raise FanboxError('lease_expired', '下载租约已失效')
            if not quota['enabled']:
                return None
            used = self._usage(db, quota['timezone'])
            held = db.execute('SELECT COALESCE(SUM(held),0) FROM leases WHERE token<>?', (token,)).fetchone()[0]
            available = int(quota['limit_gib']*1024**3)-used-held
            wanted = available if expected is None else expected
            if wanted < 0 or wanted > available or (wanted == 0 and expected is None):
                code = 'quota_busy' if held and wanted <= available+held else 'quota_exceeded'
                raise FanboxError(code, '当日下载额度不足' if code=='quota_exceeded' else '下载额度正在使用')
            db.execute('UPDATE leases SET held=? WHERE token=?', (wanted,token))
            return wanted

    def charge(self, token, count):
        with self.transaction() as db:
            # Received payload is counted even when its contents fail validation.
            db.execute('INSERT INTO traffic VALUES(?,?) ON CONFLICT(bucket) DO UPDATE SET bytes=bytes+excluded.bytes',
                       (int(self.clock()//60),count))
            db.execute('UPDATE leases SET held=MAX(0,held-?),expires=? WHERE token=?', (count,self.clock()+120,token))

    def usage(self, zone):
        with self.connect() as db:
            return self._usage(db, zone)
