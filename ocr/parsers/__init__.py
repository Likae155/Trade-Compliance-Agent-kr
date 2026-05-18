"""문서 타입별 파서 패키지."""
from .base import BaseParser, ParseResult
from .contract import SalesContractParser
from .lc import LetterOfCreditParser
from .bl import BillOfLadingParser
from .invoice_like import (
    InvoiceLikeBase,
    CommercialInvoiceParser,
    ProformaInvoiceParser,
    PurchaseOrderParser,
    PackingListParser,
)


def get_parser(doc_type: str) -> BaseParser:
    """
    문서 타입 → 파서 인스턴스.
    미구현 타입은 BaseParser 반환 (공통 필드만 추출).
    """
    parsers = {
        'SalesContract': SalesContractParser,
        'LetterOfCredit': LetterOfCreditParser,
        'BillOfLading': BillOfLadingParser,
        'CommercialInvoice': CommercialInvoiceParser,
        'ProformaInvoice': ProformaInvoiceParser,
        'PurchaseOrder': PurchaseOrderParser,
        'PackingList': PackingListParser,
    }
    cls = parsers.get(doc_type, BaseParser)
    return cls()


__all__ = [
    'BaseParser', 'ParseResult', 'get_parser',
    'SalesContractParser',
    'LetterOfCreditParser',
    'BillOfLadingParser',
    'InvoiceLikeBase',
    'CommercialInvoiceParser',
    'ProformaInvoiceParser',
    'PurchaseOrderParser',
    'PackingListParser',
]
