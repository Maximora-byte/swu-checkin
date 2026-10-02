# Exercise the real ACL helper without creating, reading or exporting signing keys.
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $repoRoot 'scripts/android/build-signed-preview.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors) { throw 'Signing script did not parse.' }
$helper = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Set-SigningAcl' }, $true)
if (-not $helper) { throw 'Signing ACL helper was not found.' }
# This is the checked-in helper definition, without executing the build script.
Invoke-Expression $helper.Extent.Text
$directory = Join-Path ([IO.Path]::GetTempPath()) ('SWU-SigningAclSmoke-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $directory
$file = Join-Path $directory 'synthetic-private-fixture.txt'
[IO.File]::WriteAllText($file, 'synthetic-non-secret')
$owner = [Security.Principal.WindowsIdentity]::GetCurrent().User
$systemSid = New-Object Security.Principal.SecurityIdentifier('S-1-5-18')
for ($pass = 0; $pass -lt 2; $pass++) {
    $acl = Get-Acl -LiteralPath $directory
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) { $acl.RemoveAccessRuleSpecific($rule) }
    $acl.SetOwner($owner)
    foreach ($sid in @($owner, $systemSid)) {
        $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
    }
    Set-SigningAcl $directory $acl -Directory
    $acl = Get-Acl -LiteralPath $file
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) { $acl.RemoveAccessRuleSpecific($rule) }
    $acl.SetOwner($owner)
    foreach ($sid in @($owner, $systemSid)) {
        $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'Allow')))
    }
    Set-SigningAcl $file $acl
    foreach ($path in @($directory, $file)) {
        $actual = Get-Acl -LiteralPath $path
        if (-not $actual.AreAccessRulesProtected -or $actual.Access.Count -ne 2) { throw 'Expected a protected two-principal ACL.' }
        foreach ($rule in $actual.Access) {
            $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
            if ($sid -notin @($owner.Value, $systemSid.Value) -or $rule.IsInherited -or $rule.AccessControlType -ne 'Allow') {
                throw 'Unexpected signing-fixture access rule.'
            }
        }
    }
}
if ([IO.File]::ReadAllText($file) -ne 'synthetic-non-secret') { throw 'ACL update altered fixture contents.' }
Write-Output "Signing ACL smoke passed on PowerShell $($PSVersionTable.PSVersion). No private key was accessed."
