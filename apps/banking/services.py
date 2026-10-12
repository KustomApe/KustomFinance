import datetime
import hashlib
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.ledger.models import JournalSource, Side
from apps.ledger.services import LineInput, post_journal
from apps.masters.documents import DocStatus
from apps.masters.models import Partner
from apps.purchasing.models import Bill
from apps.purchasing.services import create_payment
from apps.sales.models import Invoice
from apps.sales.services import create_receipt

from .models import BankAccount, BankRule, BankTransaction, ImportBatch
from .parsing import normalize_name, parse_csv

# 入金時に差し引かれる振込手数料として許容する差額
FEE_TOLERANCE = Decimal(1000)


@transaction.atomic
def import_statement(
    bank_account: BankAccount, file_name: str, data: bytes, user
) -> tuple[ImportBatch, list[str]]:
    profile = bank_account.import_profile
    if profile is None:
        raise ValidationError("口座に明細CSVの形式が設定されていません。")
    rows, errors = parse_csv(data, profile)
    if errors and not rows:
        raise ValidationError(errors)
    batch = ImportBatch.objects.create(
        bank_account=bank_account,
        file_name=file_name,
        file_sha256=hashlib.sha256(data).hexdigest(),
        created_by=user,
    )
    seen: dict[str, int] = {}
    for row in rows:
        base = f"{row.date}|{row.description}|{row.deposit}|{row.withdrawal}|{row.balance}"
        # 同じ内容の取引が同じファイルに複数ある場合も区別する
        seen[base] = seen.get(base, 0) + 1
        fingerprint = hashlib.sha256(f"{base}|{seen[base]}".encode()).hexdigest()
        if BankTransaction.objects.filter(bank_account=bank_account, fingerprint=fingerprint).exists():
            batch.skipped += 1
            continue
        BankTransaction.objects.create(
            bank_account=bank_account,
            batch=batch,
            date=row.date,
            description=row.description,
            deposit=row.deposit,
            withdrawal=row.withdrawal,
            balance=row.balance,
            fingerprint=fingerprint,
        )
        batch.imported += 1
    batch.save()
    return batch, errors


def match_rule(tx: BankTransaction, rules=None) -> BankRule | None:
    text = normalize_name(tx.description)
    for rule in (
        rules
        if rules is not None
        else BankRule.objects.filter(is_active=True).select_related("account", "tax_category", "partner")
    ):
        if rule.direction == BankRule.Direction.DEPOSIT and not tx.deposit:
            continue
        if rule.direction == BankRule.Direction.WITHDRAWAL and not tx.withdrawal:
            continue
        if normalize_name(rule.keyword) in text:
            return rule
    return None


@dataclass
class Candidate:
    document: object  # Invoice or Bill
    outstanding: Decimal
    fee: Decimal
    name_match: bool

    @property
    def score(self) -> tuple:
        return (self.name_match, self.fee == 0, -self.fee)


def _name_matches(partner: Partner, text: str) -> bool:
    keys = [normalize_name(partner.name_kana), normalize_name(partner.name)]
    return any(k and k in text for k in keys)


def candidates(tx: BankTransaction) -> list[Candidate]:
    """入金なら請求書、出金なら仕入請求書から、金額（手数料差引を含む）と名義で消込候補を探す。"""
    text = normalize_name(tx.description)
    if tx.deposit:
        docs = Invoice.objects.filter(
            status=DocStatus.ISSUED, total__gte=tx.deposit, total__lte=tx.deposit + FEE_TOLERANCE
        )
        amount = tx.deposit
    else:
        docs = Bill.objects.filter(
            status=DocStatus.ISSUED, total__gte=tx.withdrawal, total__lte=tx.withdrawal + FEE_TOLERANCE
        )
        amount = tx.withdrawal
    result = []
    for doc in docs.select_related("partner"):
        outstanding = doc.outstanding
        if outstanding <= 0:
            continue
        fee = outstanding - amount
        if 0 <= fee <= FEE_TOLERANCE:
            result.append(Candidate(doc, outstanding, fee, _name_matches(doc.partner, text)))
    result.sort(key=lambda c: c.score, reverse=True)
    # 名義が一致しない手数料差引の候補は誤りやすいので、金額が完全一致するか名義が一致するものに限る
    return [c for c in result if c.name_match or c.fee == 0][:5]


def _ensure_unprocessed(tx: BankTransaction) -> BankTransaction:
    tx = BankTransaction.objects.select_for_update().get(pk=tx.pk)
    if tx.status != BankTransaction.Status.UNPROCESSED:
        raise ValidationError("この明細はすでに処理されています。")
    return tx


@transaction.atomic
def apply_match(tx: BankTransaction, document, user) -> BankTransaction:
    """明細を請求書（入金）・仕入請求書（出金）に消し込む。差額は振込手数料として処理する。"""
    tx = _ensure_unprocessed(tx)
    bank = tx.bank_account
    common = {"date": tx.date, "user": user, "memo": tx.description}
    if isinstance(document, Invoice):
        fee = document.outstanding - tx.deposit
        receipt = create_receipt(
            partner=document.partner,
            deposit_account=bank.account,
            deposit_sub_account=bank.sub_account,
            amount=tx.deposit,
            fee=fee,
            allocations=[(document, document.outstanding)],
            **common,
        )
        tx.journal = receipt.journal
    elif isinstance(document, Bill):
        deduction = document.outstanding - tx.withdrawal
        payment = create_payment(
            partner=document.partner,
            pay_account=bank.account,
            pay_sub_account=bank.sub_account,
            amount=tx.withdrawal,
            fee=Decimal(0),
            deduction=deduction,
            allocations=[(document, document.outstanding)],
            **common,
        )
        tx.journal = payment.journal
    else:
        raise ValidationError("消込対象が不正です。")
    tx.status = BankTransaction.Status.DONE
    tx.save()
    return tx


@transaction.atomic
def post_transaction(
    tx: BankTransaction, user, *, account, tax_category=None, partner=None, description: str = ""
) -> BankTransaction:
    """明細から仕訳を登録する（入金: 預金 / 相手科目、出金: 相手科目 / 預金）。"""
    tx = _ensure_unprocessed(tx)
    bank = tx.bank_account
    if account == bank.account:
        raise ValidationError("相手科目に口座と同じ科目は指定できません。")
    amount = tx.deposit or tx.withdrawal
    text = description or tx.description
    bank_line = LineInput(
        bank.account,
        Side.DEBIT if tx.deposit else Side.CREDIT,
        amount,
        sub_account=bank.sub_account,
        partner=partner,
    )
    other = LineInput(
        account, Side.CREDIT if tx.deposit else Side.DEBIT, amount, tax_category, partner=partner
    )
    tx.journal = post_journal(
        tx.date, text, [bank_line, other], source=JournalSource.BANK, source_object=tx, user=user
    )
    tx.status = BankTransaction.Status.DONE
    tx.save()
    return tx


@transaction.atomic
def ignore_transaction(tx: BankTransaction, note: str) -> BankTransaction:
    tx = _ensure_unprocessed(tx)
    tx.status = BankTransaction.Status.IGNORED
    tx.note = note or "対象外"
    tx.save()
    return tx


@transaction.atomic
def reopen_transaction(tx: BankTransaction) -> BankTransaction:
    """「対象外」にした明細を未処理に戻す（仕訳済みの明細は仕訳の取消で対応する）。"""
    tx = BankTransaction.objects.select_for_update().get(pk=tx.pk)
    if tx.status != BankTransaction.Status.IGNORED:
        raise ValidationError("対象外の明細のみ戻せます。")
    tx.status = BankTransaction.Status.UNPROCESSED
    tx.note = ""
    tx.save()
    return tx


def reconciliation(bank: BankAccount, as_of: datetime.date) -> dict:
    """通帳（取込明細）の残高と帳簿残高を比較する。"""
    from apps.ledger.selectors import general_ledger

    last = bank.transactions.filter(date__lte=as_of, balance__isnull=False).order_by("-date", "-id").first()
    opening, entries = general_ledger(bank.account, as_of, as_of, bank.sub_account)
    book = entries[-1].balance if entries else opening
    return {
        "statement_balance": last.balance if last else None,
        "statement_date": last.date if last else None,
        "book_balance": book,
        "difference": (last.balance - book) if last else None,
        "unprocessed": bank.transactions.filter(
            status=BankTransaction.Status.UNPROCESSED, date__lte=as_of
        ).count(),
    }
