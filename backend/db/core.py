"""
db/core.py — connection pool, transactions and time helpers shared by every
db module.

All timestamps are stored as naive UTC DATETIMEs. Use utcnow()/now_iso()
when writing and compare against UTC_TIMESTAMP() in SQL — never NOW(), which
is the database server's local time.
"""

import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import pymysql
import pymysql.cursors
from dbutils.pooled_db import PooledDB

import config

LEVELS = ["Low", "Medium", "High"]  # index order matters — used for escalation

_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    """Created lazily so importing the package never needs a database."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = PooledDB(
                    creator=pymysql,
                    maxconnections=config.DB_POOL_SIZE,
                    mincached=1,
                    blocking=True,      # wait for a free connection instead of failing
                    ping=1,             # check a connection is alive before handing it out
                    host=config.DB_HOST,
                    port=config.DB_PORT,
                    user=config.DB_USER,
                    password=config.DB_PASSWORD,
                    database=config.DB_NAME,
                    cursorclass=pymysql.cursors.DictCursor,
                    autocommit=False,
                    charset="utf8mb4",
                )
    return _pool


def reset_pool():
    """Drop the pool (tests switch databases)."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
        _pool = None


def get_connection():
    """A pooled connection — close() returns it to the pool."""
    return _get_pool().connection()


@contextmanager
def transaction():
    """`with transaction() as cur:` — commits on success, rolls back on any
    exception, and always returns the connection to the pool."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_all(sql, params=()):
    with transaction() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_one(sql, params=()):
    with transaction() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def execute(sql, params=()):
    """Runs one write; returns (lastrowid, rowcount)."""
    with transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid, cur.rowcount


def utcnow():
    """Current time as naive UTC (matches how DATETIME columns are stored)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_db(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def now_iso():
    return to_db(utcnow())


def ping():
    try:
        fetch_one("SELECT 1 AS ok")
        return True
    except Exception:
        return False
