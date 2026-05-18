"""
LetterOfCredit 파서 — 신용장.

두 가지 포맷 지원:
  1. SWIFT MT700 정형 포맷 (:20:, :31C:, :32B: 등 필드 코드)
  2. 서술형 LC 양식 (은행별 자유 양식)

SWIFT MT700 주요 필드:
  :20:    Documentary Credit Number
  :23:    Reference to Pre-Advice
  :27:    Sequence of Total
  :31C:   Date of Issue
  :31D:   Date and Place of Expiry
  :32B:   Currency Code, Amount
  :39A:   Percentage Credit Amount Tolerance
  :40A:   Form of Documentary Credit
  :40E:   Applicable Rules
  :41A:   Available With ... By ...
  :42C:   Drafts at
  :42A:   Drawee
  :43P:   Partial Shipments
  :43T:   Transhipment
  :44A:   Place of Taking in Charge
  :44E:   Port of Loading / Airport of Departure
  :44F:   Port of Discharge / Airport of Destination
  :44B:   Place of Final Destination / For Transportation
  :44C:   Latest Date of Shipment
  :44D:   Shipment Period
  :45A:   Description of Goods and/or Services
  :46A:   Documents Required
  :47A:   Additional Conditions
  :48:    Period for Presentation
  :49:    Confirmation Instructions
  :50:    Applicant (수입자/개설의뢰인)
  :51A:   Applicant Bank
  :52A:   Issuing Bank (개설은행)
  :53A:   Reimbursing Bank
  :56A:   Advising Through Bank
  :57A:   'Advise Through' Bank
  :59:    Beneficiary (수출자/수익자)
  :71B:   Charges
  :72:    Sender to Receiver Information
  :78:    Instructions to Paying/Accepting/Negotiating Bank
"""
from __future__ import annotations
import re
from .base import BaseParser, ParseResult


# ────────────────────────────────────────────────────────────
# SWIFT 필드 정규식
# ────────────────────────────────────────────────────────────
# :XX: 또는 :XXA: 형식의 필드 코드
# 변형 양식: ":20: LC NUMBER: VALUE" 처럼 코드 뒤에 라벨이 다시 명시되고 값이 따라오는 케이스도 지원
# (정영석 4/27 합성 데이터 패턴). 라벨 부분은 optional 캡처.
SWIFT_FIELD_PAT = re.compile(
    r':(?P<code>\d{2}[A-Z]?):\s*'
    r'(?:(?P<label>[A-Za-z][A-Za-z\s/0-9\.]{2,40}?):\s+)?'  # 4/30 — mixed case 허용
                                                              # ('L/C No' 같은 normalize 결과 매칭)
    r'(?P<value>'
    r'(?:[^\n:]+?)'                                       # 한 줄 양식: 콜론 또는 줄바꿈 직전까지
    r'(?:\n(?!\s*:\d{2}[A-Z]?:)[^\n]*)*'                 # 멀티라인 (\s* 추가 4/30 — ' :NN:' 케이스 인식)
    r')'
    r'(?=\s*:\d{2}[A-Z]?:|\s*$)',                        # 다음 SWIFT 코드 또는 끝 lookahead
    re.MULTILINE,
)


# SWIFT 필드 코드 → 의미
SWIFT_FIELD_MEANING = {
    '20': 'documentary_credit_number',
    '23': 'reference_to_pre_advice',
    '27': 'sequence_of_total',
    '31C': 'date_of_issue',
    '31D': 'date_and_place_of_expiry',
    '32B': 'currency_amount',
    '39A': 'credit_amount_tolerance',
    '40A': 'form_of_credit',
    '40E': 'applicable_rules',
    '41A': 'available_with_by',
    '41D': 'available_with_by',
    '42A': 'drawee',
    '42C': 'drafts_at',
    '43P': 'partial_shipments',
    '43T': 'transhipment',
    '44A': 'place_of_taking_charge',
    '44B': 'place_of_final_destination',
    '44C': 'latest_date_of_shipment',
    '44D': 'shipment_period',
    '44E': 'port_of_loading',
    '44F': 'port_of_discharge',
    '45A': 'description_of_goods',
    '46A': 'documents_required',
    '47A': 'additional_conditions',
    '48': 'period_for_presentation',
    '49': 'confirmation_instructions',
    '50': 'applicant',
    '51A': 'applicant_bank',
    '52A': 'issuing_bank',
    '53A': 'reimbursing_bank',
    '56A': 'advising_through_bank',
    '57A': 'advise_through_bank',
    '59': 'beneficiary',
    '71B': 'charges',
    '72': 'sender_to_receiver_info',
    '78': 'instructions_to_bank',
}


# ────────────────────────────────────────────────────────────
# 서술형 LC 양식 정규식 (SWIFT 아닌 경우)
# ────────────────────────────────────────────────────────────
# OCR 표 구조 특성: 값 먼저, 라벨 뒤에 나옴 → **역방향 패턴 먼저** 시도
# 이후 fallback으로 정방향 시도.
NARRATIVE_PATTERNS = {
    'lc_number': [
        # 역방향: 값이 라벨 앞
        re.compile(r'([A-Z]\d{2,3}LC\d{4,}|[A-Z]{1,3}\d{5,}[A-Z0-9\-/]{0,10})\s*\n\s*(?:Documentary\s*Credit|L/?C|Credit)\s*(?:No\.?|Number)', re.IGNORECASE),
        # 정방향
        re.compile(r'(?:Documentary\s*Credit|L/?C|Credit)\s*(?:No\.?|Number)\s*[:\.]?\s*([A-Z]\d{2,3}LC\d{4,}|[A-Z0-9\-/]{5,30})', re.IGNORECASE),
    ],
    'date_of_issue': [
        re.compile(r'(\d{4}[-./]\d{1,2}[-./]\d{1,2})\s*\n\s*(?:Date\s*of\s*Issue|Issue\s*Date)', re.IGNORECASE),
        re.compile(r'(?:Date\s*of\s*Issue|Issue\s*Date)\s*[:\.]?\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})', re.IGNORECASE),
    ],
    'expiry_date': [
        re.compile(r'(\d{4}[-./]\d{1,2}[-./]\d{1,2})\s*\n\s*(?:Date\s*of\s*Expiry|Expiry)', re.IGNORECASE),
        re.compile(r'(?:Date\s*of\s*Expiry|Expiry\s*Date|Valid\s*until)\s*[:\.]?\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})', re.IGNORECASE),
        # 4/30 — 양식 B (ADVICE) '31D: EXPIRY 2026-05-10 IN KOREA' (콜론 없는 SWIFT 코드)
        re.compile(r'\b31D\s*[:\.]?\s*(?:EXPIRY|DATE\s*AND\s*PLACE\s*OF\s*EXPIRY)?\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})', re.IGNORECASE),
    ],
    'amount': [
        # 역방향
        re.compile(r'([A-Z]{3})\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.\d{1,2})?)\s*\n\s*Amount', re.IGNORECASE),
        re.compile(r'(?:Amount|Sum|Total)\s*[:\.]?\s*([A-Z]{3})\s*([0-9,\.]+)', re.IGNORECASE),
        re.compile(r'([A-Z]{3})\s+([0-9]{1,3}(?:,[0-9]{3})*(?:\.\d{1,2})?)\s*(?:only|ONLY)', re.IGNORECASE),
        # SWIFT 변형 — '32B: CURR/AMT' 같은 라벨 + 다음 줄 USD 100000
        re.compile(r'(?:CURRENCY/AMOUNT|CURR(?:ENCY)?\s*/?\s*AMT|32B)\s*[:\.]?\s*\n?\s*([A-Z]{3})\s+([0-9,\.]+)', re.IGNORECASE),
    ],
    'applicant': [
        # 역방향: "회사명 주소\nApplicant"
        re.compile(r'([^\n]{5,200})\s*\n\s*Applicant(?!\s*Bank)', re.IGNORECASE),
        # 정방향
        re.compile(r'Applicant\s*[:\.]?\s*\n\s*([^\n]{5,200})', re.IGNORECASE),
        re.compile(r'Applicant\s*[:\.]\s*([^\n]{5,200})', re.IGNORECASE),
        re.compile(r'(?:개설의뢰인|수입자)\s*[:\.]?\s*([^\n]{5,150})'),
    ],
    'beneficiary': [
        re.compile(r'([^\n]{5,200})\s*\n\s*Beneficiary', re.IGNORECASE),
        re.compile(r'Beneficiary\s*[:\.]?\s*\n\s*([^\n]{5,200})', re.IGNORECASE),
        re.compile(r'Beneficiary\s*[:\.]\s*([^\n]{5,200})', re.IGNORECASE),
        re.compile(r'(?:수익자|수출자)\s*[:\.]?\s*([^\n]{5,150})'),
    ],
    'issuing_bank': [
        re.compile(r'([^\n]{3,150})\s*\n\s*Issuing\s*Bank', re.IGNORECASE),
        re.compile(r'Issuing\s*Bank\s*[:\.]?\s*\n\s*([^\n]{3,150})', re.IGNORECASE),
        re.compile(r'Issuing\s*Bank\s*[:\.]\s*([^\n]{3,150})', re.IGNORECASE),
        re.compile(r'(?:개설은행)\s*[:\.]?\s*([^\n]{3,100})'),
    ],
    'advising_bank': [
        re.compile(r'([^\n]{3,150})\s*\n\s*Advising\s*Bank', re.IGNORECASE),
        re.compile(r'Advising\s*Bank\s*[:\.]?\s*\n\s*([^\n]{3,150})', re.IGNORECASE),
        re.compile(r'Advising\s*Bank\s*[:\.]\s*([^\n]{3,150})', re.IGNORECASE),
    ],
    'port_of_loading': [
        re.compile(r'([^\n]{3,80})\s*\n\s*Port\s*of\s*Loading', re.IGNORECASE),
        re.compile(r'Port\s*of\s*Loading\s*[:\.]?\s*([^\n]{3,80})', re.IGNORECASE),
        re.compile(r'(?:선적항)\s*[:\.]?\s*([^\n]{3,80})'),
    ],
    'port_of_discharge': [
        re.compile(r'([^\n]{3,80})\s*\n\s*Port\s*of\s*Discharge', re.IGNORECASE),
        re.compile(r'Port\s*of\s*Discharge\s*[:\.]?\s*([^\n]{3,80})', re.IGNORECASE),
        re.compile(r'(?:도착항|양륙항)\s*[:\.]?\s*([^\n]{3,80})'),
    ],
    'latest_shipment_date': [
        re.compile(r'(\d{4}[-./]\d{1,2}[-./]\d{1,2})\s*\n\s*Latest\s*(?:Date\s*of\s*)?Shipment', re.IGNORECASE),
        re.compile(r'Latest\s*(?:Date\s*of\s*)?Shipment\s*[:\.]?\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})', re.IGNORECASE),
    ],
    'expiry_place': [
        re.compile(r'([^\n]{3,80})\s*\n\s*Place\s*of\s*Expiry', re.IGNORECASE),
        re.compile(r'Place\s*of\s*Expiry\s*[:\.]?\s*([^\n]{3,80})', re.IGNORECASE),
    ],
    'incoterm': [
        re.compile(r'((?:EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b\s*[A-Za-z가-힣]+)\s*\n\s*Incoterms?', re.IGNORECASE),
        re.compile(r'Incoterms?\s*[:\.]?\s*(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b\s*([A-Za-z가-힣]+)?', re.IGNORECASE),
    ],
    'partial_shipments': [
        re.compile(r'\b(ALLOWED|NOT\s*ALLOWED|PROHIBITED)\s*\n\s*Partial\s*Shipments?', re.IGNORECASE),
        re.compile(r'Partial\s*Shipments?\s*[:\.]?\s*(ALLOWED|NOT\s*ALLOWED|PROHIBITED)', re.IGNORECASE),
    ],
    'transhipment': [
        re.compile(r'\b(ALLOWED|NOT\s*ALLOWED|PROHIBITED)\s*\n\s*Trans(?:h|s)ipment', re.IGNORECASE),
        re.compile(r'Trans(?:h|s)ipment\s*[:\.]?\s*(ALLOWED|NOT\s*ALLOWED|PROHIBITED)', re.IGNORECASE),
    ],
}


def _extract_swift_fields(text: str) -> dict:
    """SWIFT MT700 필드 형식 추출. 없으면 빈 dict."""
    fields = {}
    for m in SWIFT_FIELD_PAT.finditer(text):
        code = m.group('code')
        value = m.group('value').strip()
        name = SWIFT_FIELD_MEANING.get(code, f'field_{code}')
        fields[name] = {
            'code': code,
            'value': value,
        }
    return fields


# 값이면 안 되는 키워드 (라벨·섹션 헤더·섹션 구분자 등)
# 역방향 매칭 시 이런 게 잡히면 스킵
LC_VALUE_BLACKLIST = {
    'port of loading', 'port of discharge', 'place of expiry',
    'date of issue', 'issue date', 'date of expiry', 'expiry date',
    'latest date of shipment', 'latest shipment', 'documentary credit no.',
    'applicant', 'beneficiary', 'issuing bank', 'advising bank',
    'confirming bank', 'reimbursing bank', 'drawee',
    'amount', 'currency', 'form of credit', 'parties',
    'partial shipments', 'transhipment', 'incoterms',
    'shipment terms', 'documents required', 'additional conditions',
    'charges', 'drafts at', 'period for presentation',
    'confirmation instructions', 'credit amount and payment',
    'description of goods', 'available with', 'available by',
    'ref', 'ref:', 'swift',
}


def _is_blacklisted(value: str, blacklist: set) -> bool:
    """값이 라벨처럼 보이면 True."""
    if not value:
        return True
    v = value.strip().lower()
    v_clean = re.sub(r'[:\.\-\s]+$', '', v).strip()
    if v_clean in blacklist:
        return True
    # 값이 너무 짧거나 라벨로 시작하는 경우
    if len(v_clean) < 3:
        return True
    # 특정 단어 시작
    if any(v_clean.startswith(prefix) for prefix in [
        'port of', 'place of', 'date of', 'issue ', 'applicant',
        'beneficiary', 'issuing bank', 'advising bank', 'amount',
    ]):
        return True
    return False


def _extract_narrative(text: str) -> dict:
    """서술형 LC 양식에서 필드 추출. 값 블랙리스트 필터 적용."""
    found = {}
    for field_name, patterns in NARRATIVE_PATTERNS.items():
        for pat in patterns:
            for m in pat.finditer(text):
                # amount는 (currency, value) 그룹
                if field_name == 'amount' and m.lastindex and m.lastindex >= 2:
                    found[field_name] = {
                        'currency': m.group(1).upper(),
                        'value': m.group(2).replace(',', ''),
                        'raw': m.group(0),
                    }
                    break
                else:
                    raw_value = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    # 블랙리스트 필터
                    if _is_blacklisted(raw_value, LC_VALUE_BLACKLIST):
                        continue
                    found[field_name] = {
                        'value': raw_value,
                        'raw': m.group(0),
                    }
                    break
            if field_name in found:
                break
    return found


def _detect_format(text: str) -> str:
    """SWIFT 포맷인지 서술형인지 판별."""
    # :XX: 패턴이 3개 이상 있으면 SWIFT
    swift_count = len(SWIFT_FIELD_PAT.findall(text))
    if swift_count >= 3:
        return 'swift_mt700'
    return 'narrative'


# ────────────────────────────────────────────────────────────
class LetterOfCreditParser(BaseParser):
    """신용장 파서."""
    DOCUMENT_TYPE = 'LetterOfCredit'

    def _extract_type_specific(self, text: str, ocr_result: dict,
                                result: ParseResult) -> None:
        # 4/30 — LC SWIFT escape 멀티라인 정규화 (DEUTSCHE 양식 등)
        # 'APPLICANT:\\nNAME\\n' 두 글자 escape → 실제 newline
        from .postprocess_ocr import normalize_swift_escaped_newline
        text = normalize_swift_escaped_newline(text)

        fmt = _detect_format(text)
        result.type_specific['format'] = fmt

        if fmt == 'swift_mt700':
            fields = _extract_swift_fields(text)
            result.type_specific['swift_fields'] = fields
            # 핵심 필드를 표준화된 평탄 구조로도 제공
            result.type_specific['key_fields'] = {
                name: data['value']
                for name, data in fields.items()
            }
        else:
            narrative = _extract_narrative(text)
            result.type_specific['narrative_fields'] = narrative
            result.type_specific['key_fields'] = {
                name: data.get('value') or data.get('raw')
                for name, data in narrative.items()
            }
            # narrative amount 매칭 결과에 currency 가 부속 dict 으로 들어 있어
            # 평탄화 시 분실 — 별도 키로 노출
            amt = narrative.get('amount') or {}
            cur = amt.get('currency')
            if cur and 'currency' not in result.type_specific['key_fields']:
                result.type_specific['key_fields']['currency'] = cur

        # currency_amount 후처리 — 'EUR 240000.0' → currency + amount 분리
        kf = result.type_specific.get('key_fields', {})
        ca = kf.get('currency_amount') or ''
        if ca and ('currency' not in kf or 'amount' not in kf):
            m = re.match(r'\s*([A-Z]{3})\s*([0-9][0-9,\.]*)\s*$', str(ca).strip())
            if m:
                if 'currency' not in kf:
                    kf['currency'] = m.group(1)
                if 'amount' not in kf:
                    kf['amount'] = m.group(2)

        # warnings
        essential = ['lc_number', 'applicant', 'beneficiary',
                     'amount', 'currency_amount']
        key = result.type_specific.get('key_fields', {})
        # swift에서는 다른 이름
        has_lc_no = any(k in key for k in ['lc_number', 'documentary_credit_number'])
        has_applicant = 'applicant' in key
        has_beneficiary = 'beneficiary' in key
        has_amount = any(k in key for k in ['amount', 'currency_amount'])

        missing = []
        if not has_lc_no:
            missing.append('LC_NUMBER')
        if not has_applicant:
            missing.append('APPLICANT')
        if not has_beneficiary:
            missing.append('BENEFICIARY')
        if not has_amount:
            missing.append('AMOUNT')
        if missing:
            result.warnings.append(f'MISSING_FIELDS:{",".join(missing)}')

    def _compute_confidence(self, result: ParseResult) -> float:
        # LC는 필드 기반이라 필드 수 비중이 큼
        key_fields = result.type_specific.get('key_fields', {})
        n = len(key_fields)
        if n >= 10:
            base = 0.8
        elif n >= 5:
            base = 0.6
        elif n >= 3:
            base = 0.4
        elif n >= 1:
            base = 0.2
        else:
            base = 0.0
        # 공통 필드 보너스
        cf = result.common_fields
        if cf.get('dates'): base += 0.05
        if cf.get('amounts'): base += 0.05
        if cf.get('parties'): base += 0.05
        return min(base, 1.0)
