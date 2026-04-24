# paste_to_actress.ps1
# クリップボードの内容全体で actress.txt を丸ごと上書きする

$base        = Join-Path $env:APPDATA "sakura\avtext"
$actressPath = Join-Path $base "actress.txt"

# フォルダがなければ作る
if (-not (Test-Path $base)) {
    New-Item -ItemType Directory -Path $base -Force | Out-Null
}

# クリップボード取得（テキスト）
try {
    $text = Get-Clipboard -Format Text -Raw
} catch {
    $text = $null
}

if ($null -eq $text) {
    $text = ""
}

# 改行を CRLF に正規化して書き出し
$text = $text -replace "`r`n", "`n"
$text = $text -replace "`r", "`n"
$contentOut = $text -replace "`n", "`r`n"

[System.IO.File]::WriteAllText(
    $actressPath,
    $contentOut,
    [System.Text.Encoding]::UTF8
)
