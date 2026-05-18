"""OCR 라우팅 — text-PDF 면 OpenDataLoader, 스캔/이미지면 PaddleOCR.

4/27 §14 OpenDataLoader 평가 결과:
  - 5.9x 빠름 (Java 백엔드, conda openjdk=21)
  - 정확도는 PaddleOCR 우세 (스캔/저화질 PDF에서)
  - 결론: 메인 OCR 교체는 보류, 라우팅(Phase 2)으로 보존

설계:
  1. `is_text_extractable_pdf()` — pypdf 로 첫 N 페이지 추출 시도
  2. `extract_via_odl()`         — OpenDataLoader 호출 (text 포맷)
  3. `route_ocr()`              — 라우팅 결정 + 호출

기존 `OCRPipeline.process()` 와 같이 쓰려면 `route_ocr()` 의 `paddle_engine`
콜러블에 wrapper 를 넣어주면 됨 (예: `lambda p: pipeline.process(p)`).
"""
from __future__ import annotations

import os
import sys
import time
import cv2
import numpy as np
from pathlib import Path
from typing import Callable, Optional, List, Dict, Any


# Windows + conda env: python.exe 직접 호출 시 env 의 Library/bin 이 PATH 에
# 잡히지 않아 java 등 외부 바이너리 호출 실패. 자동으로 PATH 에 prepend.
_env_bin = Path(sys.executable).parent / 'Library' / 'bin'
if _env_bin.exists() and str(_env_bin) not in os.environ.get('PATH', ''):
    os.environ['PATH'] = str(_env_bin) + os.pathsep + os.environ.get('PATH', '')


IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.gif', '.webp'}


def is_text_extractable_pdf(pdf_path: Path,
                             min_chars_per_page: int = 50,
                             sample_pages: int = 3) -> tuple[bool, dict]:
    """pypdf 로 첫 N 페이지 텍스트 추출 시도해 text-PDF 여부 판별.

    Returns:
        (is_text_pdf, info_dict)
        info_dict: n_pages, sampled_pages, avg_chars_per_page, page_chars[, error]
    """
    pdf_path = Path(pdf_path)
    if pdf_path.suffix.lower() in IMAGE_EXTS:
        return False, {'reason': 'image_input', 'ext': pdf_path.suffix}
    if pdf_path.suffix.lower() != '.pdf':
        return False, {'reason': 'non_pdf', 'ext': pdf_path.suffix}
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        n_pages = len(reader.pages)
        page_chars: list[int] = []
        for i, page in enumerate(reader.pages[:sample_pages]):
            text = (page.extract_text() or '').strip()
            page_chars.append(len(text))
        total = sum(page_chars)
        avg = total / max(1, len(page_chars))
        return avg >= min_chars_per_page, {
            'n_pages': n_pages,
            'sampled_pages': len(page_chars),
            'avg_chars_per_page': round(avg, 1),
            'page_chars': page_chars,
            'threshold': min_chars_per_page,
        }
    except Exception as e:
        return False, {'reason': 'pypdf_error',
                       'error': f'{type(e).__name__}: {e}'}


def extract_via_odl(file_path: Path, out_dir: Path) -> dict:
    """OpenDataLoader 로 텍스트 추출. 호출 결과 통일 dict 반환.
    PDF뿐만 아니라 이미지 파일에서도 작동함 (사용자 확인).
    """
    file_path = Path(file_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        from opendataloader_pdf import convert
        convert(input_path=str(file_path), output_dir=str(out_dir),
                format='text', quiet=True)
        elapsed = time.time() - t0
        
        # 파일명 매칭 문제 해결을 위한 로직 (robust glob)
        txt_files = list(out_dir.rglob('*.txt'))
        text = ''
        if txt_files:
            # 파일 이름순(페이지 순서)으로 정렬하여 모두 병합
            txt_files.sort()
            text = '\n\n'.join([p.read_text(encoding='utf-8') for p in txt_files])
        
        if not text:
            # 기존 방식 fallback 시도
            txt_path = out_dir / f'{file_path.stem}.txt'
            if txt_path.exists():
                text = txt_path.read_text(encoding='utf-8')
        
        return {
            'ok': True if text else False,
            'engine': 'odl',
            'elapsed_sec': round(elapsed, 3),
            'full_text': text,
            'n_chars': len(text),
            'error': None if text else 'no_text_found_in_odl_output',
        }
    except Exception as e:
        return {
            'ok': False,
            'engine': 'odl',
            'elapsed_sec': round(time.time() - t0, 3),
            'full_text': '',
            'n_chars': 0,
            'error': f'{type(e).__name__}: {e}',
        }


def route_ocr(file_path,
              paddle_engine: Optional[Callable] = None,
              odl_out_dir: Optional[Path] = None,
              force_engine: Optional[str] = None,
              min_chars_per_page: int = 50) -> dict:
    """OCR 라우팅 — text-PDF 면 ODL, 이미지거나 스캔본이면 PaddleOCR/VLM.
    단, ODL이 이미지 OCR을 지원하므로 이미지에서도 선택 가능하도록 수정.
    """
    file_path = Path(file_path)
    is_image = file_path.suffix.lower() in IMAGE_EXTS

    if force_engine == 'odl':
        is_text, info = True, {'forced': True}
    elif force_engine == 'paddle':
        is_text, info = False, {'forced': True}
    else:
        is_text, info = is_text_extractable_pdf(file_path, min_chars_per_page)

    # ODL 사용 조건: 텍스트 PDF이거나 이미지 파일인 경우 (사용자 요청)
    use_odl = (is_text or is_image) and (odl_out_dir is not None)

    routing = {'engine': 'odl' if use_odl else 'paddle',
               'is_text_pdf': is_text, 'is_image': is_image, **info}

    if use_odl:
        result = extract_via_odl(file_path, odl_out_dir)
        result['routing'] = routing
        return result

    # paddle 호출
    if paddle_engine is None:
        return {
            'ok': False,
            'engine': 'paddle',
            'elapsed_sec': 0.0,
            'full_text': '',
            'n_chars': 0,
            'routing': routing,
            'error': 'paddle_engine callable not provided',
        }

    t0 = time.time()
    try:
        ret = paddle_engine(file_path)
        text = ret.get('full_text', '') if isinstance(ret, dict) else ''
        return {
            'ok': True,
            'engine': 'paddle',
            'elapsed_sec': round(time.time() - t0, 3),
            'full_text': text,
            'n_chars': len(text),
            'paddle_result': ret if isinstance(ret, dict) else None,
            'routing': routing,
            'error': None,
        }
    except Exception as e:
        return {
            'ok': False,
            'engine': 'paddle',
            'elapsed_sec': round(time.time() - t0, 3),
            'full_text': '',
            'n_chars': 0,
            'routing': routing,
            'error': f'{type(e).__name__}: {e}',
        }


# ────────────────────────────────────────────────────────────
# 5/6 — 하이브리드 OCR (ODL + Gemma 페이지별 분기)
# 합의: 임계치 50자/페이지, 병합 LLM = Gemma4 e2b
# ────────────────────────────────────────────────────────────
HYBRID_PAGE_CHAR_THRESHOLD = 50  # 페이지당 글자수 임계치
HYBRID_MERGE_MODEL = 'gemma4:e2b'  # ODL+Gemma 병합용 LLM


def extract_per_page_text(file_path: Path) -> list[dict]:
    """pypdf 로 페이지별 텍스트·글자수 추출. 이미지면 1페이지로 취급."""
    file_path = Path(file_path)
    if file_path.suffix.lower() in IMAGE_EXTS:
        return [{'page_num': 1, 'text': '', 'n_chars': 0}]
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(file_path))
        
        import logging
        logging.basicConfig(filename='ocr_debug.log', level=logging.INFO, force=True)
        logging.info(f"[DEBUG] extract_per_page_text: Total pages found: {len(reader.pages)}")
        
        pages = []
        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or '').strip()
            logging.info(f"[DEBUG] Page {i+1} chars: {len(text)}")
            pages.append({
                'page_num': i + 1,
                'text': text,
                'n_chars': len(text),
            })
        return pages
    except Exception as e:
        print(f"   [DEBUG] extract_per_page_text error: {e}")
        return [{'page_num': 1, 'text': '',
                 'n_chars': 0,
                 'error': f'{type(e).__name__}: {e}'}]


def extract_hybrid(file_path: Path,
                    pdf_to_image_fn: Callable,
                    image_output_root: Optional[Path] = None,
                    vlm_engine: Optional[Callable] = None,
                    threshold: int = HYBRID_PAGE_CHAR_THRESHOLD) -> dict:
    """하이브리드 OCR — ODL 결과와 Gemma 결과를 병합하여 정확도 극대화.
    PDF뿐만 아니라 이미지 파일도 지원하도록 업데이트됨.
    """
    file_path = Path(file_path)
    is_image = file_path.suffix.lower() in IMAGE_EXTS
    t0 = time.time()
    page_records = []
    
    try:
        # 1. 페이지 정보 구성 (이미지는 1페이지)
        pages = extract_per_page_text(file_path)
        for p in pages:
            page_records.append({
                'page_num': p['page_num'],
                'odl_chars': p['n_chars'],
                'gemma_used': False,
                'mode': 'odl',
                'elapsed_sec': 0.0,
            })

        # 2. ODL 로 전체 텍스트 추출 (이미지 OCR 포함)
        from pathlib import Path as _P
        # [FIX] 임시 폴더명 겹침 방지를 위해 타임스탬프 추가
        odl_out = _P('_hybrid_tmp_odl') / f"{file_path.stem}_{int(time.time())}"
        odl_out.mkdir(parents=True, exist_ok=True)
        odl_r = extract_via_odl(file_path, odl_out)
        odl_full = odl_r.get('full_text', '') if odl_r.get('ok') else ''

        # 3. 텍스트 부족 여부 판단 (이미지는 항상 부족하다고 간주하여 하이브리드 수행)
        any_short = is_image or any(p['n_chars'] < threshold for p in pages)
        
        # VLM 미설정이면 ODL 결과만 반환
        if not any_short or vlm_engine is None:
            # [FIX] odl_only 모드에서도 페이지 텍스트 강제 병합
            merged_text = '\n\n'.join([p['text'] for p in pages]).strip()
            return {
                'ok': True,
                'engine': 'hybrid',
                'elapsed_sec': round(time.time() - t0, 3),
                'full_text': merged_text,
                'n_chars': len(merged_text),
                'pages': page_records,
                'mode': 'odl_only',
                'merged_used': False,
                'threshold': threshold,
                'error': None,
            }

        # 4. 이미지 준비 (PDF면 PNG 변환, 이미지면 원본 사용)
        doc_id = f'_hybrid_{file_path.stem}_{int(time.time())}'
        if is_image:
            page_imgs = [file_path]
        else:
            meta = pdf_to_image_fn(file_path, doc_id)
            if image_output_root is None:
                from .pdf_to_image import OUTPUT_ROOT as _PDF2IMG_ROOT
                page_dir = _P(_PDF2IMG_ROOT) / doc_id
            else:
                page_dir = _P(image_output_root) / doc_id
            
            page_imgs = []
            if isinstance(meta, dict) and 'page_files' in meta:
                for pf in meta['page_files']:
                    page_imgs.append(page_dir / pf['file'])
            else:
                page_imgs = sorted(page_dir.glob('page_*.png'))

        # 5. Execute Parallel Extraction and Third-Party Merge
        final_pages = []
        for i, p in enumerate(pages):
            text_odl = p.get('text', '')
            n_chars = len(text_odl)
            
            # [수정 지점] Confidence Check 로직
            is_low_confidence = is_image or n_chars < threshold
            
            # 텍스트가 있더라도 gibberish(쓰레기값) 비율이 높으면 재검토 대상
            if not is_low_confidence:
                try:
                    if vlm_engine._gibberish_ratio(text_odl) > 0.1:
                        is_low_confidence = True
                except AttributeError: pass
            
            if not is_low_confidence:
                final_pages.append(text_odl)
                page_records[i]['gemma_used'] = False
                page_records[i]['mode'] = 'odl'
                continue
            
            # [디버깅] 페이지 데이터 확인
            print(f"   [DEBUG] Page {p['page_num']} — chars: {n_chars}, img_path: {page_imgs[i] if i < len(page_imgs) else 'None'}")
            
            # [핵심 수정] 병합 프로세스 시작
            img_path = page_imgs[i] if i < len(page_imgs) else None
            if img_path is None:
                final_pages.append(text_odl)
                continue
                
            print(f"   [VLM] Processing Third-Party Merge for page {p['page_num']}...")
            t_page = time.time()
            
            # 1. 독립적인 비전 OCR 수행 (결과 B 생성)
            gemma_res = vlm_engine.full_page_audit(img_path)
            # vlm_verify.py의 응답 구조에 따라 gemma_res.response 또는 gemma_res['response'] 사용
            text_vlm = getattr(gemma_res, 'response', '') if not hasattr(gemma_res, 'error') else ''
            
            # 2. 제3자 병합 호출 (Result A: ODL, Result B: VLM)
            # 앞서 정의한 merge_ocr_results 메서드를 여기서 호출합니다.
            merged_text = vlm_engine.merge_ocr_results(text_odl=text_odl, text_vlm=text_vlm)
            
            # 3. 최종 텍스트 확정 및 검증
            if merged_text and len(merged_text.strip()) > 0:
                # 결과가 너무 짧아지는 등 이상 징후 시 Fallback
                if len(merged_text) < (len(text_odl) * 0.3):
                    final_text = text_odl
                    page_records[i]['mode'] = 'merge_rejected_too_short'
                else:
                    final_text = merged_text
                    page_records[i]['mode'] = 'triangular_merge'
            else:
                final_text = text_odl
                page_records[i]['mode'] = 'merge_failed_fallback'
                
            page_records[i]['gemma_used'] = True
            page_records[i]['elapsed_sec'] = round(time.time() - t_page, 3)
            final_pages.append(final_text)

        # 6. Final Text Assembly (Join all pages)
        final_full_text = '\n\n'.join(final_pages).strip()

        return {
            'ok': True, 'engine': 'hybrid', 'elapsed_sec': round(time.time() - t0, 3),
            'full_text': final_full_text, 'n_chars': len(final_full_text),
            'pages': page_records, 'mode': 'page_replacement', 'merged_used': False,
            'threshold': threshold, 'error': None,
        }
    except Exception as e:
        return {
            'ok': False, 'engine': 'hybrid', 'elapsed_sec': round(time.time() - t0, 3),
            'full_text': '', 'n_chars': 0, 'pages': page_records, 'mode': 'error',
            'merged_used': False, 'threshold': threshold, 'error': f'{type(e).__name__}: {e}',
        }
