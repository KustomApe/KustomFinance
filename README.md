# KustomFinance

社内LANで動かす法人向け会計・財務管理アプリ（Django + PostgreSQL）。
インボイス制度（適格請求書）・電子帳簿保存法に対応した販売・購買・会計・経費・銀行・固定資産管理を目指します。

## 開発環境（macOS）

前提: Homebrew の `postgresql`, `pango`（WeasyPrint用）, [uv](https://docs.astral.sh/uv/)

```sh
createdb kustomfinance
cp .env.example .env          # SECRET_KEY を設定
make setup                    # 依存インストール・マイグレーション・CSSビルド
uv run manage.py createsuperuser
make dev                      # http://localhost:8000
```

CSSを編集する場合は別ターミナルで `make css-watch`。テストは `make test`。

## Docker で起動（社内サーバー）

```sh
echo "SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(50))')" > .env
echo "ALLOWED_HOSTS=localhost,192.168.1.10" >> .env           # サーバーPCのIP
echo "CSRF_TRUSTED_ORIGINS=http://192.168.1.10:8000" >> .env
docker compose up -d --build
docker compose exec app /opt/venv/bin/python manage.py createsuperuser
```

社内の他のPCからは `http://<サーバーPCのIP>:8000` でアクセスします。

## ロール

| ロール | できること |
|---|---|
| 管理者 | すべて（自社設定・ユーザー管理） |
| 経理 | 仕訳・入出金・承認・期間締め |
| 営業・購買 | 見積・受注・請求・発注の作成、経費申請 |
| 閲覧のみ | 閲覧 |

## 構成

- `apps/core` 自社情報・会計期間・採番・金額丸め
- `apps/accounts` ユーザー・ロール
- `apps/audit` 操作ログ（DBトリガーで変更・削除不可。電子帳簿保存法の訂正削除履歴）
