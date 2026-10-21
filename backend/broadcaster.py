"""
broadcaster.py — fans new activity-log rows out to live (SSE) clients.

One poller per server process reads the activity log once a second and
hands each new row to every connected client whose scope allows it. That's
one query per second per process, however many admins are watching —
instead of one per client. Because it reads the shared table, rows written
by any process (or a background job) still reach everyone.
"""

import asyncio
import logging

import db

logger = logging.getLogger("traytrack.live")
POLL_SECONDS = 1


class Subscriber:
    def __init__(self, college_id=None, mess_id=None, prefixes=None):
        self.college_id = college_id
        self.mess_id = mess_id
        self.prefixes = prefixes
        self.queue = asyncio.Queue(maxsize=1000)

    def wants(self, row):
        if self.college_id and row.get("college_id") != self.college_id:
            return False
        if self.mess_id and row.get("mess_id") not in (None, self.mess_id):
            return False
        if self.prefixes and not any(row["event_type"].startswith(p) for p in self.prefixes):
            return False
        return True


class Broadcaster:
    def __init__(self):
        self.subscribers = set()
        self.last_id = None
        self._task = None

    async def _run(self):
        while True:
            try:
                if self.subscribers and self.last_id is not None:
                    rows = await asyncio.to_thread(db.get_activity, after_id=self.last_id, limit=500)
                    for row in rows:
                        self.last_id = row["id"]
                        for sub in list(self.subscribers):
                            if sub.wants(row):
                                try:
                                    sub.queue.put_nowait(row)
                                except asyncio.QueueFull:
                                    pass  # a stuck client; it will resync on reconnect
                else:
                    self.last_id = None  # nobody listening: start fresh next time
            except Exception:
                logger.exception("Live feed poll failed")
            await asyncio.sleep(POLL_SECONDS)

    def start(self):
        if self._task is None:
            self._task = asyncio.get_event_loop().create_task(self._run())

    def subscribe(self, sub, backlog, after_id):
        """`backlog`: rows the client missed (after its last id), delivered
        first. If the poller was idle, it resumes from where this client is,
        so nothing written in between is skipped."""
        for row in backlog:
            if sub.wants(row):
                sub.queue.put_nowait(row)
        if self.last_id is None:
            self.last_id = backlog[-1]["id"] if backlog else after_id
        self.subscribers.add(sub)

    def unsubscribe(self, sub):
        self.subscribers.discard(sub)


broadcaster = Broadcaster()
