"""Run the repository's unittest suites and write an analysis-friendly report.

The runner intentionally uses only the Python standard library.  It keeps the
normal unittest output while also writing one JSON document with per-test
statuses, timings, skips, and tracebacks.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import sys
import time
import traceback
import unittest


ROOT = Path(__file__).resolve().parent.parent
SUITES = (
    ("agent", ROOT / "FlashControlAgent"),
    ("server", ROOT / "FlashControlPIBServer"),
    ("proxy", ROOT / "FlashControlProxy"),
)


def _test_id(test):
    return test.id() if hasattr(test, "id") else str(test)


def _is_integration(test_id):
    return "integration" in test_id.lower()


class ReportResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.started = {}
        self.tests = {}

    def startTest(self, test):
        super().startTest(test)
        self.started[_test_id(test)] = time.perf_counter()

    def _finish(self, test, status, detail=None):
        test_id = _test_id(test)
        started = self.started.pop(test_id, time.perf_counter())
        record = {
            "id": test_id,
            "status": status,
            "duration_seconds": round(time.perf_counter() - started, 6),
            "integration": _is_integration(test_id),
        }
        if detail:
            record["detail"] = detail
        self.tests[test_id] = record

    def addSuccess(self, test):
        super().addSuccess(test)
        self._finish(test, "passed")

    def addError(self, test, err):
        super().addError(test, err)
        self._finish(test, "error", "".join(traceback.format_exception(*err)))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._finish(test, "failed", "".join(traceback.format_exception(*err)))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._finish(test, "skipped", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._finish(test, "expected_failure", "".join(traceback.format_exception(*err)))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._finish(test, "unexpected_success")


def discover_suite(directory):
    test_dir = directory / "tests"
    if not test_dir.is_dir():
        return unittest.TestSuite()

    # A few legacy tests import support modules directly from their tests dir.
    paths = [str(directory), str(test_dir)]
    for path in reversed(paths):
        if path not in sys.path:
            sys.path.insert(0, path)
    loader = unittest.TestLoader()
    return loader.discover(
        start_dir=str(test_dir),
        pattern="test*.py",
    )


def run_suite(name, directory, verbosity):
    suite = discover_suite(directory)
    result = ReportResult()
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=verbosity)
    # TextTestRunner creates its own result, so use its formatter but our result.
    runner._makeResult = lambda: result
    started = time.perf_counter()
    success = runner.run(suite)
    records = list(result.tests.values())
    return {
        "name": name,
        "path": str(directory.relative_to(ROOT)),
        "success": success.wasSuccessful() and not any(
            test["status"] == "unexpected_success" for test in records
        ),
        "duration_seconds": round(time.perf_counter() - started, 6),
        "tests": sorted(records, key=lambda item: item["id"]),
    }


def summary(suites):
    records = [test for suite in suites for test in suite["tests"]]
    counts = {status: sum(test["status"] == status for test in records)
              for status in (
                  "passed", "failed", "error", "skipped",
                  "expected_failure", "unexpected_success",
              )}
    return {
        "total": len(records),
        **counts,
        "successful": all(suite["success"] for suite in suites),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", default="reports/test-report.json",
        help="JSON report path relative to the repository root",
    )
    parser.add_argument("--verbosity", type=int, default=2, choices=(1, 2))
    parser.add_argument(
        "--integration", action="store_true",
        help="enable tests guarded by FLASHCONTROL_INTEGRATION=1",
    )
    args = parser.parse_args(argv)

    os.environ["FLASHCONTROL_INTEGRATION"] = "1" if args.integration else "0"
    started_at = datetime.datetime.now(datetime.timezone.utc)
    suites = [
        run_suite(name, directory, args.verbosity)
        for name, directory in SUITES
    ]
    report = {
        "schema_version": 1,
        "generated_at_utc": started_at.isoformat(),
        "integration_enabled": args.integration,
        "python": sys.version,
        "platform": sys.platform,
        "summary": summary(suites),
        "suites": suites,
    }
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print("\nJSON report: {}".format(output))
    return 0 if report["summary"]["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
