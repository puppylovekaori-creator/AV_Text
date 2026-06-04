# AV Text 専用入力エディタ

`title.txt` / `actress.txt` / `no.txt` をサクラではなく専用 GUI で編集し、既存の変換 BAT をそのまま呼び出すための入力パッドです。

## 置き場所

- 本体: `C:\dev\avtext_runtime\avtext_input_pad\`
- ランチャー: `C:\dev\avtext_runtime\avtext_input_pad\Open-AVTextInputPad.cmd`
- 実運用ランタイム既定値: `C:\Users\ジョージ・ブッシュ\AppData\Roaming\sakura\avtext`
- 設定保存: `%LOCALAPPDATA%\AVTextInputPad\settings.json`
- ログ: `%LOCALAPPDATA%\AVTextInputPad\logs\avtext_input_pad.log`

## 何を触るか

- 入力: `title.txt` / `actress.txt` / `no.txt`
- 結果表示: `conv_converted.txt`
- 変換実行:
  - `run_av_text_convert.bat`
  - `run_av_title_convert.bat`
  - `run_no_title_to_conv.bat`

既存 BAT / daemon / one-shot fallback は再利用し、GUI 側では変換ロジックを再実装していません。

## 使い方

1. `Open-AVTextInputPad.cmd` か `avtext_input_pad.pyw` をダブルクリックします。
2. 必要なら上部の `ランタイムフォルダ` を切り替えます。
3. `女優` / `タイトル` / `変換結果` はタブで切り替え、`品番` は上部で編集します。
4. 編集後は debounce 付き自動保存で `title.txt` / `actress.txt` / `no.txt` に反映されます。
5. `変換` / `タイトルのみ変換` / `品番連番変換` のいずれかを押します。
6. `変換` と `タイトルのみ変換` は成功後に変換結果を自動でクリップボードへ送ります。`品番連番変換` は成功後に大きい番号の行から先に clipboard へ流し、最後に `01` が残る向きで Clibor の `CLIPIGNORE` をまたぐ間隔で履歴へ残す形にします。
7. `出力ファイルを開く` で `conv_converted.txt` を直接開けます。
8. 既定サイズは添付で示されたサクラエディタより大きくしない前提の小さめ固定です。以前の壊れた保存サイズ `1x1` や大きすぎる保存サイズは次回起動時に補正します。

## 監視と性能

- 監視対象は `title.txt` / `actress.txt` / `no.txt` / `conv_converted.txt` の 4 ファイルだけです。
- 常時全件走査はせず、低頻度の `mtime_ns + size` 署名監視だけを行います。
- ファイル内容の再読込は署名変化があったファイルだけに限定しています。
- 入力保存は debounce、外部更新反映も debounce して UI 再描画をまとめています。
- キャッシュ寿命は GUI プロセス存続中だけです。
- 無効化条件は `mtime_ns + size` 変化、ランタイムフォルダ変更、アプリ再起動です。
- 自分で保存した内容は署名と正規化テキストで握り、自己更新ループを避けています。

## 外部更新

- Firefox / Native Host が `title.txt` などを書き換えた場合、dirty でなければ静かに GUI に反映します。
- ローカル編集中に外部更新がぶつかった場合だけ、非モーダルの通知欄に保留を出します。
- 競合時は編集中のローカル入力を優先し、外部更新は通知のみで上書きしません。
- モーダルな再読込ダイアログは出しません。

## トラブル時

- `状態` が `エラー` のときは通知欄と `%LOCALAPPDATA%\AVTextInputPad\logs\avtext_input_pad.log` を見てください。
- 変換自体の失敗は既存ログも併せて確認します。
  - `av_text_convert.log`
  - `av_title_convert.log`
  - `no_title_to_conv.log`
- `conv_converted.txt` が更新されない場合は、既存の daemon / one-shot fallback 系のログを先に確認してください。
