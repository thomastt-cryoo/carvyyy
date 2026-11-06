param([string]$ManifestPin = '')
$ErrorActionPreference = 'Stop'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$installation = & $vswhere -latest -products '*' -property installationPath
$devShell = Join-Path $installation 'Common7/Tools/Microsoft.VisualStudio.DevShell.dll'
if (Test-Path $devShell) {
    Import-Module $devShell
    Enter-VsDevShell -VsInstallPath $installation -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64' | Out-Null
}
$compiler = Get-ChildItem (Join-Path $installation 'VC/Tools/MSVC') -Directory | Sort-Object Name -Descending | Select-Object -First 1
$env:PATH = (Join-Path $compiler.FullName 'bin/Hostx64/x64') + ';' + $env:PATH
$compilerLib = Join-Path $compiler.FullName 'lib/x64'
$env:LIB = $compilerLib + ';' + $env:LIB
$sdk = Join-Path $PSScriptRoot '../../data/m1/windows-sdk/x64/c'
if (Test-Path $sdk) { $env:LIB += ';' + (Join-Path $sdk 'um/x64') + ';' + (Join-Path $sdk 'ucrt/x64') }
$sdkIncludes = Join-Path $PSScriptRoot '../../data/m1/windows-sdk/sdk/c/Include/10.0.28000.0'
$env:INCLUDE = (Join-Path $compiler.FullName 'include') + ';' + $env:INCLUDE
if (Test-Path $sdkIncludes) { foreach ($part in @('ucrt', 'um', 'shared')) { $env:INCLUDE += ';' + (Join-Path $sdkIncludes $part) } }
if ($ManifestPin) { $env:P2R_MANIFEST_SHA256 = $ManifestPin } else { Remove-Item Env:P2R_MANIFEST_SHA256 -ErrorAction SilentlyContinue }
cargo build --release --locked --manifest-path (Join-Path $PSScriptRoot '../../bootstrapper/Cargo.toml')
if ($LASTEXITCODE) { exit $LASTEXITCODE }
cargo test --locked --manifest-path (Join-Path $PSScriptRoot '../../bootstrapper/Cargo.toml')
exit $LASTEXITCODE
