"""
################################################################################
# 범용 계약 조항 추출기 (ocr/parsers/clause_extractor.py)
# 
# [개발자 가이드]
# - 계약서 텍스트를 입력받아 법리 분석(Legal RAG)에 최적화된 '평탄한(Flat)' 
#   Clause 리스트로 구조화합니다.
# - 제N조(한글) 또는 Article N(영문) 형태의 헤더를 패턴으로 탐지합니다.
# - 헤더 패턴 탐지 실패 시 빈 줄 기준(paragraph fallback)으로 분할합니다.
# 
# [주의사항]
# - 정규식(Regex) 기반 패턴 매칭을 사용하므로, 계약서 형식이 비표준일 경우 
#   추출 결과가 누락되거나 병합될 수 있습니다. (이 경우 파서 패턴 업데이트 필요)
# - 법령 RAG의 정확도는 본 모듈이 추출한 텍스트의 정합성에 크게 의존합니다.
################################################################################
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional


# ────────────────────────────────────────────────────────────
# Clause 데이터 구조 (평탄)
# ────────────────────────────────────────────────────────────
@dataclass
class Clause:
    """조항 1건 — RAG 입력용 평탄 구조."""
    clause_id: str             # 'article_1', '제5조', 'para_3' 등
    title: str                 # 조항 제목 (없으면 '')
    text: str                  # 본문
    start: int                 # 원본 텍스트 내 시작 오프셋
    end: int
    article_no: Optional[str] = None  # 번호 (문자열: "1", "1.2", "V")
    lang: str = 'auto'         # 'ko' | 'en' | 'mixed' | 'paragraph'


# ────────────────────────────────────────────────────────────
# 패턴
# ────────────────────────────────────────────────────────────

# 한국어 — 기존 contract.py 패턴 참조하되 평탄용으로 단순화
_KO_PATTERNS = [
    # 제N조 (제목) — 가장 구체적
    re.compile(
        r'제\s*(?P<no>\d+)\s*조\s*[\(\[【]\s*(?P<title>[^\)\]】\n]{1,40})\s*[\)\]】]',
        re.MULTILINE,
    ),
    # 제N조 제목 (괄호 없음, 같은 줄 뒤)
    re.compile(
        r'제\s*(?P<no>\d+)\s*조\s+(?P<title>[가-힣A-Za-z0-9·,\.·\s]{1,40}?)(?=\n|$|①|②|\d+\.\s)',
        re.MULTILINE,
    ),
    # 제N조만
    re.compile(
        r'제\s*(?P<no>\d+)\s*조(?!\w)',
        re.MULTILINE,
    ),
]

# 영문
_EN_PATTERNS = [
    # Article N. Title / Article N: Title / Article N — Title / Article N Title
    re.compile(
        r'(?:^|\n)\s*ARTICLE\s+(?P<no>\d+)(?:\s*[\.\:\-—–]\s*|\s+)(?P<title>[A-Za-z][A-Za-z0-9\s,\-&\'()]{1,60}?)(?=\n|$)',
        re.IGNORECASE | re.MULTILINE,
    ),
    # Section N. Title
    re.compile(
        r'(?:^|\n)\s*SECTION\s+(?P<no>\d+)(?:\s*[\.\:\-—–]\s*|\s+)(?P<title>[A-Za-z][A-Za-z0-9\s,\-&\'()]{1,60}?)(?=\n|$)',
        re.IGNORECASE | re.MULTILINE,
    ),
    # Clause N
    re.compile(
        r'(?:^|\n)\s*CLAUSE\s+(?P<no>\d+)(?:\s*[\.\:\-—–]\s*|\s+)(?P<title>[A-Za-z][A-Za-z0-9\s,\-&\'()]{1,60}?)(?=\n|$)',
        re.IGNORECASE | re.MULTILINE,
    ),
    # 제목 없는 버전 (Article 3 만)
    re.compile(
        r'(?:^|\n)\s*ARTICLE\s+(?P<no>\d+)(?=\s*\n)',
        re.IGNORECASE | re.MULTILINE,
    ),
    # 로마숫자: ARTICLE I. / ARTICLE II —
    re.compile(
        r'(?:^|\n)\s*ARTICLE\s+(?P<no>[IVX]+)(?:\s*[\.\:\-—–]\s*|\s+)(?P<title>[A-Za-z][A-Za-z0-9\s,\-&\'()]{1,60}?)(?=\n|$)',
        re.MULTILINE,
    ),
]


# ────────────────────────────────────────────────────────────
# 헤더 찾기
# ────────────────────────────────────────────────────────────
def _find_headers(text: str, patterns: list[re.Pattern], lang: str) -> list[dict]:
    """패턴 순회해서 헤더 위치 수집. 중복 제거."""
    hits: list[dict] = []
    for rank, pat in enumerate(patterns):
        for m in pat.finditer(text):
            title = ''
            if 'title' in m.groupdict():
                title = (m.group('title') or '').strip()
            hits.append({
                'no': m.group('no'),
                'title': title,
                'start': m.start(),
                'end': m.end(),
                'rank': rank,
                'lang': lang,
                'raw': m.group(0).strip(),
            })

    if not hits:
        return []

    # 위치 근접 중복 제거 (10자 이내 = 같은 헤더에 대한 다른 패턴 매칭)
    hits.sort(key=lambda h: (h['start'], h['rank']))
    unique = []
    seen_starts: list[int] = []
    for h in hits:
        if any(abs(h['start'] - s) < 10 for s in seen_starts):
            continue
        seen_starts.append(h['start'])
        unique.append(h)

    # 조항 번호별 첫 등장만 (본문 참조 제외)
    by_no = {}
    for h in unique:
        no = h['no']
        if no not in by_no:
            by_no[no] = h

    return sorted(by_no.values(), key=lambda h: h['start'])


def _detect_language(text: str) -> Literal['ko', 'en', 'mixed']:
    """대략 언어 감지 — 한글 음절 비율 기반."""
    if not text:
        return 'en'
    ko_chars = sum(1 for c in text if '가' <= c <= '힣')
    total_letters = sum(1 for c in text if c.isalpha() or '가' <= c <= '힣')
    if total_letters == 0:
        return 'en'
    ko_ratio = ko_chars / total_letters
    if ko_ratio > 0.5:
        return 'ko'
    if ko_ratio < 0.05:
        return 'en'
    return 'mixed'


# ────────────────────────────────────────────────────────────
# paragraph fallback
# ────────────────────────────────────────────────────────────
_PARA_SPLIT = re.compile(r'\n\s*\n+')


def _paragraph_fallback(text: str) -> list[Clause]:
    """헤더 못 찾을 때 — 빈 줄 기준 paragraph 분할."""
    clauses: list[Clause] = []
    pos = 0
    idx = 1
    for block in _PARA_SPLIT.split(text):
        body = block.strip()
        if len(body) < 30:  # 너무 짧으면 스킵 (페이지 번호·헤더·서명 등)
            pos += len(block) + 2  # 대략 추정
            continue
        start = text.find(body, pos)
        if start < 0:
            start = pos
        clauses.append(Clause(
            clause_id=f'para_{idx}',
            title='',
            text=body,
            start=start,
            end=start + len(body),
            article_no=str(idx),
            lang='paragraph',
        ))
        pos = start + len(body)
        idx += 1
    return clauses


# ────────────────────────────────────────────────────────────
# 메인 추출
# ────────────────────────────────────────────────────────────
def extract_clauses(text: str,
                    language: Literal['auto', 'ko', 'en', 'both'] = 'auto',
                    min_body_chars: int = 10) -> list[Clause]:
    """
    계약서 텍스트 → 조항 리스트.

    Args:
        text: 원본 계약서 텍스트
        language: 'auto' 면 감지 후 적합 패턴. 'both' 면 한·영 패턴 전부.
        min_body_chars: 이 값 미만 본문은 제외

    Returns:
        Clause 리스트 (원본 텍스트 순서대로)
    """
    if not text or not text.strip():
        return []

    # 패턴 선택
    if language == 'auto':
        detected = _detect_language(text)
        if detected == 'ko':
            patterns_ko = _KO_PATTERNS
            patterns_en: list[re.Pattern] = []
        elif detected == 'en':
            patterns_ko = []
            patterns_en = _EN_PATTERNS
        else:
            patterns_ko = _KO_PATTERNS
            patterns_en = _EN_PATTERNS
    elif language == 'ko':
        patterns_ko, patterns_en = _KO_PATTERNS, []
    elif language == 'en':
        patterns_ko, patterns_en = [], _EN_PATTERNS
    else:  # 'both'
        patterns_ko, patterns_en = _KO_PATTERNS, _EN_PATTERNS

    # 헤더 수집
    ko_hits = _find_headers(text, patterns_ko, 'ko') if patterns_ko else []
    en_hits = _find_headers(text, patterns_en, 'en') if patterns_en else []
    all_hits = sorted(ko_hits + en_hits, key=lambda h: h['start'])

    # 위치 중복 재정리
    dedup = []
    last_start = -100
    for h in all_hits:
        if h['start'] - last_start < 10:
            continue
        dedup.append(h)
        last_start = h['start']

    # 헤더 없으면 paragraph fallback
    if not dedup:
        return _paragraph_fallback(text)

    # 헤더 사이 본문으로 Clause 구성
    clauses: list[Clause] = []
    for i, h in enumerate(dedup):
        body_start = h['end']
        body_end = dedup[i + 1]['start'] if i + 1 < len(dedup) else len(text)
        body = text[body_start:body_end].strip()
        if len(body) < min_body_chars:
            continue
        # clause_id: 언어+번호
        if h['lang'] == 'ko':
            clause_id = f'제{h["no"]}조'
        else:
            clause_id = f'article_{h["no"]}'
        clauses.append(Clause(
            clause_id=clause_id,
            title=h['title'],
            text=body,
            start=body_start,
            end=body_end,
            article_no=h['no'],
            lang=h['lang'],
        ))

    return clauses


# ────────────────────────────────────────────────────────────
# CLI — 스모크 테스트
# ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    test_cases = [
        # 한국어 계약서
        ('ko',
         '''
매매계약서

본 계약은 갑(주식회사 ABC)과 을(XYZ Co.) 간의 물품 매매에 관한 계약이다.

제1조 (목적)
본 계약은 갑이 을로부터 전자부품을 구매함에 있어 그 조건을 정함을 목적으로 한다.

제2조 (물품의 인도)
① 을은 2026년 6월 30일까지 계약 물품을 지정 장소에 인도한다.
② 인도 지연 시 일당 0.1%의 지연손해금을 지급한다.

제3조 (지급조건)
대금은 L/C 90일 Usance 조건으로 지급한다.

IN WITNESS WHEREOF, 양 당사자는 서명한다.
'''),
        # 영문 계약서
        ('en',
         '''
SALES AGREEMENT

THIS AGREEMENT is made between ABC Corp. ("Seller") and XYZ Ltd. ("Buyer").

Article 1. Goods
The Seller shall sell and the Buyer shall purchase electronic components
as specified in Exhibit A.

Article 2. Delivery
Delivery shall be made FOB Busan no later than June 30, 2026.
Risk of loss passes to the Buyer upon delivery at the port of shipment.

Section 3. Payment
Payment shall be made by irrevocable letter of credit at sight,
confirmed by a prime bank acceptable to the Seller.

Article 4. Governing Law
This Agreement shall be governed by the laws of the Republic of Korea.

IN WITNESS WHEREOF, the parties have executed this Agreement.
'''),
        # 번호 헤더 없는 케이스 (fallback 테스트)
        ('fallback',
         '''
TERMS AND CONDITIONS

The goods shall be of merchantable quality and free from defects.

Delivery will be made within thirty days of receipt of the purchase order.

Any disputes arising shall be resolved by arbitration in Seoul, Korea.
'''),
    ]

    for name, text in test_cases:
        print(f'\n{"=" * 70}')
        print(f'=== 케이스: {name} (text len={len(text)}) ===')
        print('=' * 70)
        clauses = extract_clauses(text)
        print(f'추출 조항 수: {len(clauses)}')
        for c in clauses:
            print(f'\n  [{c.clause_id}] lang={c.lang}, title={c.title!r}')
            print(f'    article_no={c.article_no}, pos=[{c.start}-{c.end}]')
            preview = c.text.replace('\n', ' ')[:80]
            print(f'    text: {preview}...')
