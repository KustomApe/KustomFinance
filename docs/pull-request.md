# Pull Request のテンプレート

| ファイル | いつ使うか |
| --- | --- |
| `.github/pull_request_template.md` | **既定**。機能の追加・改善、法令対応など |
| `.github/PULL_REQUEST_TEMPLATE/bugfix.md` | 不具合を直したとき |
| `.github/PULL_REQUEST_TEMPLATE/chore.md` | 依存の更新・設定・リファクタ |
| `.github/PULL_REQUEST_TEMPLATE/docs.md` | ドキュメントだけを直したとき |

既定以外のひな形は、PR を作る URL に `?template=bugfix.md` を付けるか、
`gh pr create --template bugfix.md` で選びます。

```bash
gh pr create --template bugfix.md --title "請求書の取消で納品書の紐付けが外れない"
```

## 確認のしかた

チェック欄は**実際に確かめたものだけ**付けてください。とくにこの 3 つは
帳簿の正しさに直結します。

- `make test`（pytest）— 消費税の端数・貸借一致・締め後の記帳拒否などを確かめています
- `uv run manage.py makemigrations --check` — モデルを変えたのにマイグレーションが無いと、本番で落ちます
- 試算表と決算書 — 仕訳の作り方を変えたときは、前後で数字を見比べてください

仕訳・発行済み帳票・証憑・操作ログは、DB のトリガーで**変更・削除できない**ように
なっています。マイグレーションでこれらのトリガーに触れるときは、PR の
「帳簿・法令への影響」に必ず書いてください。

## ラベル

PR には Issue と同じラベル（`enhancement` `bug` `compliance` `chore` `documentation`）を
付けてください。リリースノートの分類はラベルで決まります（[docs/release.md](release.md)）。
