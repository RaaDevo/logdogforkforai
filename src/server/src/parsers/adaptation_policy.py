from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RouteStats:
    success: int = 0
    failure: int = 0

    @property
    def total(self) -> int:
        return self.success + self.failure

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.5
        return self.success / self.total


def adjusted_priority(*, base_confidence: float, stats: RouteStats, min_samples: int = 3, floor: float = 0.2) -> float:
    """Adjust parser selection priority with conservative safety floor."""
    if stats.total < min_samples:
        return max(base_confidence, floor)
    calibrated = (base_confidence * 0.6) + (stats.success_rate * 0.4)
    return max(calibrated, floor)


def should_promote(*, candidate: RouteStats, incumbent: RouteStats, safety_floor: float = 0.55) -> bool:
    """Only promote when candidate has enough evidence and clears the floor."""
    if candidate.total < 5:
        return False
    if candidate.success_rate < safety_floor:
        return False
    return candidate.success_rate > incumbent.success_rate
