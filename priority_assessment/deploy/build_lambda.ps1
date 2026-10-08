[CmdletBinding()]
param(
    [string]$PythonLauncher = "py"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$DeployDir = $PSScriptRoot
$PackageRoot = Split-Path -Parent $DeployDir
$StagingDir = Join-Path $DeployDir ".staging"
$DistDir = Join-Path $PackageRoot "dist"
$ZipPath = Join-Path $DistDir "priority_assessment_lambda.zip"
$RequirementsPath = Join-Path $PackageRoot "requirements-lambda.txt"

if (Test-Path -LiteralPath $StagingDir) {
    Remove-Item -LiteralPath $StagingDir -Recurse -Force
}
New-Item -ItemType Directory -Path $StagingDir | Out-Null
New-Item -ItemType Directory -Path $DistDir -Force | Out-Null

try {
    # The pip target options below select CPython 3.12 Linux wheels. The local
    # interpreter only runs pip; it is not copied into the deployment package.
    & $PythonLauncher -m pip install `
        --disable-pip-version-check `
        --no-compile `
        --target $StagingDir `
        --platform manylinux2014_x86_64 `
        --implementation cp `
        --python-version 3.12 `
        --only-binary=:all: `
        -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "pip dependency installation failed with exit code $LASTEXITCODE"
    }
}
catch {
    throw "A local Python 3.12 launcher and compatible Linux wheels are required. $($_.Exception.Message)"
}

foreach ($directory in @("src", "prompts", "schemas")) {
    Copy-Item -LiteralPath (Join-Path $PackageRoot $directory) `
        -Destination (Join-Path $StagingDir $directory) -Recurse -Force
}

Get-ChildItem -LiteralPath $StagingDir -Directory -Recurse -Force |
    Where-Object { $_.Name -in @("__pycache__", "tests") } |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $StagingDir -File -Recurse -Force |
    Where-Object { $_.Extension -eq ".pyc" } |
    Remove-Item -Force

$BinDir = Join-Path $StagingDir "bin"
if (Test-Path -LiteralPath $BinDir) {
    Remove-Item -LiteralPath $BinDir -Recurse -Force
}

foreach ($runtimeProvidedPackage in @("boto3", "botocore")) {
    if (Test-Path -LiteralPath (Join-Path $StagingDir $runtimeProvidedPackage)) {
        throw "The Lambda runtime-provided package $runtimeProvidedPackage must not be bundled."
    }
}

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path (Join-Path $StagingDir "*") -DestinationPath $ZipPath -Force

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
try {
    $entries = $archive.Entries.FullName
    foreach ($requiredEntry in @(
        "src/lambda_handler.py",
        "src/run_priority_assessment.py",
        "prompts/priority_assessment_v0.3_article.md",
        "schemas/priority_assessment_article_schema_v0.1.json"
    )) {
        if ($entries -notcontains $requiredEntry) {
            throw "Required ZIP entry is missing: $requiredEntry"
        }
    }

    foreach ($forbiddenPattern in @(
        "(^|/)tests/",
        "(^|/)data/",
        "(^|/)backup/",
        "(^|/)\.env$",
        "(^|/)AGENTS\.md$",
        "(^|/)bin/",
        "\.patch$",
        "__pycache__/",
        "\.pyc$"
    )) {
        if ($entries | Where-Object { $_ -match $forbiddenPattern }) {
            throw "Forbidden ZIP content matched: $forbiddenPattern"
        }
    }

    if (-not ($entries | Where-Object { $_ -match "^jsonschema/" })) {
        throw "jsonschema was not packaged."
    }

    $topLevelEntries = $entries |
        Where-Object { $_ } |
        ForEach-Object { ($_ -split "/")[0] } |
        Sort-Object -Unique
    Write-Host "ZIP created: $ZipPath"
    Write-Host ("Compressed size: {0:N2} MB" -f ((Get-Item -LiteralPath $ZipPath).Length / 1MB))
    Write-Host "Top-level entries:"
    $topLevelEntries | ForEach-Object { Write-Host "  $_" }
}
finally {
    $archive.Dispose()
}
