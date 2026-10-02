# Persistent local preview signing. Never write passwords or private keys into the checkout.
[CmdletBinding()]
param(
    [string]$SigningRoot = (Join-Path $env:LOCALAPPDATA 'SWUCheckin\ReleaseSigning\Android'),
    [switch]$IncludeTests,
    [Uri]$DownloadProxy
)
$ErrorActionPreference = 'Stop'
function Set-SigningAcl([string]$Path, [Security.AccessControl.FileSystemSecurity]$Security, [switch]$Directory) {
    # Set-Acl's provider may request SACL privileges unnecessarily on PowerShell 7.
    # Persist only the edited filesystem security descriptor directly instead.
    if ($PSVersionTable.PSEdition -eq 'Core') {
        if ($Directory) { [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($Path), $Security) }
        else { [IO.FileSystemAclExtensions]::SetAccessControl([IO.FileInfo]::new($Path), $Security) }
    } else {
        if ($Directory) { [IO.Directory]::SetAccessControl($Path, $Security) }
        else { [IO.File]::SetAccessControl($Path, $Security) }
    }
}
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$signingPath = [IO.Path]::GetFullPath($SigningRoot)
if ($signingPath.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or $signingPath -eq $projectRoot) {
    throw 'The persistent signing key must remain outside the repository.'
}
. (Join-Path $PSScriptRoot 'env.ps1') -DownloadProxy $DownloadProxy
Add-Type -AssemblyName System.Security
$keyFile = Join-Path $signingPath 'preview.p12'
$passwordFile = Join-Path $signingPath 'password.dpapi'
$certificateFile = Join-Path $signingPath 'preview.cer'
$aliasName = 'swu-checkin-preview'
if ((Test-Path -LiteralPath $keyFile) -xor (Test-Path -LiteralPath $passwordFile)) {
    throw 'The existing signing key/password pair is incomplete. Refusing to overwrite it.'
}
if (-not (Test-Path -LiteralPath $signingPath)) {
    $null = New-Item -ItemType Directory -Path $signingPath
}
for ($ancestor = $signingPath; $ancestor; $ancestor = [IO.Path]::GetDirectoryName($ancestor)) {
    if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Refusing a redirected signing directory or ancestor.'
    }
}
foreach ($existing in @($keyFile, $passwordFile, $certificateFile)) {
    if ((Test-Path -LiteralPath $existing) -and ((Get-Item -LiteralPath $existing -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Refusing a redirected signing file.'
    }
}
# Restrict this dedicated directory to the current Windows user and SYSTEM.
$owner = [Security.Principal.WindowsIdentity]::GetCurrent().User
$systemSid = New-Object Security.Principal.SecurityIdentifier('S-1-5-18')
$acl = Get-Acl -LiteralPath $signingPath
$acl.SetAccessRuleProtection($true, $false)
foreach ($existingRule in @($acl.Access)) { $acl.RemoveAccessRuleSpecific($existingRule) }
$acl.SetOwner($owner)
foreach ($sid in @($owner, $systemSid)) {
    $rule = New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
}
Set-SigningAcl $signingPath $acl -Directory
foreach ($existing in @($keyFile, $passwordFile)) {
    if (Test-Path -LiteralPath $existing) {
        $fileAcl = Get-Acl -LiteralPath $existing
        $fileAcl.SetAccessRuleProtection($true, $false)
        foreach ($existingRule in @($fileAcl.Access)) { $fileAcl.RemoveAccessRuleSpecific($existingRule) }
        $fileAcl.SetOwner($owner)
        foreach ($sid in @($owner, $systemSid)) {
            $fileAcl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'Allow')))
        }
        Set-SigningAcl $existing $fileAcl
    }
}
$savedSigningEnvironment = @{}
foreach ($name in @('SWU_ANDROID_KEYSTORE_PASSWORD', 'SWU_ANDROID_KEYSTORE', 'SWU_ANDROID_KEY_ALIAS')) {
    $savedSigningEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$passwordBytes = $null
$secret = $null
try {
    if (-not (Test-Path -LiteralPath $keyFile)) {
        $random = New-Object byte[] 48
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($random) } finally { $rng.Dispose() }
        $secret = [Convert]::ToBase64String($random)
        [Array]::Clear($random, 0, $random.Length)
        $passwordBytes = [Text.Encoding]::UTF8.GetBytes($secret)
        $protected = [Security.Cryptography.ProtectedData]::Protect($passwordBytes, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
        [IO.File]::WriteAllBytes($passwordFile, $protected)
        $env:SWU_ANDROID_KEYSTORE_PASSWORD = $secret
        & (Join-Path $env:JAVA_HOME 'bin/keytool.exe') -genkeypair -keystore $keyFile -storetype PKCS12 `
            -storepass:env SWU_ANDROID_KEYSTORE_PASSWORD -keypass:env SWU_ANDROID_KEYSTORE_PASSWORD `
            -alias $aliasName -keyalg RSA -keysize 4096 -sigalg SHA256withRSA -validity 36500 `
            -dname 'CN=SWUCheckin Preview,OU=Community,O=Maximora-byte,C=CN' -noprompt
        if ($LASTEXITCODE -ne 0) { throw 'Persistent preview key generation failed.' }
    } else {
        $passwordBytes = [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($passwordFile), $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
        $secret = [Text.Encoding]::UTF8.GetString($passwordBytes)
        $env:SWU_ANDROID_KEYSTORE_PASSWORD = $secret
    }
    $env:SWU_ANDROID_KEYSTORE = $keyFile
    $env:SWU_ANDROID_KEY_ALIAS = $aliasName
    & (Join-Path $env:JAVA_HOME 'bin/keytool.exe') -exportcert -keystore $keyFile -storetype PKCS12 `
        -storepass:env SWU_ANDROID_KEYSTORE_PASSWORD -alias $aliasName -file $certificateFile
    if ($LASTEXITCODE -ne 0) { throw 'Existing persistent signing key could not be verified.' }
    & python (Join-Path $PSScriptRoot 'write_build_metadata.py') --output `
        (Join-Path $projectRoot 'android/app/build/generated/release-provenance/BUILD-INFO.json')
    if ($LASTEXITCODE -ne 0) { throw 'Clean signed-preview source metadata generation failed.' }
    $tasks = @('--no-daemon', '-p', (Join-Path $projectRoot 'android'), ':app:assembleRelease', ':app:lintRelease')
    if ($IncludeTests) { $tasks += @('-PswuTestBuildType=release', ':app:assembleReleaseAndroidTest') }
    & (Join-Path $projectRoot 'android/gradlew.bat') @tasks
    if ($LASTEXITCODE -ne 0) { throw 'Signed Android preview build failed.' }
    $dependencyReport = Join-Path $projectRoot 'android/app/build/release-runtime-dependencies.txt'
    & (Join-Path $projectRoot 'android/gradlew.bat') --no-daemon -p (Join-Path $projectRoot 'android') `
        :app:dependencies --configuration releaseRuntimeClasspath | Out-File -LiteralPath $dependencyReport -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw 'Android production dependency inventory failed.' }
    & python (Join-Path $projectRoot 'packaging/android/verify_maven_inventory.py') $dependencyReport
    if ($LASTEXITCODE -ne 0) { throw 'Android production Maven licensing verification failed.' }
    $apk = Join-Path $projectRoot 'android/app/build/outputs/apk/release/app-release.apk'
    & (Join-Path $env:JAVA_HOME 'bin/java.exe') -jar (Join-Path $env:ANDROID_HOME 'build-tools/35.0.0/lib/apksigner.jar') verify --verbose --print-certs $apk
    if ($LASTEXITCODE -ne 0) { throw 'Signed APK verification failed.' }
    & (Join-Path $env:ANDROID_HOME 'build-tools/35.0.0/zipalign.exe') -c -P 16 4 $apk
    if ($LASTEXITCODE -ne 0) { throw 'Signed APK 16 KB ZIP alignment failed.' }
    & python (Join-Path $PSScriptRoot 'verify_signed_apk.py') --apk $apk --sdk $env:ANDROID_HOME `
        --java (Join-Path $env:JAVA_HOME 'bin/java.exe') --certificate $certificateFile `
        --output (Join-Path $projectRoot 'android/app/build/outputs/release-verification.json')
    if ($LASTEXITCODE -ne 0) { throw 'Final signed preview source, licensing or signature gate failed.' }
    Write-Output 'Persistent signed preview built and verified. No release has been published.'
} finally {
    foreach ($name in $savedSigningEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedSigningEnvironment[$name], 'Process')
    }
    if ($passwordBytes) { [Array]::Clear($passwordBytes, 0, $passwordBytes.Length) }
    $secret = $null
}
