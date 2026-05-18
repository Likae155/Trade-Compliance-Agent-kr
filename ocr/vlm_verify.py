"""
Step 3.9.2: VLM (Vision-Language Model) 재검증 모듈

Ollama 기반 VLM 클라이언트. 두 모델 병행 테스트 용이하도록 공통 인터페이스.

용도:
  1. 저신뢰도 OCR 블록 재읽기
  2. 전체 페이지 재OCR (비교 테스트용)
  3. 문서 타입 재분류 (분류기가 애매한 경우)

지원 모델:
  - gemma4:e4b-ocr  (Gemma 4 E4B OCR)
  - qwen2.5vl:7b  (Qwen 2.5 VL 7B)

절대 원칙 (기획서 준수):
  - 원본 오타 수정 금지
  - 읽힌 그대로 반환
  - 읽을 수 없으면 [UNREADABLE]
  - 외부 API 호출 절대 없음 (Ollama는 로컬)
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

# Add project root for src.llm_engine_v2 imports
import sys
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.llm_engine_v2 import get_engine_v2


OLLAMA_HOST = 'http://localhost:11434'
OLLAMA_TIMEOUT = 90   # 페이지 당 최대 90초


# ────────────────────────────────────────────────────────────
# Verification Prompts (Audit & Integrity)
# ────────────────────────────────────────────────────────────
SYSTEM_PROMPT_AUDITOR = """You are a precision Vision OCR engine for trade documents. 
Your goal is to transcribe every single visible character from the image without exception.

STRICT RULES:
1. [Absolute Transcription]: Read and write EVERYTHING you see. If there is a tiny text at the bottom or a handwritten note, you MUST include it.
2. [No Summarization]: Do not summarize or condense any part of the document. If a section looks repetitive, transcribe it exactly as it is repeated.
3. [Spatial Sequencing]: This document may have TWO COLUMNS or complex tables. Read from left-to-right, then top-to-bottom. Do not skip the right-side column (e.g., Buyer details).
4. [Zero Edit Policy]: Keep all Hanja, special characters, and original typos (e.g., "SOUL" instead of "Seoul"). DO NOT correct grammar.
5. [Table Detail]: Extract tables row-by-row. If a cell is empty, leave it blank, but do not skip the row.
6. [No Markdown]: Output raw text only. Do not use Markdown table syntax (|---|), as it can cause data loss during parsing."""

# [수정] 블록 재확인 프롬프트: '완벽하게' 대신 '모든 글자 전사' 강조
PROMPT_RECHECK_BLOCK = """
Transcribe EVERY SINGLE character in this image. 
Maintain the exact sequence of text, including values in tables and both columns. 
Zero omission is the priority.
"""

# [수정] 전체 페이지 감사 프롬프트: '누락 금지'를 넘어 '전체 텍스트 추출' 강제
PROMPT_AUDIT_PAGE = """
Perform a full-scale transcription of this page. 
You must capture every word from the Seller/Buyer sections, all table rows, and any small print at the borders. 
Read horizontally across columns to ensure no data on the right side is skipped. 
DO NOT SUMMARIZE. Output the raw, complete text.
"""

# 5/6 — 하이브리드 OCR 병합용 (ODL + Gemma 두 결과 합치기)
SYSTEM_PROMPT_MERGE = """You are a mechanical data integration engine for trade documents. 
Your mission is to unify two OCR sources into one COMPLETE text without losing a single character.

STRICT RULES:
1. [ZERO OMISSION]: Do not summarize. Do not skip any line, word, or character present in either Source A or Source B.
2. [INFORMATION ADDITIVITY]: If Source B contains information that Source A missed, you MUST include it. The final output must be as long or longer than the longest source.
3. [DATA INTEGRITY]: Do not fix typos, do not improve flow. Every single character must be accounted for.
4. [LAYOUT PRIORITY]: Follow the structural layout (headers, columns, tables) of ENGINE_VLM, but fill the content using the precision of ENGINE_ODL.
5. [NO FILLER]: Return only the merged raw text. No "Here is the result" or explanations."""

PROMPT_MERGE = """
[SOURCE A: ENGINE_ODL]
{text_a}

[SOURCE B: ENGINE_VLM]
{text_b}

[COMMAND]
Integrate every single detail from Source A and Source B. 
Ensure all terms, values, and punctuation marks are preserved. 
If there is a conflict, prioritize Source A's spelling but follow Source B's positioning. 
DO NOT SUMMARIZE.
"""


# ────────────────────────────────────────────────────────────
# 결과 스키마
# ────────────────────────────────────────────────────────────
@dataclass
class VLMResult:
    model: str
    prompt_type: str
    image_path: str
    response: str
    elapsed_seconds: float
    error: Optional[str] = None


# ────────────────────────────────────────────────────────────
# 통합 Gemma VLM 클라이언트
# ────────────────────────────────────────────────────────────
class OllamaVLM:
    """Ollama API 기반 Gemma VLM 호출."""

    def __init__(self, model: str = "gemma4:e4b-ocr", **kwargs):
        self.model_name = model
        # 모델 이름에 따라 타입 결정 (ocr 키워드 우선 확인)
        if "ocr" in model.lower():
            self.engine = get_engine_v2(model_type="ocr")
        else:
            self.engine = get_engine_v2(model_type="general")

    def _encode_image(self, image_path: str | Path) -> str:
        """이미지 to base64."""
        data = Path(image_path).read_bytes()
        return base64.b64encode(data).decode('utf-8')

    def call(self, prompt: str, image_path: str | Path,
              system: Optional[str] = None,
              temperature: float = 0.2) -> VLMResult:
        """단일 이미지 + 프롬프트 to 응답."""
        image_b64 = self._encode_image(image_path)
        
        t0 = time.time()
        try:
            # 통합 엔진의 vision_ocr 호출
            full_prompt = f"{system}\n\n{prompt}" if system else prompt
            print(f"  [VLM] Calling vision_ocr for {Path(image_path).name}...")
            content = self.engine.vision_ocr(image_b64, prompt=full_prompt, temperature=temperature)
            print(f"  [VLM] Response (first 100 chars): {content[:100]!r}")
            elapsed = time.time() - t0

            return VLMResult(
                model=self.model_name,
                prompt_type='chat',
                image_path=str(image_path),
                response=content,
                elapsed_seconds=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  [VLM] Error during vision_ocr: {e}")
            return VLMResult(
                model=self.model_name,
                prompt_type='chat',
                image_path=str(image_path),
                response='',
                elapsed_seconds=elapsed,
                error=f'{type(e).__name__}: {e}',
            )

    # ────────────────────────────────────────
    # High-level API
    # ────────────────────────────────────────
    def recheck_block(self, image_path: Path, ocr_text: str) -> VLMResult:
        """Re-verify low-confidence OCR blocks."""
        prompt = PROMPT_RECHECK_BLOCK.format(ocr_text=ocr_text)
        return self.call(prompt, image_path, system=SYSTEM_PROMPT_AUDITOR)

    def full_page_audit(self, image_path: Path, ocr_text: str = "") -> VLMResult:
        """Pure Vision OCR for the entire page."""
        prompt = PROMPT_AUDIT_PAGE
        return self.call(
            prompt,
            image_path,
            system=SYSTEM_PROMPT_AUDITOR,
        )

    # vlm_verify.py 내부 OllamaVLM 클래스에 추가

    def merge_ocr_results(self, text_odl: str, text_vlm: str) -> str:
        """
        Asks the VLM to merge two different OCR outputs into a single, high-integrity version.
        """
        # [영어 프롬프트] 데이터 무결성을 위해 엄격한 지침 부여
        prompt = f"""
    [Role]
    You are a mechanical data integration engine. Your SOLE purpose is to combine Result A and Result B without losing a SINGLE character. 
    You do NOT summarize. You do NOT edit. You do NOT omit.

    [Inputs]
    - Result A (from PDF structure): 
    \"\"\"{text_odl}\"\"\"

    - Result B (from Visual analysis): 
    \"\"\"{text_vlm}\"\"\"

    [STRICT INTEGRATION RULES]
    1. ZERO OMISSION: Every single piece of information present in either Result A or Result B MUST be included in the final output. If Source B has details that Source A lacks, you must append or integrate them.
    2. TOTAL VOLUME PRESERVATION: The final text length should generally be equal to or longer than the longest input. If the output is significantly shorter, you have failed the mission.
    3. NO REWRITING: Do not improve flow, do not fix grammar, and do not summarize multiple lines into one. 
    4. NUMERICAL SUPREMACY: If Result A and B show different numbers for the same field, use Result A's characters but place them according to Result B's layout.
    5. TABLE/COLUMN INTEGRITY: Trade documents often have side-by-side columns (Seller/Buyer). You must ensure both columns are fully transcribed sequentially. Do not merge them into a single summary.
    6. NO CONTEXTUAL GUESSING: If a word is "SOUL", keep it "SOUL". Do not change to "Seoul".
    7. Repeated meaningless data (ex. "the the the", "[quantity] [quantity] [quantity]", "D.\\nDate: 2025\\nMode: ABC CO, LTD.\\nDate: 2025\\nMode: ABC CO, LT") must be removed.

    [Output]
    Return ONLY the raw, integrated text. No explanations. No "Here is the merged text". 
    Start immediately with the data.
    """
        try:
            # 텍스트 전용 병합 (llm_engine_v2의 invoke 사용)
            # temperature=0 설정을 위해 직접 invoke 호출
            res = self.engine.invoke(prompt, temperature=0.0)
            return res.content.strip()
        except Exception as e:
            print(f"[Merge Error] {e}")
        return text_odl  # 실패 시 PDF 텍스트를 Fallback으로 사용

    def merge_two_ocr_texts(self, text_a: str, text_b: str,
                             temperature: float = 0.0) -> VLMResult:
        """Hybrid mode: Merge ODL(A) and Gemma VLM(B) results using LLM."""
        prompt = PROMPT_MERGE.format(text_a=text_a or '(empty)',
                                      text_b=text_b or '(empty)')
        
        t0 = time.time()
        try:
            # 텍스트 전용 병합 (invoke 사용)
            res = self.engine.invoke(prompt, system=SYSTEM_PROMPT_MERGE, temperature=temperature)
            content = res.content
            print(f"  [VLM] Merge response (first 100 chars): {content[:100]!r}")
            
            return VLMResult(
                model=self.model_name,
                prompt_type='merge',
                image_path='(text-only)',
                response=content,
                elapsed_seconds=time.time() - t0,
            )
        except Exception as e:
            print(f"  [VLM] Error during merge: {e}")
            return VLMResult(
                model=self.model_name,
                prompt_type='merge',
                image_path='(text-only)',
                response='',
                elapsed_seconds=time.time() - t0,
                error=f'{type(e).__name__}: {e}',
            )

    # ────────────────────────────────────────
    # 품질 평가 유틸
    # ────────────────────────────────────────
    @staticmethod
    def _count_articles(text: str) -> int:
        """텍스트에서 '제N조' 패턴 고유 개수 (한국 계약서 조항 회수 판단)."""
        import re
        if not text:
            return 0
        pat = re.compile(r'제\s*(\d+)\s*조')
        return len(set(pat.findall(text)))

    @staticmethod
    def _gibberish_ratio(text: str) -> float:
        """
        OCR/VLM 응답의 '비정상 토큰 비율' 대략 추정.
        """
        import re
        if not text:
            return 1.0
        total = len(text)
        valid = sum(1 for c in text if re.match(
            r"[A-Za-z0-9가-힣\s.,:;()/\-+*#@%\'\"!?\[\]{}<>\\&=$^`~|_·①-⑳]", c
        ))
        return 1.0 - (valid / total) if total else 1.0

    @staticmethod
    def _has_prompt_leakage(text: str) -> bool:
        """VLM이 프롬프트를 그대로 재생한 경우 탐지."""
        import re
        t = text.lower()
        markers = [
            'do not correct', 'preserve line breaks', 'unreadable',
            'output only', 'read the image', 'rules (strict)',
            'output format', '[system_prompt]',
        ]
        hits = sum(1 for m in markers if m in t)
        return hits >= 2

    # ────────────────────────────────────────
    # 병합 의사결정 (VLM vs 원본)
    # ────────────────────────────────────────
    def _decide_merge(self, orig_text: str, vlm_text: str,
                       vlm_error: str = None) -> tuple[str, str]:
        """
        원본 OCR과 VLM 응답 중 어느 쪽을 채택할지 결정.
        """
        if vlm_error:
            return 'original', f'vlm_error:{vlm_error[:40]}'
        if not vlm_text or len(vlm_text) < 20:
            return 'original', 'vlm_too_short'

        if self._has_prompt_leakage(vlm_text):
            return 'original', 'vlm_prompt_leakage'

        v_gib = self._gibberish_ratio(vlm_text)
        o_gib = self._gibberish_ratio(orig_text)
        if v_gib > 0.25 and v_gib > o_gib + 0.1:
            return 'original', f'vlm_gibberish({v_gib:.2f})'

        if len(orig_text) < 150 and len(vlm_text) > len(orig_text) * 2:
            return 'vlm', 'orig_too_short'

        v_arts = self._count_articles(vlm_text)
        o_arts = self._count_articles(orig_text)
        if v_arts > o_arts and v_arts >= 3:
            return 'vlm', f'more_articles({o_arts}->{v_arts})'
        if o_arts >= 3 and v_arts < o_arts * 0.6:
            return 'original', f'vlm_lost_articles({o_arts}->{v_arts})'

        if len(vlm_text) > len(orig_text) * 1.2 and v_gib < 0.15:
            return 'vlm', f'longer_clean({len(orig_text)}->{len(vlm_text)})'

        return 'original', 'default'

    # ────────────────────────────────────────
    # 선택적 재검증 (문서 단위)
    # ────────────────────────────────────────
    def recheck_document(
        self,
        ocr_result: dict,
        preprocessed_dir: Path,
        confidence_threshold: float = 0.75,
        min_chars_per_page: int = 300,
        max_pages_to_recheck: int = 6,
        article_drop_threshold: float = 0.5,
    ) -> dict:
        """
        OCR 결과에서 품질 의심 페이지를 식별 -> VLM으로 재OCR -> 지능적 병합.
        """
        if ocr_result.get('engine') in ('hybrid', 'odl'):
            return ocr_result

        preprocessed_dir = Path(preprocessed_dir)
        pages = ocr_result.get('pages', [])
        is_primary_vlm = ocr_result.get('engine') == 'vlm_only'
        
        if not pages and not is_primary_vlm:
            return ocr_result

        rechecks_needed = []
        
        if is_primary_vlm:
            images = sorted(preprocessed_dir.glob('page_*.png'))
            for img_path in images:
                page_num = int(img_path.stem.split('_')[-1])
                rechecks_needed.append(({
                    'page_number': page_num,
                    'raw_text': '',
                    'avg_confidence': 0.0,
                    'n_blocks': 0
                }, ['primary_vlm_request']))
        else:
            for page in pages:
                n_blocks = page.get('n_blocks', 0)
                avg_conf = page.get('avg_confidence', 0)
                text = page.get('raw_text', '')

                needs = False
                reasons = []

                if n_blocks > 0 and avg_conf < confidence_threshold:
                    needs = True
                    reasons.append(f'low_conf({avg_conf:.2f})')
                if len(text) < min_chars_per_page and n_blocks > 0:
                    needs = True
                    reasons.append(f'short_text({len(text)})')
                if n_blocks == 0:
                    needs = True
                    reasons.append('no_blocks')
                
                page_articles = self._count_articles(text)
                other_articles_total = sum(
                    self._count_articles(p.get('raw_text', '')) for p in pages
                    if p.get('page_number') != page.get('page_number')
                )
                if (other_articles_total >= 3 and page_articles == 0 and len(text) > 200):
                    needs = True
                    reasons.append('no_articles_suspect')
                
                if self._gibberish_ratio(text) > 0.2 and len(text) > 100:
                    needs = True
                    reasons.append('high_gibberish')

                if needs:
                    rechecks_needed.append((page, reasons))

        if len(rechecks_needed) > max_pages_to_recheck:
            def prio(item):
                page, reasons = item
                if 'low_conf' in ' '.join(reasons): return 0
                if 'short_text' in ' '.join(reasons): return 1
                if 'no_articles_suspect' in ' '.join(reasons): return 2
                return 3
            rechecks_needed.sort(key=prio)
            rechecks_needed = rechecks_needed[:max_pages_to_recheck]

        rechecked_pages = []
        t_total = time.time()

        for page, reasons in rechecks_needed:
            page_num = page.get('page_number', 1)
            img_path = preprocessed_dir / f'page_{page_num:02d}.png'
            if not img_path.exists():
                continue

            orig_text = page.get('raw_text', '')
            t0 = time.time()
            vlm_result = self.full_page_audit(img_path, ocr_text=orig_text)
            elapsed = time.time() - t0

            vlm_text = vlm_result.response

            chosen, reason = self._decide_merge(orig_text, vlm_text, vlm_result.error)
            final_text = vlm_text if chosen == 'vlm' else orig_text

            rechecked_pages.append({
                'page_number': page_num,
                'reasons': reasons,
                'original_length': len(orig_text),
                'vlm_length': len(vlm_text),
                'original_articles': self._count_articles(orig_text),
                'vlm_articles': self._count_articles(vlm_text),
                'vlm_gibberish': round(self._gibberish_ratio(vlm_text), 3),
                'original_gibberish': round(self._gibberish_ratio(orig_text), 3),
                'chosen': chosen,
                'decision_reason': reason,
                'vlm_elapsed': elapsed,
                'vlm_error': vlm_result.error,
                'final_text': final_text,
                'vlm_text': vlm_text,
            })

        merged = dict(ocr_result)
        # 업데이트된 텍스트 병합
        for rp in rechecked_pages:
            p_idx = rp['page_number'] - 1
            if 0 <= p_idx < len(merged['pages']):
                merged['pages'][p_idx]['raw_text'] = rp['final_text']
        
        merged['full_text'] = '\n\n'.join([p['raw_text'] for p in merged['pages']])
        
        merged['vlm_rechecked'] = {
            'model': self.model_name,
            'threshold': confidence_threshold,
            'min_chars': min_chars_per_page,
            'n_pages_rechecked': len(rechecked_pages),
            'total_elapsed': time.time() - t_total,
            'details': rechecked_pages,
        }

        if rechecked_pages:
            vlm_by_page = {r['page_number']: r for r in rechecked_pages}
            merged_pages_text = []
            
            if is_primary_vlm:
                # 모든 결과가 VLM에서 온 경우
                for r in rechecked_pages:
                    merged_pages_text.append(r['final_text'])
                merged['n_pages'] = len(rechecked_pages)
                merged['avg_confidence'] = 0.95
            else:
                for page in pages:
                    p_num = page.get('page_number', 1)
                    if p_num in vlm_by_page and vlm_by_page[p_num]['chosen'] == 'vlm':
                        merged_pages_text.append(vlm_by_page[p_num]['final_text'])
                    else:
                        merged_pages_text.append(page.get('raw_text', ''))
            
            merged['full_text'] = '\n\n'.join(merged_pages_text)

        return merged


def check_ollama() -> dict:
    """Ollama 서버·모델 상태 확인."""
    try:
        resp = requests.get(f'{OLLAMA_HOST}/api/tags', timeout=5)
        resp.raise_for_status()
        models = [m['name'] for m in resp.json().get('models', [])]
        return {
            'ok': True,
            'models': models,
            'has_gemma4_e4b_ocr': any('gemma4:e4b-ocr' in m for m in models),
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


if __name__ == '__main__':
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    status = check_ollama()
    print('=== Ollama Status ===')
    print(json.dumps(status, ensure_ascii=False, indent=2))
