"""
SalesContract 파서 — 무역 계약서.

핵심 작업:
  1. 조항 세그먼트 (제N조 ~ 다음 제(N+1)조 전까지)  — 한국어
  2. 각 조항의 제목·본문 분리
  3. 서문(preamble) 추출
  4. 서명 블록 추출
  5. 표(Table) 영역 식별 (선적 조건표 등)
  6. 영문 계약서 key_fields 추출 (4/30) — Contract No / Date / Seller / Buyer
                                         / Currency / Incoterms / Total

조항 단위로 쪼개놓으면 Step 5 RAG 분석 엔진에서 조항별로
법령 DB와 교차검증 가능.
"""
from __future__ import annotations
import re

from .base import BaseParser, ParseResult, INCOTERMS_LIST, CURRENCY_CODES


# ────────────────────────────────────────────────────────────
# 조항 헤더 패턴 (여러 양식 지원)
# ────────────────────────────────────────────────────────────
# "제1조", "제 1조", "제1조(목적)", "제1조 [목적]", "제1조 【목적】"
ARTICLE_HEADER_PATTERNS = [
    # 제목 괄호 포함
    re.compile(
        r'제\s*(\d+)\s*조\s*[\(\[【]([^\)\]】]+)[\)\]】]',
    ),
    # 제목 괄호 없음, 조 번호 뒤 공백 + 한글·숫자
    re.compile(
        r'제\s*(\d+)\s*조\s+([가-힣A-Za-z0-9\s,\.·]+?)(?=\n|$|①|②|\d+\.\s)',
    ),
    # 제 N 조 (공백 변형)
    re.compile(
        r'제\s*(\d+)\s*조',
    ),
]

# 항 표시 ①②③
PARA_MARKER_PAT = re.compile(r'[①-⑳]|\([①-⑳]\)')
PARA_NUMBER_PAT = re.compile(r'^([①-⑳])\s*')

# 호 표시 1. 2. 3.
ITEM_PAT = re.compile(r'^\s*([0-9]+)\.\s+')

# 목 표시 가. 나. 다.
SUB_ITEM_PAT = re.compile(r'^\s*([가-하])\.\s+')


def _find_article_headers(text: str) -> list[dict]:
    """
    텍스트 전체에서 '제N조' 헤더 위치와 정보 수집.
    여러 패턴 순회하며 우선순위 높은 것부터.
    """
    hits = []
    # 패턴 1, 2: 제목 있는 버전
    for pat_idx, pat in enumerate(ARTICLE_HEADER_PATTERNS[:2]):
        for m in pat.finditer(text):
            article_no = int(m.group(1))
            title = m.group(2).strip() if m.lastindex >= 2 else ''
            hits.append({
                'article_no': article_no,
                'title': title,
                'start': m.start(),
                'end': m.end(),
                'pattern_rank': pat_idx,
                'raw': m.group(0),
            })
    # article_no + start 기준 중복 제거 (더 좋은 패턴 우선)
    hits.sort(key=lambda h: (h['start'], h['pattern_rank']))
    unique = []
    seen_positions = set()
    for h in hits:
        # 같은 위치 근처 (10자 이내) 중복 제거
        if any(abs(h['start'] - s) < 10 for s in seen_positions):
            continue
        seen_positions.add(h['start'])
        unique.append(h)

    # article_no 오름차순 중복 제거 (같은 번호 여러 번 나오면 첫 등장만)
    # 단, 본문 내 참조 ("제1조에 따라")는 이미 패턴 1의 괄호 조건으로 걸러짐
    by_no = {}
    for h in unique:
        no = h['article_no']
        if no not in by_no:
            by_no[no] = h
    result = sorted(by_no.values(), key=lambda h: h['article_no'])
    return result


def _split_article_body(body: str) -> dict:
    """
    조항 본문을 항(①②③) / 호(1. 2.) / 목(가. 나.) 단위로 구조화.
    계층 없이 본문 전체만 text로 반환할 수도 있음.
    """
    lines = [l.strip() for l in body.split('\n') if l.strip()]
    paragraphs = []  # [{'number': '①', 'text': '...', 'items': [...]}]
    current_para = None

    for line in lines:
        pm = PARA_NUMBER_PAT.match(line)
        if pm:
            # 새 항 시작
            if current_para:
                paragraphs.append(current_para)
            current_para = {
                'number': pm.group(1),
                'text': PARA_NUMBER_PAT.sub('', line).strip(),
                'items': [],
            }
        elif current_para is not None:
            # 현재 항에 이어붙임
            im = ITEM_PAT.match(line)
            if im:
                current_para['items'].append({
                    'number': im.group(1),
                    'text': ITEM_PAT.sub('', line).strip(),
                })
            else:
                current_para['text'] += ' ' + line
        else:
            # 항 없는 직접 본문 → "preamble"
            paragraphs.append({
                'number': None,
                'text': line,
                'items': [],
            })

    if current_para:
        paragraphs.append(current_para)

    # 평문 본문
    return {
        'full_body': body.strip(),
        'paragraphs': paragraphs,
    }


def _extract_clauses(text: str) -> list[dict]:
    """조항 단위 분할."""
    headers = _find_article_headers(text)
    if not headers:
        return []

    clauses = []
    for i, h in enumerate(headers):
        body_start = h['end']
        body_end = headers[i + 1]['start'] if i + 1 < len(headers) else len(text)
        body = text[body_start:body_end].strip()
        structured = _split_article_body(body)
        clauses.append({
            'article_no': h['article_no'],
            'title': h['title'],
            'header': h['raw'],
            **structured,
        })
    return clauses


def _extract_preamble(text: str, clauses: list[dict]) -> str:
    """첫 조항 이전의 서문."""
    if not clauses:
        return text.strip()
    # 첫 조항 헤더 위치까지가 서문
    # re-locate first header
    first = clauses[0]
    m = re.search(
        r'제\s*' + str(first['article_no']) + r'\s*조',
        text,
    )
    if m:
        return text[:m.start()].strip()
    return ''


def _extract_signature_block(text: str) -> dict:
    """
    마지막 부분의 서명 블록 추출.
    패턴: "계약일자: 년 월 일" + (갑/을) + 주소·상호·대표자 etc.
    """
    # 마지막 조항 이후 영역 찾기
    headers = _find_article_headers(text)
    if headers:
        last_end = max(
            re.search(
                r'제\s*' + str(h['article_no']) + r'\s*조', text
            ).end() if re.search(
                r'제\s*' + str(h['article_no']) + r'\s*조', text
            ) else 0
            for h in headers
        )
        tail = text[last_end:]
    else:
        tail = text[len(text) // 2:]

    # 서명 블록 키워드 포함 여부
    sig_keys = ['계약일자', '서명일자', '년 월 일',
                '(인)', '날인', '서명']
    has_sig = any(k in tail for k in sig_keys)

    if not has_sig:
        return {'found': False, 'text': ''}

    # 간단하게 tail 자체를 서명 블록으로
    return {
        'found': True,
        'text': tail.strip(),
        'raw_length': len(tail),
    }


# ────────────────────────────────────────────────────────────
# 영문 계약서 key_fields 추출 (4/30 — 양식 A/B 양식 지원)
# ────────────────────────────────────────────────────────────

ENGLISH_KF_PATTERNS: dict = {
    'contract_no': [
        # 양식 A: 라벨 두 개 한 줄 — 'Contract Date : Contract No. : YYYY-MM-DD ABC-XYZ'
        re.compile(
            r'Contract\s*Date\s*:\s*Contract\s*No\.?\s*:\s*\d{4}[-./]\d{1,2}[-./]\d{1,2}\s+([A-Z][A-Z0-9\-]{2,40})',
            re.IGNORECASE,
        ),
        # 양식 B: 'CONTRACT DATE\nREFERENCE NO.\n<date>\n<contract_no>'
        re.compile(
            r'(?:CONTRACT\s*DATE|REFERENCE\s*NO\.?)\s*\n+\s*(?:CONTRACT\s*DATE|REFERENCE\s*NO\.?)\s*\n+\s*\d{4}[-./]\d{1,2}[-./]\d{1,2}\s*\n+\s*([A-Z][A-Z0-9\-]{2,40})',
            re.IGNORECASE,
        ),
        # 단순: 'Contract No: ABC-123' / 'Contract No. ABC-123'
        re.compile(
            r'Contract\s*No\.?\s*[:.]\s*([A-Z][A-Z0-9\-]{2,40})',
            re.IGNORECASE,
        ),
        # Reference 라벨
        re.compile(
            r'Reference\s*No\.?\s*[:.]\s*([A-Z][A-Z0-9\-]{2,40})',
            re.IGNORECASE,
        ),
    ],
    'date': [
        # 양식 A: 'Contract Date : Contract No. : 2026-03-20 ABC' — 첫 날짜
        re.compile(
            r'Contract\s*Date\s*:\s*(?:Contract\s*No\.?\s*:\s*)?(\d{4}[-./]\d{1,2}[-./]\d{1,2})',
            re.IGNORECASE,
        ),
        # 양식 B: 라벨 두 줄 후 날짜 두 줄
        re.compile(
            r'(?:CONTRACT\s*DATE|REFERENCE\s*NO\.?)\s*\n+\s*(?:CONTRACT\s*DATE|REFERENCE\s*NO\.?)\s*\n+\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})',
            re.IGNORECASE,
        ),
        # 단순: 'Date: 2024-08-10'
        re.compile(
            r'(?<!Cancellation\s)(?<!Shipment\s)\b(?:Contract\s*Date|Issue\s*Date|Date)\s*[:.]?\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})',
            re.IGNORECASE,
        ),
    ],
    'seller': [
        # 양식 A: '<NAME>, (hereinafter referred to as "the Seller")'
        re.compile(
            r'((?:(?!\bBuyer\b)[A-Z][A-Z\s\.,&\-\(\)]){2,80}?)\s*,?\s*\(hereinafter\s+referred\s+to\s+as\s+(?:the\s+)?"?(?:the\s+)?Seller"?\)',
            re.IGNORECASE,
        ),
        # 양식 B: 'between <NAME> (Seller)'
        re.compile(
            r'between\s+((?:(?!\bBuyer\b)[A-Z][A-Z\s\.,&\-]){2,80}?)\s*\(Seller\)',
            re.IGNORECASE,
        ),
        # 단순: 'SELLER: <NAME>'
        re.compile(
            r'\bSELLER\s*[:.]\s*((?:(?!\bBUYER\b)[A-Z][A-Z\s\.,&\-]){2,80}?)(?=\n|BUYER|$)',
            re.IGNORECASE,
        ),
        # 5/6 sc015 양식: 'THE SELLER <NAME>'
        re.compile(
            r'\bTHE\s+SELLER\s+((?:(?!\bBUYER\b)[A-Z][A-Z0-9\s\.,&\-]){2,80}?(?:CO\.|LTD\.?|INC\.?|CORP\.?|GMBH|S\.A\.|LLC|LIMITED|COMPANY)\.?)',
            re.IGNORECASE,
        ),
        # 5/6 sc2_4/5 양식: 'SELLER <NAME ADDR>'
        re.compile(
            r'\bSELLER\s+((?:(?!\bBUYER\b)[A-Z][A-Za-z0-9\s\.,&\-])*?(?:CO\.,?\s*LTD\.?|LTD\.?|INC\.?|CORP\.?|S\.A\.?|SARL|GMBH|JSC|LLC))(?=\s+\d|\s+\w+\s*\d|\s+Av\.|\s+,|\s*[\t])',
            re.IGNORECASE,
        ),
        # 5/6 synv2 양식 C: 'SELLER <NAME> <COUNTRY>' (종결자 없는 합성)
        re.compile(
            r'\bSELLER\s+((?:(?!\bBUYER\b)[A-Z][A-Za-z0-9\s\.,&\-]){2,80}?)\s+'
            r'(?:South\s+Korea|Korea|Japan|China|Vietnam|Thailand|Philippines|Indonesia|'
            r'Malaysia|Singapore|India|USA|United\s+States|Canada|Mexico|Brazil|Argentina|'
            r'Chile|United\s+Kingdom|UK|Germany|France|Italy|Netherlands|Belgium|Spain|'
            r'Switzerland|Sweden|Norway|Denmark|Finland|Russia|Turkey|Greece|Poland|Austria|'
            r'Australia|New\s+Zealand|Egypt|Morocco|South\s+Africa|Nigeria|Kenya|UAE|'
            r'Saudi\s+Arabia|Qatar|Israel|Iran|Pakistan|Taiwan)\b',
            re.IGNORECASE,
        ),
    ],
    'buyer': [
        re.compile(
            r'((?:(?!\bSeller\b)[A-Z][A-Z\s\.,&\-\(\)]){2,80}?)\s*,?\s*\(hereinafter\s+referred\s+to\s+as\s+(?:the\s+)?"?(?:the\s+)?Buyer"?\)',
            re.IGNORECASE,
        ),
        re.compile(
            r'and\s+((?:(?!\bSeller\b)[A-Z][A-Z\s\.,&\-]){2,80}?)\s*\(Buyer\)',
            re.IGNORECASE,
        ),
        re.compile(
            r'\bBUYER\s*[:.]\s*((?:(?!\bSELLER\b)[A-Z][A-Z\s\.,&\-]){2,80}?)(?=\n|SELLER|Address|$)',
            re.IGNORECASE,
        ),
        # 5/6 sc015 양식: 'THE BUYER <NAME>'
        re.compile(
            r'\bTHE\s+BUYER\s+((?:(?!\bSELLER\b)[A-Z][A-Z0-9\s\.,&\-]){2,80}?(?:CO\.|LTD\.?|INC\.?|CORP\.?|GMBH|S\.A\.|LLC|LIMITED|COMPANY)\.?)',
            re.IGNORECASE,
        ),
        # 5/6 sc2_4/5 양식: 'BUYER <NAME ADDR>'
        re.compile(
            r'\bBUYER\s+((?:(?!\bSELLER\b)[A-Z][A-Za-z0-9\s\.,&\-])*?(?:CO\.,?\s*LTD\.?|LTD\.?|INC\.?|CORP\.?|S\.A\.?|SARL|GMBH|JSC|LLC))(?=\s+\d|\s+\w+\s*\d|\s+Av\.|\s+,|\s*[\t]|$)',
            re.IGNORECASE,
        ),
        # 5/6 synv2 양식 C: 'BUYER <NAME> <COUNTRY>' (종결자 없는 합성)
        re.compile(
            r'\bBUYER\s+((?:(?!\bSELLER\b)[A-Z][A-Za-z0-9\s\.,&\-]){2,80}?)\s+'
            r'(?:South\s+Korea|Korea|Japan|China|Vietnam|Thailand|Philippines|Indonesia|'
            r'Malaysia|Singapore|India|USA|United\s+States|Canada|Mexico|Brazil|Argentina|'
            r'Chile|United\s+Kingdom|UK|Germany|France|Italy|Netherlands|Belgium|Spain|'
            r'Switzerland|Sweden|Norway|Denmark|Finland|Russia|Turkey|Greece|Poland|Austria|'
            r'Australia|New\s+Zealand|Egypt|Morocco|South\s+Africa|Nigeria|Kenya|UAE|'
            r'Saudi\s+Arabia|Qatar|Israel|Iran|Pakistan|Taiwan)\b',
            re.IGNORECASE,
        ),
    ],
    'currency': [
        # 'USD 45000.0' / 'EUR 240,000.00'
        re.compile(
            r'\b(' + '|'.join(CURRENCY_CODES) + r')\s+\d',
            re.IGNORECASE,
        ),
        # 'Currency: USD'
        re.compile(
            r'Currency\s*[:.]\s*(' + '|'.join(CURRENCY_CODES) + r')',
            re.IGNORECASE,
        ),
    ],
    'incoterms': [
        # 'FOB Busan' / 'CIF Alexandria'
        re.compile(
            r'\b(' + '|'.join(INCOTERMS_LIST) + r')\s+([A-Z][A-Z\s]{2,30}?)(?:\s+PORT|\s+$|\n|$)',
            re.IGNORECASE,
        ),
        # 'TERMS OF DELIVERY:\n\nCIF ALEXANDRIA PORT'
        re.compile(
            r'(?:TERMS\s*OF\s*DELIVERY|Incoterms?|Price\s*Term)\s*[:.]?\s*\n*\s*(' + '|'.join(INCOTERMS_LIST) + r')\s*([A-Z][A-Z\s]{0,30})?',
            re.IGNORECASE,
        ),
        # 단순 단어 매칭 (마지막 fallback)
        re.compile(
            r'\b(' + '|'.join(INCOTERMS_LIST) + r')\b',
            re.IGNORECASE,
        ),
    ],
    'total_amount': [
        # 'TOTAL AMOUNT TOTAL AMOUNT TOTAL AMOUNT TOTAL AMOUNT 300000.0'
        re.compile(
            r'TOTAL\s*AMOUNT(?:\s*TOTAL\s*AMOUNT)*\s+([\d,]+(?:\.\d+)?)',
            re.IGNORECASE,
        ),
        # 5/6 sc015: 'TOTAL CONTRACT VALUE: USD 200000'
        re.compile(
            r'TOTAL\s+CONTRACT\s+VALUE\s*[:.]?\s*(?:[A-Z]{3}\s*)?([\d,]+(?:\.\d+)?)',
            re.IGNORECASE,
        ),
        # 'Total: USD 300,000.00'
        re.compile(
            r'Total\s*[:.]?\s*(?:[A-Z]{3}\s*)?([\d,]+(?:\.\d+)?)',
            re.IGNORECASE,
        ),
    ],
    # 5/6 sc015 신규 — governing law (강행규정 검색에 결정적)
    'governing_law': [
        # 'governed by and construed in accordance with the laws of <LAW>'
        re.compile(
            r'governed\s+by\s+and\s+construed\s+in\s+accordance\s+with\s+the\s+laws?\s+of\s+([^\.\n]{3,200}?)(?:\.|$|\n)',
            re.IGNORECASE,
        ),
        # 'This Contract shall be governed by <LAW>'
        re.compile(
            r'governed\s+by\s+(?:the\s+)?([A-Z][A-Za-z\s,\/\-]{3,150}?(?:Act|Code|Law|UCC|CISG))',
            re.IGNORECASE,
        ),
        # 'Governing Law: <LAW>'
        re.compile(
            r'Governing\s+Law\s*[:.]?\s*([^\.\n]{3,200}?)(?:\.|\n|$)',
            re.IGNORECASE,
        ),
    ],
    # 5/6 sc015 신규 — arbitration seat (분쟁해결 분석)
    'arbitration_seat': [
        # 'arbitration in <CITY>, <COUNTRY>'
        re.compile(
            r'arbitration\s+in\s+([A-Z][A-Za-z\s,]{2,80}?)(?:\.|$|\n)',
            re.IGNORECASE,
        ),
        # 'seat of arbitration shall be <CITY>'
        re.compile(
            r'(?:seat|venue|place)\s+of\s+arbitration\s+(?:shall\s+be|is)\s+([A-Z][A-Za-z\s,]{2,80}?)(?:\.|$|\n)',
            re.IGNORECASE,
        ),
        # 5/6 양식 C: 'Arbitration: Seoul.' / 'Arbitration: London' 콜론 라벨
        re.compile(
            r'\bArbitration\s*[:.]\s*([A-Z][A-Za-z\s,]{2,80}?)(?:\.|$|\n|\|)',
            re.IGNORECASE,
        ),
    ],
}


def _clean_value(s: str) -> str:
    """추출 값에서 공백/쉼표/괄호 후행 노이즈 제거."""
    if not s:
        return s
    s = s.strip().rstrip(',').rstrip('.').strip()
    # 'COMPANY NAME (' 같은 trailing
    s = re.sub(r'\s*\([^\)]*$', '', s)
    return s


def _extract_english_keyfields(text: str) -> dict:
    """영문 계약서에서 라벨 기반 key_fields 추출.

    양식 A (SALES CONTRACT + hereinafter) / 양식 B (INTERNATIONAL SALES AGREEMENT
    + between) / 단순 라벨 양식 모두 지원. 패턴 우선순위순.
    """
    kf = {}
    for field_name, patterns in ENGLISH_KF_PATTERNS.items():
        for pat in patterns:
            for m in pat.finditer(text):
                # incoterms 는 두 그룹 (코드 + 지명) 합쳐서 보존
                if field_name == 'incoterms':
                    code = m.group(1).upper()
                    place = (m.group(2) or '').strip() if m.lastindex and m.lastindex >= 2 else ''
                    val = f'{code} {place}'.strip() if place else code
                else:
                    val = _clean_value(m.group(1))
                if not val:
                    continue
                # 첫 매칭 채택, 이후 무시
                if field_name not in kf:
                    kf[field_name] = val
                    break
            if field_name in kf:
                break
    
    # [NEW] Seller/Buyer 교차 검증 (뒤바뀜 방지)
    kf = _refine_seller_buyer_swap(kf, text)
    return kf


def _refine_seller_buyer_swap(kf: dict, text: str) -> dict:
    """Seller와 Buyer가 바뀌었는지 인덱스 거리로 최종 확인."""
    if 'seller' not in kf or 'buyer' not in kf:
        return kf
    
    s_val = kf['seller']
    b_val = kf['buyer']
    if s_val == b_val:
        return kf
    
    # 각 이름이 텍스트에서 처음 나타나는 위치
    s_idx = text.find(s_val)
    b_idx = text.find(b_val)
    if s_idx == -1 or b_idx == -1:
        return kf
    
    # 'SELLER', 'BUYER' 라벨들의 위치 (대소문자 무시)
    text_upper = text.upper()
    s_labels = [m.start() for m in re.finditer(r'\bSELLER\b', text_upper)]
    b_labels = [m.start() for m in re.finditer(r'\bBUYER\b', text_upper)]
    
    if not s_labels or not b_labels:
        return kf

    # 현재 seller 이름과 가장 가까운 라벨 찾기
    dist_to_s = min([abs(s_idx - l) for l in s_labels])
    dist_to_b = min([abs(s_idx - l) for l in b_labels])
    
    # 만약 현재 seller가 SELLER 라벨보다 BUYER 라벨에 훨씬 가깝다면 (뒤바뀜 의심)
    # 임계치 20자: 라벨 바로 옆에 있는 것이 우선순위
    if dist_to_b < dist_to_s and (dist_to_s - dist_to_b) > 20:
        kf['seller'], kf['buyer'] = b_val, s_val
        
    return kf


def _extract_items_structural_v2(ocr_result: dict, parser_inst: BaseParser) -> list[dict]:
    """BaseParser의 가상 격자 알고리즘을 활용한 고정밀 품목 추출"""
    all_blocks = []
    for page in ocr_result.get('pages', []):
        all_blocks.extend(page.get('blocks', []))
    
    if not all_blocks: return []

    # 1. 행 복원 (BaseParser 메서드 활용)
    rows = parser_inst._cluster_blocks_to_rows(all_blocks)
    
    # 2. 헤더 위치 파악 (중요 키워드들)
    header_keywords = ['DESCRIPTION', 'QUANTITY', 'UNIT PRICE', 'AMOUNT', 'TOTAL']
    anchors = parser_inst._get_header_anchors(rows, header_keywords)
    
    if not anchors: return [] # 헤더를 못 찾으면 구조적 추출 불가

    # 3. 데이터 매핑 (수직 정렬 기반)
    items = []
    table_started = False
    for row in rows:
        row_text = " ".join(b['text'] for b in row).upper()
        # 헤더 행 스킵
        if any(kw in row_text for kw in anchors):
            table_started = True
            continue
        
        if table_started:
            # 숫자가 하나라도 포함된 행만 데이터로 간주
            if any(re.search(r'\d', b['text']) for b in row):
                mapped = parser_inst._map_row_to_headers(row, anchors)
                # 매핑된 결과가 유의미한지 확인 (적어도 2개 이상의 필드가 채워졌는지)
                filled_count = sum(1 for v in mapped.values() if v)
                if filled_count >= 2:
                    items.append({
                        'description': mapped.get('DESCRIPTION', ''),
                        'quantity': mapped.get('QUANTITY', ''),
                        'unit_price': mapped.get('UNIT PRICE', ''),
                        'amount': mapped.get('AMOUNT', mapped.get('TOTAL', ''))
                    })
    return items


def _extract_parties_positional(preamble: str) -> dict:
    """서문(Preamble) 내 문맥적 위치를 활용한 당사자 추출"""
    parties = {'seller': None, 'buyer': None}
    
    # 1. 'Between [A] and [B]' 패턴 (가장 일반적)
    m = re.search(r'between\s+(.*?)\s+and\s+(.*?)(?:\s+hereinafter|$)', preamble, re.IGNORECASE | re.DOTALL)
    if m:
        parties['seller'] = m.group(1).strip()
        parties['buyer'] = m.group(2).strip()
    
    # 2. 'By and Between [A] ... [B]' (공식 법률 양식)
    if not parties['seller']:
        m = re.search(r'by\s+and\s+between\s+([A-Z\s\.,&]{2,100})\s+.*?(?:and|&)\s+([A-Z\s\.,&]{2,100})', preamble, re.IGNORECASE)
        if m:
            parties['seller'] = m.group(1).strip()
            parties['buyer'] = m.group(2).strip()

    return parties


# ────────────────────────────────────────────────────────────
class SalesContractParser(BaseParser):
    """무역 계약서 파서."""
    DOCUMENT_TYPE = 'SalesContract'

    def _extract_type_specific(self, text: str, ocr_result: dict,
                                result: ParseResult) -> None:
        # 조항 추출 (한국어 제N조)
        clauses = _extract_clauses(text)
        # 서문·서명
        preamble = _extract_preamble(text, clauses)
        signature = _extract_signature_block(text)

        result.type_specific['clauses'] = clauses
        result.type_specific['n_clauses'] = len(clauses)
        result.type_specific['preamble'] = preamble
        result.type_specific['signature_block'] = signature

        # [NEW] 문맥 기반 당사자 추출 (Parties)
        parties = _extract_parties_positional(preamble)
        result.type_specific['parties'] = parties

        # 4/30 — 영문 계약서 key_fields 추출
        kf = _extract_english_keyfields(text)
        if kf:
            # 문맥 기반 결과가 있으면 우선 적용 (정확도 보완)
            if parties['seller']: kf['seller'] = parties['seller']
            if parties['buyer']: kf['buyer'] = parties['buyer']
            result.type_specific['key_fields'] = kf

        # [NEW] 지능형 좌표 기반 구조적 품목 추출 (BaseParser 기능 활용)
        items = _extract_items_structural_v2(ocr_result, self)
        if items:
            result.type_specific['items'] = items

        # Warning
        if not clauses:
            result.warnings.append('NO_CLAUSES_DETECTED')
        if not signature['found']:
            result.warnings.append('NO_SIGNATURE_BLOCK')
        if not kf:
            result.warnings.append('NO_KEYFIELDS')
        if not items:
            result.warnings.append('NO_ITEMS_STRUCTURAL_DETECTED')


# ────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import io
    import json
    import sys
    from pathlib import Path

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    if len(sys.argv) >= 2:
        ocr_json = Path(sys.argv[1])
    else:
        ocr_json = Path('ocr_storage/preprocessed/수입_수출계약서_0001/_ocr_result.json')

    with open(ocr_json, encoding='utf-8') as f:
        ocr_result = json.load(f)

    parser = SalesContractParser()
    parsed = parser.parse(ocr_result)

    print(f'=== {ocr_result.get("document_id", "?")} ===')
    print(f'document_type: {parsed.document_type}')
    print(f'confidence: {parsed.confidence:.2f}')
    print(f'warnings: {parsed.warnings}')

    print('\n--- common_fields ---')
    for k, v in parsed.common_fields.items():
        print(f'  {k}: {v}')

    print('\n--- clauses ---')
    for c in parsed.type_specific['clauses'][:5]:
        print(f'  제{c["article_no"]}조 [{c["title"]}]')
        print(f'    paragraphs: {len(c["paragraphs"])}')
    print(f'  ... (총 {parsed.type_specific["n_clauses"]}개)')

    print('\n--- signature ---')
    sig = parsed.type_specific['signature_block']
    print(f'  found: {sig["found"]}')
    if sig['found']:
        print(f'  text (앞 200자): {sig["text"][:200]}')
