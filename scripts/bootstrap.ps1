# One-command setup for the `tnotes` command on Windows (PowerShell).
#
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
#
# Installs uv (if missing) and the `tnotes` command. Then, in a NEW terminal:
#   tnotes auth set-key
#   tnotes extract <pdf> --pages 14 --model claude-sonnet-4-6 --out data\notes
#
# This is all `tnotes` needs to be functional (the API-key path). `mise`/`ant` are
# only for the optional account-login path - see README.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "-> installing uv..."
  powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"   # so this script can use uv now
}

Write-Host "-> installing the tnotes command..."
uv tool install --editable . --reinstall
uv tool update-shell

Write-Host ""
Write-Host "Done. Open a NEW terminal (so PATH refreshes), then:"
Write-Host "    tnotes auth set-key"
Write-Host "    tnotes extract `"<your.pdf>`" --pages 14 --model claude-sonnet-4-6 --out data\notes"
