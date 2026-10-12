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
