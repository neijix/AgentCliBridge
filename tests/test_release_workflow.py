"""The release workflow (AC9): ``.github/workflows/release.yml``.

The workflow is parsed, never run: what is checked is the shape the plan fixes - a ``v*`` tag only,
GitHub-hosted runners, the macOS / Windows jobs after the Linux one, no
``--clobber``, one last job that writes ``SHA256SUMS``, signing secrets mapped to the packagers' variables.
"""
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
RELEASE_YML = WORKFLOWS / "release.yml"

BUILD_JOBS = ("linux", "macos", "windows")
RUNNERS = {"linux": "ubuntu-latest", "macos": "macos-latest", "windows": "windows-latest"}


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(RELEASE_YML.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def jobs(workflow) -> dict:
    return workflow["jobs"]


def _condition(job: dict) -> str:
    """The job's ``if`` without the ``${{ }}`` wrapper and without extra spaces."""
    text = str(job.get("if", "")).strip()
    match = re.fullmatch(r"\$\{\{(.*)\}\}", text, re.S)
    return " ".join((match.group(1) if match else text).split())


def _run_lines(job: dict) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def _release_call(job: dict) -> str:
    calls = [run for run in _run_lines(job) if "packaging/release.sh" in run]
    assert len(calls) == 1, calls
    return calls[0]


def test_triggers_on_v_tags_only(workflow):
    # YAML 1.1 reads the key `on` as True.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers == {"push": {"tags": ["v*"]}}


def test_the_jobs_are_the_three_builds_and_one_sums_job(jobs):
    assert set(jobs) == {*BUILD_JOBS, "sums"}


@pytest.mark.parametrize("name", (*BUILD_JOBS, "sums"))
def test_every_job_runs_on_its_os_github_hosted_runner(jobs, name):
    assert jobs[name]["runs-on"] == RUNNERS.get(name, RUNNERS["linux"])


def test_the_linux_job_has_no_condition_and_the_others_wait_for_it(jobs):
    assert "if" not in jobs["linux"]
    assert "needs" not in jobs["linux"]
    # Linux creates the Release and uploads the snapshot; two jobs doing that at once would collide.
    assert jobs["macos"]["needs"] == "linux"
    assert jobs["windows"]["needs"] == "linux"


def test_every_job_always_runs_and_the_last_one_waits_for_every_build(jobs):
    for name, job in jobs.items():
        assert _condition(job) == "", name
    assert sorted(jobs["sums"]["needs"]) == sorted(BUILD_JOBS)


def test_the_build_jobs_upload_without_building_the_sums_and_the_last_job_writes_them(jobs):
    for name in BUILD_JOBS:
        call = _release_call(jobs[name])
        assert "release.sh release" in call
        assert '--tag "$GITHUB_REF_NAME"' in call
        assert "--no-sums" in call
    last = _release_call(jobs["sums"])
    assert "release.sh sums" in last
    assert '--tag "$GITHUB_REF_NAME"' in last
    assert "release.sh release" not in last
    # Only the last job writes SHA256SUMS: one writer, no race between the build jobs.
    assert sum("release.sh sums" in _release_call(job) for job in jobs.values()) == 1


def test_nothing_replaces_an_uploaded_asset():
    for path in WORKFLOWS.glob("release.y*ml"):
        text = path.read_text(encoding="utf-8")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        assert "--clobber" not in code, path


def test_the_release_token_is_the_workflow_token_with_write_access_on_each_job(workflow, jobs):
    assert workflow["permissions"] == {"contents": "read"}
    for name, job in jobs.items():
        assert job["permissions"] == {"contents": "write"}, name
        assert job["env"]["GH_TOKEN"] == "${{ github.token }}", name


def test_only_checkout_and_setup_uv_are_used_and_pinned_as_ci_pins_them(jobs):
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    ci_steps = ci["jobs"]["test"]["steps"]
    ci_pins = {
        name: next(step["uses"] for step in ci_steps if str(step.get("uses", "")).startswith(name + "@"))
        for name in ("actions/checkout", "astral-sh/setup-uv")
    }
    for name, job in jobs.items():
        used = [step["uses"] for step in job["steps"] if "uses" in step]
        assert used == list(ci_pins.values()), name


def test_every_job_gets_python_312_from_uv_and_sets_PYTHON_before_release_sh(jobs):
    for name, job in jobs.items():
        steps = job["steps"]
        setup = next(i for i, step in enumerate(steps) if str(step.get("uses", "")).startswith("astral-sh/setup-uv@"))
        assert steps[setup]["with"] == {"python-version": "3.12"}, name
        export = next(i for i, step in enumerate(steps) if "GITHUB_ENV" in step.get("run", ""))
        assert (
            steps[export]["run"]
            == 'uv python install 3.12 && py="$(uv python find 3.12)" && echo "PYTHON=$py" >> "$GITHUB_ENV"'
        ), name
        release = next(i for i, step in enumerate(steps) if "packaging/release.sh" in step.get("run", ""))
        assert setup < export < release, name


def test_the_windows_job_runs_the_bash_script_in_bash(jobs):
    steps = [step for step in jobs["windows"]["steps"] if "run" in step]
    assert steps and all(step.get("shell") == "bash" for step in steps)


@pytest.mark.parametrize(
    ("name", "variable"),
    (("macos", "AGENTCLIBRIDGE_PKG_SIGN_IDENTITY"), ("windows", "AGENTCLIBRIDGE_WIN_SIGN_THUMBPRINT")),
)
def test_signing_is_driven_by_an_optional_secret_and_only_in_its_own_job(jobs, name, variable):
    # The packagers read this variable and build unsigned when it is empty; an unset secret reads as empty.
    release_steps = [step for step in jobs[name]["steps"] if "packaging/release.sh" in step.get("run", "")]
    assert [step["env"][variable] for step in release_steps] == [f"${{{{ secrets.{variable} }}}}"]
    for other, job in jobs.items():
        if other != name:
            assert variable not in yaml.safe_dump(job), other


def test_the_signing_variables_are_the_ones_the_packagers_read():
    assert "AGENTCLIBRIDGE_PKG_SIGN_IDENTITY" in (ROOT / "packaging" / "macos" / "build-pkg.sh").read_text(
        encoding="utf-8"
    )
    assert "AGENTCLIBRIDGE_WIN_SIGN_THUMBPRINT" in (ROOT / "packaging" / "windows" / "build-exe.ps1").read_text(
        encoding="utf-8"
    )
