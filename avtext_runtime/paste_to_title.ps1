# paste_to_title.ps1
# クリップボードの先頭1行を title.txt の1行目に上書きする

$base      = Join-Path $env:APPDATA "sakura\avtext"
$titlePath = Join-Path $base "title.txt"

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

if ([string]::IsNullOrWhiteSpace($text)) {
    exit 0
}

# 改行正規化（LFベースにしてから分割）
$text = $text -replace "`r`n", "`n"
$text = $text -replace "`r", "`n"

# 先頭行だけ使う
$lines = $text -split "`n", 2
$first = $lines[0].Trim()

# 既存 title.txt を読んで 1行目だけ差し替え（他の行があれば維持）
if (Test-Path $titlePath) {
    $existing = Get-Content $titlePath -Raw
    $existing = $existing -replace "`r`n", "`n"
    $existing = $existing -replace "`r", "`n"
    $existLines = $existing -split "`n"
    if ($existLines.Length -eq 0) {
        $newLines = @($first)
    } else {
        $existLines[0] = $first
        $newLines = $existLines
    }
} else {
    $newLines = @($first)
}

# CRLF で書き出し（UTF-8 BOM。Python 側は UTF-8→cp932の順で読むのでOK）
$contentOut = ($newLines -join "`r`n")
[System.IO.File]::WriteAllText(
    $titlePath,
    $contentOut,
    [System.Text.Encoding]::UTF8
)
