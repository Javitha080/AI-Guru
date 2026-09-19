"""Tests for Dependabot configuration and Dependabot automation workflow."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPENDABOT_YML = ROOT / ".github" / "dependabot.yml"
WORKFLOW_YML = ROOT / ".github" / "workflows" / "dependabot-automation.yml"


def test_dependabot_config_exists_and_parses() -> None:
    assert DEPENDABOT_YML.exists(), "dependabot.yml must exist"
    data = yaml.safe_load(DEPENDABOT_YML.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "dependabot.yml must be a valid YAML mapping"
    assert data.get("version") == 2, "Dependabot configuration version must be 2"
    assert "updates" in data, "Dependabot must have an 'updates' section"


def test_dependabot_ecosystems_coverage() -> None:
    data = yaml.safe_load(DEPENDABOT_YML.read_text(encoding="utf-8"))
    updates = data.get("updates", [])
    assert len(updates) >= 4, "Must cover at least github-actions, npm, pip, and docker"

    ecosystems = {item.get("package-ecosystem"): item for item in updates}

    # Verify github-actions
    assert "github-actions" in ecosystems, "github-actions ecosystem must be configured"
    gh_cfg = ecosystems["github-actions"]
    assert gh_cfg["directory"] == "/"
    assert gh_cfg["schedule"]["interval"] == "weekly"
    assert "groups" in gh_cfg
    assert "actions-minor-patch" in gh_cfg["groups"]
    assert "dependencies" in gh_cfg.get("labels", [])

    # Verify npm
    assert "npm" in ecosystems, "npm ecosystem must be configured"
    npm_cfg = ecosystems["npm"]
    assert npm_cfg["directory"] == "/web"
    assert npm_cfg["schedule"]["interval"] == "weekly"
    assert "groups" in npm_cfg
    assert "npm-minor-patch" in npm_cfg["groups"]
    assert "dependencies" in npm_cfg.get("labels", [])

    # Verify pip
    assert "pip" in ecosystems, "pip ecosystem must be configured"
    pip_cfg = ecosystems["pip"]
    assert pip_cfg["directory"] == "/"
    assert pip_cfg["schedule"]["interval"] == "monthly"
    assert "groups" in pip_cfg
    assert "pip-minor-patch" in pip_cfg["groups"]
    assert "dependencies" in pip_cfg.get("labels", [])

    # Verify docker
    assert "docker" in ecosystems, "docker ecosystem must be configured"
    docker_cfg = ecosystems["docker"]
    assert docker_cfg["directory"] == "/"
    assert docker_cfg["schedule"]["interval"] == "monthly"
    assert "groups" in docker_cfg
    assert "docker-minor-patch" in docker_cfg["groups"]
    assert "dependencies" in docker_cfg.get("labels", [])


def test_dependabot_commit_message_conventions() -> None:
    data = yaml.safe_load(DEPENDABOT_YML.read_text(encoding="utf-8"))
    for item in data.get("updates", []):
        eco = item.get("package-ecosystem")
        commit_cfg = item.get("commit-message", {})
        assert commit_cfg.get("prefix") == "chore", f"{eco} must use chore commit prefix"
        assert commit_cfg.get("include") == "scope", f"{eco} must include scope in commits"


def test_dependabot_automation_workflow_structure() -> None:
    assert WORKFLOW_YML.exists(), "dependabot-automation.yml workflow must exist"
    data = yaml.safe_load(WORKFLOW_YML.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "workflow must be a valid YAML mapping"

    # Triggers (handle YAML 1.1 bool parsing of 'on' or quoted 'on')
    assert "on" in data or True in data, "Workflow must define 'on' trigger"
    triggers = data.get("on") if "on" in data else data.get(True)
    assert isinstance(triggers, dict), "Triggers must be a mapping"
    assert "pull_request_target" in triggers, (
        "Workflow must trigger on pull_request_target to ensure write permissions for Dependabot PRs"
    )

    # Permissions
    perms = data.get("permissions", {})
    assert perms.get("contents") == "write"
    assert perms.get("pull-requests") == "write"
    assert perms.get("issues") == "write"

    # Job & Actor Guard
    jobs = data.get("jobs", {})
    assert "dependabot" in jobs
    job = jobs["dependabot"]
    assert "dependabot[bot]" in job.get("if", ""), "Must guard on dependabot[bot] actor"

    # Steps verification
    steps = job.get("steps", [])
    step_uses = [s.get("uses", "") for s in steps if "uses" in s]
    assert any("fetch-metadata@v3" in u for u in step_uses), "Must use dependabot/fetch-metadata@v3"

    raw_text = WORKFLOW_YML.read_text(encoding="utf-8")
    assert "gh pr review --approve" in raw_text, "Must include automated approval step"
    assert "gh pr merge --auto" in raw_text, "Must include auto-merge step"
    assert "GITHUB_STEP_SUMMARY" in raw_text, "Must write workflow summary"


def test_dependabot_safety_gate_logic() -> None:
    """Ensure major updates are strictly excluded from auto-approval and auto-merge."""
    data = yaml.safe_load(WORKFLOW_YML.read_text(encoding="utf-8"))
    job = data["jobs"]["dependabot"]
    steps = {s.get("name"): s for s in job.get("steps", [])}

    approve_step = steps.get("Auto-Approve Safe PRs")
    assert approve_step is not None, "Auto-Approve step must exist"
    approve_if = approve_step.get("if", "")
    assert "!=" in approve_if and "version-update:semver-major" in approve_if, (
        "Auto-approval must explicitly exclude version-update:semver-major"
    )
    assert "!contains" in approve_if and "major" in approve_if, (
        "Auto-approval must explicitly exclude grouped major updates"
    )

    merge_step = steps.get("Enable Auto-Merge for Safe PRs")
    assert merge_step is not None, "Auto-Merge step must exist"
    merge_if = merge_step.get("if", "")
    assert "!=" in merge_if and "version-update:semver-major" in merge_if, (
        "Auto-merge must explicitly exclude version-update:semver-major"
    )
    assert "!contains" in merge_if and "major" in merge_if, (
        "Auto-merge must explicitly exclude grouped major updates"
    )

    flag_step = steps.get("Flag Major Update for Manual Review")
    assert flag_step is not None, "Flag Major Update step must exist"
    flag_if = flag_step.get("if", "")
    assert "version-update:semver-major" in flag_if
    assert "contains" in flag_if and "major" in flag_if


def test_dependabot_rebase_strategy() -> None:
    data = yaml.safe_load(DEPENDABOT_YML.read_text(encoding="utf-8"))
    for item in data.get("updates", []):
        eco = item.get("package-ecosystem")
        assert item.get("rebase-strategy") == "auto", f"{eco} must configure rebase-strategy: auto"


def test_dependabot_automation_concurrency() -> None:
    """One triage run per PR so steps never stack up on re-synchronize."""
    data = yaml.safe_load(WORKFLOW_YML.read_text(encoding="utf-8"))
    concurrency = data.get("concurrency", {})
    group = concurrency.get("group", "")
    assert "pull_request.number" in group, (
        "dependabot-automation.yml must group concurrency by PR number"
    )
    assert concurrency.get("cancel-in-progress") is True


def test_dependabot_automation_ensures_labels() -> None:
    """Label creation must precede labeling (gh fails on unknown labels)."""
    raw_text = WORKFLOW_YML.read_text(encoding="utf-8")
    assert "gh label create" in raw_text, "Must ensure triage labels exist before attaching them"
    assert "--force" in raw_text, "Label creation must be idempotent (--force)"
