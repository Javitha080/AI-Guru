"""Tests for GitHub Actions CI/CD and automated release workflows.

Verifies:
1. Valid YAML syntax for all workflows in .github/workflows/.
2. Release pipeline structural invariants (triggers, permissions, jobs, assets).
3. Docker release and PyPI release multi-trigger support (workflow_dispatch, workflow_call).
4. Single source of truth for version (__version__.py and pyproject.toml).
5. CI Summary gatekeeper configuration in ci.yml for branch protection rulesets.
"""

from __future__ import annotations

from pathlib import Path
import re

from packaging.version import Version
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _load_workflow(filename: str) -> dict:
    path = WORKFLOWS_DIR / filename
    assert path.exists(), f"Workflow file {filename} does not exist at {path}"
    content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    assert isinstance(data, dict), f"Workflow {filename} is not a valid YAML dict"
    return data


def _triggers(wf: dict) -> dict:
    """Return the `on:` trigger mapping, handling YAML 1.1 boolean parsing.

    PyYAML resolves an unquoted `on:` key to boolean True, so workflows that
    write `on:` (rather than quoted `'on':`) store their triggers under True.
    """
    if "on" in wf and isinstance(wf["on"], dict):
        return wf["on"]
    assert True in wf and isinstance(wf[True], dict), "Workflow must define an 'on' trigger mapping"
    return wf[True]


def test_all_workflows_parse_valid_yaml():
    yaml_files = list(WORKFLOWS_DIR.glob("*.yml")) + list(WORKFLOWS_DIR.glob("*.yaml"))
    assert len(yaml_files) >= 5, f"Expected at least 5 workflow files, found {len(yaml_files)}"
    for yml in yaml_files:
        content = yml.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict), f"{yml.name} did not parse as a dictionary"
        assert "name" in parsed, f"{yml.name} missing 'name' field"


def test_release_workflow_structure():
    wf = _load_workflow("release.yml")
    triggers = _triggers(wf)
    assert "push" in triggers, "release.yml missing 'push' trigger"
    assert "tags" in triggers["push"], "release.yml missing 'tags' filter in push trigger"
    assert "workflow_dispatch" in triggers, "release.yml missing 'workflow_dispatch' trigger"

    dispatch_inputs = triggers["workflow_dispatch"].get("inputs", {})
    assert "dry_run" in dispatch_inputs, "release.yml missing 'dry_run' input"
    assert "publish_docker" in dispatch_inputs, "release.yml missing 'publish_docker' input"
    assert "publish_pypi" in dispatch_inputs, "release.yml missing 'publish_pypi' input"

    permissions = wf.get("permissions", {})
    assert permissions.get("contents") == "write", "release.yml requires contents: write"
    assert permissions.get("packages") == "write", "release.yml requires packages: write"
    assert permissions.get("id-token") == "write", (
        "release.yml requires id-token: write for PyPI OIDC"
    )

    jobs = wf.get("jobs", {})
    assert "verify-and-release" in jobs, "release.yml missing 'verify-and-release' job"
    assert "docker-publish" in jobs, "release.yml missing 'docker-publish' job"
    assert "pypi-publish" in jobs, "release.yml missing 'pypi-publish' job"
    assert "summary" in jobs, "release.yml missing 'summary' job"

    # Verify release assets packaging in verify-and-release job
    vr_steps = jobs["verify-and-release"].get("steps", [])
    step_names = [s.get("name", "") for s in vr_steps]
    assert any("prepare_web_package.py" in s.get("run", "") for s in vr_steps), (
        "release.yml must run scripts/prepare_web_package.py"
    )
    assert any("build --wheel" in s.get("run", "") for s in vr_steps), (
        "release.yml must build the distribution wheel"
    )
    assert any("SHA256" in name for name in step_names), (
        "release.yml must generate SHA256 checksums"
    )
    assert any("action-gh-release" in s.get("uses", "") for s in vr_steps), (
        "release.yml must use softprops/action-gh-release"
    )


def test_docker_release_triggers():
    wf = _load_workflow("docker-release.yml")
    triggers = _triggers(wf)
    # Single-publisher design: release.yml owns Docker publishing, so this
    # workflow must NOT subscribe to `release: published` (that double-pushes
    # every release). Manual dispatch + reusable call only.
    assert "release" not in triggers, (
        "docker-release.yml must not trigger on 'release: published' — "
        "release.yml is the sole publisher"
    )
    assert "workflow_dispatch" in triggers, "docker-release.yml missing 'workflow_dispatch' trigger"
    assert "workflow_call" in triggers, "docker-release.yml missing 'workflow_call' trigger"

    permissions = wf.get("permissions", {})
    assert permissions.get("packages") == "write", "docker-release.yml requires packages: write"


def test_pypi_release_triggers():
    wf = _load_workflow("pypi-release.yml")
    triggers = _triggers(wf)
    # Single-publisher design: release.yml owns PyPI publishing, so this
    # workflow must NOT subscribe to `release: published` (the second upload
    # would fail on "version already exists"). Manual dispatch + reusable
    # call only.
    assert "release" not in triggers, (
        "pypi-release.yml must not trigger on 'release: published' — "
        "release.yml is the sole publisher"
    )
    assert "workflow_dispatch" in triggers, "pypi-release.yml missing 'workflow_dispatch' trigger"
    assert "workflow_call" in triggers, "pypi-release.yml missing 'workflow_call' trigger"

    permissions = wf.get("permissions", {})
    assert permissions.get("id-token") == "write", "pypi-release.yml requires id-token: write"


def test_single_publisher_per_artifact():
    """Exactly one workflow may publish each release artifact.

    release.yml performs the Docker + PyPI publishes internally, so the
    standalone publisher workflows must not also fire automatically on the
    Release they would duplicate.
    """
    release_wf = _load_workflow("release.yml")
    release_jobs = release_wf.get("jobs", {})
    assert "docker-publish" in release_jobs, "release.yml must own the Docker publish"
    assert "pypi-publish" in release_jobs, "release.yml must own the PyPI publish"

    for filename in ("docker-release.yml", "pypi-release.yml"):
        assert "release" not in _triggers(_load_workflow(filename)), (
            f"{filename} must not auto-fire on releases while release.yml "
            "publishes the same artifact"
        )


def test_ci_summary_gatekeeper():
    wf = _load_workflow("ci.yml")
    jobs = wf.get("jobs", {})
    assert "summary" in jobs, "ci.yml must have a 'summary' job"
    summary_job = jobs["summary"]
    assert summary_job.get("name") == "CI Summary", "ci.yml summary job must be named 'CI Summary'"
    needs = summary_job.get("needs", [])
    expected_gates = ["lint", "typecheck", "security", "web", "python-tests", "docker"]
    for gate in expected_gates:
        assert gate in needs, f"CI Summary must depend on gate '{gate}'"


def test_single_source_of_truth_version():
    version_file = REPO_ROOT / "deeptutor" / "__version__.py"
    assert version_file.exists()
    content = version_file.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', content, re.MULTILINE)
    assert match, "Could not find __version__ in deeptutor/__version__.py"
    raw_version = match.group(1)

    # Validate PEP 440 compliance
    v = Version(raw_version)
    assert str(v) == raw_version or str(v).startswith(raw_version.split("-")[0])

    pyproject_file = REPO_ROOT / "pyproject.toml"
    assert pyproject_file.exists()
    pyproject_text = pyproject_file.read_text(encoding="utf-8")
    assert 'version = {attr = "deeptutor.__version__.__version__"}' in pyproject_text


def test_release_concurrency_precedence():
    wf = _load_workflow("release.yml")
    concurrency = wf.get("concurrency", {})
    group = concurrency.get("group", "")
    assert "inputs.tag_name || github.ref_name" in group, (
        "release.yml concurrency group must prioritize inputs.tag_name over github.ref_name"
    )


def test_release_summary_failure_propagation():
    wf = _load_workflow("release.yml")
    jobs = wf.get("jobs", {})
    summary = jobs.get("summary", {})
    steps = summary.get("steps", [])
    fail_step = next(
        (
            s
            for s in steps
            if "fail" in s.get("name", "").lower() or "check" in s.get("name", "").lower()
        ),
        None,
    )
    assert fail_step is not None, "release.yml summary job missing final status check step"
    condition = fail_step.get("if", "")
    assert "docker-publish.result" in condition, (
        "release.yml summary must propagate docker-publish failure to prevent silent build failures"
    )


def test_pypi_publish_exports_status():
    wf = _load_workflow("release.yml")
    jobs = wf.get("jobs", {})
    pypi_job = jobs.get("pypi-publish", {})
    outputs = pypi_job.get("outputs", {})
    assert "published" in outputs, (
        "pypi-publish job must export 'published' output so summary table can accurately report status"
    )


def test_docker_release_safe_checkout():
    wf = _load_workflow("docker-release.yml")
    jobs = wf.get("jobs", {})
    bp_job = jobs.get("build-and-push", {})
    steps = bp_job.get("steps", [])
    checkout_step = next((s for s in steps if "checkout" in s.get("name", "").lower()), None)
    assert checkout_step is not None
    ref = checkout_step.get("with", {}).get("ref", "")
    assert "github.sha" in ref, (
        "docker-release.yml checkout must safely use github.sha to avoid crashing on unpushed tags"
    )


def test_ancestry_check_uses_force_refspecs():
    for filename in ["release.yml", "pypi-release.yml"]:
        wf = _load_workflow(filename)
        jobs = wf.get("jobs", {})
        steps = next(iter(jobs.values())).get("steps", [])
        ancestry_step = next(
            (
                s
                for s in steps
                if "ancestor" in s.get("name", "").lower()
                or "default branch" in s.get("name", "").lower()
            ),
            None,
        )
        assert ancestry_step is not None, f"{filename} missing ancestry verification step"
        run_script = ancestry_step.get("run", "")
        assert "+refs/heads/master:refs/remotes/origin/master" in run_script, (
            f"{filename} must use force refspecs (+refs/heads/master) to prevent non-fast-forward rejection"
        )
        assert "HEAD^{commit}" in run_script, (
            f"{filename} must resolve commit using HEAD^{{commit}} for annotated tag safety"
        )


def test_ci_push_skips_docs_only_commits():
    """Docs-only pushes to long-lived branches must not burn a full pipeline."""
    wf = _load_workflow("ci.yml")
    push = _triggers(wf).get("push", {})
    paths = push.get("paths", [])
    assert paths, "ci.yml push trigger must keep its path filter"
    for docs_only in ("docs/**", "README.md", "CONTRIBUTING.md", ".secrets.baseline"):
        assert docs_only not in paths, (
            f"ci.yml push paths must not contain {docs_only!r}: a docs-only "
            "push would otherwise run all six gates"
        )
    # PRs stay unfiltered so docs changes are still gated before merge.
    assert "pull_request" in _triggers(wf), "ci.yml must trigger unfiltered on pull_request"
    assert "paths" not in _triggers(wf).get("pull_request", {}), (
        "ci.yml pull_request trigger must never be path-filtered (stranded checks)"
    )


def test_ci_typecheck_includes_routers():
    """The mypy gate must cover the auth-gated router layer."""
    raw = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "deeptutor/api/routers/" not in raw.split("Run mypy", 1)[-1].split("- name:", 1)[0], (
        "ci.yml mypy --exclude must not drop deeptutor/api/routers/"
    )


def test_ci_bandit_scans_scripts():
    """HIGH-severity Bandit gate must cover CI helper scripts too."""
    wf = _load_workflow("ci.yml")
    steps = wf["jobs"]["security"]["steps"]
    bandit_step = next(s for s in steps if "bandit" in s.get("name", "").lower())
    assert "scripts" in bandit_step.get("run", ""), (
        "ci.yml Bandit step must scan scripts/ in addition to the packages"
    )


def test_ci_smoke_requires_api_ping():
    """Container smoke test must fail when the API probe is down, even if `/` responds."""
    raw = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    smoke = raw.split("Smoke-test container", 1)[-1]
    assert "/api/v1/health/ping" in smoke, "smoke test must probe the API liveness endpoint"
    assert "backend_degraded" in smoke or "failed to mount" in smoke, (
        "smoke test must distinguish a degraded backend (root-only) from a healthy one"
    )
