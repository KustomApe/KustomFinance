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
- `apps/ledger` 勘定科目・税区分・仕訳・総勘定元帳・試算表・締め処理
- `apps/masters` 取引先・品目・部門・プロジェクト、帳票共通部品（明細・税率別集計・発行・PDF）
- `apps/sales` 見積書→受注（注文請書）→納品書→請求書、締め請求、入金消込、売掛金年齢表

## 販売の流れ

- 帳票は「下書き→発行」。発行時に番号を採番し、発行時点のPDFを控えとして保存（SHA-256を記録）。発行後は編集不可で、訂正は「取消」＋「複製」。
- 請求書は適格請求書の記載事項（登録番号・税率ごとの対象額と消費税額・軽減税率対象の表示）を満たします。消費税は請求書ごと・税率ごとに1回端数処理します。
- 請求書の発行で「売掛金 / 売上高・仮受消費税」を自動計上。入金登録で消込し、手数料差引入金・前受金にも対応。

## 会計の仕組み

- **税抜経理**: 仕訳は税込金額で入力し、課税取引の消費税は仮払消費税／仮受消費税へ自動で振り分けます。
  経過措置（免税事業者等からの仕入の80%・50%控除）は税区分で選択します。
- **仕訳は変更・削除不可**: DBトリガーで保護しています。訂正は取消仕訳（赤伝）＋新しい仕訳で行います。
- **貸借一致はDBで保証**: コミット時に制約トリガーで検証します。
- **繰越**: 前期以前の損益は繰越利益剰余金の期首残高に自動で含めます（決算振替仕訳は不要）。
- **締め**: 月次締め日以前・決算締め済みの期間には記帳できません。
- 他システムからの移行時は、期首日付で「開始残高」にチェックを付けて仕訳を登録します。
