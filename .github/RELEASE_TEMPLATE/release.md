<!--
既定のリリースノート。使い方は docs/release.md。

  gh release create vX.Y.Z --notes-file .github/RELEASE_TEMPLATE/release.md --generate-notes --draft

で下書きを作り、GitHub 上で埋めるのが早いです。
コメント行は投稿しても表示されません。空の節はまるごと消して構いません。
-->

## このリリースでできるようになったこと

<!-- 1〜3 行。経理・営業・申請者から見て何が変わったか。実装の話は下の一覧へ -->

## 法令・税制への対応

<!-- 制度の改正に合わせたものだけ。施行日と、既存のデータを遡って変えるかを書く。無ければ節ごと消す -->

- 

## 新しい機能・改善

- 

## 不具合の修正

- 

## 更新の手順

```bash
git pull
uv sync                 # Python の依存
make migrate            # マイグレーション（必ずバックアップの後に）
make css                # 画面の CSS
```

<!-- Docker なら `docker compose up -d --build`。システムの依存（Homebrew・apt）が増えたときはここに書く -->

**更新の前に `uv run manage.py backup` でバックアップを取ってください。**
仕訳・発行済み帳票は削除できないため、失敗したときはバックアップから戻すのが確実です。

## 動かすのに要ること

<!-- 新しい環境変数・Homebrew のパッケージなど。無ければ「なし」 -->

なし

## 既知の問題

<!-- 直っていないと分かっているもの。Issue 番号を添える。無ければ「なし」 -->

なし

---

**Full Changelog**: https://github.com/KustomApe/KustomFinance/compare/vX.Y.Z-1...vX.Y.Z
