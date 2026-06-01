param(
    [string]$RemoteName = "hf",
    [string]$BranchName = "main"
)

$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $false
}

function Get-GitOutput {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args,
        [string]$WorkingDirectory = (Get-Location).Path
    )

    $output = & git -C $WorkingDirectory @Args
    if ($LASTEXITCODE -ne 0) {
        throw "git command failed: git -C $WorkingDirectory $($Args -join ' ')"
    }
    return $output
}

function Remove-PathIfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

$repoRoot = [string](Get-GitOutput -Args @("rev-parse", "--show-toplevel") | Select-Object -First 1)
$repoRoot = $repoRoot.Trim()
$remoteUrl = [string](Get-GitOutput -Args @("remote", "get-url", $RemoteName) -WorkingDirectory $repoRoot | Select-Object -First 1)
$remoteUrl = $remoteUrl.Trim()
$userName = [string](Get-GitOutput -Args @("config", "user.name") -WorkingDirectory $repoRoot | Select-Object -First 1)
$userName = $userName.Trim()
$userEmail = [string](Get-GitOutput -Args @("config", "user.email") -WorkingDirectory $repoRoot | Select-Object -First 1)
$userEmail = $userEmail.Trim()

$publishDir = Join-Path $env:TEMP "hf-space-publish"
Remove-PathIfExists -Path $publishDir
New-Item -ItemType Directory -Path $publishDir | Out-Null

$robocopyArgs = @(
    $repoRoot,
    $publishDir,
    "/MIR",
    "/XD",
    (Join-Path $repoRoot ".git")
)

& robocopy @robocopyArgs | Out-Null
if ($LASTEXITCODE -gt 7) {
    throw "Workspace copy to publish directory failed."
}

$excludedDirectories = @(
    ".idea",
    ".vscode",
    "__pycache__",
    ".venv",
    ".gradio",
    "image",
    "image_extract_preview",
    "outputs",
    "uploaded_reports"
)
foreach ($directoryName in $excludedDirectories) {
    $matchingDirectories = Get-ChildItem -Path $publishDir -Directory -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq $directoryName }
    foreach ($directory in $matchingDirectories) {
        Remove-PathIfExists -Path $directory.FullName
    }

    $topLevelDirectory = Join-Path $publishDir $directoryName
    Remove-PathIfExists -Path $topLevelDirectory
}

$excludedFiles = @(
    "medical_data.xlsx",
    "verify_input.jpg",
    "~$*",
    "*.log",
    "err.txt",
    "error.txt",
    "error2.txt",
    "run_err.txt",
    "_xls_output.txt"
)
foreach ($pattern in $excludedFiles) {
    $matchingFiles = Get-ChildItem -Path $publishDir -Recurse -File -Force -Filter $pattern -ErrorAction SilentlyContinue
    foreach ($file in $matchingFiles) {
        Remove-Item -LiteralPath $file.FullName -Force
    }
}

$binaryDocFiles = Get-ChildItem -Path $publishDir -Recurse -File -Include *.doc, *.docx, *.pdf
foreach ($file in $binaryDocFiles) {
    Remove-Item -LiteralPath $file.FullName -Force
}

Get-GitOutput -Args @("init", "-b", $BranchName) -WorkingDirectory $publishDir | Out-Null
Get-GitOutput -Args @("config", "user.name", $userName) -WorkingDirectory $publishDir | Out-Null
Get-GitOutput -Args @("config", "user.email", $userEmail) -WorkingDirectory $publishDir | Out-Null
Get-GitOutput -Args @("config", "core.autocrlf", "false") -WorkingDirectory $publishDir | Out-Null
Get-GitOutput -Args @("add", ".") -WorkingDirectory $publishDir | Out-Null
Get-GitOutput -Args @("commit", "-m", "Deploy current Gradio frontend snapshot") -WorkingDirectory $publishDir | Out-Null

Get-GitOutput -Args @("remote", "add", $RemoteName, $remoteUrl) -WorkingDirectory $publishDir | Out-Null

$remoteMain = ""
try {
    $remoteLine = Get-GitOutput -Args @("ls-remote", "--heads", $RemoteName, $BranchName) -WorkingDirectory $publishDir
    if ($remoteLine) {
        $remoteFirstLine = [string]($remoteLine | Select-Object -First 1)
        $remoteMain = ($remoteFirstLine -split "\s+")[0]
    }
} catch {
    Write-Host "Unable to read remote branch, will try a normal push first."
}

if ($remoteMain) {
    git -C $publishDir push --force-with-lease="$BranchName`:$remoteMain" $RemoteName "HEAD:$BranchName"
} else {
    git -C $publishDir push $RemoteName "HEAD:$BranchName"
}

if ($LASTEXITCODE -ne 0) {
    throw "Push to Hugging Face Space failed."
}

Write-Host "Hugging Face Space deploy finished."
