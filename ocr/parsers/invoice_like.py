"""
Invoice-like 공통 파서 — Commercial Invoice / Proforma Invoice /
Purchase Order / Packing List 4가지 공유.

공통 구조:
  [상단] 헤더 필드 (문서번호, 발행일, 당사자 정보, 조건)
  [중단] 표 (품목 리스트 — 품목명·수량·단가·금액)
  [하단] 합계 + 서명

80% 공통, 20%만 문서별 특화 필드.
"""
from __future__ import annotations
import re
from .base import BaseParser, ParseResult


# ────────────────────────────────────────────────────────────
# 공통 헤더 필드
# ────────────────────────────────────────────────────────────
# Invoice-like 공용 HEADER_PATTERNS (정방향 우선)
# PO는 이 정방향 우선이 맞음. CI/PI/PL은 별도 HEADER_PATTERNS_REV 사용.
HEADER_PATTERNS_FWD = {
    'invoice_no': [
        # Proforma Invoice No. 명시 시 우선 — PI가 CI/invoice_no에 잘못 잡히는 것 방지
        re.compile(r'Proforma\s*Invoice\s*(?:No\.?|Number|#)\s*[:\.]?\s*\n?\s*([A-Z]{2,3}-?\d{2}-?\d{3,6}|[A-Z0-9\-/]{3,30})', re.IGNORECASE),
        re.compile(r'([A-Z]{2,3}-?\d{2}-?\d{3,6}|[A-Z]{2,}\d{4,})\s*\n\s*Proforma\s*Invoice\s*(?:No\.?|Number)', re.IGNORECASE),
        # 일반 Invoice No. — 날짜 포맷은 명시적으로 제외하기 위해 접두부 매치 우선
        re.compile(r'(?:^|\n)\s*Invoice\s*(?:No\.?|Number|#)\s*[:\.]?\s*\n?\s*([A-Z]{2,3}-?\d{2}-?\d{3,6}|[A-Z]{2,}\d{4,}[A-Z0-9\-/]*)', re.IGNORECASE),
        re.compile(r'([A-Z]{2,3}-?\d{2}-?\d{3,6}|[A-Z]{2,}\d{4,})\s*\n\s*Invoice\s*(?:No\.?|Number|#)', re.IGNORECASE),
        re.compile(r'(?:송장|인보이스)\s*번호\s*[:\.]?\s*([A-Z0-9\-/]{3,30})'),
    ],
    'order_no': [
        re.compile(r'(?:P\.?O\.?|Order|Purchase)\s*(?:No\.?|Number|#)\s*[:\.]?\s*\n?\s*([A-Z]{2,3}-?\d{2,6}-?\d{3,6}|[A-Z0-9\-/]{3,30})', re.IGNORECASE),
        re.compile(r'([A-Z]{2,3}-?\d{2,6}-?\d{3,6}|[A-Z]{2,}\d{4,})\s*\n\s*(?:P\.?O\.?|Purchase\s*Order|Order)\s*(?:No\.?|Number|#)?', re.IGNORECASE),
        re.compile(r'(?:발주|주문)\s*번호\s*[:\.]?\s*([A-Z0-9\-/]{3,30})'),
    ],
    'packing_no': [
        re.compile(r'Packing\s*List\s*(?:No\.?|Number)\s*[:\.]?\s*\n?\s*([A-Z0-9\-/]{3,30})', re.IGNORECASE),
        # 단축형: "PL No: ..." (현장 양식 다수)
        re.compile(r'\bPL\s*No\.?\s*[:\.]?\s*([A-Z0-9\-/]{3,30})', re.IGNORECASE),
        re.compile(r'P/L\s*No\.?\s*[:\.]?\s*([A-Z0-9\-/]{3,30})', re.IGNORECASE),
        re.compile(r'([A-Z]{2,3}-?\d{2}-?\d{3,6})\s*\n\s*Packing\s*List\s*(?:No\.?|Number)?', re.IGNORECASE),
        re.compile(r'(?:포장|패킹)\s*번호\s*[:\.]?\s*([A-Z0-9\-/]{3,30})'),
    ],
    'quotation_no': [
        re.compile(r'(?:Quotation|Proforma)\s*(?:Invoice)?\s*(?:No\.?|Number|#)\s*[:\.]?\s*\n?\s*([A-Z0-9\-/]{3,30})', re.IGNORECASE),
        re.compile(r'([A-Z]{2,3}-?\d{2,6})\s*\n\s*Proforma\s*Invoice\s*(?:No\.?|Number)', re.IGNORECASE),
    ],
    'date': [
        re.compile(r'(?:Invoice\s*Date|Date\s*of\s*Issue|Order\s*Date|발행일|일자)\s*[:\.]?\s*\n?\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})', re.IGNORECASE),
        re.compile(r'(\d{4}[-./]\d{1,2}[-./]\d{1,2})\s*\n\s*(?:Invoice\s*Date|Date\s*of\s*Issue|Order\s*Date)(?!\s*of\s*Expiry)', re.IGNORECASE),
    ],
    'seller': [
        # 줄 시작 라벨 + 탭/공백 + 값 (표 형식 — PO/CI/PI 양식 다수)
        # 한글 회사명 '(주) ...' 도 매치 가능하도록 시작 문자 확장
        re.compile(r'(?:^|\n|\t)(?:Seller|Vendor|Shipper|Consignor|Exporter)\s+([A-Za-z가-힣\(㈜][^\n\t|]{4,200}?)(?=\s*(?:\t|\||\n|Invoice\s*No|L/C\s*No|PO\s*No|Order\s*Date|Consignee|Buyer|Customer|Importer|Ship\s*To))', re.IGNORECASE),
        # 정방향: Seller/Vendor/Consignor 라벨 뒤 다음 줄
        re.compile(r'(?:Seller|Vendor|Shipper|Consignor|Exporter|수출자|매도인|공급자|송하인)\s*[:\.]?\s*\n\s*([^\n]{5,250})', re.IGNORECASE),
        # 같은 줄: 콜론 뒤 ~ ' | ' or 다음 라벨 직전까지 (탐욕 방지)
        re.compile(r'(?:Seller|Vendor|Shipper|Consignor|Exporter)\s*[:\.]\s*([^|\n]{5,150}?)(?=\s*(?:\||$|Consignee|Buyer|Customer))', re.IGNORECASE),
        re.compile(r'(?:Seller|Vendor|Shipper|Consignor|Exporter)\s*[:\.]\s*([^\n]{5,250})', re.IGNORECASE),
        # 역방향 (간혹 있음)
        re.compile(r'([^\n]{5,250})\s*\n\s*(?:Seller|Vendor|Shipper|Consignor)(?!\s*Bank)', re.IGNORECASE),
        re.compile(r'(?:From|Sold\s*By)\s*[:\.]\s*([^\n]{3,200})', re.IGNORECASE),
    ],
    'buyer': [
        # 줄 시작 라벨 + 탭/공백 + 값 (한글 회사명 '(주) 가야...' 등)
        re.compile(r'(?:^|\n|\t)(?:Buyer|Customer|Consignee|Importer)\s+([A-Za-z가-힣\(㈜][^\n\t|]{4,200}?)(?=\s*(?:\t|\||\n|Invoice\s*No|L/C\s*No|PO\s*No|PL\s*No|Description|Notify|Vendor|Seller|Shipper|Ship\s*To))', re.IGNORECASE),
        re.compile(r'(?:Buyer|Customer|Consignee|Importer|수입자|매수인|구매자|수하인)\s*[:\.]?\s*\n\s*([^\n]{5,250})', re.IGNORECASE),
        # 같은 줄: 콜론 뒤 ~ ' | ' or 다음 라벨 직전까지 (탐욕 방지)
        re.compile(r'(?:Buyer|Customer|Consignee|Importer)\s*[:\.]\s*([^|\n]{5,150}?)(?=\s*(?:\||$|PL\s*No|Invoice\s*No|Date|Description))', re.IGNORECASE),
        re.compile(r'(?:Buyer|Customer|Consignee|Importer)\s*[:\.]\s*([^\n]{5,250})', re.IGNORECASE),
        re.compile(r'([^\n]{5,250})\s*\n\s*(?:Buyer|Customer|Consignee)(?!\s*.)', re.IGNORECASE),
        re.compile(r'(?:To|Sold\s*To|Bill\s*To|Messrs)\s*[:\.]\s*([^\n]{3,200})', re.IGNORECASE),
    ],
    'ship_to': [
        re.compile(r'(?:Ship\s*To|Delivery\s*Address|배송지)\s*[:\.]?\s*\n\s*([^\n]{5,200})', re.IGNORECASE),
        re.compile(r'([^\n]{5,200})\s*\n\s*Ship\s*To', re.IGNORECASE),
    ],
    'payment_terms': [
        re.compile(r'(?:Payment\s*Terms?|지급조건|결제조건)\s*[:\.]?\s*\n?\s*([^\n]{3,100})', re.IGNORECASE),
        re.compile(r'([^\n]{3,100})\s*\n\s*(?:Payment\s*Terms?)', re.IGNORECASE),
    ],
    'delivery_date': [
        re.compile(r'(?:Delivery\s*Date|Required\s*(?:Delivery\s*)?Date|납기일?)\s*[:\.]?\s*\n?\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})', re.IGNORECASE),
        re.compile(r'(\d{4}[-./]\d{1,2}[-./]\d{1,2})\s*\n\s*(?:Delivery\s*Date|Required\s*Date|납기)', re.IGNORECASE),
    ],
    'incoterms': [
        re.compile(r'Incoterms?\s*[:\.]?\s*\n?\s*(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP|DAT)\b\s*([A-Za-z가-힣]+)?', re.IGNORECASE),
        re.compile(r'((?:EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP|DAT)\b\s*[A-Za-z가-힣]+)\s*\n\s*Incoterms?', re.IGNORECASE),
        re.compile(r'\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP|DAT)\s+([A-Za-z가-힣]+)', re.IGNORECASE),
    ],
    'total_amount': [
        re.compile(r'(?:Grand\s*Total|Total\s*Amount|TOTAL(?:\s*QUOTATION)?|합계|총액)\s*[:\.]?\s*([A-Z]{3})?\s*([0-9,]+(?:\.\d{1,2})?)', re.IGNORECASE),
    ],
    'currency': [
        re.compile(r'(?:Currency|통화)\s*[:\.]?\s*\n?\s*([A-Z]{3})', re.IGNORECASE),
        re.compile(r'([A-Z]{3})\s*\n\s*Currency', re.IGNORECASE),
    ],
    'country_of_origin': [
        re.compile(r'(?:Country\s*of\s*Origin|Origin|원산지)\s*[:\.]?\s*\n?\s*([A-Za-z가-힣]{2,40})', re.IGNORECASE),
        re.compile(r'([A-Z가-힣]{2,40})\s*\n\s*Country\s*of\s*Origin', re.IGNORECASE),
    ],
    'hs_code': [
        re.compile(r'H\.?S\.?\s*(?:Code|Number)\s*[:\.]?\s*(\d{4}\.\d{2,4}(?:\.\d{2})?)', re.IGNORECASE),
    ],
    'port_of_loading': [
        # 정방향 먼저
        re.compile(r'Port\s*of\s*Loading\s*[:\.]?\s*\n?\s*([^\n]{3,60})', re.IGNORECASE),
        # 역방향
        re.compile(r'([^\n]{3,60})\s*\n\s*Port\s*of\s*Loading', re.IGNORECASE),
        re.compile(r'(?:선적항)\s*[:\.]?\s*([^\n]{3,60})'),
    ],
    'port_of_discharge': [
        re.compile(r'Port\s*of\s*(?:Discharge|Destination)\s*[:\.]?\s*\n?\s*([^\n]{3,60})', re.IGNORECASE),
        re.compile(r'([^\n]{3,60})\s*\n\s*Port\s*of\s*(?:Discharge|Destination)', re.IGNORECASE),
        re.compile(r'(?:도착항|양륙항|목적항)\s*[:\.]?\s*([^\n]{3,60})'),
    ],
    'valid_until': [
        re.compile(r'Valid\s*Until\s*[:\.]?\s*\n?\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})', re.IGNORECASE),
        re.compile(r'(\d{4}[-./]\d{1,2}[-./]\d{1,2})\s*\n\s*Valid\s*Until', re.IGNORECASE),
    ],
    # Packing List 특화
    'gross_weight': [
        re.compile(r'([0-9,\.]+)\s*(KGS?|LBS?|TONS?)\s*\n\s*(?:Gross\s*W(?:eigh)?t|Total\s*Gross\s*W(?:eigh)?t)', re.IGNORECASE),
        # "Gross Weight" / "Gross Wt" 약자형 + "TOTAL GROSS WT" 변형 모두 대응
        re.compile(r'(?:Total\s*)?Gross\s*W(?:eigh)?t\.?\s*[:\.]?\s*([0-9,\.]+)\s*(KGS?|LBS?|TONS?)?', re.IGNORECASE),
        re.compile(r'\bG\.W\.?\s*[:\.]?\s*([0-9,\.]+)\s*(KGS?|LBS?|TONS?)?', re.IGNORECASE),
        re.compile(r'(?:총중량)\s*[:\.]?\s*([0-9,\.]+)\s*(KGS?|LBS?|TONS?)?'),
    ],
    'net_weight': [
        re.compile(r'([0-9,\.]+)\s*(KGS?|LBS?|TONS?)\s*\n\s*(?:Net\s*W(?:eigh)?t|Total\s*Net\s*W(?:eigh)?t)', re.IGNORECASE),
        # "Net Weight" / "Net Wt" 약자형 + "TOTAL NET WT" 변형 모두 대응
        re.compile(r'(?:Total\s*)?Net\s*W(?:eigh)?t\.?\s*[:\.]?\s*([0-9,\.]+)\s*(KGS?|LBS?|TONS?)?', re.IGNORECASE),
        re.compile(r'\bN\.W\.?\s*[:\.]?\s*([0-9,\.]+)\s*(KGS?|LBS?|TONS?)?', re.IGNORECASE),
        re.compile(r'(?:순중량)\s*[:\.]?\s*([0-9,\.]+)\s*(KGS?|LBS?|TONS?)?'),
    ],
    'measurement': [
        re.compile(r'([0-9,\.]+)\s*(M3|CBM|CFT)\s*\n\s*(?:Measurement|Total\s*Measurement)', re.IGNORECASE),
        re.compile(r'(?:Measurement|Total\s*Measurement|CBM|용적)\s*[:\.]?\s*([0-9,\.]+)\s*(M3|CBM|CFT)?', re.IGNORECASE),
        # 4/30 — 'TOTAL ... 60 CBM' 표 마지막 행 마지막 측정 (sc2_4/5 양식)
        re.compile(r'\bTOTAL\b[^\n]*?([0-9][0-9,\.]*)\s*(M3|CBM|CFT)\b', re.IGNORECASE),
    ],
    'n_packages': [
        re.compile(r'(\d+)\s+(CTNS?|PKGS?|PLTS?|CARTONS|PALLETS|PACKAGES|CASES)\s*\n\s*Total\s*Packages', re.IGNORECASE),
        re.compile(r'(?:Number\s*of\s*Packages|Total\s*Packages|Packages|박스\s*수)\s*[:\.]?\s*(\d+)\s*(CTNS?|PKGS?|PLTS?|CARTONS|PALLETS|PACKAGES|CASES)?', re.IGNORECASE),
    ],
    'marks_numbers': [
        re.compile(r'([A-Z]{2,6}/\d+\s*-\s*\d+)\s*\n\s*Marks', re.IGNORECASE),
        re.compile(r'Marks\s*(?:&|and)\s*Numbers\s*[:\.]?\s*([^\n]{3,60})', re.IGNORECASE),
    ],
}

# CI/PI/PL 용: 역방향 우선 (각 필드의 첫 2개 순서 swap)
def _reverse_order(patterns_dict):
    """각 필드 패턴 리스트의 첫 두 개 순서만 바꾼 dict 반환."""
    result = {}
    for field, pats in patterns_dict.items():
        if len(pats) >= 2:
            new_pats = [pats[1], pats[0]] + list(pats[2:])
        else:
            new_pats = list(pats)
        result[field] = new_pats
    return result


HEADER_PATTERNS_REV = _reverse_order(HEADER_PATTERNS_FWD)

# seller/buyer는 정방향 3개 + 역방향 1개 구조라 단순 swap으로 역방향이 앞으로 못 옴
# REV 버전에서만 역방향을 맨 앞에 두도록 명시적 override
#
# 중요: Buyer 라벨 바로 앞 줄이 'Email:' 같은 이메일 라벨일 수 있음
# → "회사명 ... Email:\nBuyer\nxxx@..." 순서일 때
#    회사명은 Buyer 2-3줄 위에 있을 수 있음
# 따라서 Buyer 라벨 위 1~5줄 연속을 보고 회사명처럼 보이는 첫 줄을 찾음
# 라벨 직전 1줄 매칭 (OCR이 "회사명\nSeller" 순서로 읽는 케이스)
# 단, 'Parties' 같은 섹션 헤더는 제외
_SELLER_REV = [
    # 슬래시 결합 라벨 (PL 양식 자주: 'Shipper / Seller', 'Seller / Exporter')
    re.compile(r'(?:^|\n|\t)(?:Shipper\s*/\s*(?:Seller|Exporter|Consignor)|Seller\s*/\s*(?:Shipper|Exporter)|Exporter\s*/\s*(?:Seller|Shipper)|Consignor\s*/\s*Shipper)\s*[:\.]?\s+([A-Za-z가-힣\(㈜][^\n\t|]{4,200}?)(?=\s*(?:\t|\||\n|Consignee|Buyer|Customer|Importer))', re.IGNORECASE),
    # 줄 시작 라벨 + 공백 + 값 (콜론 없는 표 패턴) — 우선순위 최상위로
    # 'EXPORTER Hyundai Robotics Co., Ltd.\tINVOICE NO ...' 같은 표 양식
    re.compile(r'(?:^|\n|\t)(?:Seller|Vendor|Shipper|Consignor|Exporter)\s+([A-Za-z가-힣\(㈜][^\n\t|]{4,200}?)(?=\s*(?:\t|\||\n|Invoice\s*No|L/C\s*No|Consignee|Buyer|Customer|Importer))', re.IGNORECASE),
    # 라벨 + 콜론 + 같은 줄 값 (탭/파이프 구분자 포함, 다음 라벨 직전까지)
    re.compile(r'(?:Seller|Vendor|Shipper|Consignor|Exporter)\s*[:\.]\s*([^|\n\t]{5,150}?)(?=\s*(?:\t|\||$|Consignee|Buyer|Customer|Importer|Invoice\s*No))', re.IGNORECASE),
    # 라벨 뒤 다음 줄 (콜론 없는 형태)
    re.compile(r'(?:Seller|Vendor|Shipper|Consignor|Exporter|수출자|매도인|공급자|송하인)\s*[:\.]?\s*\n\s*([^\n\t|]{5,250}?)(?=\s*(?:\t|\||\n|$))', re.IGNORECASE),
    re.compile(r'(?:Seller|Vendor|Shipper|Consignor|Exporter|수출자|매도인|공급자|송하인)\s*[:\.]?\s*\n\s*([^\n]{5,250})', re.IGNORECASE),
    re.compile(r'(?:Seller|Vendor|Shipper|Consignor|Exporter)\s*[:\.]\s*([^\n]{5,250})', re.IGNORECASE),
    # 1줄 직전 (회사명이 라벨 바로 위) — 마지막 fallback (양식 제목 잡힐 위험 있어 우선순위 낮춤)
    re.compile(
        r'([A-Za-z가-힣(㈜][^\n]{3,250})\s*\n\s*(?:Seller|Vendor|Shipper|Consignor|Exporter)(?!\s*Bank)',
        re.IGNORECASE,
    ),
    re.compile(r'(?:From|Sold\s*By)\s*[:\.]\s*([^\n]{3,200})', re.IGNORECASE),
]
_BUYER_REV = [
    # 슬래시 결합 라벨 (PL: 'Consignee / Buyer', 'Buyer / Importer')
    re.compile(r'(?:^|\n|\t)(?:Consignee\s*/\s*(?:Buyer|Importer|Customer)|Buyer\s*/\s*(?:Consignee|Importer)|Importer\s*/\s*(?:Buyer|Consignee))\s*[:\.]?\s+([A-Za-z가-힣\(㈜][^\n\t|]{4,200}?)(?=\s*(?:\t|\||\n|PL\s*No|Invoice\s*No|Description|Notify|Vendor|Seller|Shipper|Port))', re.IGNORECASE),
    # 줄 시작 라벨 + 공백 + 값 (콜론 없는 표 패턴) — 우선순위 최상위
    re.compile(r'(?:^|\n|\t)(?:Buyer|Customer|Consignee|Importer)\s+([A-Za-z가-힣\(㈜][^\n\t|]{4,200}?)(?=\s*(?:\t|\||\n|Invoice\s*No|L/C\s*No|PL\s*No|Description|Notify))', re.IGNORECASE),
    # 라벨 + 콜론 + 같은 줄 (탐욕 방지)
    re.compile(r'(?:Buyer|Customer|Consignee|Importer)\s*[:\.]\s*([^|\n\t]{5,150}?)(?=\s*(?:\t|\||$|PL\s*No|Invoice\s*No|Date|Description|Notify))', re.IGNORECASE),
    # 라벨 뒤 다음 줄
    re.compile(r'(?:Buyer|Customer|Consignee|Importer|수입자|매수인|구매자|수하인)\s*[:\.]?\s*\n\s*([^\n\t|]{5,250}?)(?=\s*(?:\t|\||\n|$))', re.IGNORECASE),
    re.compile(r'(?:Buyer|Customer|Consignee|Importer|수입자|매수인|구매자|수하인)\s*[:\.]?\s*\n\s*([^\n]{5,250})', re.IGNORECASE),
    re.compile(r'(?:Buyer|Customer|Consignee|Importer)\s*[:\.]\s*([^\n]{5,250})', re.IGNORECASE),
    # 1줄 직전 — 마지막 fallback
    re.compile(
        r'([A-Za-z가-힣(㈜][^\n]{3,250})\s*\n\s*(?:Buyer|Customer|Consignee|Importer)(?!\s*\.)',
        re.IGNORECASE,
    ),
    re.compile(r'(?:To|Sold\s*To|Bill\s*To|Messrs)\s*[:\.]\s*([^\n]{3,200})', re.IGNORECASE),
]
HEADER_PATTERNS_REV['seller'] = _SELLER_REV
HEADER_PATTERNS_REV['buyer'] = _BUYER_REV


# 값이면 안 되는 키워드
INVOICE_VALUE_BLACKLIST = {
    'invoice no.', 'invoice number', 'invoice date',
    'po no.', 'order no.', 'purchase order', 'packing list',
    'proforma invoice', 'quotation', 'valid until',
    'seller', 'buyer', 'vendor', 'customer', 'shipper',
    'consignee', 'ship to', 'bill to',
    'port of loading', 'port of discharge', 'port of destination',
    'payment terms', 'delivery date', 'required delivery date',
    'incoterms', 'country of origin', 'currency',
    'total', 'total amount', 'grand total', 'total quotation',
    'gross weight', 'net weight', 'measurement', 'cbm',
    'number of packages', 'total packages', 'marks & numbers',
    'parties', 'goods description', 'packing details',
    'ordered items', 'quoted items',
    'ref', 'ref:',
}

# seller/buyer 값에 추가로 차단할 단어 (주소·연락처만 들어있는 라인 등)
_CONTACT_ONLY_PATTERNS = [
    re.compile(r'^\s*(Tel|Fax|Email|Phone|Contact)\s*[:\.]', re.IGNORECASE),
    re.compile(r'^\s*\d{2,4}[-]?\d{3,4}[-]?\d{4}'),  # 전화번호만
    re.compile(r'^\s*\([\d\s\-]+\)'),               # (966)402-5124 같은
    re.compile(r'^[^\w]{0,3}\s*\d'),                # 숫자로 시작
]


def _is_contact_only(value: str) -> bool:
    """값이 연락처·전화·이메일만 포함하는지 (회사명 없는)."""
    if not value:
        return False
    return any(p.match(value) for p in _CONTACT_ONLY_PATTERNS)


# ────────────────────────────────────────────────────────────────────
# 4/30 — 합성 PDF 양식 보완 (콜론 없는 라벨 + 슬래시 결합 라벨)
# ────────────────────────────────────────────────────────────────────
# OCR이 합성 PDF (reportlab 출력) 처리 시 라벨/값이 한 줄에 압축되거나
# 슬래시 결합 라벨(예: 'CONSIGNEE / BILL TO NAME', 'SELLER / EXPORTER NAME')
# 이 콜론 없이 등장하는 케이스. 기존 HEADER_PATTERNS 가 못 잡는 약점 보완.

SYNTH_PATTERNS = {
    'invoice_no': [
        # 'INVOICE NO. DN-INV-20260420' / 'Invoice No: ABC' (콜론 옵셔널)
        re.compile(r'\bINVOICE\s+NO\.?\s*[:.]?\s*([A-Z][A-Z0-9\-]{3,30})', re.IGNORECASE),
        # 5/6 sc2_4/5 양식: 'INVOICE NO / DATE INV-2023-001 2023-10-09' (결합 라벨)
        re.compile(r'\bINVOICE\s*NO\s*/\s*DATE\s+([A-Z][A-Z0-9\-]{3,30})', re.IGNORECASE),
    ],
    'pl_no': [
        # 'PL No. DN-PL-20260420' / 'PL No: ABC' (콜론 옵셔널)
        re.compile(r'\bPL\s+No\.?\s*[:.]?\s*([A-Z][A-Z0-9\-]{3,30})', re.IGNORECASE),
        re.compile(r'\bP/L\s+No\.?\s*[:.]?\s*([A-Z][A-Z0-9\-]{3,30})', re.IGNORECASE),
        # 5/6 sc2_4/5 양식: 'PL NO / DATE PL-2023-001 2023-10-09' (결합 라벨)
        re.compile(r'\bPL\s*NO\s*/\s*DATE\s+([A-Z][A-Z0-9\-]{3,30})', re.IGNORECASE),
    ],
    'date': [
        # 'DATE 2026-04-20' / 'Date 2026-04-20' / 'Date: 2026-04-12' / '| Date: 2026-04-12'
        re.compile(r'(?:^|\s|\n|\t|\|)(?:DATE|Date)\s*[:\.]?\s+(\d{4}[-./]\d{1,2}[-./]\d{1,2})\b'),
        # 5/6 sc2_4/5: 'PL NO / DATE PL-2023-001 2023-10-09' — 결합 라벨 두 번째 값
        re.compile(r'\bPL\s*NO\s*/\s*DATE\s+\S+\s+(\d{4}[-./]\d{1,2}[-./]\d{1,2})', re.IGNORECASE),
        # 5/6 sc2_4/5 invoice: 'INVOICE NO / DATE INV-2023-001 2023-10-09'
        re.compile(r'\bINVOICE\s*NO\s*/\s*DATE\s+\S+\s+(\d{4}[-./]\d{1,2}[-./]\d{1,2})', re.IGNORECASE),
    ],
    'currency': [
        # 'TOTAL: USD 300000.0' / 'USD 300000.0' (값 직전 통화)
        re.compile(r'\b(USD|EUR|KRW|JPY|GBP|CNY|HKD|SGD)\s+\d'),
        # 'Currency: USD' / 'Currency USD'
        re.compile(r'Currency\s*[:.]?\s+(USD|EUR|KRW|JPY|GBP|CNY|HKD|SGD)\b', re.IGNORECASE),
    ],
    'buyer': [
        # 'CONSIGNEE / BILL TO NAME' — 다음 라벨 직전까지
        re.compile(
            r'CONSIGNEE\s*/\s*BILL\s*TO\s+([A-Z][A-Z0-9\s\.,&\-]{4,80}?)\s+(?=INVOICE\s*NO|VESSEL|DATE|PAYMENT|TOTAL|TERMS\s*OF|$)',
            re.IGNORECASE,
        ),
        # 'BUYER / IMPORTER NAME'
        re.compile(
            r'BUYER\s*/\s*IMPORTER\s+([A-Z][A-Z0-9\s\.,&\-]{4,80}?)\s+(?=Invoice\s*Ref|Transport|Description|SELLER|$)',
            re.IGNORECASE,
        ),
        # 'BILL TO NAME' (CONSIGNEE 없이)
        re.compile(
            r'\bBILL\s+TO\s+([A-Z][A-Z0-9\s\.,&\-]{4,80}?)\s+(?=INVOICE\s*NO|VESSEL|DATE|PAYMENT|$)',
            re.IGNORECASE,
        ),
    ],
    'seller': [
        # 'SELLER / EXPORTER NAME'
        re.compile(
            r'SELLER\s*/\s*EXPORTER\s+([A-Z][A-Z0-9\s\.,&\-]{4,80}?)\s+(?=BUYER|IMPORTER|Invoice\s*Ref|Transport|$)',
            re.IGNORECASE,
        ),
        # 헤더에서 'COMPANY INVOICE' 패턴 (Invoice 헤더 직전 첫 회사명)
        re.compile(
            r'^\s*([A-Z][A-Z0-9\s\.,&\-]{4,80}?)\s+INVOICE\b',
            re.IGNORECASE | re.MULTILINE,
        ),
        # 5/6 sc2_4/5 PL/Invoice 양식: 'EXPORTER {NAME}\t(PL NO|INVOICE NO) / DATE ...'
        re.compile(
            r'\bEXPORTER\s+([A-Za-z][A-Za-z0-9\s\.,&\-]{4,80}?)\s*[\t]\s*(?:PL\s*NO|INVOICE\s*NO)',
            re.IGNORECASE,
        ),
    ],
    'incoterms': [
        # 'TERMS OF SALE FCA BUSAN (INCOTERMS 2020)'
        re.compile(
            r'TERMS\s+OF\s+SALE\s+(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP|DAT)\s+([A-Z][A-Z\s]{2,40}?)\s*\(?',
            re.IGNORECASE,
        ),
    ],
    # 5/6 sc2_4 PL 양식: 'TOTAL\t10 Crates\t10,500 KGS\t12,000 KGS\t60 CBM'
    # 헤더 순서: Net Weight | Gross Weight | Measurement → 행도 동일 순서
    'gross_weight': [
        # TOTAL 행: 두 번째 KGS 값 = gross
        re.compile(
            r'\bTOTAL\b[^\n]*?[\d,\.]+\s*KGS?\s+([\d,\.]+)\s*KGS?\s+[\d,\.]+\s*(?:M3|CBM|CFT)',
            re.IGNORECASE,
        ),
    ],
    'net_weight': [
        # TOTAL 행: 첫 번째 KGS 값 = net
        re.compile(
            r'\bTOTAL\b[^\n]*?\b([\d,\.]+)\s*KGS?\s+[\d,\.]+\s*KGS?\s+[\d,\.]+\s*(?:M3|CBM|CFT)',
            re.IGNORECASE,
        ),
    ],
}


def _clean_synth_value(s: str) -> str:
    if not s:
        return s
    s = s.strip().rstrip(',').rstrip('.').strip()
    # 'COMPANY (' 같은 trailing
    s = re.sub(r'\s*\([^\)]*$', '', s)
    return s


def _extract_synth_keyfields(text: str) -> dict:
    """합성 PDF 양식 보완 추출. 빠진 필드만 채움 — 기존 fields 덮어쓰지 않음.

    호출자가 기존 fields와 merge하여 setdefault 식으로 채움.
    """
    out = {}
    for field_name, pats in SYNTH_PATTERNS.items():
        for pat in pats:
            for m in pat.finditer(text):
                if field_name == 'incoterms':
                    code = m.group(1).upper()
                    place = (m.group(2) or '').strip() if m.lastindex >= 2 else ''
                    val = f'{code} {place}'.strip() if place else code
                    out.setdefault(field_name, {'term': code, 'place': place, 'value': val, 'raw': m.group(0)})
                else:
                    val = _clean_synth_value(m.group(1))
                    if not val or _is_blacklisted(val, field_name):
                        continue
                    out.setdefault(field_name, {'value': val, 'raw': m.group(0)})
                if field_name in out:
                    break
            if field_name in out:
                break
    return out


_NUMERIC_FIELDS_ALLOW_SHORT = {
    'gross_weight', 'net_weight', 'measurement', 'n_packages',
    'total_amount', 'total_quantity', 'quantity',
}


def _is_blacklisted(value: str, field_name: str = '') -> bool:
    if not value:
        return True
    v = value.strip().lower()
    v_clean = re.sub(r'[:\.\-\s]+$', '', v).strip()
    if v_clean in INVOICE_VALUE_BLACKLIST:
        return True
    # 4/30 — 숫자 필드는 짧은 값 허용 ('60' 같은 measurement)
    is_numeric_short = (
        field_name in _NUMERIC_FIELDS_ALLOW_SHORT
        and re.fullmatch(r'[0-9.,]+', v_clean) is not None
    )
    if not is_numeric_short and len(v_clean) < 3:
        return True
    if any(v_clean.startswith(prefix) for prefix in [
        'invoice', 'po ', 'order', 'packing', 'proforma',
        'port of', 'place of', 'payment', 'delivery',
        'seller', 'buyer', 'vendor', 'shipper', 'consignee',
        'total', 'gross', 'net', 'number of', 'marks',
        'country of', 'currency', 'incoterms',
    ]):
        return True
    # seller/buyer 필드에서는 연락처·숫자만 있는 라인 차단
    if field_name in ('seller', 'buyer') and _is_contact_only(value):
        return True
    return False


def _fallback_parties_from_block(text: str) -> tuple[str, str]:
    """
    seller/buyer 직접 매칭 실패 시 휴리스틱.
    'Parties' 헤더 밑 2개 회사 블록을 순서대로 seller/buyer 간주.

    회사명 식별: 영문 대문자 시작 또는 한글 시작 + 최소 4자 이상
    """
    # 'Parties' 헤더 위치
    m = re.search(r'Parties', text, re.IGNORECASE)
    if not m:
        return '', ''
    tail = text[m.end():m.end() + 1500]
    # 줄 단위로 훑어서 회사명 후보 2개 수집
    candidates = []
    for line in tail.split('\n'):
        line = line.strip()
        if not line or len(line) < 4:
            continue
        # 스킵: 섹션 라벨, 국가 포트, 날짜, 이메일, 전화번호 등
        if re.match(r'^(Port|Payment|Delivery|Incoterms|Currency|Country|'
                    r'Parties|Goods|Ordered|Quoted|Items|Packing|Weight|'
                    r'Marks|Total|Ship|Seller|Buyer|Vendor|Customer|'
                    r'Consignee|Shipper)\b', line, re.IGNORECASE):
            continue
        if re.match(r'^(Tel|Fax|Email|Contact)\s*[:\.]', line, re.IGNORECASE):
            continue
        if re.fullmatch(r'[\d\-/.\s()]+', line):  # 숫자·기호만
            continue
        if re.fullmatch(r'\d{4}[-./]\d{1,2}[-./]\d{1,2}', line):
            continue
        # 회사명 후보 (영문 대문자 시작 또는 한글)
        if re.match(r'[A-Z가-힣(㈜]', line) and len(line) >= 5:
            candidates.append(line)
            if len(candidates) >= 2:
                break
    if len(candidates) >= 2:
        return candidates[0], candidates[1]
    elif len(candidates) == 1:
        return candidates[0], ''
    return '', ''


def _extract_header_fields(text: str, patterns_dict=None) -> dict:
    """공통 헤더 필드 추출 + 블랙리스트 필터.

    patterns_dict: 기본 HEADER_PATTERNS_FWD (정방향 우선).
                   PO가 아닌 경우 HEADER_PATTERNS_REV 전달.
    """
    if patterns_dict is None:
        patterns_dict = HEADER_PATTERNS_FWD
    found = {}
    for field_name, patterns in patterns_dict.items():
        for pat in patterns:
            for m in pat.finditer(text):
                # 1) 특수 포맷 필드
                if field_name == 'total_amount':
                    # group1=currency(옵션), group2=value
                    value_str = (m.group(2) if m.lastindex and m.lastindex >= 2
                                 else m.group(1) if m.lastindex else '')
                    if not value_str:
                        continue
                    found[field_name] = {
                        'currency': (m.group(1) or '') if m.lastindex and m.lastindex >= 2 else '',
                        'value': value_str.replace(',', ''),
                        'raw': m.group(0),
                    }
                    break
                elif field_name == 'incoterms':
                    found[field_name] = {
                        'term': m.group(1).upper() if m.group(1) else '',
                        'place': (m.group(2) if m.lastindex and m.lastindex >= 2 and m.group(2) else '').strip(),
                        'raw': m.group(0),
                    }
                    break
                elif field_name in ('gross_weight', 'net_weight',
                                    'measurement', 'n_packages'):
                    v = (m.group(1) or '').replace(',', '').strip()
                    if _is_blacklisted(v, field_name):
                        continue
                    found[field_name] = {
                        'value': v,
                        'unit': m.group(2) if m.lastindex and m.lastindex >= 2 and m.group(2) else '',
                        'raw': m.group(0),
                    }
                    break
                else:
                    raw_value = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    if _is_blacklisted(raw_value, field_name):
                        continue
                    found[field_name] = {
                        'value': raw_value,
                        'raw': m.group(0),
                    }
                    break
            if field_name in found:
                break
    return found


def _extract_items_rough(text: str) -> list[dict]:
    """
    표의 품목 리스트를 대략 추출.
    정확한 테이블 파싱은 Step 4b에서 할 예정이지만, 일단 간단한 휴리스틱.

    패턴: "품명 수량 단가 금액" 형태의 라인 감지.
    """
    items = []
    # 숫자 + 숫자 + 숫자 패턴 (수량·단가·금액)
    # 텍스트 + 공백 + 숫자 + 공백 + 숫자 + 공백 + 숫자
    pat = re.compile(
        r'^([A-Za-z가-힣].{3,60})\s+(\d+(?:\.\d+)?)\s+([0-9,\.]+)\s+([0-9,\.]+)\s*$',
        re.MULTILINE,
    )
    for m in pat.finditer(text):
        description = m.group(1).strip()
        # 헤더 라인 제거 ("Description Qty Unit Price Amount")
        if re.search(r'(description|quantity|unit price|amount|품명|수량|단가|금액)',
                     description, re.IGNORECASE):
            continue
        try:
            qty = float(m.group(2).replace(',', ''))
            unit_price = float(m.group(3).replace(',', ''))
            amount = float(m.group(4).replace(',', ''))
        except ValueError:
            continue
        items.append({
            'description': description,
            'quantity': qty,
            'unit_price': unit_price,
            'amount': amount,
            'raw': m.group(0),
        })
    return items


# ────────────────────────────────────────────────────────────
# 공통 Invoice-like 베이스
# ────────────────────────────────────────────────────────────
class InvoiceLikeBase(BaseParser):
    """CI/PI/PO/PL 공통 로직. 서브클래스가 DOCUMENT_TYPE 오버라이드."""
    DOCUMENT_TYPE = 'Unknown'
    PRIMARY_DOC_NO_FIELD = 'invoice_no'
    ESSENTIAL_FIELDS = ['invoice_no', 'seller', 'buyer']
    # 기본: 역방향 우선 (CI/PI/PL에 적합). PO만 정방향 우선 override.
    LABEL_ORDER = 'reverse'  # 'reverse' | 'forward'

    def _get_patterns(self):
        if self.LABEL_ORDER == 'forward':
            return HEADER_PATTERNS_FWD
        return HEADER_PATTERNS_REV

    def _extract_type_specific(self, text: str, ocr_result: dict,
                                result: ParseResult) -> None:
        fields = _extract_header_fields(text, patterns_dict=self._get_patterns())

        # 4/30 — 합성 PDF 양식 보완 (콜론 없는 라벨 + 슬래시 결합)
        synth = _extract_synth_keyfields(text)
        for k, v in synth.items():
            fields.setdefault(k, v)

        # Fallback: seller/buyer 추출 실패 시 'Parties' 블록에서 휴리스틱
        need_seller = 'seller' not in fields
        need_buyer = 'buyer' not in fields
        if need_seller or need_buyer:
            fb_seller, fb_buyer = _fallback_parties_from_block(text)
            if need_seller and fb_seller:
                fields['seller'] = {'value': fb_seller, 'raw': '[fallback]'}
            if need_buyer and fb_buyer:
                fields['buyer'] = {'value': fb_buyer, 'raw': '[fallback]'}

        items = _extract_items_rough(text)

        result.type_specific['fields'] = fields
        result.type_specific['items'] = items
        result.type_specific['n_items'] = len(items)

        # 평탄 key_fields
        result.type_specific['key_fields'] = {
            name: data.get('value') or data.get('term') or data.get('raw')
            for name, data in fields.items()
        }

        # warnings
        missing = [f for f in self.ESSENTIAL_FIELDS if f not in fields]
        if missing:
            result.warnings.append(f'MISSING_FIELDS:{",".join(missing).upper()}')
        if not items:
            result.warnings.append('NO_ITEMS_DETECTED')

    def _compute_confidence(self, result: ParseResult) -> float:
        fields = result.type_specific.get('fields', {})
        items = result.type_specific.get('items', [])
        n_fields = len(fields)
        # 필드 + 아이템 비례
        base = 0.0
        if n_fields >= 6:
            base += 0.5
        elif n_fields >= 3:
            base += 0.3
        elif n_fields >= 1:
            base += 0.15
        if items:
            base += min(0.3, len(items) * 0.05)
        cf = result.common_fields
        if cf.get('incoterms'):
            base += 0.1
        if cf.get('amounts'):
            base += 0.1
        return min(base, 1.0)


# ────────────────────────────────────────────────────────────
# 4개 서류 타입별 래퍼
# ────────────────────────────────────────────────────────────
class CommercialInvoiceParser(InvoiceLikeBase):
    DOCUMENT_TYPE = 'CommercialInvoice'
    PRIMARY_DOC_NO_FIELD = 'invoice_no'
    ESSENTIAL_FIELDS = ['invoice_no', 'date', 'seller', 'buyer']


class ProformaInvoiceParser(InvoiceLikeBase):
    DOCUMENT_TYPE = 'ProformaInvoice'
    PRIMARY_DOC_NO_FIELD = 'invoice_no'  # or quotation_no
    ESSENTIAL_FIELDS = ['seller', 'buyer']


class PurchaseOrderParser(InvoiceLikeBase):
    DOCUMENT_TYPE = 'PurchaseOrder'
    PRIMARY_DOC_NO_FIELD = 'order_no'
    ESSENTIAL_FIELDS = ['order_no', 'seller', 'buyer']
    LABEL_ORDER = 'forward'  # PO만 정방향 우선 (Buyer/Vendor 섹션형 렌더)


class PackingListParser(InvoiceLikeBase):
    DOCUMENT_TYPE = 'PackingList'
    PRIMARY_DOC_NO_FIELD = 'packing_no'
    ESSENTIAL_FIELDS = ['seller', 'buyer']

    def _extract_type_specific(self, text: str, ocr_result: dict,
                                result: ParseResult) -> None:
        super()._extract_type_specific(text, ocr_result, result)
        # 패킹 리스트는 무게·치수가 특히 중요
        fields = result.type_specific['fields']
        has_weight = 'gross_weight' in fields or 'net_weight' in fields
        has_measurement = 'measurement' in fields
        if not has_weight:
            result.warnings.append('NO_WEIGHT_INFO')
        if not has_measurement:
            result.warnings.append('NO_MEASUREMENT')
