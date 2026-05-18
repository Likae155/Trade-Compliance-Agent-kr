"""
Step 3.4: 문서 타입 분류기 (v2 — 영문 확장 + 위치 가중치)

v1 문제점 (진단 결과 36.4% 정확도):
  - 영문 "SALES AGREEMENT" 등 키워드 누락
  - 본문 언급 vs 제목을 구분 안 함 (본문에 "letter of credit" 나오면 오분류)
  - 영문 계약서 시그니처 (Buyer/Seller/hereby confirms) 미지원

v2 개선:
  1. 영문 키워드 대폭 확장 (특히 SalesContract 계열)
  2. 위치 가중치: 상단 300자 내 등장 = 3배 가중치
  3. 부정적 신호 (negative keywords): 다른 타입에 있으면 감점
  4. 문서 시그니처 패턴 (문장 단위)
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field


# ────────────────────────────────────────────────────────────
# 타입별 키워드 스펙 (v2)
# ────────────────────────────────────────────────────────────
# each spec:
#   title_keywords: 문서 제목으로 쓰이는 강한 시그널 (상단 300자 내 가중치 ×3)
#   body_keywords: 본문에 있으면 가중치 +2
#   signature_patterns: 문장 단위 패턴 (문서 타입 강한 증거)
#   priority: 동점 시 우선 타입 (큰 수 우선)

TYPE_SPECS = {
    'LetterOfCredit': {
        'title_keywords': [
            'LETTER OF CREDIT',
            'DOCUMENTARY CREDIT',
            'IRREVOCABLE LETTER OF CREDIT',
            'IRREVOCABLE DOCUMENTARY CREDIT',
            '신용장',
        ],
        'body_keywords': [
            'L/C No', 'LC No', 'LC NUMBER', 'L/C NUMBER', 'MT700',
            ':27:', ':40A:', ':50:', ':59:', ':32B:', ':45A:',
            ':46A:', ':47A:', ':78:',
            'Issuing Bank', 'Advising Bank', 'Confirming Bank',
            'Place of Expiry', 'Date of Expiry', 'DATE AND PLACE OF EXPIRY',
            'DOCUMENTS REQUIRED', 'SWIFT CODE',
            '개설의뢰인', '수익자', '개설은행', '통지은행',
            '신용장번호', '신용장금액',
        ],
        'signature_patterns': [
            r'issued by [\w\s]+ bank',
            r'this credit is subject to',
            r'available by .* draft',
        ],
        'priority': 90,
    },
    'BillOfLading': {
        'title_keywords': [
            'BILL OF LADING',
            'OCEAN BILL OF LADING',
            'MULTIMODAL TRANSPORT DOCUMENT',
            'AIR WAYBILL',
            'AIR CONSIGNMENT NOTE',
            '선하증권', '항공운송장',
        ],
        'body_keywords': [
            'B/L No', 'BL No', 'B/L NUMBER', 'AWB NO',
            'Shipper', 'Consignee', 'Notify Party', 'Notify',
            'Vessel', 'Voyage No', 'Voyage',
            'Port of Loading', 'Port of Discharge',
            'Port of Receipt', 'Place of Delivery',
            'Container No', 'Seal No',
            'Freight Prepaid', 'Freight Collect',
            'SHIPPED ON BOARD',
            '송하인', '수하인', '통지처', '선적항', '도착항', '항해번호',
        ],
        'signature_patterns': [
            r'clean on board',
            r'shipper.*consignee.*notify',
        ],
        'priority': 85,
    },
    'CommercialInvoice': {
        'title_keywords': [
            # 'INVOICE' 단독은 PI/일반 송장과 충돌하나,
            # body_keywords 매칭 시 PI가 아닌 걸 확인하는 부정 체크는 classify_text()에서 처리
            'COMMERCIAL INVOICE',
            '상업송장',
        ],
        'body_keywords': [
            # OCR 깨짐에 강건하도록 자주 보이는 필드 + 금액 표기 대폭 추가
            'Invoice No', 'Invoice Date', 'Invoice Number', 'Invoice #',
            'Total Amount', 'Grand Total', 'Unit Price', 'Quantity',
            'Description of Goods', 'Description', 'Country of Origin',
            'HS Code', 'H.S Code', 'Amount',
            'Shipper', 'Consignee',
            '수출자', '수입자', '송장번호', '송장',
            # 금액 관련
            'USD', 'EUR', 'JPY', 'KRW',
        ],
        'signature_patterns': [
            r'(total|grand total)\s*[:\s]*(usd|eur|krw|jpy|cny)',
            # "INVOICE" 단어가 본문에 있으면 약한 시그널
            r'\bINVOICE\b',
        ],
        'priority': 80,
        # 'INVOICE' 근처에 'PROFORMA'/'PRO FORMA'가 있으면 CI 아님 (부정 신호)
        'negative_if_near': ['PROFORMA', 'PRO FORMA', 'PRO-FORMA', '견적'],
    },
    'ProformaInvoice': {
        'title_keywords': [
            'PROFORMA INVOICE',
            'PRO FORMA INVOICE',
            'PRO-FORMA INVOICE',
            '견적송장', '견적서',
        ],
        'body_keywords': [
            'Proforma', 'Quotation',
            'Unit Price', 'Total Amount', 'Payment Terms',
            'Validity', 'Valid Until',
            '견적', '단가', '총액', '유효기간',
        ],
        'signature_patterns': [],
        'priority': 82,  # CI보다 살짝 높게 (proforma가 더 specific)
    },
    'PurchaseOrder': {
        'title_keywords': [
            'PURCHASE ORDER',
            'PO NUMBER',
            '구매주문서', '발주서', '주문서',
        ],
        'body_keywords': [
            'PO No', 'Order No', 'Order Date', 'Delivery Date',
            'Payment Terms', 'Bill To', 'Ship To', 'Vendor',
            '주문일', '납기', '결제조건', '발주번호',
        ],
        'signature_patterns': [
            r'purchase order',
            r'please supply',
        ],
        'priority': 75,
    },
    'PackingList': {
        'title_keywords': [
            'PACKING LIST',
            'PACKING',
            '포장명세서', '패킹리스트',
        ],
        'body_keywords': [
            'Gross Weight', 'Net Weight', 'Measurement', 'CBM',
            'Package No', 'Box No', 'Carton No', 'Pallet',
            'G.W.', 'N.W.', 'KGS', 'CTN',
            '총중량', '순중량', '용적', '박스', '카톤',
        ],
        'signature_patterns': [
            r'(gross|net)\s*weight\s*[:\s]*\d',
            r'cbm\s*[:\s]*\d',
        ],
        'priority': 72,
    },
    'SalesContract': {
        # 계약서는 형태·언어 다양 — 영문 확장 대폭
        'title_keywords': [
            # 한글
            '계약서', '공급계약서', '매매계약서', '대행계약서',
            '수출계약서', '수입계약서', '수출입계약서',
            '수입수출계약서', '수출공급계약서',
            # 영문 주 키워드
            'SALES CONTRACT',
            'SALES AGREEMENT',
            'SUPPLY CONTRACT',
            'SUPPLY AGREEMENT',
            'EXPORT CONTRACT',
            'EXPORT AGREEMENT',
            'IMPORT CONTRACT',
            'IMPORT AGREEMENT',
            'PURCHASE AGREEMENT',  # purchase는 PO 우선순위가 더 높지만 agreement면 contract
            'TRADE AGREEMENT',
            'TRADING AGREEMENT',
            'AGENCY AGREEMENT',
            'DISTRIBUTION AGREEMENT',
            'PURCHASE CONTRACT',
        ],
        'body_keywords': [
            # 한글 계약 구조
            '제1조', '제2조', '제3조', '계약일자', '서명일자',
            '갑', '을', '구매자', '공급자',
            '본 계약', '본계약',
            # 영문 계약 구조
            'Article 1', 'Article 2', 'ARTICLE 1', 'ARTICLE 2',
            'Buyer', 'Seller', 'BUYER', 'SELLER',
            'hereby agrees', 'hereby confirms', 'hereinafter referred',
            'in witness whereof', 'witnesseth',
            'IN WITNESS WHEREOF',
            'TERMS AND CONDITIONS',
            'Governing Law', 'Jurisdiction',
            'Force Majeure', 'Arbitration',
            'Both parties', 'Parties agree',
        ],
        'signature_patterns': [
            r'hereby\s+(agrees|confirms)',
            r'hereinafter\s+referred\s+to\s+as',
            r'article\s*\d+\s*[\.\:]',
        ],
        'priority': 60,  # 마지막 fallback 성격
    },
}


# ────────────────────────────────────────────────────────────
# 위치 가중치 설정
# ────────────────────────────────────────────────────────────
TITLE_REGION_CHARS = 300  # 상단 N자 내 = "제목 영역"
TITLE_WEIGHT_MULTIPLIER = 3.0  # 제목 영역 매치는 3배 가중치


@dataclass
class ClassificationResult:
    doc_type: str                       # 'SalesContract' 등
    confidence: float                   # 0~1
    matched_keywords: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    needs_vlm_fallback: bool = False    # 신뢰도 낮으면 VLM 재검증 필요


_WHITESPACE_RE = re.compile(r'\s+')


def _count_match_with_position(text: str, text_upper: str,
                                keyword: str,
                                normalize_ws: bool = False) -> tuple[int, int]:
    """
    키워드 등장 횟수와 가중치 있는 위치(상단 영역) 등장 횟수 반환.

    Args:
        normalize_ws: True면 `\\s+` 를 단일 공백으로 정규화 후 매칭.
            OCR이 세로 레이아웃 제목("BILL\\nOF\\nLADING")을 개행으로 분리하는
            경우 여러 단어로 된 title_keywords 매칭을 복구하기 위함.
    Returns: (total_count, top_region_count)
    """
    kw_upper = keyword.upper()
    if normalize_ws:
        haystack = _WHITESPACE_RE.sub(' ', text_upper)
        # top region 경계도 정규화된 텍스트 기준으로 다시 계산
        total = haystack.count(kw_upper)
        top_region = haystack[:TITLE_REGION_CHARS].count(kw_upper)
        return total, top_region
    total = text_upper.count(kw_upper)
    top_region = text_upper[:TITLE_REGION_CHARS].count(kw_upper)
    return total, top_region


def classify_text(text: str) -> ClassificationResult:
    """
    텍스트 → 문서 타입 판정. v2 위치 가중치 적용.
    """
    if not text:
        return ClassificationResult('Unknown', 0.0, needs_vlm_fallback=True)

    text_upper = text.upper()
    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}

    for type_name, spec in TYPE_SPECS.items():
        score = 0.0
        kws = []

        # 1) title_keywords (제목 영역 가중치 ×3)
        # OCR이 세로 레이아웃 제목을 개행으로 분리("BILL\nOF\nLADING")하는 경우
        # 대비해 공백 정규화 매칭 병행
        for kw in spec['title_keywords']:
            total, top = _count_match_with_position(text, text_upper, kw)
            if total == 0 and ' ' in kw:
                total, top = _count_match_with_position(
                    text, text_upper, kw, normalize_ws=True)
            if total == 0:
                continue
            # 기본 매치: 베이스 점수 + priority
            base = 10 + spec['priority'] / 10
            # 제목 영역 보너스
            title_bonus = top * (TITLE_WEIGHT_MULTIPLIER - 1) * base
            score += base + title_bonus
            kws.append(kw)

        # 2) body_keywords (각 +2, 상단 영역이면 ×3 = +6)
        body_found = 0
        for kw in spec['body_keywords']:
            total, top = _count_match_with_position(text, text_upper, kw)
            if total == 0:
                continue
            # 기본 +2, 상단 등장은 ×3
            score += 2 + (top * 2 * (TITLE_WEIGHT_MULTIPLIER - 1))
            kws.append(kw)
            body_found += 1
            if body_found >= 15:
                break

        # 3) signature_patterns (매우 강력한 시그널: +15)
        for pat in spec.get('signature_patterns', []):
            if re.search(pat, text, re.IGNORECASE):
                score += 15
                kws.append(f'[pattern] {pat}')

        # 4) negative_if_near: 부정 시그널 (해당 키워드가 텍스트에 있으면 큰 감점)
        for neg_kw in spec.get('negative_if_near', []):
            if neg_kw.upper() in text_upper:
                score -= 40  # 분류 차단 수준의 감점
                kws.append(f'[neg] {neg_kw}')

        if score > 0:
            scores[type_name] = score
            matched[type_name] = kws

    if not scores:
        return ClassificationResult(
            'Unknown', 0.0,
            scores={},
            needs_vlm_fallback=True,
        )

    best_type = max(scores, key=scores.get)

    # 신뢰도: top1과 top2 margin 기반
    sorted_scores = sorted(scores.values(), reverse=True)
    top1 = sorted_scores[0]
    top2 = sorted_scores[1] if len(sorted_scores) > 1 else 0
    if top1 > 0:
        margin = (top1 - top2) / top1
        confidence = min(1.0, (top1 / 50) * 0.5 + margin * 0.5)
    else:
        confidence = 0.0

    needs_vlm = confidence < 0.5

    return ClassificationResult(
        doc_type=best_type,
        confidence=confidence,
        matched_keywords=matched.get(best_type, []),
        scores=scores,
        needs_vlm_fallback=needs_vlm,
    )


def classify_ocr_result(ocr_result: dict) -> ClassificationResult:
    """
    ocr_engine.py의 결과 dict → 분류.
    문서 단위 결과 (full_text 필드) 또는 페이지 단위 (raw_text) 모두 지원.
    """
    if 'full_text' in ocr_result:
        text = ocr_result['full_text']
    elif 'raw_text' in ocr_result:
        text = ocr_result['raw_text']
    else:
        text = ''
    return classify_text(text)


# ────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import io
    import json
    import sys
    from pathlib import Path

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    # 기본: 방금 OCR 돌린 0001 문서 결과 사용
    if len(sys.argv) >= 2:
        ocr_json = Path(sys.argv[1])
    else:
        ocr_json = Path('ocr_storage/preprocessed/수입_수출계약서_0001/_ocr_result.json')

    result = json.load(open(ocr_json, encoding='utf-8'))
    classification = classify_ocr_result(result)

    print(f'=== {result.get("document_id", "?")} ===')
    print(f'[결과] {classification.doc_type} (신뢰도 {classification.confidence:.2f})')
    print(f'[매치 키워드] {classification.matched_keywords[:8]}')
    print(f'\n[전체 점수]')
    for t, s in sorted(classification.scores.items(), key=lambda x: -x[1]):
        print(f'  {t}: {s:.1f}')
    if classification.needs_vlm_fallback:
        print('\n⚠ 신뢰도 낮음 → Gemma 4 VLM 재분류 필요')
