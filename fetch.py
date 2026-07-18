"""Polite, strictly-sequential client for the wank.wavu.wiki replays API.

The API (https://wank.wavu.wiki/api/replays) returns replays newest-first for a
700-second window ending at `before` (unix seconds). We page by decrementing
`before` by 700. Per the API docs the rate limit is never hit as long as only
one request is in flight at a time, so everything here is blocking and serial
with a small sleep between calls.
"""

import time

import requests

API_URL = "https://wank.wavu.wiki/api/replays"
WINDOW = 700  # seconds covered per request
USER_AGENT = "wavu-stats/1.0 (personal Tekken 8 stats; sequential)"

import db


class Fetcher:
    def __init__(self, delay=1.1, timeout=30, max_retries=5):
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        })

    def _get_window(self, before=None):
        """Fetch one 700s window. `before=None` returns the latest window."""
        params = {} if before is None else {"before": int(before)}
        backoff = 2.0
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(API_URL, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    raise
                print(f"  request error ({e}); retrying in {backoff:.0f}s")
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    resp.raise_for_status()
                wait = float(resp.headers.get("Retry-After", backoff))
                print(f"  HTTP {resp.status_code}; backing off {wait:.0f}s")
                time.sleep(wait)
                backoff *= 2
                continue
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):  # tolerate {"replays": [...]} shape
                data = data.get("replays") or data.get("data") or []
            return data
        return []

    def _walk(self, conn, start_before, stop_at, label):
        """Walk windows from `start_before` down while newer than `stop_at`.

        Stops when a window ends at or below `stop_at`. Returns rows inserted.
        """
        before = start_before
        total_new = 0
        windows = 0
        while before is None or before > stop_at:
            batch = self._get_window(before)
            windows += 1
            if not batch:
                # No games in this window; step back and keep going, but if we
                # were already at the latest window with nothing, we're done.
                if before is None:
                    break
                before -= WINDOW
                time.sleep(self.delay)
                continue
            new = db.insert_replays(conn, batch)
            total_new += new
            oldest = min(r["battle_at"] for r in batch)
            newest = max(r["battle_at"] for r in batch)
            ts = time.strftime("%Y-%m-%d %H:%M", time.gmtime(newest))
            print(f"  [{label}] {ts}Z  +{new:>4} new / {len(batch):>4} rows "
                  f"(total new {total_new})", flush=True)
            # Next window sits just below the oldest we just saw.
            before = oldest - 1
            if before <= stop_at:
                break
            time.sleep(self.delay)
        return total_new

    def top_up(self, conn):
        """Fetch everything newer than what's already stored.

        On an empty DB there is no floor to stop at, so we only grab the single
        latest window and tell the user to run `backfill` for history.
        """
        stop_at = db.max_battle_at(conn)
        if stop_at is None:
            print("Top-up: empty DB — fetching the latest window only. "
                  "Use 'backfill --days N' to build history.")
            batch = self._get_window(None)
            added = db.insert_replays(conn, batch) if batch else 0
            print(f"  fetched {len(batch)} rows, {added} new.", flush=True)
            return added
        when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(stop_at))
        print(f"Top-up: fetching games newer than {when}Z ...")
        return self._walk(conn, start_before=None, stop_at=stop_at, label="top-up")

    def backfill(self, conn, days):
        """Fetch ~`days` of history, extending backwards from the oldest stored
        game (or now if the DB is empty)."""
        newest = db.max_battle_at(conn) or int(time.time())
        anchor = db.min_battle_at(conn)  # resume from where we left off
        start_before = None if anchor is None else anchor - 1
        target = newest - int(days * 86400)
        cutoff = time.strftime("%Y-%m-%d %H:%M", time.gmtime(target))
        print(f"Backfill: collecting back to ~{cutoff}Z "
              f"({days} days). Ctrl-C is safe to resume.")
        return self._walk(conn, start_before=start_before, stop_at=target,
                          label="backfill")
