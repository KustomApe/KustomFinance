# Issue のテンプレート

`Issues → New issue` を押すと、ひな形の一覧が出ます。選ぶと本文と
タイトルの頭書き・ラベルが入った状態で開きます。

| ファイル | 出てくる名前 | ラベル | タイトル |
| --- | --- | --- | --- |
| `.github/ISSUE_TEMPLATE/bug.md` | 不具合の報告 | `bug` | `[Bug] ` |
| `.github/ISSUE_TEMPLATE/feature.md` | 機能の追加・改善 | `enhancement` | `[Feature] ` |
| `.github/ISSUE_TEMPLATE/compliance.md` | 法令・税制対応 | `compliance` | `[Compliance] ` |
| `.github/ISSUE_TEMPLATE/docs.md` | ドキュメント | `documentation` | `[Docs] ` |
| `.github/ISSUE_TEMPLATE/chore.md` | 保守・技術的負債 | `chore` | `[Chore] ` |
| `.github/ISSUE_TEMPLATE/config.yml` | （一覧の設定） | — | — |

どれにも当てはまらないときのために、ひな形なしの Issue も開けるようにしてあります
（`config.yml` の `blank_issues_enabled: true`）。

PR 側のひな形は [docs/pull-request.md](pull-request.md) にあります。

---

## 0. 先にラベルを作る（初回だけ）

`compliance` `chore` などは GitHub の既定のラベルにありません。**無いラベルは
黙って付かない**ので、一度だけ作っておいてください。

```bash
gh label create compliance       --description "法令・税制（消費税・インボイス・電帳法）への対応" --color 5319e7
gh label create chore            --description "保守・依存の更新・技術的負債"                 --color fef2c0
gh label create breaking         --description "互換性のない変更"                             --color b60205
gh label create dependencies     --description "依存の更新"                                   --color 0366d6
gh label create skip-changelog   --description "リリースノートに出さない"                     --color ededed
gh label create "priority: high"   --description "帳簿の数字・請求・申告に関わる。先に片づける" --color b60205
gh label create "priority: medium" --description "近いうちにやりたい"                         --color fbca04
gh label create "priority: low"    --description "いつか（メモとして残す）"                   --color c5def5
gh label list                      # 既にあるか確認する
```

`bug` `enhancement` `documentation` は既定であります。作り直す必要はありません。

## 1. 使う

ブラウザなら `Issues → New issue` から選ぶだけです。設定は要りません。

`gh` からも開けます。

```bash
gh issue create                         # 対話。ひな形を選べる
gh issue create --template bug.md
gh issue create --template compliance.md --title "[Compliance] 少額特例"
gh issue list --label compliance        # 種類で絞って見る
```

`<!-- … -->` の行はコメントで、**投稿すると表示されません**。書き方の案内なので、
消しても残しても構いません。チェック欄も、当てはまらない行は消してよいです。

## 2. どれを選ぶか

| 状況 | ひな形 |
| --- | --- |
| 動くはずのものが動かない・金額が合わない | 不具合の報告 |
| まだ無いものが欲しい・今より良くしたい | 機能の追加・改善 |
| 制度が変わった／制度どおりに計算・記載・保存できていない | 法令・税制対応 |
| 手順書どおりにやったのに進まない | ドキュメント |
| 依存を上げたい・設定を直したい・あとで直すメモ | 保守・技術的負債 |

迷ったら**不具合か、それ以外か**だけで分けてください。
「動くはずのものが動かない」なら不具合、それ以外は要望です。

## 3. 何を書くか（迷ったとき）

**不具合で効くのは再現手順と番号です。** このアプリは**ロールと締め処理の状態で
動きが変わる**うえ、仕訳・帳票には必ず番号（`JE-`・`INV-` など）が付いています。
どのロールで、どの番号のデータで起きたかが分かれば、調べる時間がほぼ消えます。

**金額の不具合は「いくらになるはずか」と根拠を書いてください。** 消費税は
税率ごと・帳票ごとに1回端数処理するなど、計算の決まりが細かいので、期待値の
根拠（請求書の記載・国税庁の Q&A など）があると早く確定できます。

**要望で効くのは「なぜ」です。** いま手作業（仕訳入力・Excel）でやっている手順を
書いてもらえれば、解き方はあとから選べます。

**「こうなったら完了」が書けない要望は、まだ早い** ことが多いです。

## 4. ひな形そのものを直す

先頭の `---` で挟まれた部分が設定で、GitHub はここを読みます。

```yaml
---
name: 不具合の報告          # 一覧に出る名前
about: 動かない・壊れている  # 名前の下の説明
title: "[Bug] "            # タイトルの頭に入る文字
labels: bug                # 自動で付くラベル（複数なら bug, compliance）
assignees: ''              # 自動で割り当てる人。空でよい
---
```

`---` から下は、ただの Markdown です。編集して既定のブランチ（master）に入れれば、
次の Issue から新しいひな形が出ます。**既に開いている Issue の本文は変わりません**。

種類を増やすときは、ファイルを 1 枚足してこのページの表に 1 行足します。
ラベルを新しく使うなら、0 章のとおり先に作ってください。

## 5. Issue と PR をつなぐ

PR の本文に `Closes #12` と書くと、PR を master に入れたときに Issue が閉じます。
