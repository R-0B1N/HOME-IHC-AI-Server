"""
Unit test wrapper for the Conversational & Workflow Backtesting Suite.
Ensures CI/CD test runners validate all backtesting scenarios on every commit/push.
"""

import unittest
from tests.backtest.scenarios import build_default_backtest_harness


class TestBacktestingSuite(unittest.TestCase):
    """Executes the full conversational backtesting replay matrix."""

    def test_all_scenarios_pass(self):
        harness = build_default_backtest_harness()
        self.assertGreaterEqual(len(harness.scenarios), 7)

        suite_result = harness.run_all()

        for s in suite_result.scenarios:
            with self.subTest(scenario=s.scenario_id):
                if not s.passed:
                    failed_asserts = [a.name for a in s.assertions if not a.passed]
                    self.fail(
                        f"Scenario {s.scenario_id} failed. Failed assertions: {failed_asserts}. Error: {s.error}"
                    )
                self.assertTrue(s.passed)

        self.assertEqual(suite_result.failed_scenarios, 0)
        self.assertEqual(suite_result.pass_rate_percent, 100.0)


if __name__ == "__main__":
    unittest.main()
