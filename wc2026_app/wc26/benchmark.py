"""Latency benchmark for live providers.

Vendor latency claims (Sportmonks "<15s", API-Football "5s refresh") describe
their internal pipelines, not what your process sees. This measures, with a
real key: request RTT, and how often/quickly the live payload actually changes
across a polling window — the numbers that bound an in-play strategy.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BenchmarkResult:
    provider: str
    polls: int
    rtts: List[float] = field(default_factory=list)
    state_changes: int = 0
    change_gaps: List[float] = field(default_factory=list)
    errors: int = 0

    def summary(self) -> str:
        if not self.rtts:
            return f"{self.provider}: no successful polls ({self.errors} errors)"
        lines = [
            f"{self.provider}: {len(self.rtts)}/{self.polls} polls ok, {self.errors} errors",
            f"  rtt: median {statistics.median(self.rtts)*1000:.0f}ms"
            f"  p95 {sorted(self.rtts)[int(0.95 * (len(self.rtts) - 1))]*1000:.0f}ms"
            f"  max {max(self.rtts)*1000:.0f}ms",
            f"  payload changes observed: {self.state_changes}",
        ]
        if self.change_gaps:
            lines.append(
                f"  gap between changes: median {statistics.median(self.change_gaps):.1f}s"
                f"  min {min(self.change_gaps):.1f}s"
            )
        lines.append(
            "  note: change cadence only meaningful while the match is in play"
        )
        return "\n".join(lines)


def run_benchmark(
    provider,
    home: str,
    away: str,
    polls: int = 20,
    interval: float = 5.0,
    include_odds: bool = False,
) -> BenchmarkResult:
    """Poll live_state (and optionally odds) repeatedly, recording RTT and
    payload-change timing."""
    result = BenchmarkResult(provider=provider.name, polls=polls)
    last_fingerprint: Optional[tuple] = None
    last_change_at: Optional[float] = None

    for i in range(polls):
        if i:
            time.sleep(interval)
        try:
            state = provider.live_state(home, away)
            if include_odds:
                quotes = provider.odds(home, away)
                odds_fp = tuple(sorted((q.market, q.outcome, q.line, q.odds) for q in quotes))
            else:
                odds_fp = ()
        except Exception:
            result.errors += 1
            continue
        if provider.last_rtt is not None:
            result.rtts.append(provider.last_rtt)
        fingerprint = (
            (state.minute, state.score_home, state.score_away, state.red_home, state.red_away)
            if state
            else None,
            odds_fp,
        )
        now = time.time()
        if last_fingerprint is not None and fingerprint != last_fingerprint:
            result.state_changes += 1
            if last_change_at is not None:
                result.change_gaps.append(now - last_change_at)
            last_change_at = now
        last_fingerprint = fingerprint

    return result
