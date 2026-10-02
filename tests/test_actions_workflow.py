"""Execute the actual workflow shell branches with offline synthetic outputs."""

import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/checkin.yml"


def _step(name: str) -> str:
    return WORKFLOW.read_text(encoding="utf-8").split(f"      - name: {name}\n", 1)[1].split("\n      - ", 1)[0]


def _script(name: str) -> str:
    return textwrap.dedent(_step(name).split("        run: |\n", 1)[1])


def _run(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # On Windows, CreateProcess may resolve system32/bash.exe (the WSL launcher)
    # before PATH, which drops the synthetic environment passed to this test.
    bash = shutil.which("bash")
    if os.name == "nt":
        git = shutil.which("git")
        git_bash = Path(git).resolve().parent.parent / "bin" / "bash.exe" if git else None
        bash = str(git_bash) if git_bash is not None and git_bash.is_file() else None
    if bash is None:
        raise RuntimeError("Bash (Git for Windows on Windows) is required for workflow shell acceptance")
    return subprocess.run(
        [bash, "-e", "-o", "pipefail", "-c", script],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.parametrize("code", ["0", "1", "2", "3", "4", "5", "OUTPUT_ERROR", ""])
@pytest.mark.parametrize("exit_code", ["0", "1", ""])
@pytest.mark.parametrize("outcome", ["success", "failure", "skipped"])
def test_final_status_respects_business_result_exit_code_and_step_outcome(tmp_path, code, exit_code, outcome):
    output = tmp_path / "outputs"
    result = _run(
        _script("汇总签到执行结果"),
        {
            "GITHUB_OUTPUT": str(output),
            "CHECKIN_STATUS_CODE": code,
            "CHECKIN_EXIT_CODE": exit_code,
            "CHECKIN_OUTCOME": outcome,
        },
    )
    assert result.returncode == 0, result.stderr
    ok = output.read_text(encoding="utf-8").strip().split("=", 1)[1]
    expected = code in {"1", "2", "5"} and exit_code == "0" and outcome == "success"
    assert (ok == "true") is expected

    # Substitute only fixed synthetic values; no CLI, school request or SMTP call.
    values = {
        "steps.checkin.outputs.status_code": code,
        "steps.checkin.outputs.status_msg": "fixture",
        "matrix.account.name": "fixture",
        "steps.mail_config.outputs.configured": "false",
        "steps.send_mail.outcome": "skipped",
    }
    final = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", lambda match: values[match[1]], _script("最终状态检查"))
    result = _run(final, {"CHECKIN_OK": ok})
    assert (result.returncode == 0) is expected, result.stderr


def test_all_notification_steps_use_the_same_final_result():
    for name in ("检查邮件通知配置", "发送通知邮件", "邮件通知结果"):
        condition = re.search(r"^        if: (.+)$", _step(name), re.MULTILINE)
        assert condition is not None
        assert "steps.execution_result.outputs.ok != 'true'" in condition[1]
        assert "steps.checkin.outputs.status_code" not in condition[1]


@pytest.mark.parametrize("ok", ["false", ""])
def test_missing_or_failed_summary_cannot_become_success(ok):
    final = re.sub(
        r"\$\{\{\s*(.*?)\s*\}\}",
        lambda match: "1" if match[1] == "steps.checkin.outputs.status_code" else "fixture",
        _script("最终状态检查"),
    )
    assert _run(final, {"CHECKIN_OK": ok}).returncode == 1
