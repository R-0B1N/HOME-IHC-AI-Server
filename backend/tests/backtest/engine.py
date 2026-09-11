"""
Object-Oriented Conversational & Workflow Backtesting Engine.
Home IHC Real Estate WhatsApp AI CRM Automation.

Provides deterministic, replayable execution of multi-turn conversational scenarios,
evaluating persona state transitions, qualification completeness, lead temperatures,
Meta WhatsApp 24-hour messaging window enforcement, and document generation integrity.
"""

import time
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class BacktestAssertion:
    """Represents an individual verifiable assertion within a backtest."""
    name: str
    expected: Any
    actual: Any
    passed: bool
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "expected": str(self.expected),
            "actual": str(self.actual),
            "passed": self.passed,
            "details": self.details,
        }


@dataclass
class ScenarioResult:
    """Outcome of a single executed scenario."""
    scenario_id: str
    name: str
    persona: str
    passed: bool
    assertions: List[BacktestAssertion] = field(default_factory=list)
    latency_ms: float = 0.0
    turns_executed: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "persona": self.persona,
            "passed": self.passed,
            "latency_ms": round(self.latency_ms, 2),
            "turns_executed": self.turns_executed,
            "error": self.error,
            "assertions_count": len(self.assertions),
            "assertions_passed": sum(1 for a in self.assertions if a.passed),
            "assertions": [a.to_dict() for a in self.assertions],
            "metadata": self.metadata,
        }


@dataclass
class BacktestSuiteResult:
    """Aggregate outcome of all executed backtesting scenarios."""
    timestamp: str
    total_scenarios: int
    passed_scenarios: int
    failed_scenarios: int
    pass_rate_percent: float
    total_latency_ms: float
    scenarios: List[ScenarioResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_scenarios": self.total_scenarios,
            "passed_scenarios": self.passed_scenarios,
            "failed_scenarios": self.failed_scenarios,
            "pass_rate_percent": round(self.pass_rate_percent, 2),
            "total_latency_ms": round(self.total_latency_ms, 2),
            "scenarios": [s.to_dict() for s in self.scenarios],
        }

    def to_markdown(self) -> str:
        """Generates a professional Markdown audit report."""
        status_symbol = "✅ PASSED" if self.failed_scenarios == 0 else "❌ FAILED"
        lines = [
            "# Conversational & Workflow Backtesting Report",
            "",
            f"**System:** Home IHC WhatsApp AI CRM Automation ([BentongLand.com.my](https://bentongland.com.my/))",
            f"**Execution Timestamp:** {self.timestamp}",
            f"**Status:** {status_symbol}",
            f"**Pass Rate:** {self.pass_rate_percent:.1f}% ({self.passed_scenarios}/{self.total_scenarios} scenarios)",
            f"**Total Execution Latency:** {self.total_latency_ms:.2f} ms",
            "",
            "## Scenario Summary Matrix",
            "",
            "| Scenario ID | Name | Persona | Status | Latency | Assertions Passed |",
            "|:---|:---|:---|:---:|:---:|:---:|",
        ]

        for s in self.scenarios:
            icon = "✅ Pass" if s.passed else "❌ Fail"
            passed_asserts = sum(1 for a in s.assertions if a.passed)
            lines.append(
                f"| `{s.scenario_id}` | {s.name} | {s.persona} | {icon} | {s.latency_ms:.1f}ms | {passed_asserts}/{len(s.assertions)} |"
            )

        lines.extend([
            "",
            "## Detailed Scenario Audit & Assertions",
            ""
        ])

        for s in self.scenarios:
            lines.append(f"### `{s.scenario_id}`: {s.name}")
            lines.append(f"- **Persona:** {s.persona}")
            lines.append(f"- **Execution Time:** {s.latency_ms:.2f} ms")
            if s.error:
                lines.append(f"- **Error:** `{s.error}`")
            lines.append("- **Verification Assertions:**")
            for a in s.assertions:
                a_icon = "✓" if a.passed else "✗"
                lines.append(f"  - [{a_icon}] **{a.name}**: {a.details or f'Expected {a.expected}, got {a.actual}'}")
            lines.append("")

        return "\n".join(lines)


class BaseScenario:
    """Abstract Base Class for an individual backtest scenario."""

    def __init__(self, scenario_id: str, name: str, persona: str, description: str):
        self.scenario_id = scenario_id
        self.name = name
        self.persona = persona
        self.description = description

    def execute(self) -> ScenarioResult:
        """Executes scenario steps and returns ScenarioResult."""
        raise NotImplementedError("Subclasses must implement execute()")


class ConversationalBacktestHarness:
    """Master runner for executing and scoring a collection of backtest scenarios."""

    def __init__(self):
        self.scenarios: List[BaseScenario] = []

    def register_scenario(self, scenario: BaseScenario) -> None:
        """Registers a scenario into the backtest harness."""
        self.scenarios.append(scenario)

    def run_all(self) -> BacktestSuiteResult:
        """Executes all registered scenarios and calculates suite metrics."""
        results: List[ScenarioResult] = []
        start_total = time.time()

        for scenario in self.scenarios:
            logger.info(f"Running backtest scenario: [{scenario.scenario_id}] {scenario.name}")
            t0 = time.time()
            try:
                result = scenario.execute()
            except Exception as e:
                logger.error(f"Scenario {scenario.scenario_id} crashed: {e}", exc_info=True)
                result = ScenarioResult(
                    scenario_id=scenario.scenario_id,
                    name=scenario.name,
                    persona=scenario.persona,
                    passed=False,
                    error=str(e),
                    latency_ms=(time.time() - t0) * 1000.0,
                )
            results.append(result)

        total_latency = (time.time() - start_total) * 1000.0
        passed_count = sum(1 for r in results if r.passed)
        failed_count = len(results) - passed_count
        pass_rate = (passed_count / len(results) * 100.0) if results else 0.0

        return BacktestSuiteResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_scenarios=len(results),
            passed_scenarios=passed_count,
            failed_scenarios=failed_count,
            pass_rate_percent=pass_rate,
            total_latency_ms=total_latency,
            scenarios=results,
        )
