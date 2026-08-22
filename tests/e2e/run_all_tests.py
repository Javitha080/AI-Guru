"""
Master End-to-End (E2E) Test Runner for AI Guru.

Executes all 4 Tiers of requirement-driven E2E tests:
- Tier 1: Feature Coverage (R1 - R9 Isolated Tests)
- Tier 2: Boundary & Corner Cases (Limits, Debounce, Whitelists & Cooldowns)
- Tier 3: Cross-Feature Combinations (Multi-Module Integration Pipelines)
- Tier 4: Real-World Application Scenarios (Full Student & Parent Workflows)

Usage:
    python tests/e2e/run_all_tests.py
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from typing import Dict, List, Tuple

# ANSI terminal styling
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


class StructuredE2ETestResult(unittest.TestResult):
    """Custom TestResult collecting structured tier metrics and timings."""

    def __init__(self, tier_name: str):
        super().__init__()
        self.tier_name = tier_name
        self.test_details: List[Tuple[str, str, float, str]] = []  # (test_id, status, elapsed, err_msg)
        self._current_start_time: float = 0.0

    def startTest(self, test: unittest.TestCase):
        super().startTest(test)
        self._current_start_time = time.perf_counter()

    def addSuccess(self, test: unittest.TestCase):
        super().addSuccess(test)
        elapsed = time.perf_counter() - self._current_start_time
        test_name = test.id().split(".")[-1]
        self.test_details.append((test_name, "PASSED", elapsed, ""))

    def addFailure(self, test: unittest.TestCase, err):
        super().addFailure(test, err)
        elapsed = time.perf_counter() - self._current_start_time
        test_name = test.id().split(".")[-1]
        self.test_details.append((test_name, "FAILED", elapsed, self._exc_info_to_string(err, test)))

    def addError(self, test: unittest.TestCase, err):
        super().addError(test, err)
        elapsed = time.perf_counter() - self._current_start_time
        test_name = test.id().split(".")[-1]
        self.test_details.append((test_name, "ERROR", elapsed, self._exc_info_to_string(err, test)))


def run_tier(tier_name: str, test_class_or_module) -> StructuredE2ETestResult:
    """Executes a single test tier and returns structured results."""
    suite = unittest.TestSuite()
    
    if isinstance(test_class_or_module, type) and issubclass(test_class_or_module, unittest.TestCase):
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class_or_module)
        suite.addTests(tests)
    else:
        # Load functions starting with test_ from class
        instance = test_class_or_module()
        for attr in dir(instance):
            if attr.startswith("test_") and callable(getattr(instance, attr)):
                # Wrap pytest test function in a TestCase
                method = getattr(instance, attr)
                
                class DynamicTestCase(unittest.TestCase):
                    def runTest(self, m=method):
                        # Instantiate fixtures
                        from tests.e2e.conftest import (
                            AIGuruTestDB,
                            MockCVPipeline,
                            MockTutorProvider,
                            MockParentRemoteGateway,
                            MockConnectivityManager,
                            GamificationEngine,
                        )
                        import inspect
                        sig = inspect.signature(m)
                        kwargs = {}
                        db_instance = None
                        if "isolated_db" in sig.parameters:
                            db_instance = AIGuruTestDB(":memory:")
                            kwargs["isolated_db"] = db_instance
                        if "cv_pipeline" in sig.parameters:
                            kwargs["cv_pipeline"] = MockCVPipeline()
                        if "tutor_provider" in sig.parameters:
                            kwargs["tutor_provider"] = MockTutorProvider()
                        if "parent_gateway" in sig.parameters:
                            if not db_instance:
                                db_instance = AIGuruTestDB(":memory:")
                            kwargs["parent_gateway"] = MockParentRemoteGateway(db_instance)
                        if "connectivity_manager" in sig.parameters:
                            kwargs["connectivity_manager"] = MockConnectivityManager()
                        if "gamification_engine" in sig.parameters:
                            kwargs["gamification_engine"] = GamificationEngine()
                        
                        try:
                            m(**kwargs)
                        finally:
                            if db_instance:
                                db_instance.close()

                DynamicTestCase.__name__ = f"{test_class_or_module.__name__}_{attr}"
                suite.addTest(DynamicTestCase())

    result = StructuredE2ETestResult(tier_name)
    suite.run(result)
    return result


def main() -> int:
    """Main CLI test runner entry point."""
    print(f"\n{BOLD}{CYAN}==============================================================================={RESET}")
    print(f"{BOLD}{CYAN}                  AI GURU — MASTER E2E TEST SUITE RUNNER                      {RESET}")
    print(f"{BOLD}{CYAN}==============================================================================={RESET}")
    print(f"{DIM}Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}{RESET}\n")

    # Import test classes
    from tests.e2e.test_tier1_features import TestTier1FeatureCoverage
    from tests.e2e.test_tier2_boundaries import TestTier2BoundariesAndCornerCases
    from tests.e2e.test_tier3_cross_feature import TestTier3CrossFeatureCombinations
    from tests.e2e.test_tier4_scenarios import TestTier4RealWorldScenarios

    tiers = [
        ("Tier 1: Feature Coverage (R1 - R9)", TestTier1FeatureCoverage),
        ("Tier 2: Boundary & Corner Cases", TestTier2BoundariesAndCornerCases),
        ("Tier 3: Cross-Feature Combinations", TestTier3CrossFeatureCombinations),
        ("Tier 4: Real-World Application Scenarios", TestTier4RealWorldScenarios),
    ]

    tier_results: List[StructuredE2ETestResult] = []
    total_start_time = time.perf_counter()

    for tier_name, test_class in tiers:
        print(f"{BOLD}{YELLOW}>>> Executing {tier_name}...{RESET}")
        res = run_tier(tier_name, test_class)
        tier_results.append(res)
        for test_name, status, elapsed, err in res.test_details:
            status_badge = f"{GREEN}[PASS]{RESET}" if status == "PASSED" else f"{RED}[{status}]{RESET}"
            print(f"    {status_badge} {test_name:<55} {DIM}({elapsed*1000:6.1f}ms){RESET}")
            if err:
                print(f"{RED}{err}{RESET}")
        print()

    total_elapsed = time.perf_counter() - total_start_time

    # Summary table
    print(f"{BOLD}{CYAN}==============================================================================={RESET}")
    print(f"{BOLD}{CYAN}                          TEST EXECUTION SUMMARY                               {RESET}")
    print(f"{BOLD}{CYAN}==============================================================================={RESET}")
    print(f"{'Tier Name':<45} | {'Tests':<6} | {'Passed':<6} | {'Failed':<6} | {'Status'}")
    print("-" * 79)

    grand_total = 0
    grand_passed = 0
    grand_failed = 0

    all_passed = True
    for res in tier_results:
        total = len(res.test_details)
        passed = sum(1 for _, st, _, _ in res.test_details if st == "PASSED")
        failed = total - passed
        grand_total += total
        grand_passed += passed
        grand_failed += failed

        tier_status = f"{GREEN}ALL PASSED{RESET}" if failed == 0 else f"{RED}{failed} FAILED{RESET}"
        if failed > 0:
            all_passed = False
        print(f"{res.tier_name:<45} | {total:<6} | {passed:<6} | {failed:<6} | {tier_status}")

    print("-" * 79)
    print(f"{'TOTALS':<45} | {grand_total:<6} | {grand_passed:<6} | {grand_failed:<6} | {'ALL PASSED' if all_passed else 'FAILED'}")
    print(f"{BOLD}Total Execution Time:{RESET} {total_elapsed:.2f} seconds\n")

    if all_passed:
        print(f"{BOLD}{GREEN}✓ VERIFICATION SUCCESSFUL: 100% of E2E Tests Passed ({grand_passed}/{grand_total}).{RESET}\n")
        return 0
    else:
        print(f"{BOLD}{RED}✗ VERIFICATION FAILED: {grand_failed} test(s) failed.{RESET}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
