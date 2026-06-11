# AV_Text ローカル運用メモ

## 配置
- ソース正本: `C:\dev\AV_Text`
- live copy: `C:\dev\avtext_host` / `C:\dev\avtext-ffext`
- アドオン配布物: `C:\dev\AV_Text\avtext-ffext-signed`

## 今回の方針
- Git の正本更新は `C:\dev\AV_Text` で行う
- 実運用に使う live copy へは、ソース更新後に同内容を反映する
- 右クリックメニューの追記系は全置換系と分け、既存動作は残す
