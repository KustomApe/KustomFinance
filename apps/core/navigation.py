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
        "title": "マスタ",
        "items": [
            {"label": "取引先", "url": "masters:partner_list", "cap": roles.VIEW},
            {"label": "品目", "url": "masters:item_list", "cap": roles.VIEW},
            {"label": "部門", "url": "masters:department_list", "cap": roles.VIEW},
            {"label": "プロジェクト", "url": "masters:project_list", "cap": roles.VIEW},
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
