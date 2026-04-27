$src = 'C:\dev\firefox-autoconfig-staging'
$dstRoot = 'C:\Program Files\Mozilla Firefox'
Copy-Item -LiteralPath (Join-Path $src 'mozilla.cfg') -Destination (Join-Path $dstRoot 'mozilla.cfg') -Force
Copy-Item -LiteralPath (Join-Path $src 'local-settings.js') -Destination (Join-Path $dstRoot 'defaults\pref\local-settings.js') -Force
Write-Host 'done'
