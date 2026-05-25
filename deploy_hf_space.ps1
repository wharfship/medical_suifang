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

$repoRoot = [string](Get-GitOutput -Args @("rev-parse", "--show-toplevel") | Select-Object -First 1)
$repoRoot = $repoRoot.Trim()
$remoteUrl = [string](Get-GitOutput -Args @("remote", "get-url", $RemoteName) -WorkingDirectory $repoRoot | Select-Object -First 1)
$remoteUrl = $remoteUrl.Trim()
$userName = [string](Get-GitOutput -Args @("config", "user.name") -WorkingDirectory $repoRoot | Select-Object -First 1)
$userName = $userName.Trim()
$userEmail = [string](Get-GitOutput -Args @("config", "user.email") -WorkingDirectory $repoRoot | Select-Object -First 1)
$userEmail = $userEmail.Trim()

$publishDir = Join-Path $env:TEMP "hf-space-publish"
if (Test-Path $publishDir) {
    Remove-Item -LiteralPath $publishDir -Recurse -Force
}
New-Item -ItemType Directory -Path $publishDir | Out-Null

$checkoutOutput = git -C $repoRoot --work-tree="$publishDir" checkout-index -a -f
if ($LASTEXITCODE -ne 0) {
    throw "git checkout-index failed."
}

$uploadedReportsPath = Join-Path $publishDir "uploaded_reports"
if (Test-Path $uploadedReportsPath) {
    Remove-Item -LiteralPath $uploadedReportsPath -Recurse -Force
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
