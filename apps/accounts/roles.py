"""ロールと操作権限の対応表。

ビューは `RoleRequiredMixin.required_capability` / `@require_capability` で
ここに定義した capability を要求する。
"""

from django.db import models


class Role(models.TextChoices):
    ADMIN = "admin", "管理者"
    ACCOUNTANT = "accountant", "経理"
    SALES = "sales", "営業・購買"
    VIEWER = "viewer", "閲覧のみ"


VIEW = "view"  # 全画面の閲覧
SALES_EDIT = "sales_edit"  # 見積・受注・請求・発注などの作成/編集
EXPENSE_SUBMIT = "expense_submit"  # 経費申請
LEDGER_EDIT = "ledger_edit"  # 仕訳・入出金・償却・承認など経理操作
PERIOD_CLOSE = "period_close"  # 期間締め・締め解除
SETTINGS = "settings"  # 自社設定・ユーザー管理・マスタの削除

CAPABILITIES: dict[str, set[str]] = {
    Role.ADMIN: {VIEW, SALES_EDIT, EXPENSE_SUBMIT, LEDGER_EDIT, PERIOD_CLOSE, SETTINGS},
    Role.ACCOUNTANT: {VIEW, SALES_EDIT, EXPENSE_SUBMIT, LEDGER_EDIT, PERIOD_CLOSE},
    Role.SALES: {VIEW, SALES_EDIT, EXPENSE_SUBMIT},
    Role.VIEWER: {VIEW},
}
