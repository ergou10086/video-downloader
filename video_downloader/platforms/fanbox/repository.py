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
    VERSION = 2

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
            db.execute('BEGIN IMMEDIATE')
            try:
                if db.execute('PRAGMA user_version').fetchone()[0]==1:
                    if version==1:
                        backup=self.path.with_suffix(self.path.suffix+'.v1.bak')
                        if backup.exists() or backup.is_symlink():
                            backup=self.path.with_suffix(self.path.suffix+'.v1.'+uuid.uuid4().hex+'.bak')
                        with sqlite3.connect(self.path) as source,sqlite3.connect(backup) as target:
                            source.backup(target)
                    db.execute('CREATE TABLE IF NOT EXISTS requests(key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, job TEXT NOT NULL)')
                    db.execute('PRAGMA user_version=2')
                db.commit()
            except BaseException:
                db.rollback()
                raise

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

    def create_requested(self,state,key,fingerprint):
        with self.transaction() as db:
            old=db.execute('SELECT fingerprint,job FROM requests WHERE key=?',(key,)).fetchone()
            if old:
                if old['fingerprint']!=fingerprint:
                    raise FanboxError('request_conflict','重复请求标识对应了不同参数')
                return json.loads(db.execute('SELECT state FROM jobs WHERE id=?',(old['job'],)).fetchone()[0]),False
            state['version']=1;state['updated_at']=self.clock()
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(state['id'],1,state['status'],state['updated_at'],json.dumps(state,ensure_ascii=False)))
            db.execute('INSERT INTO requests VALUES(?,?,?)',(key,fingerprint,state['id']))
            return state,True

    def transition(self,state,expected):
        with self.transaction() as db:
            old=db.execute('SELECT version FROM jobs WHERE id=?',(state['id'],)).fetchone()
            if old is None or old[0]!=expected:
                raise FanboxError('stale_version','任务版本已改变，请刷新后重试')
            if db.execute('SELECT 1 FROM leases WHERE kind=? AND expires>?',('job:'+state['id'],self.clock())).fetchone():
                raise FanboxError('job_busy','任务仍在运行或收尾')
            state['version']=expected+1;state['updated_at']=self.clock()
            db.execute('UPDATE jobs SET version=?,status=?,updated=?,state=? WHERE id=?',
                       (state['version'],state['status'],state['updated_at'],json.dumps(state,ensure_ascii=False),state['id']))

    def has_lease(self,kind):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM leases WHERE kind=? AND expires>?',(kind,self.clock())).fetchone() is not None

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

    def usage_history(self,zone,days=30):
        tz=ZoneInfo(zone)
        today=datetime.fromtimestamp(self.clock(),timezone.utc).astimezone(tz).date()
        totals={str(today-timedelta(days=i)):0 for i in reversed(range(days))}
        with self.connect() as db:
            for row in db.execute('SELECT bucket,bytes FROM traffic WHERE bucket>=?',(int((self.clock()-days*86400)//60),)):
                date=str(datetime.fromtimestamp(row['bucket']*60,timezone.utc).astimezone(tz).date())
                if date in totals:totals[date]+=row['bytes']
        return [{'date':date,'bytes':count} for date,count in totals.items()]
