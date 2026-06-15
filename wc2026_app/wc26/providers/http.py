"""Tiny stdlib HTTP helper shared by API adapters (no extra dependencies)."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Optional, Tuple


def get_json(
    url: str,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = 10.0,
) -> Tuple[dict, float]:
    """GET a JSON document; returns (payload, rtt_seconds)."""
    if params:
        # Sportmonks include/filter syntax uses literal ';' ',' ':' separators;
        # urlencoding them (%3B etc.) makes the API reject the request (403).
        query = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}, safe=";,:"
        )
        url = f"{url}?{query}"
    # Some APIs (Sportmonks) WAF-block the default "Python-urllib" agent (403).
    final_headers = {"User-Agent": "wc26/1.0", "Accept": "application/json"}
    final_headers.update(headers or {})
    req = urllib.request.Request(url, headers=final_headers)
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload, time.perf_counter() - start
