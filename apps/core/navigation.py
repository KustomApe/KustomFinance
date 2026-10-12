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
        "title": "設定",
        "items": [
            {"label": "自社情報", "url": "core:company", "cap": roles.SETTINGS},
            {"label": "会計期間", "url": "core:fiscal_years", "cap": roles.VIEW},
            {"label": "ユーザー", "url": "accounts:users", "cap": roles.SETTINGS},
            {"label": "操作ログ", "url": "audit:logs", "cap": roles.LEDGER_EDIT},
        ],
    },
]
