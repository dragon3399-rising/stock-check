# inventory-stock-check

eBay在庫管理スプレッドシートの「在庫状況=在庫有り」行の仕入先URLを実際にチェックし、
売り切れ・リンク切れ・判定不能があればLINEに通知する。

- スケジュール: 毎日 JST 3:00 / 11:00 / 19:00（GitHub Actions。メルカリは55件/回のローテーションで全件を約8時間周期でカバー）
- 手動実行: Actions タブ → inventory-stock-check → Run workflow（dry_run=1 でLINE送信なしテスト）

## 判定方法

| サイト | 方法 |
|---|---|
| メルカリ (jp.mercari.com/item) | 公式API（DPoP署名）。on_sale / sold_out / trading / 404 |
| PayPayフリマ | ページ内JSON `"status":"OPEN"` / `"SOLD_OUT"` |
| Amazon | `id="availability"` 欄＋カートボタン。bot対策ページはUNKNOWN |
| Disneyストア | availability div の schema.org/InStock・OutOfStock |
| ジブリ美術館 / 楽天 ほか | 商品本体の JSON-LD availability |
| Yahoo!ショッピング / USJ | `"isAvailable":true/false` フラグ |
| ポケモンセンター | カートボタンの disabled 有無 |
| ヤフオク | 開催中 / 終了表示 |
| ラクマ (fril.jp) | 「すぐに購入可」/「売り切れました」 |
| 楽天 | `'soldout':[0]/[1]` フラグ |
| どんぐり共和国 | 「在庫数：あと N点」の数量 |
| その他 | JSON-LD → 汎用マーカー（確証なければUNKNOWN） |
| メルカリShops | 自動判定未対応（UNKNOWNとして通知） |

## 役割分担（ハイブリッド構成）

GitHubのIP（Azure）はAmazon・楽天・駿河屋・任天堂ストアにbot判定されるため、
これらは `SKIP_HOSTS` でスキップし、**ローカルMacのスケジュールタスク側が家庭IPで巡回**する。
GitHub側はメルカリ・PayPayフリマ・Disney等の約185件を担当。

## Secrets

`SHEET_ID` / `LINE_CHANNEL_ID` / `LINE_CHANNEL_SECRET` / `LINE_USER_ID`

LINEは既存チャネルのステートレストークン方式（channel_id+secretから毎回取得）。
**LINE Developersコンソールでの長期トークン再発行は厳禁**（既存eBayシステムが壊れる）。
