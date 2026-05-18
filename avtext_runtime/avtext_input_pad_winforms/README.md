# AV Text 専用入力エディタ WinForms 版

## 役割
- `title.txt`
- `actress.txt`
- `no.txt`

を専用 UI で編集し、既存の変換 BAT を呼び出します。

## 起動
- 通常起動:
  - [C:\dev\avtext_runtime\avtext_input_pad\Open-AVTextInputPad.cmd](C:/dev/avtext_runtime/avtext_input_pad/Open-AVTextInputPad.cmd)
- Firefox 右クリック:
  - `サクラを前面に`
  - 実際にはこの WinForms 版を前面化します

## ビルド
- [C:\dev\avtext_runtime\avtext_input_pad_winforms\Build-AVTextInputPad.cmd](C:/dev/avtext_runtime/avtext_input_pad_winforms/Build-AVTextInputPad.cmd)

## 実体
- source:
  - [C:\dev\avtext_runtime\avtext_input_pad_winforms\src\AVTextInputPad](C:/dev/avtext_runtime/avtext_input_pad_winforms/src/AVTextInputPad)
- release exe:
  - `src\AVTextInputPad\bin\Release\net9.0-windows\AVTextInputPad.exe`
- publish exe:
  - `publish\AVTextInputPad.exe`

## 既存変換との関係
- `run_av_text_convert.bat`
- `run_av_title_convert.bat`
- `run_no_title_to_conv.bat`

をそのまま再利用します。変換ロジックは GUI 側で再実装していません。
