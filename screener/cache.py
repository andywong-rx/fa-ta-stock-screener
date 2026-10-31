"""Small local SQLite cache with atomic backup and non-destructive recovery.

A process-wide lock serializes this pilot's cache operations. No contact identity
is stored here. If disk is unavailable, only previously read/current process data
can be retained in memory; callers receive a generic warning.
"""
from pathlib import Path
import json
import math
import os
import sqlite3
import threading
import time
import uuid

class Cache:
    _lock = threading.RLock()
    _memory = {}

    def __init__(self, path=None):
        self.path = Path(path or os.environ.get('SCREENER_CACHE', '.cache/v2a.sqlite')).resolve()
        self.backup = self.path.with_name(self.path.name + '.backup')
        self.warnings = []
        self.available = False
        self.memory = self._memory.setdefault(str(self.path.resolve()), {})
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if not self.path.exists() and self.backup.exists():
                    self._recover()
                    return
                with self._connect() as db:
                    self._check(db)
                self.available = True
            except (sqlite3.DatabaseError, OSError):
                self._recover()

    def _note(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def _connect(self):
        return sqlite3.connect(self.path, timeout=5)

    @staticmethod
    def _check(db):
        if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise sqlite3.DatabaseError('Invalid cache')
        db.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, updated REAL, body TEXT)')
        if [r[1] for r in db.execute('PRAGMA table_info(cache)')] != ['key', 'updated', 'body']:
            raise sqlite3.DatabaseError('Unsupported cache schema')

    def _recover(self):
        self.available = False
        self._note('Local cache recovery was needed. Last readable backup/process data is retained where possible; unavailable data remains UNKNOWN.')
        try:
            # Quarantine instead of deleting an unreadable file. Do not replace a
            # merely locked/readonly database; leave it intact and use memory.
            if self.path.exists():
                try:
                    with self._connect() as db:
                        self._check(db)
                except sqlite3.OperationalError:
                    self._note('Local persistence is unavailable. Current process memory only; retry after resolving storage access.')
                    return
                except sqlite3.DatabaseError:
                    suffix = '.corrupt-' + uuid.uuid4().hex
                    self.path.replace(self.path.with_name(self.path.name + suffix))
                    for ext in ('-journal', '-wal', '-shm'):
                        sidecar = Path(str(self.path) + ext)
                        if sidecar.exists():
                            sidecar.replace(Path(str(self.path) + suffix + ext))
                else:
                    # A transient write/lock failure is not corruption. Never
                    # restore an older backup over a structurally healthy file.
                    self.available = True
                    self._note('Cache access was interrupted. The existing disk cache is retained; current process data is retained where possible.')
                    return
            if self.backup.exists():
                try:
                    with sqlite3.connect(self.backup.as_uri() + '?mode=ro', uri=True) as source:
                        if source.execute('PRAGMA quick_check').fetchone() != ('ok',):
                            raise sqlite3.DatabaseError('Invalid backup')
                        source.execute('SELECT key, updated, body FROM cache LIMIT 0')
                        with self._connect() as dest:
                            source.backup(dest)
                except (sqlite3.DatabaseError, OSError):
                    self._note('No readable disk backup is available. Refresh is required for missing data.')
            with self._connect() as db:
                self._check(db)
                for key, (updated, body) in self.memory.items():
                    db.execute('INSERT INTO cache VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET updated=excluded.updated, body=excluded.body WHERE cache.updated < excluded.updated', (key, updated, body))
            self.available = True
        except (sqlite3.DatabaseError, OSError):
            self._note('Local persistence is unavailable. Current process memory only; retry after resolving storage access.')

    def _backup(self):
        temporary = self.backup.with_name(self.backup.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with self._connect() as source, sqlite3.connect(temporary) as dest:
                source.backup(dest)
            temporary.replace(self.backup)
        except (sqlite3.DatabaseError, OSError):
            self._note('Cache backup could not be updated. Existing cache and earlier backup are retained.')
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def get(self, key, ttl=None, validator=None):
        with self._lock:
            row = None
            if self.available:
                try:
                    with self._connect() as db:
                        row = db.execute('SELECT updated,body FROM cache WHERE key=?', (key,)).fetchone()
                except (sqlite3.DatabaseError, OSError):
                    self._recover()
                    if self.available:
                        try:
                            with self._connect() as db:
                                row = db.execute('SELECT updated,body FROM cache WHERE key=?', (key,)).fetchone()
                        except (sqlite3.DatabaseError, OSError):
                            self.available = False
            candidates = [row, self.memory.get(key)]
            candidates.sort(key=lambda r: r[0] if r and isinstance(r[0],(int,float)) else -math.inf, reverse=True)
            for candidate in candidates:
                if candidate is None:
                    continue
                try:
                    updated, body = candidate
                    if not isinstance(updated, (int, float)) or not math.isfinite(updated) or not 0 <= updated <= time.time()+300:
                        raise ValueError('Invalid timestamp')
                    value = json.loads(body)
                    if validator:
                        validator(value)
                    if ttl is not None and time.time() - updated >= ttl:
                        return None
                    self.memory[key] = (updated, body)
                    return updated, value
                except Exception:
                    self._note('A cached response is unreadable or invalid. Valid process data is retained where possible; otherwise refresh is required.')
            # A damaged JSON row need not imply the entire database is lost.
            # Try the independent last-successful disk snapshot before UNKNOWN.
            if self.backup.exists():
                try:
                    with sqlite3.connect(self.backup.as_uri() + '?mode=ro', uri=True) as db:
                        backup_row = db.execute('SELECT updated,body FROM cache WHERE key=?', (key,)).fetchone()
                    if backup_row:
                        stamp, body = backup_row
                        value = json.loads(body)
                        if validator:
                            validator(value)
                        if math.isfinite(stamp) and 0 <= stamp <= time.time()+300 and (ttl is None or time.time()-stamp < ttl):
                            self.memory[key] = (stamp, body)
                            self._note('A cached response was restored from backup. Its original refresh timestamp is retained.')
                            return stamp, value
                except Exception:
                    self._note('A cached response is unavailable. Refresh is required for missing data.')
            return None

    def put(self, key, value, updated=None):
        body = json.dumps(value, allow_nan=False)
        stamp = time.time() if updated is None else updated
        with self._lock:
            self.memory[key] = (stamp, body)
            if not self.available:
                return
            try:
                with self._connect() as db:
                    db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (key, stamp, body))
                self._backup()
            except (sqlite3.DatabaseError, OSError):
                self._recover()
                if self.available:
                    try:
                        with self._connect() as db:
                            db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (key, stamp, body))
                        self._backup()
                    except (sqlite3.DatabaseError, OSError):
                        self.available = False
