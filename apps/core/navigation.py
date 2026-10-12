"""サイドバーのメニュー定義。各マイルストーンで機能を追加する。"""

from apps.accounts import roles

NAV = [
    {
        "title": "ホーム",
        "items": [
            {"label": "ダッシュボード", "url": "core:dashboard"},
        ],
    },
    {
        "title": "販売",
        "items": [
            {"label": "見積書", "url": "sales:estimate_list", "cap": roles.VIEW},
            {"label": "受注", "url": "sales:order_list", "cap": roles.VIEW},
            {"label": "納品書", "url": "sales:delivery_list", "cap": roles.VIEW},
            {"label": "請求書", "url": "sales:invoice_list", "cap": roles.VIEW},
            {"label": "締め請求", "url": "sales:billing", "cap": roles.VIEW},
            {"label": "入金・消込", "url": "sales:receipts", "cap": roles.VIEW},
            {"label": "売掛金残高", "url": "sales:receivables", "cap": roles.VIEW},
            {"label": "前受金残高", "url": "sales:advances", "cap": roles.VIEW},
        ],
    },
    {
        "title": "購買",
        "items": [
            {"label": "注文書", "url": "purchasing:order_list", "cap": roles.VIEW},
            {"label": "検収", "url": "purchasing:receipt_list", "cap": roles.VIEW},
            {"label": "仕入請求書", "url": "purchasing:bill_list", "cap": roles.VIEW},
            {"label": "未計上の検収", "url": "purchasing:unbilled", "cap": roles.VIEW},
            {"label": "支払予定表", "url": "purchasing:schedule", "cap": roles.VIEW},
            {"label": "支払・消込", "url": "purchasing:payments", "cap": roles.VIEW},
            {"label": "買掛金残高", "url": "purchasing:payables", "cap": roles.VIEW},
            {"label": "前渡金残高", "url": "purchasing:advances", "cap": roles.VIEW},
        ],
    },
    {
        "title": "経費・銀行",
        "items": [
            {"label": "経費精算", "url": "expenses:list", "cap": roles.VIEW},
            {"label": "銀行明細の処理", "url": "banking:transactions", "cap": roles.VIEW},
            {"label": "明細の取込", "url": "banking:import", "cap": roles.LEDGER_EDIT},
            {"label": "残高照合", "url": "banking:reconciliation", "cap": roles.VIEW},
        ],
    },
    {
        "title": "固定資産",
        "items": [
            {"label": "固定資産台帳", "url": "assets:list", "cap": roles.VIEW},
            {"label": "減価償却の計上", "url": "assets:run", "cap": roles.LEDGER_EDIT},
        ],
    },
    {
        "title": "会計",
        "items": [
            {"label": "仕訳入力", "url": "ledger:journal_new", "cap": roles.LEDGER_EDIT},
            {"label": "仕訳帳", "url": "ledger:journals", "cap": roles.VIEW},
            {"label": "総勘定元帳", "url": "ledger:general_ledger", "cap": roles.VIEW},
            {"label": "試算表", "url": "ledger:trial_balance", "cap": roles.VIEW},
            {"label": "締め処理", "url": "ledger:period_close", "cap": roles.PERIOD_CLOSE},
        ],
    },
    {
        "title": "決算・帳票",
        "items": [
            {"label": "損益計算書", "url": "reports:pl", "cap": roles.VIEW},
            {"label": "貸借対照表", "url": "reports:bs", "cap": roles.VIEW},
            {"label": "消費税集計表", "url": "reports:tax", "cap": roles.VIEW},
            {"label": "証憑の検索", "url": "documents:search", "cap": roles.VIEW},
        ],
    },
    {
        "title": "マスタ",
        "items": [
            {"label": "取引先", "url": "masters:partner_list", "cap": roles.VIEW},
            {"label": "品目", "url": "masters:item_list", "cap": roles.VIEW},
            {"label": "部門", "url": "masters:department_list", "cap": roles.VIEW},
            {"label": "プロジェクト", "url": "masters:project_list", "cap": roles.VIEW},
            {"label": "銀行口座", "url": "banking:account_list", "cap": roles.VIEW},
            {"label": "自動仕訳ルール", "url": "banking:rule_list", "cap": roles.VIEW},
            {"label": "明細CSV形式", "url": "banking:profile_list", "cap": roles.VIEW},
        ],
    },
    {
        "title": "設定",
        "items": [
            {"label": "自社情報", "url": "core:company", "cap": roles.SETTINGS},
            {"label": "会計期間", "url": "core:fiscal_years", "cap": roles.VIEW},
            {"label": "勘定科目", "url": "ledger:accounts", "cap": roles.VIEW},
            {"label": "税区分", "url": "ledger:tax_categories", "cap": roles.VIEW},
            {"label": "ユーザー", "url": "accounts:users", "cap": roles.SETTINGS},
            {"label": "操作ログ", "url": "audit:logs", "cap": roles.LEDGER_EDIT},
        ],
    },
]
