"""
Demo adapter — serves the seeded synthetic dashboard.

Reads `merchant/seed/dashboard_seed.json`, which is the same file the mock
dashboard renders from. That shared source is what makes the demo honest: the
number Clicky explains is provably the number on screen.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from merchant.adapters.base import AdapterError, DashboardAdapter, DataResult
from merchant.models import AdapterMode

SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "dashboard_seed.json"

_SETTLEMENT_REQUIRED = ("gross_amount", "fees", "tax", "refunds", "adjustments", "net_amount")


@lru_cache(maxsize=1)
def load_seed(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else SEED_PATH
    if not p.exists():
        raise AdapterError(f"seed file missing at {p}", code="SEED_MISSING")
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def list_scenarios(seed: dict[str, Any] | None = None) -> list[dict[str, str]]:
    data = seed or load_seed()
    return [
        {
            "id": s["id"],
            "title": s["title"],
            "description": s.get("description", ""),
            "page": s.get("page", "home"),
            "default": bool(s.get("default", False)),
        }
        for s in data.get("scenarios", [])
    ]


def default_scenario_id(seed: dict[str, Any] | None = None) -> str:
    data = seed or load_seed()
    for s in data.get("scenarios", []):
        if s.get("default"):
            return str(s["id"])
    scenarios = data.get("scenarios", [])
    if not scenarios:
        raise AdapterError("seed contains no scenarios", code="SEED_EMPTY")
    return str(scenarios[0]["id"])


def ui_anchors(seed: dict[str, Any] | None = None) -> dict[str, str]:
    data = seed or load_seed()
    return {k: v for k, v in data.get("ui_anchors", {}).items() if not k.startswith("_")}


class DemoAdapter(DashboardAdapter):
    """Read-only adapter over one seeded scenario."""

    mode = AdapterMode.DEMO

    def __init__(self, scenario_id: Optional[str] = None, seed_path: Optional[str] = None):
        self._seed = load_seed(seed_path)
        self.scenario_id = scenario_id or default_scenario_id(self._seed)
        self._scenario = self._find_scenario(self.scenario_id)

    def _find_scenario(self, scenario_id: str) -> dict[str, Any]:
        for s in self._seed.get("scenarios", []):
            if s["id"] == scenario_id:
                return s
        raise AdapterError(f"unknown scenario '{scenario_id}'", code="UNKNOWN_SCENARIO")

    # ── Scenario metadata ────────────────────────────────────────────────────

    @property
    def scenario_title(self) -> str:
        return str(self._scenario.get("title", self.scenario_id))

    @property
    def scenario_page(self) -> str:
        return str(self._scenario.get("page", "home"))

    @property
    def simulated_error(self) -> Optional[dict[str, str]]:
        return self._scenario.get("simulate_error")

    def health(self) -> bool:
        # The demo adapter is always reachable; a scenario may still simulate a
        # *data source* error, which is a different thing and surfaces per-call.
        return True

    # ── Reads ────────────────────────────────────────────────────────────────

    def _guard(self) -> Optional[DataResult]:
        err = self.simulated_error
        if err:
            return DataResult.failure(
                message=str(err.get("message", "Data source unavailable.")),
                code=str(err.get("code", "SERVER_ERROR")),
                source="demo_adapter",
            )
        return None

    def _collect(self, key: str, limit: int) -> DataResult:
        blocked = self._guard()
        if blocked:
            return blocked
        rows = list(self._scenario.get(key) or [])[:limit]
        return DataResult(ok=True, rows=rows, source="demo_adapter")

    def settlements(self, limit: int = 10) -> DataResult:
        result = self._collect("settlements", limit)
        if not result.ok:
            return result
        # Surface incompleteness explicitly rather than treating null as zero.
        missing: list[str] = []
        for row in result.rows:
            for fld in _SETTLEMENT_REQUIRED:
                if row.get(fld) is None:
                    missing.append(f"{row.get('id', '?')}.{fld}")
        result.missing_fields = missing
        result.partial = bool(missing)
        return result

    def payments(self, limit: int = 25, status: Optional[str] = None) -> DataResult:
        blocked = self._guard()
        if blocked:
            return blocked
        rows: list[dict[str, Any]] = list(self._scenario.get("payments") or [])
        rows += list(self._scenario.get("failed_payments") or [])
        if status:
            rows = [r for r in rows if str(r.get("status", "")).lower() == status.lower()]
        rows.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
        return DataResult(ok=True, rows=rows[:limit], source="demo_adapter")

    def refunds(self, limit: int = 25) -> DataResult:
        return self._collect("refunds", limit)

    def payment_links(self, limit: int = 25) -> DataResult:
        return self._collect("payment_links", limit)
