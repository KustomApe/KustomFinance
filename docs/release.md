# リリースノートとタグ

master に入れたものに版の名前（タグ）を付けて、そのとき何が変わったかを
Releases に残します。

| ファイル | 何 |
| --- | --- |
| `.github/release.yml` | 自動生成されるノートの分類（ラベルごと） |
| `.github/RELEASE_TEMPLATE/release.md` | **既定**のひな形 |
| `.github/RELEASE_TEMPLATE/hotfix.md` | 帳簿・帳票に関わる不具合を直したとき（パッチ版） |

GitHub には Issue や PR のような「リリースのひな形」の仕組みが**ありません**。
`RELEASE_TEMPLATE/` はただの Markdown で、`gh release create --notes-file` で読ませるか、
中身をコピーして貼ります。

## 0. 先に用意する（初回だけ）

ラベルは [docs/issue.md](issue.md) の 0 章のとおり作ってください。

## 1. タグの付け方

`vMAJOR.MINOR.PATCH` です。頭の `v` を必ず付けます。

| 上げる桁 | いつ | 例 |
| --- | --- | --- |
| **MAJOR** | 既存のデータや手順との互換が崩れるとき | 勘定科目の体系を変えた・データの作り直しが要る |
| **MINOR** | 足したとき・制度に対応したとき | 新しい帳票・OCR・制度改正への対応 |
| **PATCH** | 直したとき | 不具合の修正・文言・見た目・ドキュメント |

迷ったら MINOR です。タグは **master に入ったコミットにだけ**打ちます。

## 2. 出す

```bash
git log --oneline v0.1.0..master          # 何が入ったかを見る
gh release create v0.2.0 \
  --title "v0.2.0 — レシートのOCRと請求書PDFのダウンロード" \
  --notes-file .github/RELEASE_TEMPLATE/release.md \
  --generate-notes --draft
gh release view v0.2.0 --web              # ブラウザで埋める
gh release edit v0.2.0 --draft=false      # 公開する
```

## 3. 社内のサーバーへ反映する

リリースノートの「更新の手順」のとおりです。**必ず先にバックアップを取ってください**
（`uv run manage.py backup`）。仕訳・発行済み帳票は削除できないため、更新に失敗したときは
バックアップから戻すのがいちばん確実です。
