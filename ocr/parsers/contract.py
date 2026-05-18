"""
SalesContract 파서 — 무역 계약서.

핵심 작업:
  1. 조항 세그먼트 (제N조 ~ 다음 제(N+1)조 전까지)
  2. 각 조항의 제목·본문 분리
  3. 서문(preamble) 추출
  4. 서명 블록 추출
  5. 표(Table) 영역 식별 (선적 조건표 등)

조항 단위로 쪼개놓으면 Step 5 RAG 분석 엔진에서 조항별로
법령 DB와 교차검증 가능.
"""
from __future__ import annotations
import re

from .base import BaseParser, ParseResult


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
    import logging
    logging.basicConfig(filename='ocr_debug.log', level=logging.INFO, force=True)
    logging.info(f"[DEBUG] Parsing clauses: Total text length: {len(text)}")
    
    headers = _find_article_headers(text)
    if not headers:
        # 헤더가 없으면 텍스트 전체를 하나의 항으로 처리
        return [{'article_no': 0, 'title': '전체', 'body': _split_article_body(text)}]

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
class SalesContractParser(BaseParser):
    """무역 계약서 파서."""
    DOCUMENT_TYPE = 'SalesContract'

    def _extract_type_specific(self, text: str, ocr_result: dict,
                                result: ParseResult) -> None:
        # 조항 추출
        clauses = _extract_clauses(text)
        # 서문·서명
        preamble = _extract_preamble(text, clauses)
        signature = _extract_signature_block(text)

        result.type_specific['clauses'] = clauses
        result.type_specific['n_clauses'] = len(clauses)
        result.type_specific['preamble'] = preamble
        result.type_specific['signature_block'] = signature

        # Warning
        if not clauses:
            result.warnings.append('NO_CLAUSES_DETECTED')
        if not signature['found']:
            result.warnings.append('NO_SIGNATURE_BLOCK')


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