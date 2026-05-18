"""
파서 공통 base — 모든 서류 타입이 상속.

공통 추출 필드:
  - 당사자 (party_a, party_b — 갑/을, 구매자/공급자 등)
  - 금액 (amount)
  - 날짜 (dates — 계약일, 서명일 등)
  - Incoterms (FOB, CIF, EXW 등)
  - 통화 (USD, KRW, EUR 등)
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any


# ────────────────────────────────────────────────────────────
# 공통 결과 스키마
# ────────────────────────────────────────────────────────────
@dataclass
class ParseResult:
    """파서 공통 출력."""
    document_type: str
    common_fields: dict[str, Any] = field(default_factory=dict)
    type_specific: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ''
    confidence: float = 0.0      # 파싱 신뢰도 (0~1)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'document_type': self.document_type,
            'common_fields': self.common_fields,
            'type_specific': self.type_specific,
            'confidence': self.confidence,
            'warnings': self.warnings,
            # raw_text는 storage에서 별도 저장
        }


# ────────────────────────────────────────────────────────────
# 공통 정규식 패턴
# ────────────────────────────────────────────────────────────
INCOTERMS_LIST = [
    'EXW', 'FCA', 'FAS', 'FOB', 'CFR', 'CIF', 'CPT', 'CIP',
    'DAP', 'DPU', 'DDP', 'DAT',
]

# 통화 코드
CURRENCY_CODES = ['USD', 'KRW', 'EUR', 'JPY', 'CNY', 'GBP', 'HKD', 'SGD']

# 금액 패턴: 통화 + 숫자
AMOUNT_PATTERN = re.compile(
    r'(' + '|'.join(CURRENCY_CODES) + r')\s*([0-9]{1,3}(?:[,\.][0-9]{3})*(?:\.[0-9]{1,2})?)',
    re.IGNORECASE,
)

# 날짜 패턴: 다양한 형식
DATE_PATTERNS = [
    re.compile(r'(\d{4})[-./\s]?(\d{1,2})[-./\s]?(\d{1,2})'),     # 2026-04-22
    re.compile(r'(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일'),  # 2026년 4월 22일
]


# ────────────────────────────────────────────────────────────
# 공통 추출 함수
# ────────────────────────────────────────────────────────────
def extract_incoterms(text: str) -> list[str]:
    """Incoterms 조건 추출. e.g. 'FOB Busan'"""
    found = []
    for term in INCOTERMS_LIST:
        # 단어 경계, 뒤에 공백·지명 허용
        pat = re.compile(r'\b' + term + r'\b\s*([A-Za-z가-힣]+)?')
        for m in pat.finditer(text):
            place = m.group(1) if m.group(1) else ''
            found.append(f'{term} {place}'.strip())
    # 중복 제거 순서 유지
    seen = set()
    unique = []
    for f in found:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique


def extract_amounts(text: str) -> list[dict]:
    """금액 추출 (통화 + 숫자)."""
    results = []
    for m in AMOUNT_PATTERN.finditer(text):
        currency = m.group(1).upper()
        amount_str = m.group(2).replace(',', '')
        try:
            amount = float(amount_str)
        except ValueError:
            continue
        results.append({
            'currency': currency,
            'value': amount,
            'raw': m.group(0),
        })
    return results


def extract_dates(text: str) -> list[dict]:
    """날짜 추출. 다양한 형식 지원."""
    results = []
    for pat in DATE_PATTERNS:
        for m in pat.finditer(text):
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
                    iso = f'{y:04d}-{mo:02d}-{d:02d}'
                    results.append({
                        'iso': iso,
                        'raw': m.group(0),
                    })
            except (ValueError, IndexError):
                continue
    # 중복 제거
    seen = set()
    unique = []
    for r in results:
        if r['iso'] not in seen:
            seen.add(r['iso'])
            unique.append(r)
    return unique


def extract_parties_korean(text: str) -> dict:
    """
    한국 계약서의 '갑/을' 또는 '구매자/공급자' 패턴 추출.
    정답 정보 없으면 @회사명 플레이스홀더만 발견될 수도 있음.
    """
    parties = {}

    # "갑"/"을" 패턴
    if re.search(r'[“"]갑[”"]|\b갑\b', text):
        parties['party_a_role'] = '갑'
    if re.search(r'[“"]을[”"]|\b을\b', text):
        parties['party_b_role'] = '을'

    # "구매자"/"공급자" 등 역할
    role_keywords = {
        '구매자': 'buyer', '공급자': 'supplier', '수입자': 'importer',
        '수출자': 'exporter', '매도인': 'seller', '매수인': 'buyer',
        '위탁자': 'consignor', '수탁자': 'consignee',
    }
    found_roles = []
    for kw, role in role_keywords.items():
        if kw in text:
            found_roles.append(kw)
    if found_roles:
        parties['roles_mentioned'] = found_roles

    # @회사명1 / @회사명2 같은 플레이스홀더 추출 (AI Hub 데이터 특성)
    placeholders = re.findall(r'@[가-힣]+[12]?', text)
    seen = set()
    unique_ph = []
    for p in placeholders:
        if p not in seen:
            seen.add(p)
            unique_ph.append(p)
    if unique_ph:
        parties['placeholders'] = unique_ph[:10]

    return parties


# ────────────────────────────────────────────────────────────
# BaseParser
# ────────────────────────────────────────────────────────────
class BaseParser:
    """공통 파서. 서류 타입별 파서는 이걸 상속."""
    DOCUMENT_TYPE = 'Unknown'

    def parse(self, ocr_result: dict) -> ParseResult:
        """
        OCR 결과 dict → 파싱 결과.
        """
        text = ocr_result.get('full_text') or ocr_result.get('raw_text') or ''

        result = ParseResult(
            document_type=self.DOCUMENT_TYPE,
            raw_text=text,
        )

        # 공통 필드 추출
        result.common_fields = self._extract_common(text)

        # 서브클래스가 타입별 필드 채움
        self._extract_type_specific(text, ocr_result, result)

        # 신뢰도 계산 (공통 필드 기반)
        result.confidence = self._compute_confidence(result)

        return result

    def _extract_common(self, text: str) -> dict:
        return {
            'amounts': extract_amounts(text),
            'dates': extract_dates(text),
            'incoterms': extract_incoterms(text),
            'parties': extract_parties_korean(text),
        }

    def _extract_type_specific(self, text: str, ocr_result: dict,
                                result: ParseResult) -> None:
        """서브클래스 오버라이드."""
        pass

    def _compute_confidence(self, result: ParseResult) -> float:
        """
        파싱 신뢰도: 주요 필드 추출 성공 여부에 비례.
        """
        score = 0.0
        cf = result.common_fields
        if cf.get('parties'):
            score += 0.25
        if cf.get('dates'):
            score += 0.15
        if cf.get('incoterms'):
            score += 0.15
        if cf.get('amounts'):
            score += 0.15
        if result.type_specific:
            score += 0.30
        return min(score, 1.0)

    # ─── [NEW] 지능형 좌표 기반 추출 유틸리티 (Virtual Grid) ───

    @staticmethod
    def _cluster_blocks_to_rows(blocks: list[dict], y_threshold: int = 8) -> list[list[dict]]:
        """y좌표 기반 행 클러스터링. 줄 없는 표 대응의 핵심."""
        # [DEBUG TEST] 주석 처리: 좌표 기반 클러스터링 비활성화
        return [blocks]
        # if not blocks: return []
        # # y_min 기준 정렬
        # sorted_blocks = sorted(blocks, key=lambda b: b['bbox_aabb'][1])
        # rows = []
        # current_row = [sorted_blocks[0]]
        # for b in sorted_blocks[1:]:
        #     if abs(b['bbox_aabb'][1] - current_row[0]['bbox_aabb'][1]) <= y_threshold:
        #         current_row.append(b)
        #     else:
        #         rows.append(sorted(current_row, key=lambda x: x['bbox_aabb'][0]))
        #         current_row = [b]
        # rows.append(sorted(current_row, key=lambda x: x['bbox_aabb'][0]))
        # return rows

    def _get_header_anchors(self, rows: list[list[dict]], keywords: list[str]) -> dict[str, tuple[float, float]]:
        """헤더 키워드의 x좌표 범위(min_x, max_x) 추출. 수직 정렬의 기준점 파악."""
        return {}
        # anchors = {}
        # for row in rows:
        #     for b in row:
        #         text_upper = b['text'].upper()
        #         for kw in keywords:
        #             if kw.upper() in text_upper:
        #                 # 이미 찾은 헤더가 더 긴 텍스트를 포함하고 있으면 스킵 (부분 매칭 방지)
        #                 if kw in anchors and len(b['text']) < 3: continue 
        #                 anchors[kw] = (b['bbox_aabb'][0], b['bbox_aabb'][2])
        # return anchors

    def _map_row_to_headers(self, row: list[dict], anchors: dict[str, tuple[float, float]]) -> dict[str, str]:
        """한 행의 블록들을 헤더 x좌표 범위에 따라 매핑 (수직 정렬 기반)."""
        return {}
        # mapped = {kw: "" for kw in anchors}
        # for b in row:
        #     b_mid_x = (b['bbox_aabb'][0] + b['bbox_aabb'][2]) / 2
        #     best_kw = None
        #     min_dist = 9999
        #     
        #     for kw, (h_min, h_max) in anchors.items():
        #         # 1. 헤더 수직 범위 내(마진 15px)에 들어오는지 확인
        #         if h_min - 15 <= b_mid_x <= h_max + 15:
        #             best_kw = kw
        #             break
        #         # 2. 아니면 중앙값 거리 비교
        #         h_mid_x = (h_min + h_max) / 2
        #         dist = abs(b_mid_x - h_mid_x)
        #         if dist < min_dist:
        #             min_dist = dist
        #             best_kw = kw
        #     
        #     if best_kw and (min_dist < 80 or best_kw is not None): # 텍스트가 헤더와 수직으로 어느 정도 정렬됨
        #         mapped[best_kw] = (mapped[best_kw] + " " + b['text']).strip()
        # return mapped
