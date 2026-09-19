#!/usr/bin/env python3
"""AI Guru / DeepTutor — Local CI Gate Runner.

Runs the same gating checks executed in the GitHub Actions CI pipeline:
  - Ruff lint & format check
  - mypy static type analysis
  - Security scanning (Bandit + detect-secrets if in git repository)
  - Web checks (ESLint, tsc type-check, Node tests)
  - Python tests (verification battery or full suite)

Usage:
  python scripts/ci_check.py                 # run all gates (fast test battery)
  python scripts/ci_check.py --all-tests     # run all gates with full pytest suite
  python scripts/ci_check.py --fast          # run fast gates (lint, typecheck, web)
  python scripts/ci_check.py --gate lint     # run only lint gate
  python scripts/ci_check.py --gate typecheck
  python scripts/ci_check.py --gate security
  python scripts/ci_check.py --gate web
  python scripts/ci_check.py --gate python
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"

if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


@dataclass
class GateResult:
    name: str
    passed: bool
    duration_s: float
    output: str = ""


def _run_cmd(
    cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> tuple[bool, str, float]:
    start = time.perf_counter()
    try:
        run_env = dict(os.environ)
        # Force UTF-8 child output: on Windows consoles with a legacy code
        # page, tools printing non-ASCII (e.g. Bandit echoing matched source
        # lines) crash with UnicodeEncodeError instead of reporting findings.
        run_env.setdefault("PYTHONIOENCODING", "utf-8")
        if env:
            run_env.update(env)
        # shell=True is constrained to the npm/npx shims (argv[0] allowlist);
        # remaining argv are fixed gate commands, never user input.
        proc = subprocess.run(
            cmd,
            cwd=cwd or PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=run_env,
            shell=(sys.platform == "win32" and cmd[0] in ("npm", "npx", "npm.cmd", "npx.cmd")),  # nosec B602
        )
        duration = time.perf_counter() - start
        return proc.returncode == 0, proc.stdout, duration
    except Exception as exc:
        duration = time.perf_counter() - start
        return False, str(exc), duration


def check_lint() -> GateResult:
    print("▶ [1/5] Running Ruff lint & format check...")
    t0 = time.perf_counter()
    ok_lint, out_lint, _ = _run_cmd([sys.executable, "-m", "ruff", "check", "."])
    ok_fmt, out_fmt, _ = _run_cmd([sys.executable, "-m", "ruff", "format", "--check", "."])
    duration = time.perf_counter() - t0

    passed = ok_lint and ok_fmt
    out = ""
    if not ok_lint:
        out += f"Ruff lint errors:\n{out_lint}\n"
    if not ok_fmt:
        out += f"Ruff formatting errors:\n{out_fmt}\n"

    status = "✅ PASSED" if passed else "❌ FAILED"
    print(f"  {status} ({duration:.1f}s)")
    return GateResult("Lint (Ruff)", passed, duration, out)


def check_typecheck() -> GateResult:
    print("▶ [2/5] Running mypy type check...")
    t0 = time.perf_counter()
    cmd = [
        sys.executable,
        "-m",
        "mypy",
        "--no-site-packages",
        "--platform",
        "linux",
        "--ignore-missing-imports",
        "--no-error-summary",
        "--no-strict-optional",
        "--exclude",
        # Same exclusion profile as the CI typecheck gate (ci.yml) and the
        # pre-commit mypy hook: api/routers/ is INCLUDED.
        "^(tests/|scripts/|data/|deeptutor/agents/|deeptutor/services/rag/)",
        ".",
    ]
    ok, out, duration = _run_cmd(cmd)
    status = "✅ PASSED" if ok else "❌ FAILED"
    print(f"  {status} ({duration:.1f}s)")
    return GateResult("Type Check (mypy)", ok, duration, out if not ok else "")


def check_security() -> GateResult:
    print("▶ [3/5] Running security scan (Bandit + detect-secrets)...")
    t0 = time.perf_counter()
    bandit_cmd = [
        sys.executable,
        "-m",
        "bandit",
        "-c",
        "pyproject.toml",
        "-q",
        "-lll",
        "-r",
        "deeptutor",
        "deeptutor_cli",
        "scripts",
    ]
    ok_bandit, out_bandit, _ = _run_cmd(bandit_cmd)

    ok_secrets = True
    out_secrets = ""
    is_git_repo = (PROJECT_ROOT / ".git").is_dir()
    if is_git_repo and shutil.which("detect-secrets-hook"):
        # Run detect-secrets against git tracked files
        try:
            ls_proc = subprocess.run(
                ["git", "ls-files"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            files = [
                f
                for f in ls_proc.stdout.splitlines()
                if not f.startswith(("ictfromabc/", "data/"))
                and not f.endswith((".pdf", ".zip", ".lock", ".tar.gz"))
            ]
            if files:
                ds_proc = subprocess.run(
                    ["detect-secrets-hook", "--baseline", ".secrets.baseline", *files],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                )
                if ds_proc.returncode == 1:
                    ok_secrets = False
                    out_secrets = (
                        f"detect-secrets found new secrets:\n{ds_proc.stdout}\n{ds_proc.stderr}\n"
                    )
                elif ds_proc.returncode == 3:
                    # Stale baseline line numbers only: no new secrets, but
                    # warn like CI does and refresh the baseline on request.
                    # (CI step exits 0 with a warning; mirror that here.)
                    out_secrets = (
                        "detect-secrets: no new secrets, but .secrets.baseline "
                        "line numbers are stale. Run "
                        "`pre-commit run detect-secrets --all-files` and commit "
                        "the refreshed baseline.\n"
                        f"{ds_proc.stdout}\n{ds_proc.stderr}\n"
                    )
                elif ds_proc.returncode not in (0, 1, 3):
                    ok_secrets = False
                    out_secrets = (
                        f"detect-secrets-hook failed with exit code {ds_proc.returncode}:\n"
                        f"{ds_proc.stdout}\n{ds_proc.stderr}\n"
                    )
        except Exception as exc:
            out_secrets = f"detect-secrets check error: {exc}\n"
    elif not is_git_repo:
        print("  ℹ️ Skipped detect-secrets (non-git environment; checked in GitHub Actions CI)")

    duration = time.perf_counter() - t0
    passed = ok_bandit and ok_secrets
    out = ""
    if not ok_bandit:
        out += f"Bandit security issues:\n{out_bandit}\n"
    if not ok_secrets:
        out += out_secrets
    elif out_secrets:
        # Non-blocking warning (exit 3, stale baseline): surface it without
        # failing the gate, mirroring the CI security step.
        print(f"  ⚠️ {out_secrets.splitlines()[0]}")

    status = "✅ PASSED" if passed else "❌ FAILED"
    print(f"  {status} ({duration:.1f}s)")
    return GateResult("Security (Bandit + Secrets)", passed, duration, out)


def check_web() -> GateResult:
    print("▶ [4/5] Running Web checks (ESLint + tsc + node tests)...")
    t0 = time.perf_counter()
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    npm = "npm.cmd" if sys.platform == "win32" else "npm"

    if not shutil.which(npm) and not shutil.which(npx):
        print("  ⚠️ Node/npm not found, skipping web checks.")
        return GateResult("Web (lint + tsc + tests)", True, 0.0, "Node not found")

    ok_lint, out_lint, _ = _run_cmd([npm, "run", "lint"], cwd=WEB_DIR)
    ok_tsc, out_tsc, _ = _run_cmd([npx, "tsc", "--noEmit"], cwd=WEB_DIR)
    ok_tests, out_tests, _ = _run_cmd([npm, "run", "test:node"], cwd=WEB_DIR)
    duration = time.perf_counter() - t0

    passed = ok_lint and ok_tsc and ok_tests
    out = ""
    if not ok_lint:
        out += f"ESLint errors:\n{out_lint}\n"
    if not ok_tsc:
        out += f"TypeScript errors:\n{out_tsc}\n"
    if not ok_tests:
        out += f"Node test failures:\n{out_tests}\n"

    status = "✅ PASSED" if passed else "❌ FAILED"
    print(f"  {status} ({duration:.1f}s)")
    return GateResult("Web (lint + tsc + tests)", passed, duration, out)


def check_python_tests(*, all_tests: bool = False) -> GateResult:
    suite_desc = "full test suite" if all_tests else "verification tests"
    print(f"▶ [5/5] Running Python {suite_desc}...")
    t0 = time.perf_counter()
    if all_tests:
        test_args = ["tests", "deeptutor/learning/tests"]
    else:
        test_args = [
            "tests/e2e",
            "tests/test_study_monitoring.py",
            "tests/test_study_monitoring_stress.py",
            "tests/test_cv_adversarial.py",
            "tests/services/test_remote_security.py",
            "tests/test_fresh_install_smoke.py",
        ]
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        *test_args,
    ]
    ok, out, duration = _run_cmd(cmd)
    status = "✅ PASSED" if ok else "❌ FAILED"
    print(f"  {status} ({duration:.1f}s)")
    gate_name = "Python Tests (full)" if all_tests else "Python Tests (verification)"
    return GateResult(gate_name, ok, duration, out if not ok else "")


GATES: dict[str, Callable[[], GateResult]] = {
    "lint": check_lint,
    "typecheck": check_typecheck,
    "security": check_security,
    "web": check_web,
    "python": check_python_tests,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AI Guru CI gates locally.")
    parser.add_argument(
        "--gate",
        choices=list(GATES.keys()),
        help="Run only a single gate.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Run fast gates only (lint, typecheck, web).",
    )
    parser.add_argument(
        "--all-tests",
        action="store_true",
        help="Run full pytest test suite (tests + deeptutor/learning/tests) instead of fast verification battery.",
    )
    args = parser.parse_args()

    # Ensure runtime settings exist for tests
    settings_dir = PROJECT_ROOT / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    main_yaml = settings_dir / "main.yaml"
    if not main_yaml.exists():
        main_yaml.write_text(
            "system:\n  language: en\nlogging:\n  level: WARNING\n", encoding="utf-8"
        )

    selected_gates: list[str]
    if args.gate:
        selected_gates = [args.gate]
    elif args.fast:
        selected_gates = ["lint", "typecheck", "web"]
    else:
        selected_gates = list(GATES.keys())

    print("=" * 60)
    print("🚀 AI Guru — Local CI Gate Runner")
    print(f"Gates to execute: {', '.join(selected_gates)}")
    print("=" * 60)

    start_total = time.perf_counter()
    results: list[GateResult] = []

    for name in selected_gates:
        if name == "python":
            res = check_python_tests(all_tests=args.all_tests)
        else:
            res = GATES[name]()
        results.append(res)

    total_duration = time.perf_counter() - start_total

    print("\n" + "=" * 60)
    print("📋 SUMMARY RESULTS")
    print("=" * 60)
    all_passed = True
    for r in results:
        status_icon = "✅ Passed" if r.passed else "❌ Failed"
        print(f"| {r.name:<30} | {status_icon:<10} | {r.duration_s:>6.1f}s |")
        if not r.passed:
            all_passed = False

    print("-" * 60)
    print(f"Total time: {total_duration:.1f}s")

    if not all_passed:
        print("\n💥 GATE FAILURES:")
        for r in results:
            if not r.passed:
                print(f"\n--- {r.name} ---")
                print(r.output.strip() or "No output captured.")
        return 1

    print("\n🎉 All local CI gates passed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
