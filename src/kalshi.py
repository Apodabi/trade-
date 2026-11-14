"""Minimal read-only Kalshi public-API client (no auth, no order endpoints).

Only GET requests against public market-data endpoints are issued. There is
deliberately no signing code and no order/portfolio method in this module.
"""
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.elections.kalshi.com/trade-api/v2"
UA = "research-readonly/1.0"


class Client:
    def __init__(self, min_interval=0.35, max_retries=12, timeout=30):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self._last = 0.0
        self.n_calls = 0
        self.n_429 = 0

    def get(self, path, **params):
        params = {k: v for k, v in params.items() if v is not None and v != ""}
        url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        delay = 1.0
        for attempt in range(self.max_retries):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.n_calls += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    self.n_429 += e.code == 429
                    time.sleep(delay + random.random() * 0.5)
                    delay = min(delay * 1.7, 30)
                    continue
                if e.code == 404:
                    return None
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(delay)
                delay = min(delay * 1.7, 30)
        raise RuntimeError(f"gave up on {url}")

    def paged(self, path, key, limit=1000, max_pages=None, **params):
        cursor, pages = None, 0
        while True:
            d = self.get(path, limit=limit, cursor=cursor, **params)
            if not d:
                return
            items = d.get(key) or []
            yield from items
            cursor = d.get("cursor")
            pages += 1
            if not cursor or not items or (max_pages and pages >= max_pages):
                return
