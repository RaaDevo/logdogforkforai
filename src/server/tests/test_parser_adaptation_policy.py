from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from parsers.adaptation_policy import RouteStats, adjusted_priority, should_promote


def test_route_priority_drops_after_repeated_failures() -> None:
    healthy = RouteStats(success=8, failure=1)
    degraded = RouteStats(success=1, failure=8)

    healthy_score = adjusted_priority(base_confidence=0.8, stats=healthy)
    degraded_score = adjusted_priority(base_confidence=0.8, stats=degraded)

    assert healthy_score > degraded_score


def test_safety_floor_blocks_bad_promotion() -> None:
    incumbent = RouteStats(success=6, failure=4)
    weak_candidate = RouteStats(success=2, failure=3)

    assert should_promote(candidate=weak_candidate, incumbent=incumbent) is False
