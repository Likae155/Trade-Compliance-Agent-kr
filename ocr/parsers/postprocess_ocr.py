"""4/30 — OCR 후처리 컨텍스트 사전 매칭.

PaddleOCR이 0/O, 1/I/l, 5/S, 8/B 같은 유사 문자를 혼동했을 때 무역서류
필드 컨텍스트로 자동 보정.

원칙:
1. 숫자 전용 필드(HS code/amount/qty/weight)는 토큰 단위로 숫자화 강제
2. 알파벳 우세 필드(company/addr)는 보수적 — 잘못 보정하면 더 큰 손실
3. 정규식 검증 통과한 결과만 채택, 실패 시 원본 유지
4. 미지의 필드는 no-op (회귀 위험 회피)

사용:
    from parsers import postprocess_ocr as pp
    fixed = pp.fix_key_fields(parsed['key_fields'])
"""
from __future__ import annotations

import re
from typing import Any, Dict


# ────────────────────────────────────────────────────────────────────────
# 컨텍스트별 OCR 혼동 사전
# ────────────────────────────────────────────────────────────────────────

# 숫자 컨텍스트 — 알파벳/기호 → 숫자
NUMERIC_CONFUSIONS = {
    'O': '0', 'o': '0', 'D': '0',
    'I': '1', 'l': '1', '|': '1', 'i': '1',
    'Z': '2', 'z': '2',
    'S': '5', 's': '5',
    'G': '6',
    'T': '7',
    'B': '8',
    'g': '9', 'q': '9',
}

# 알파벳 컨텍스트 — 숫자 → 알파벳 (보수적, 매우 제한적)
# 회사명에 진짜 숫자 있을 수 있어 위험. 토큰 단위 + 인접 알파벳 확인 필요.
ALPHA_IN_WORD_CONFUSIONS = {
    '0': 'O',  # 'C0SCO' → 'COSCO'
}


# ────────────────────────────────────────────────────────────────────────
# 필드명 분류 — 우선순위 순서 (specific 먼저)
# ────────────────────────────────────────────────────────────────────────

# 숫자 강제 필드 (대부분 100% 숫자만 등장)
PURE_NUMERIC_FIELDS = {
    'hs_code', 'hs', 'hscode',
    'phone', 'fax', 'tel',
    'gross_weight', 'net_weight',
    'total_gross_weight', 'total_net_weight',
    'measurement', 'total_measurement',
    'quantity', 'qty', 'total_quantity',
    'reg_no', 'tax_id',  # 사업자등록번호류 (대부분 숫자)
}

# 통화+숫자 필드 (currency 코드 + 금액)
AMOUNT_FIELDS = {
    'amount', 'total_amount', 'price', 'unit_price', 'total',
    'invoice_amount', 'lc_amount', 'contract_amount',
}

# 날짜 필드 (YYYY-MM-DD / YYYY/MM/DD / DD-MM-YYYY)
DATE_FIELDS = {
    'date', 'issue_date', 'expiry_date', 'shipment_date',
    'shipment_deadline', 'latest_shipment_date',
    'issuance_date', 'effective_date', 'maturity_date',
    'contract_date', 'invoice_date', 'bl_date', 'lc_date',
    'departure_date', 'arrival_date',
}

# 알파벳 우세 필드 (사람/회사/장소 — 보수 보정만)
ALPHA_FIELDS = {
    'name', 'seller', 'buyer', 'exporter', 'importer',
    'shipper', 'consignee', 'consignor', 'notify_party',
    'beneficiary', 'applicant',
    'company', 'company_name',
    'addr', 'address',
    'country', 'country_of_origin',
    'port_of_loading', 'port_of_discharge',
    'place_of_receipt', 'place_of_delivery',
    'person_name', 'contact_person', 'contact',
}

# 혼합 필드 (영숫자 식별자) — 보정 안 함 (영문자도 진짜일 수 있음)
MIXED_FIELDS = {
    'invoice_no', 'lc_no', 'lc_number', 'contract_no', 'contract_number',
    'bl_no', 'bl_number', 'awb_no', 'awb_number', 'pl_no',
    'voyage_no', 'vessel_name', 'flight_no',
    'reference_no', 'order_no', 'po_no',
    'marks_and_nos', 'marks_no',
    'incoterms',  # 'FOB Busan' 류
}


# ────────────────────────────────────────────────────────────────────────
# 정규식 검증 패턴
# ────────────────────────────────────────────────────────────────────────

HS_CODE_PAT = re.compile(r'^\d{4}(?:[\.\-]?\d{2}){0,3}$')
AMOUNT_PAT = re.compile(r'^([A-Z]{3})?\s*([\d,]+(?:\.\d{1,4})?)\s*$')
DATE_PAT = re.compile(r'^(\d{2,4})[-/.](\d{1,2})[-/.](\d{1,4})$')
QUANTITY_PAT = re.compile(r'^(\d+(?:[\.\,]\d+)?)\s*([A-Za-z]{1,8})?$')
PHONE_PAT = re.compile(r'^[\+\d\s\-\(\)]+$')
PURE_NUMBER_PAT = re.compile(r'^[\d,\.\s\-]+$')


# ────────────────────────────────────────────────────────────────────────
# 보정 함수
# ────────────────────────────────────────────────────────────────────────

def _force_numeric(s: str) -> str:
    """문자열의 모든 OCR 혼동 글자를 숫자로 강제 치환."""
    out = []
    for ch in s:
        out.append(NUMERIC_CONFUSIONS.get(ch, ch))
    return ''.join(out)


def fix_pure_numeric(value: str) -> str:
    """숫자 전용 필드. 모든 알파벳/기호 → 숫자."""
    if not value or not isinstance(value, str):
        return value
    fixed = _force_numeric(value)
    # 검증: 숫자/구분자만 남았으면 채택, 아니면 원본
    if PURE_NUMBER_PAT.match(fixed):
        return fixed
    return value


def fix_hs_code(value: str) -> str:
    """HS code (4-10자리 숫자, 점/대시 구분 가능)."""
    if not value or not isinstance(value, str):
        return value
    fixed = _force_numeric(value.strip())
    if HS_CODE_PAT.match(fixed):
        return fixed
    return value


def fix_amount(value: str) -> str:
    """금액 — '[ABC] 123,456.00' 형태. 통화 코드는 알파벳 보존, 숫자부만 보정."""
    if not value or not isinstance(value, str):
        return value
    s = value.strip()

    # 패턴: 통화 + 공백 + 숫자
    m = re.match(r'^([A-Z]{3})\s+(.+)$', s)
    if m:
        curr = m.group(1)
        nums = _force_numeric(m.group(2).strip())
        if AMOUNT_PAT.match(curr + ' ' + nums):
            return f'{curr} {nums}'
        return value

    # 패턴: 통화 코드 없이 숫자만
    fixed = _force_numeric(s)
    if AMOUNT_PAT.match(fixed):
        return fixed
    return value


def fix_date(value: str) -> str:
    """날짜 — 숫자 강제 + 형식 검증."""
    if not value or not isinstance(value, str):
        return value
    fixed = _force_numeric(value.strip())
    m = DATE_PAT.match(fixed)
    if m:
        # 추가 검증: 월/일 범위
        try:
            y, mo, d = m.group(1), m.group(2), m.group(3)
            # YYYY-MM-DD 우선, DD-MM-YYYY 도 허용
            if len(y) == 4 and 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
                return fixed
            if len(d) == 4 and 1 <= int(mo) <= 12 and 1 <= int(y) <= 31:
                return fixed
        except ValueError:
            return value
    return value


def fix_quantity(value: str) -> str:
    """수량 — '500 PCS' / '12,000 KG' 형태. 숫자부만 보정, 단위 보존."""
    if not value or not isinstance(value, str):
        return value
    s = value.strip()

    # 숫자 + 공백 + 단위
    m = re.match(r'^(.+?)\s+([A-Za-z가-힣]{1,8})$', s)
    if m:
        nums = _force_numeric(m.group(1).strip())
        unit = m.group(2)
        if QUANTITY_PAT.match(nums):
            return f'{nums} {unit}'
        return value

    # 단위 없이 숫자만
    fixed = _force_numeric(s)
    if QUANTITY_PAT.match(fixed):
        return fixed
    return value


def fix_alpha_word(value: str) -> str:
    """알파벳 우세 — 단어 안에 들어간 숫자만 보정 (보수적).

    'C0SCO' → 'COSCO' 같은 케이스만. 'Suite 100' 같은 진짜 숫자는 건드리지 않음.
    원칙: 단어가 알파벳 우세이고 단어 안 숫자가 알파벳 사이에 끼어 있으면 보정.
    """
    if not value or not isinstance(value, str):
        return value

    def fix_token(tok: str) -> str:
        # 토큰이 100% 숫자이거나 100% 비알파벳이면 건드리지 않음
        if not re.search(r'[A-Za-z가-힣]', tok):
            return tok
        # 알파벳 비중이 높은 토큰만 보정
        n_alpha = sum(1 for c in tok if c.isalpha())
        n_digit = sum(1 for c in tok if c.isdigit())
        if n_alpha == 0 or n_digit == 0:
            return tok
        # 알파벳이 숫자보다 많을 때만 (알파벳 우세 토큰)
        if n_alpha <= n_digit:
            return tok
        out = []
        for i, ch in enumerate(tok):
            if ch in ALPHA_IN_WORD_CONFUSIONS:
                # 좌/우에 알파벳이 있어야 변환
                left = tok[i - 1] if i > 0 else ''
                right = tok[i + 1] if i + 1 < len(tok) else ''
                if left.isalpha() or right.isalpha():
                    out.append(ALPHA_IN_WORD_CONFUSIONS[ch])
                    continue
            out.append(ch)
        return ''.join(out)

    return ' '.join(fix_token(tok) for tok in value.split(' '))


# ────────────────────────────────────────────────────────────────────────
# 디스패처
# ────────────────────────────────────────────────────────────────────────

def _classify_field(field_name: str) -> str:
    """필드명 → 카테고리. 'numeric' / 'amount' / 'date' / 'quantity' / 'alpha' / 'mixed' / 'unknown'"""
    fname = field_name.lower().strip()

    # 1) 정확 매칭 우선
    if fname in PURE_NUMERIC_FIELDS:
        if 'weight' in fname or 'measurement' in fname or 'quantity' in fname or 'qty' in fname:
            return 'quantity'
        return 'numeric'
    if fname in AMOUNT_FIELDS:
        return 'amount'
    if fname in DATE_FIELDS:
        return 'date'
    if fname in ALPHA_FIELDS:
        return 'alpha'
    if fname in MIXED_FIELDS:
        return 'mixed'

    # 2) 부분 매칭 (suffix/contains)
    if 'hs_code' in fname or fname.endswith('_hs') or fname == 'hs':
        return 'numeric'  # HS code → 순수 숫자
    if 'phone' in fname or 'fax' in fname or 'tel' in fname:
        return 'numeric'
    if 'date' in fname or 'deadline' in fname or 'expiry' in fname:
        return 'date'
    if 'amount' in fname or 'price' in fname or fname == 'total':
        return 'amount'
    if 'qty' in fname or 'quantity' in fname or 'weight' in fname or 'measurement' in fname:
        return 'quantity'
    if 'name' in fname or 'addr' in fname or 'company' in fname:
        return 'alpha'
    if any(k in fname for k in ('port', 'country', 'place', 'consign', 'shipper', 'beneficiary', 'applicant')):
        return 'alpha'
    if any(k in fname for k in ('_no', '_number', 'voyage', 'vessel', 'flight', 'marks', 'incoterms')):
        return 'mixed'

    return 'unknown'


def fix_field(field_name: str, value: Any) -> Any:
    """필드 컨텍스트에 맞춰 보정."""
    if not isinstance(value, str) or not value:
        return value

    cat = _classify_field(field_name)

    if cat == 'numeric':
        return fix_pure_numeric(value)
    if cat == 'amount':
        return fix_amount(value)
    if cat == 'date':
        return fix_date(value)
    if cat == 'quantity':
        return fix_quantity(value)
    if cat == 'alpha':
        return fix_alpha_word(value)
    # mixed / unknown — no-op (회귀 위험 회피)
    return value


def fix_key_fields(key_fields: Dict[str, Any]) -> Dict[str, Any]:
    """전체 key_fields dict 보정. 재귀 처리."""
    if not isinstance(key_fields, dict):
        return key_fields

    out: Dict[str, Any] = {}
    for k, v in key_fields.items():
        if isinstance(v, str):
            out[k] = fix_field(k, v)
        elif isinstance(v, dict):
            out[k] = fix_key_fields(v)
        elif isinstance(v, list):
            fixed_list = []
            for item in v:
                if isinstance(item, dict):
                    fixed_list.append(fix_key_fields(item))
                elif isinstance(item, str):
                    fixed_list.append(fix_field(k, item))
                else:
                    fixed_list.append(item)
            out[k] = fixed_list
        else:
            out[k] = v
    return out


# ────────────────────────────────────────────────────────────────────────
# Full text 정규화 — 파서 입력 직전 단계 라벨 정규화
# ────────────────────────────────────────────────────────────────────────

# 라벨 키워드 — 뒤에 오는 N[oO0] 을 'No' 로 통일.
# 인접 word boundary (\b) 로 감싸 회사명 같은 비라벨 컨텍스트는 건드리지 않음.
_NO_LABEL_KEYWORDS = (
    r'B\s*/\s*L',           # B/L
    r'L\s*/\s*C',           # L/C
    r'LC',                  # LC
    r'AWB',                 # AWB
    r'REF',                 # REF / REE (OCR 손상)
    r'REE',
    r'Invoice',
    r'Inv\.?',
    r'Contract',
    r'Con\.?',
    r'P\s*/\s*L',           # P/L
    r'PL',
    r'P\s*/\s*O',           # P/O
    r'PO',
    r'Voyage',
    r'Voy\.?',
    r'Order',
    r'Customer',
    r'Cust\.?',
    r'Cert\.?',
    r'License',
    r'License?',
    r'Permit',
    r'Tax',
    r'Reg(?:istration|\.)?',
)

_NO_LABEL_PAT = re.compile(
    r'\b(' + '|'.join(_NO_LABEL_KEYWORDS) + r')\s*N[oO0](?=[\s:.\-,]|$)',
    re.IGNORECASE
)


def remove_repeated_patterns(text: str) -> str:
    """동일한 줄이 5회 이상 반복될 때만 제거."""
    # 한 줄(줄바꿈 포함)이 5회 이상 반복되면 하나만 남김
    return re.sub(r'(^.*\n)(\1){4,}', r'\1', text, flags=re.M)

def normalize_full_text(text: str) -> str:
    """파서 입력 직전 OCR 텍스트 라벨 정규화."""
    if not text:
        return text
    
    # [수정] 의미 있는 정보 손실 방지를 위해 반복 줄 제거 로직 삭제
    
    def _repl(m):
        return f'{m.group(1)} No'

    return _NO_LABEL_PAT.sub(_repl, text)


def normalize_swift_escaped_newline(text: str) -> str:
    """LC SWIFT 멀티라인 escape 정규화.

    합성 LC PDF에서 ':50: APPLICANT:\\\\nNAME\\\\n :59:' 같이 backslash-n 두 글자로
    escape된 멀티라인을 실제 newline으로 변환. lc.py 내부에서만 호출.
    """
    if not text or '\\n' not in text:
        return text
    return text.replace('\\n', '\n')


def normalize_ocr_result(ocr_result: Dict[str, Any]) -> Dict[str, Any]:
    """ocr_result 의 full_text + blocks 모두 정규화 (in-place + 반환)."""
    if not isinstance(ocr_result, dict):
        return ocr_result

    # full_text 보정
    raw_full = ocr_result.get('full_text', '')
    if raw_full:
        ocr_result['full_text_raw'] = raw_full
        ocr_result['full_text'] = normalize_full_text(raw_full)

    # blocks 안 텍스트 보정 (파서가 blocks 단위로 패턴 매칭)
    for block in ocr_result.get('blocks', []) or []:
        if isinstance(block, dict) and 'text' in block:
            t = block['text']
            if t:
                block['text_raw'] = t
                block['text'] = normalize_full_text(t)

    return ocr_result


# ────────────────────────────────────────────────────────────────────────
# Diff 도구 — 보정 전/후 비교 (디버깅·측정용)
# ────────────────────────────────────────────────────────────────────────

def diff_fix(key_fields: Dict[str, Any]) -> Dict[str, tuple]:
    """보정으로 바뀐 필드만 dict로 반환. {field: (before, after)}"""
    fixed = fix_key_fields(key_fields)
    diff = {}
    def _walk(orig, fix, prefix=''):
        if isinstance(orig, dict):
            for k in orig:
                if k in fix:
                    _walk(orig[k], fix[k], f'{prefix}{k}.')
        elif isinstance(orig, str):
            if orig != fix:
                diff[prefix.rstrip('.')] = (orig, fix)
    _walk(key_fields, fixed)
    return diff


if __name__ == '__main__':
    # 단위 테스트 — 보정 효과 + 회귀 안전성 확인
    cases = [
        # 정상 (변경 없어야 함)
        ('hs_code', '8479.50.00', '8479.50.00'),
        ('amount', 'USD 500,000.00', 'USD 500,000.00'),
        ('quantity', '500 PCS', '500 PCS'),
        ('shipment_date', '2024-09-15', '2024-09-15'),
        ('exporter_name', 'COSCO Pioneer', 'COSCO Pioneer'),
        ('vessel_name', 'COSCO Pioneer', 'COSCO Pioneer'),  # mixed → no-op
        # 0/O 혼동 (보정 필요)
        ('hs_code', '847O.5O.OO', '8470.50.00'),
        ('amount', 'USD 5OO,OOO.OO', 'USD 500,000.00'),
        ('quantity', '5OO PCS', '500 PCS'),
        ('shipment_date', '2O24-O9-15', '2024-09-15'),
        ('gross_weight', '12,OOO', '12,000'),
        # I/1, l/1
        ('quantity', 'IO PCS', '10 PCS'),
        ('hs_code', '847l.50.0l', '8471.50.01'),
        # 알파벳 컨텍스트 — 단어 안 0/O
        ('exporter_name', 'C0SC0 Pioneer', 'COSCO Pioneer'),
        # 혼합 필드 — no-op
        ('lc_no', 'LC-2O24-OO1', 'LC-2O24-OO1'),  # mixed, 변경 X
        ('voyage_no', 'CS24O815', 'CS24O815'),    # mixed, 변경 X
        # 검증 실패 → 원본 유지
        ('hs_code', 'XYZ', 'XYZ'),
        ('amount', 'gibberish', 'gibberish'),
    ]
    print('=' * 60)
    print('postprocess_ocr 단위 테스트')
    print('=' * 60)
    n_pass = 0
    for fname, inp, expected in cases:
        actual = fix_field(fname, inp)
        ok = actual == expected
        flag = 'OK' if ok else 'FAIL'
        n_pass += 1 if ok else 0
        print(f'[{flag}] {fname:<20s} | {inp!r:<30s} → {actual!r}')
        if not ok:
            print(f'       expected: {expected!r}')
    print(f'\n{n_pass}/{len(cases)} pass')

    # full_text 정규화 테스트
    print()
    print('=' * 60)
    print('normalize_full_text 테스트')
    print('=' * 60)
    text_cases = [
        ('B/L N0: COSC240815-1000', 'B/L No: COSC240815-1000'),
        ('B/LN0:COSC240815', 'B/L No:COSC240815'),
        ('REF N0:SK-VN-2024-890.', 'REF No:SK-VN-2024-890.'),
        ('LC N0 ABC123', 'LC No ABC123'),
        ('Invoice N0. INV-001', 'Invoice No. INV-001'),
        ('Contract N0: C-2024', 'Contract No: C-2024'),
        ('P/L N0', 'P/L No'),
        ('Voyage N0 V123', 'Voyage No V123'),
        # 정상 케이스 (변경 없음)
        ('B/L No: COSC...', 'B/L No: COSC...'),
        ('No way', 'No way'),  # 'No' 단독은 라벨 아님
        ('COSCO Pioneer', 'COSCO Pioneer'),  # 회사명 (No 없음)
        # 'NO' (대문자) → 'No' 로 통일
        ('B/L NO: ABC', 'B/L No: ABC'),
    ]
    n_pass2 = 0
    for inp, expected in text_cases:
        out = normalize_full_text(inp)
        ok = out == expected
        n_pass2 += 1 if ok else 0
        flag = 'OK' if ok else 'FAIL'
        print(f'[{flag}] {inp!r:<45s} → {out!r}')
        if not ok:
            print(f'       expected: {expected!r}')
    print(f'\n{n_pass2}/{len(text_cases)} pass')
