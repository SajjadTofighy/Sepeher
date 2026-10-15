"""Change journal for the live operational picture: cursor, resume and snapshot reconciliation.

The console used to poll the full bootstrap (every asset with its whole track) every few
seconds. The journal instead records which entities changed since a cursor:

* ``sync`` diffs a fingerprint of every live entity against the previous sync (under the state
  lock, at most once per ``min_interval``) and appends changed or removed entities.
* ``since(cursor)`` returns the entries after a cursor. The cursor carries the process epoch, so
  a restart, an unknown cursor or one older than the bounded buffer answers ``reset=True`` and
  the client reloads the snapshot; a reconnect therefore never silently loses changes.

Entries hold principal-independent copies; per-principal projection happens when serving.
"""
from collections import deque
from copy import deepcopy
import hashlib
import json
import threading
import time
import uuid

from . import store

COLLECTIONS = ("assets", "incidents", "alerts", "missions", "commands")
# Values that change every second without any operational change; clients derive them.
VOLATILE = {"assets": ("position_age_seconds",)}


def trail(asset, points):
    """Live map trail: the newest points only; history replay uses the track query API."""
    return {**asset, "track": asset.get("track", [])[-points:]} if points else asset


def fingerprint(kind, item):
    data = {k: v for k, v in item.items() if k not in VOLATILE.get(kind, ())}
    return hashlib.blake2b(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode(),
                           digest_size=16).hexdigest()


class Journal:
    def __init__(self, capacity=20000, min_interval=0.5):
        self.epoch = uuid.uuid4().hex[:12]
        self.capacity = capacity
        self.min_interval = min_interval
        self.entries = deque(maxlen=capacity)
        self.seq = 0
        self.prints = {}
        self.summary_print = None
        self.summary = None
        self.last_sync = None
        self.lock = threading.Lock()

    def cursor(self, seq=None):
        return f"{self.epoch}:{self.seq if seq is None else seq}"

    def parse(self, cursor):
        epoch, _, seq = (cursor or "").partition(":")
        if epoch != self.epoch or not seq.isdigit():
            return None
        return int(seq)

    @store.state_locked
    def sync(self, force=False):
        """Diff the live state; called by readers, never by a background thread."""
        clock = time.monotonic()
        if not force and self.last_sync is not None and clock - self.last_sync < self.min_interval:
            return
        self.last_sync = clock
        store.refresh_commands()
        store.refresh_tracks()
        points = store.state["settings"]["map_trail_points"]
        changes, seen = [], set()
        for kind in COLLECTIONS:
            for item in store.state.get(kind, []):
                view = trail(item, points) if kind == "assets" else item
                key = (kind, item["id"])
                seen.add(key)
                value = fingerprint(kind, view)
                if self.prints.get(key) != value:
                    self.prints[key] = value
                    changes.append((kind, item["id"], deepcopy(view)))
        removed = [key for key in self.prints if key not in seen]
        summary = store.summary()
        summary_value = fingerprint("summary", summary)
        with self.lock:
            for kind, id, view in changes:
                self.seq += 1
                self.entries.append((self.seq, kind, id, view))
            for key in removed:
                del self.prints[key]
                self.seq += 1
                self.entries.append((self.seq, key[0], key[1], None))
            if summary_value != self.summary_print:
                self.summary_print, self.summary = summary_value, summary
                self.seq += 1
                self.entries.append((self.seq, "summary", "summary", deepcopy(summary)))

    def since(self, cursor, limit=5000):
        """(entries, next cursor, reset). A gap beyond the buffer or a foreign epoch forces reset."""
        seq = self.parse(cursor)
        with self.lock:
            oldest = self.entries[0][0] if self.entries else self.seq + 1
            if seq is None or seq > self.seq or (seq < oldest - 1 and seq < self.seq):
                return [], self.cursor(), True
            rows = [entry for entry in self.entries if entry[0] > seq][:limit]
            last = rows[-1][0] if rows else seq
            return rows, self.cursor(last), False

    def head(self):
        with self.lock:
            return self.seq


journal = Journal()


def reset():
    """A demo reset or restore replaces state wholesale: every client must reload its snapshot."""
    global journal
    capacity, interval = journal.capacity, journal.min_interval
    journal = Journal(capacity, interval)
    return journal
