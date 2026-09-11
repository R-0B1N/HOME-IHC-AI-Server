#!/usr/bin/env python3
"""
CLI Runner for the Home IHC Conversational & Workflow Backtesting Suite.

Executes deterministic scenario replays across all 5 operational personas,
validates 22-field OpenXML document stabilization, asserts Meta 24-hour customer
care messaging window compliance, and outputs comprehensive audit reports.

Usage:
    python scripts/run_backtest.py
"""

import sys
import os
import json
import logging

# Ensure backend root is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(SCRIPT_DIR)
WORKSPACE_ROOT = os.path.dirname(BACKEND_ROOT)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from tests.backtest.scenarios import build_default_backtest_harness

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_backtest")


def main():
    print("================================================================================")
    print("         HOME IHC REAL ESTATE WHATSAPP AI CRM - BACKTESTING SUITE               ")
    print("================================================================================")
    print("Initializing scenario harness...")

    harness = build_default_backtest_harness()
    print(f"Registered {len(harness.scenarios)} comprehensive backtest scenarios.")
    print("Executing replay matrix...\n")

    suite_result = harness.run_all()

    # Console Summary Table
    print("\n--------------------------------------------------------------------------------")
    print(f"{'SCENARIO ID':<22} | {'PERSONA':<18} | {'STATUS':<8} | {'LATENCY':<10} | {'ASSERTS'}")
    print("--------------------------------------------------------------------------------")
    for s in suite_result.scenarios:
        status_str = "PASS" if s.passed else "FAIL"
        passed_asserts = sum(1 for a in s.assertions if a.passed)
        total_asserts = len(s.assertions)
        assert_ratio = f"{passed_asserts}/{total_asserts}"
        print(f"{s.scenario_id:<22} | {s.persona:<18} | {status_str:<8} | {s.latency_ms:6.1f}ms | {assert_ratio}")
    print("--------------------------------------------------------------------------------")

    print(f"\nTotal Scenarios: {suite_result.total_scenarios}")
    print(f"Passed:          {suite_result.passed_scenarios}")
    print(f"Failed:          {suite_result.failed_scenarios}")
    print(f"Pass Rate:       {suite_result.pass_rate_percent:.1f}%")
    print(f"Total Latency:   {suite_result.total_latency_ms:.2f} ms\n")

    # Output paths
    output_locations = [
        os.path.join(WORKSPACE_ROOT, "artifacts"),
        os.path.join(BACKEND_ROOT, "tests", "backtest"),
    ]

    # Save JSON and Markdown artifacts
    json_data = json.dumps(suite_result.to_dict(), indent=2)
    md_data = suite_result.to_markdown()

    for out_dir in output_locations:
        os.makedirs(out_dir, exist_ok=True)
        json_path = os.path.join(out_dir, "backtest_report.json")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(json_data)
        logger.info(f"Exported backtest JSON report to: {json_path}")

        md_path = os.path.join(out_dir, "backtest_report.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_data)
        logger.info(f"Exported backtest Markdown report to: {md_path}")

    if suite_result.failed_scenarios > 0:
        print("\n❌ BACKTEST SUITE FAILED: One or more scenarios did not meet pass criteria.")
        sys.exit(1)
    else:
        print("✅ ALL BACKTEST SCENARIOS PASSED WITH 100% SUCCESS RATE.")
        sys.exit(0)


if __name__ == "__main__":
    main()
