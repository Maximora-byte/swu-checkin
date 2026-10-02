"""Guard the acceptance harness; these tests do not launch the application.

The full restricted-token, extracted-ZIP GUI acceptance runs only in the public
GitHub-hosted windows-2022 desktop workflow, before installer verification.
"""

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/windows/verify-portable.ps1"
LAUNCHER = Path(__file__).with_name("portable_smoke_launcher.cs")


def test_portable_smoke_checks_ci_before_reading_or_mutating_machine():
    source = SCRIPT.read_text(encoding="utf-8")
    guard = source.index("throw 'Portable smoke requires")
    assert "$env:RUNNER_ENVIRONMENT -ne 'github-hosted'" in source[:guard]
    assert "$env:ImageOS -ne 'win22'" in source[:guard]
    assert "$env:GITHUB_ACTIONS -ne 'true'" in source[:guard]
    assert guard < source.index("Resolve-Path")
    assert guard < source.index("Get-ScheduledTask")
    assert guard < source.index("New-Item")
    assert guard < source.index("Add-Type")


def test_portable_smoke_verifies_archive_payload_and_runtime_isolation():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "DistributionHashes.ContainsKey($ArchiveName)" in source
    assert "Get-FileHash -LiteralPath $Archive -Algorithm SHA256" in source
    assert "Assert-PayloadChecksums $AppDir" in source
    assert "Assert-UnchangedPayload $Before $AppDir" in source
    assert "Portable 中文路径 with spaces" in source
    assert "$Environment['PATH'] = \"$env:SystemRoot\\System32;$env:SystemRoot\"" in source
    assert "$Environment['LOCALAPPDATA'] = $LocalData" in source
    assert "PYTHON|UV_|VIRTUAL_ENV|CONDA|SWUDK_|_PYI_|PYINSTALLER" in source
    assert "foreach ($Launch in 1..2)" in source
    assert "Start-Sleep -Seconds 32" in source
    assert "$Gui.CloseMainWindow()" in source
    assert "$Launcher.ActiveProcesses -ne 0" in source
    assert "Wait-OwnedProcess $SelfTest 180" in source
    for prohibited in ("--scheduled", "Register-ScheduledTask", "Unregister-ScheduledTask", "Set-Acl", "Stop-Process"):
        assert prohibited not in source


def test_restricted_launcher_verifies_child_before_running_and_has_no_elevated_fallback():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "LUA_TOKEN | DISABLE_MAX_PRIVILEGE" in source
    assert "BuiltinAdministratorsSid" in source
    assert "SE_GROUP_USE_FOR_DENY_ONLY" in source
    assert "AssertRestricted(actualToken)" in source
    assert source.index("AssertRestricted(actualToken)") < source.index("if (ResumeThread(info.thread)")
    assert source.index("AssignProcessToJobObject(job, info.process)") < source.index("if (ResumeThread(info.thread)")
    assert "CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT" in source
    assert 'argument != "" && argument != "--self-test"' in source
    assert "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in source
    assert "QueryInformationJobObject" in source
    for prohibited in (
        "Process.Start(",
        "LogonUser",
        "CreateProcessWithLogon",
        "SetNamedSecurityInfo",
    ):
        assert prohibited not in source


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell syntax/compiler checks require pwsh")
def test_powershell_syntax_and_restricted_launcher_compilation():
    # Parsing and compiling do not instantiate the launcher or call Win32 APIs.
    # This can therefore run outside the disposable acceptance VM as well.
    command = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($env:SWU_TEST_SCRIPT, [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count -ne 0) { $errors | Write-Error; exit 1 }
Add-Type -Path $env:SWU_TEST_LAUNCHER
if ($null -eq ('PortableSmokeLauncher' -as [type])) { throw 'Launcher type did not compile.' }
"""
    result = subprocess.run(
        [shutil.which("pwsh"), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
        env={**os.environ, "SWU_TEST_SCRIPT": str(SCRIPT), "SWU_TEST_LAUNCHER": str(LAUNCHER)},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def load_diagnostic():
    spec = importlib.util.spec_from_file_location("portable_diagnostic", LAUNCHER.with_name("portable_diagnostic.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_diagnostic_refuses_non_ci_before_writing(monkeypatch, tmp_path):
    helper = load_diagnostic()
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    report = tmp_path / "report.json"
    with pytest.raises(RuntimeError, match="disposable"):
        helper.run(report)
    assert not report.exists()


def test_source_diagnostic_emits_only_stage_codes_and_continues(monkeypatch, tmp_path):
    helper = load_diagnostic()
    monkeypatch.setattr(helper.sys, "platform", "win32")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    monkeypatch.setenv("ImageOS", "win22")
    for name in ("tls", "tcl", "tk_window", "timezone", "ocr", "dpapi", "absent_task", "temporary_lock"):
        monkeypatch.setattr(helper, name, lambda: None)

    def fail():
        raise PermissionError("never-print-this-sensitive-exception")

    monkeypatch.setattr(helper, "ocr", fail)
    report = tmp_path / "report.json"
    assert helper.run(report) == 1
    output = report.read_text()
    assert "never-print" not in output
    records = json.loads(output)
    assert len(records) == 8
    assert records[4] == {"stage": "ocr", "result": "FAIL", "type": "PermissionError"}
    assert records[-1] == {"stage": "temporary-lock", "result": "PASS"}


def test_diagnostic_does_not_replace_frozen_acceptance_or_hardcode_desktop():
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.index("$FrozenFailure = $_") < source.index("$Launcher.StartDiagnostic(")
    assert "throw $FrozenFailure" in source
    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert "ProbeWritableDirectory" in launcher
    assert "RevertToSelf()" in launcher
    assert 'desktop = @"winsta0' not in launcher
    assert "var startup = new StartupInfoEx();" in launcher
    assert "startup.startup.cb = Marshal.SizeOf<StartupInfoEx>();" in launcher


def test_command_diagnostics_do_not_emit_arbitrary_output():
    helper = load_diagnostic()
    result = helper.classify_command(
        SimpleNamespace(
            returncode=3,
            stdout="private output\nIDENTITY_OK\nCOM_FAIL:-2147024891\nprivate account",
            stderr="private credential",
        )
    )
    assert result == {
        "returncode": 3,
        "stdout_category": "OTHER",
        "stderr_present": True,
        "progress_xml": False,
        "phases": ["IDENTITY_OK", "COM_FAIL:-2147024891"],
    }
    assert "private" not in json.dumps(result)


def test_partial_diagnostics_are_emitted_before_original_failure():
    source = SCRIPT.read_text(encoding="utf-8")
    emission = source.index('Write-Host "Restricted diagnostic: $_"')
    assert source.index("finally {", source.index("$FrozenFailure = $_")) < emission
    assert emission < source.index("throw $FrozenFailure")


def test_restricted_launcher_inherits_only_explicit_nul_stdio():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'CreateFile("NUL", 0xc0000000, 3, ref security, 3, 0, IntPtr.Zero)' in source
    assert "PROC_THREAD_ATTRIBUTE_HANDLE_LIST" in source
    assert "Marshal.WriteIntPtr(handleList, nullStream)" in source
    assert "startup.startup.stdInput = startup.startup.stdOutput = startup.startup.stdError = nullStream" in source
    assert "EXTENDED_STARTUPINFO_PRESENT" in source
    assert source.index("UpdateProcThreadAttribute(attributes, 0") < source.index("Require(CreateProcessAsUser(token")
    assert "DeleteProcThreadAttributeList(attributes)" in source
    assert "GetStdHandle" not in source


def test_default_dacl_change_targets_only_new_restricted_token():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert source.count("Require(SetTokenInformation(") == 1
    assert "SetTokenInformation(token, 6, ref info, Marshal.SizeOf<TokenDefaultDacl>())" in source
    assert "SetTokenInformation(original" not in source
    assert "new RawAcl(2, 2)" in source
    assert "AceQualifier.AccessAllowed, 0x10000000, user, false, null" in source
    assert "AceQualifier.AccessAllowed, 0x10000000, system, false, null" in source
    normalization = source.index("NormalizeRestrictedDefaultDacl();")
    assert source.index("CreateRestrictedToken(original") < normalization
    assert source.index("AssertRestricted(token);", normalization) > normalization
    assert "expected[i] != observed[i]" in source
    assert "DefaultDaclBefore = DescribeTokenDefaultDacl();" in source
    for forbidden in ("SetNamedSecurityInfo", "SetFileSecurity", "SetSecurityInfo", "Set-Acl", "AdjustTokenPrivileges"):
        assert forbidden not in source
