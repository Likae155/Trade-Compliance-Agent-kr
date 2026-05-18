"""
Step 3.10.2: OCR 파이프라인 오케스트레이터

전체 흐름:
    PDF 파일
    └→ [0] 원본 저장 (input/)
       └→ [1] PDF → 이미지 (preprocessed/)
          └→ [2] OCR 엔진 (중간 결과 저장)
             └→ [3] 문서 타입 분류
                └→ [4] 타입별 파서
                   └→ [5] 최종 JSON 저장 (output/)

사용법:
    # 단일 PDF
    python pipeline.py path/to/file.pdf
    python pipeline.py path/to/file.pdf --doc-id my_id

    # 이미 생성된 PDF 기반 (generated_pdfs/)
    python pipeline.py --from-generated 수입_수출계약서_0001

    # 배치
    python pipeline.py --batch generated_pdfs/TS
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .storage import StorageManager
from .pdf_to_image import convert_pdf_to_images
from .ocr_engine import OCREngine
from .classify_document import classify_ocr_result
from .parsers import get_parser
from .parsers import postprocess_ocr
from .vlm_verify import OllamaVLM
from src.llm_engine_v2 import get_engine_v2
from .ocr_router import IMAGE_EXTS

# ────────────────────────────────────────────────────────────
# 메인 파이프라인
# ────────────────────────────────────────────────────────────
class OCRPipeline:
    """전체 파이프라인 오케스트레이터."""

    def __init__(self,
                 storage_base: Path = Path('ocr_storage'),
                 preprocess_mode: str = 'light',
                 dpi: int = 200,
                 ocr_lang: str = 'korean',
                 use_vlm: bool = False,
                 vlm_model: str = 'gemma4:e2b-ocr',  # E2B-OCR 모델로 통일
                 vlm_confidence_threshold: float = 0.7,
                 vlm_min_chars: int = 300,
                 vlm_max_pages: int = 6,
                 use_router: bool = False,
                 router_min_chars_per_page: int = 50,
                 postprocess_keyfields: bool = True,
                 # 5/6 — 하이브리드 OCR (정영석님 합의: 임계치 50자, 병합 e2b)
                 use_hybrid_ocr: bool = False,
                 hybrid_page_char_threshold: int = 50,
                 hybrid_merge_model: str = 'gemma4:e2b'):
        """
        Args:
            use_vlm: True면 저품질 페이지에 VLM 재OCR 적용
            vlm_model: Ollama 모델 (기본 gemma4:e2b)
            vlm_confidence_threshold: 이 값 미만 페이지 재검증
            vlm_min_chars: 이 값 미만 텍스트 페이지 재검증
            vlm_max_pages: 문서당 최대 재검증 페이지 수
            use_router: True면 text-PDF 는 OpenDataLoader 로 라우팅 (4/28 §8 Phase 2)
            router_min_chars_per_page: 라우팅 임계 (페이지당 최소 글자 수)
            postprocess_keyfields: True면 파서 직후 OCR 후처리 사전 매칭 적용
                                   (4/30 §X — 0/O 혼동 등 컨텍스트 기반 보정)
            use_hybrid_ocr: 5/6 — True 면 페이지별 ODL+Gemma 하이브리드 사용.
                            텍스트 페이지(≥ threshold) → ODL 단독, 부족 페이지 →
                            Gemma 호출 후 LLM 으로 ODL+Gemma 병합. False (기본) 면
                            기존 라우터/PaddleOCR 흐름 유지.
            hybrid_page_char_threshold: 페이지당 글자수 임계치 (5/6 합의: 50)
            hybrid_merge_model: ODL+Gemma 병합용 LLM (5/6 합의: gemma4:e2b)
        """
        self.storage_base = Path(storage_base)
        self.preprocess_mode = preprocess_mode
        self.dpi = dpi
        self._engine = None  # lazy init
        self.ocr_lang = ocr_lang
        self.use_vlm = use_vlm
        self.vlm_model = vlm_model
        self.vlm_confidence_threshold = vlm_confidence_threshold
        self.vlm_min_chars = vlm_min_chars
        self.vlm_max_pages = vlm_max_pages
        self._vlm = None  # lazy init
        self.use_router = use_router
        self.router_min_chars_per_page = router_min_chars_per_page
        self.postprocess_keyfields = postprocess_keyfields
        # 5/6 hybrid
        self.use_hybrid_ocr = use_hybrid_ocr
        self.hybrid_page_char_threshold = hybrid_page_char_threshold
        self.hybrid_merge_model = hybrid_merge_model
        self._hybrid_vlm = None  # lazy init (병합·full_page_audit 용)

    @property
    def engine(self) -> OCREngine:
        if self._engine is None:
            try:
                self._engine = OCREngine(
                    lang=self.ocr_lang,
                    preprocess=self.preprocess_mode,
                )
            except Exception as e:
                print(f"!!! ENGINE LOAD ERROR: {e}")
                raise e
        return self._engine

    @property
    def vlm(self) -> OllamaVLM:
        if self._vlm is None:
            self._vlm = OllamaVLM(model=self.vlm_model)
        return self._vlm

    @property
    def hybrid_vlm(self) -> OllamaVLM:
        """5/6 — 하이브리드 OCR 의 페이지 OCR + 병합용 VLM. 병합 모델 (e2b) 사용."""
        if self._hybrid_vlm is None:
            self._hybrid_vlm = OllamaVLM(model=self.hybrid_merge_model)
        return self._hybrid_vlm

    # ────────────────────────────────────────
    # 단일 문서 처리
    # ────────────────────────────────────────
    def process(self, input_path: Path, doc_id: Optional[str] = None,
                skip_existing: bool = True) -> dict:
        """
        단일 입력(PDF 또는 이미지) → 구조화된 OCR 결과.

        Args:
            input_path: 입력 PDF / PNG / JPG / JPEG 등
            doc_id: 문서 식별자 (없으면 파일명_타임스탬프 사용)
            skip_existing: 이미 처리된 문서는 건너뜀

        Returns:
            전체 결과 dict (저장 경로 포함)
        """
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f'입력 파일 없음: {input_path}')

        suffix = input_path.suffix.lower()
        # [DEBUG] 확장자 체크 로그
        print(f"[DEBUG] Input: {input_path}, Suffix: '{suffix}'")
        print(f"[DEBUG] Supported: {IMAGE_EXTS}")
        
        is_image = suffix in IMAGE_EXTS
        is_pdf = suffix == '.pdf'
        if not (is_image or is_pdf):
            supported = ", ".join(sorted(list(IMAGE_EXTS) + [".pdf"]))
            raise ValueError(f'지원하지 않는 입력 형식: {suffix} ({supported} 지원)')
        
        print(f"[DEBUG] Check Passed: is_image={is_image}, is_pdf={is_pdf}")

        if doc_id is None:
            # 파일명_YYYYMMDD_HHMMSS 형식으로 고유 ID 생성 (사용자 요청)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            doc_id = f"{input_path.stem}_{ts}"

        # [NEW] OCR 시퀀스 시작 전 모델 전환 (메모리 확보를 위해 기존 모델 언로드)
        if self.use_vlm or self.use_hybrid_ocr:
            sm_log_placeholder = lambda msg: print(f"[{doc_id}] {msg}")
            sm_log_placeholder("OCR 시퀀스 시작: OCR 전용 모델(E4B) 로드 및 기존 모델 언로드")
            get_engine_v2(model_type="ocr")

        sm = StorageManager(doc_id, self.storage_base)
        sm.ensure_dirs()
        sm.log(f'파이프라인 시작: {input_path}')

        # 이미 처리됐으면 skip
        if skip_existing and sm.get_result() is not None:
            sm.log('기존 결과 존재 — 스킵')
            return {
                'document_id': doc_id,
                'status': 'skipped',
                'reason': 'already_processed',
                'result_path': str(sm.output_dir / 'result.json'),
            }

        t0 = time.time()
        phase_times: dict[str, float] = {}

        # ─── [0] 원본 저장 ───
        tp = time.time()
        sm.save_input(input_path)
        phase_times['save_input'] = time.time() - tp
        sm.log('[0] 원본 저장 완료')

        # ─── [1] 입력 → 페이지 이미지 (PDF 변환 or 이미지 복사) ───
        # 샌드위치 PDF 및 VLM 재검증을 위해 항상 이미지 변환을 수행하도록 원복 (사용자 요청)
        tp = time.time()
        if not sm.preprocessed_exists():
            if is_pdf:
                sm.log('[1] PDF → 이미지 변환 시작 (샌드위치/VLM 대응)')
                convert_pdf_to_images(
                    pdf_path=input_path,
                    doc_id=doc_id,
                    output_root=self.storage_base / 'preprocessed',
                    dpi=self.dpi,
                )
            else:
                sm.log('[1] 이미지 입력 — preprocessed 로 복사 및 메타데이터 생성')
                import shutil
                from PIL import Image
                sm.preproc_dir.mkdir(parents=True, exist_ok=True)
                dest_path = sm.preproc_dir / 'page_01.png'
                shutil.copy2(input_path, dest_path)
                
                # 이미지 메타데이터 생성 (PDF 변환 시와 동일한 구조)
                with Image.open(dest_path) as img:
                    w, h = img.size
                    meta = {
                        'document_id': doc_id,
                        'source_image': str(input_path),
                        'source_size': input_path.stat().st_size,
                        'pages': 1,
                        'dpi': self.dpi,
                        'format': img.format,
                        'image_width': w,
                        'image_height': h,
                        'page_files': [{
                            'file': 'page_01.png',
                            'width': w,
                            'height': h,
                            'size_bytes': dest_path.stat().st_size
                        }],
                        'converted_at': datetime.now().isoformat(timespec='seconds'),
                        'output_dir': str(sm.preproc_dir),
                    }
                    (sm.preproc_dir / 'meta.json').write_text(
                        json.dumps(meta, ensure_ascii=False, indent=2),
                        encoding='utf-8'
                    )
        else:
            sm.log('[1] 기존 이미지 재사용')
        phase_times['pdf_to_image'] = time.time() - tp

        # ─── [2] OCR (Phase 2 라우팅: text-PDF → ODL, 그 외 → PaddleOCR) ───
        tp = time.time()
        ocr_result = None

        # 5/6 — 하이브리드 OCR: 페이지별 ODL+Gemma 병합 (정영석님 합의)
        if self.use_hybrid_ocr:
            from .ocr_router import extract_hybrid
            from .pdf_to_image import convert_pdf_to_images as _pdf2img
            sm.log(f'[2] 하이브리드 OCR 시작 (이미지 지원, 임계치 {self.hybrid_page_char_threshold}자)')
            hybrid_r = extract_hybrid(
                input_path,
                pdf_to_image_fn=lambda p, d_id: _pdf2img(
                    p, d_id,
                    output_root=self.storage_base / 'preprocessed',
                    dpi=self.dpi,
                ),
                image_output_root=self.storage_base / 'preprocessed',
                vlm_engine=self.hybrid_vlm,
                threshold=self.hybrid_page_char_threshold,
            )
            if hybrid_r['ok'] and hybrid_r['n_chars'] > 0:
                n_pages = len(hybrid_r['pages'])
                n_gemma = sum(1 for p in hybrid_r['pages'] if p.get('gemma_used'))
                ocr_result = {
                    'engine': 'hybrid',
                    'n_pages': n_pages,
                    'total_blocks': 0,
                    'total_chars': hybrid_r['n_chars'],
                    'avg_confidence': 1.0,
                    'full_text': hybrid_r.get('full_text', ''),
                    'pages': hybrid_r['pages'],
                    'hybrid': {
                        'threshold': hybrid_r['threshold'],
                        'merge_model': self.hybrid_merge_model,
                        'mode': hybrid_r.get('mode'),  # odl_only | merged | concat_fallback
                        'merged_used': hybrid_r.get('merged_used', False),
                        'n_gemma_pages': n_gemma,
                    },
                }
                sm.save_ocr_raw(ocr_result)
                phase_times['ocr'] = time.time() - tp
                sm.log(f'[2] 하이브리드 완료: {n_pages}페이지 '
                       f'(mode={hybrid_r.get("mode")}, Gemma 호출 {n_gemma}), '
                       f'{hybrid_r["n_chars"]}자, {hybrid_r["elapsed_sec"]}s')
            else:
                pass # 로그 생략 (fallback 로그 억제)

        if ocr_result is None and self.use_router:
            from .ocr_router import route_ocr
            # sm.log('[2] 라우팅 모드 실행 (ODL 우선)')  # 로그 생략
            odl_out = sm.intermediate_dir / 'odl_out'
            odl_r = route_ocr(
                input_path,
                paddle_engine=None,
                odl_out_dir=odl_out,
                min_chars_per_page=self.router_min_chars_per_page
            )
            if odl_r['ok'] and odl_r['n_chars'] > 0:
                # ODL 결과 → ocr_result 형식 어댑터
                ocr_result = {
                    'engine': 'odl',
                    'n_pages': odl_r.get('routing', {}).get('n_pages', 1),
                    'total_blocks': 0,  # ODL은 블록 단위 X
                    'total_chars': odl_r['n_chars'],
                    'avg_confidence': 1.0,  # 직접 추출이라 N/A → 1.0
                    'full_text': odl_r['full_text'],
                    'pages': [],
                    'routing': odl_r.get('routing'),
                }
                sm.save_ocr_raw(ocr_result)
                phase_times['ocr'] = time.time() - tp
                sm.log(f'[2] ODL 완료: {odl_r["n_chars"]}자, '
                       f'{odl_r["elapsed_sec"]}s')
            else:
                pass # 로그 생략 (fallback 로그 억제)

        if ocr_result is None:
            # PaddleOCR이 설치되어 있지 않거나 VLM만 사용하고 싶은 경우의 분기
            try:
                from .ocr_engine import PaddleOCR as _Paddle
                has_paddle = _Paddle is not None
            except ImportError:
                has_paddle = False

            if not has_paddle and self.use_vlm:
                sm.log('[2] VLM(Gemma) 단독 OCR 모드로 전환')
                ocr_result = {
                    'engine': 'vlm_only',
                    'n_pages': len(list(sm.preproc_dir.glob('page_*.png'))),
                    'total_blocks': 0,
                    'total_chars': 0,
                    'avg_confidence': 0.0,
                    'pages': [],
                    'full_text': ''
                }
            else:
                # 레거시 엔진 실행 (라우터 비활성 또는 fallback)
                sm.log('[2] OCR 엔진 실행 시작')
                ocr_result = self.engine.ocr_document_dir(sm.preproc_dir)
                ocr_result.setdefault('engine', 'legacy')
            
            sm.save_ocr_raw(ocr_result)
            phase_times['ocr'] = time.time() - tp
            if ocr_result.get('engine') in ['paddle', 'legacy']:
                sm.log(f'[2] OCR 완료: {ocr_result["total_blocks"]}블록, '
                       f'평균 신뢰도 {ocr_result["avg_confidence"]:.3f}')

        # ─── [2.5] VLM 선택적 재검증 (옵션) ───
        if self.use_vlm:
            tp = time.time()
            sm.log(f'[2.5] VLM 재검증 시작 ({self.vlm_model})')
            ocr_result = self.vlm.recheck_document(
                ocr_result,
                sm.preproc_dir,
                confidence_threshold=self.vlm_confidence_threshold,
                min_chars_per_page=self.vlm_min_chars,
                max_pages_to_recheck=self.vlm_max_pages,
            )
            phase_times['vlm'] = time.time() - tp
            recheck_info = ocr_result.get('vlm_rechecked', {})
            n_rechecked = recheck_info.get('n_pages_rechecked', 0)
            sm.log(f'[2.5] VLM 재검증 완료: {n_rechecked}페이지 처리')
            # 재검증 결과 별도 저장
            if n_rechecked > 0:
                import json as _json
                vlm_report_path = sm.intermediate_dir / 'vlm_recheck.json'
                vlm_report_path.write_text(
                    _json.dumps(recheck_info, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )

        # ─── [2.7] OCR full_text 라벨 정규화 (4/30 §X — N0 → No) ───
        if self.postprocess_keyfields:
            tp = time.time()
            raw_chars = len(ocr_result.get('full_text', ''))
            ocr_result = postprocess_ocr.normalize_ocr_result(ocr_result)
            new_chars = len(ocr_result.get('full_text', ''))
            phase_times['ocr_label_norm'] = time.time() - tp
            # 보정 발생 여부 — full_text_raw 와 다르면 보정됨
            if ocr_result.get('full_text_raw') != ocr_result.get('full_text'):
                sm.log(f'[2.7] OCR 라벨 정규화 적용 ({raw_chars}→{new_chars}자)')

        # ─── [3] 문서 타입 분류 ───
        tp = time.time()
        classification = classify_ocr_result(ocr_result)
        phase_times['classify'] = time.time() - tp
        sm.log(f'[3] 문서 타입: {classification.doc_type} '
               f'(신뢰도 {classification.confidence:.2f})')

        # ─── [4] 타입별 파서 ───
        tp = time.time()
        parser = get_parser(classification.doc_type)
        parse_result = parser.parse(ocr_result)
        phase_times['parse'] = time.time() - tp
        sm.log(f'[4] 파싱 완료: 신뢰도 {parse_result.confidence:.2f}, '
               f'warnings={parse_result.warnings}')

        # ─── [4.5] OCR 후처리 사전 매칭 (4/30 §X) ───
        if self.postprocess_keyfields:
            tp = time.time()
            kf_orig = parse_result.type_specific.get('key_fields', {})
            if kf_orig:
                kf_fixed = postprocess_ocr.fix_key_fields(kf_orig)
                diff = postprocess_ocr.diff_fix(kf_orig)
                parse_result.type_specific['key_fields'] = kf_fixed
                if diff:
                    parse_result.type_specific['key_fields_postprocess_diff'] = {
                        k: {'before': b, 'after': a} for k, (b, a) in diff.items()
                    }
                    sm.log(f'[4.5] 후처리 보정: {len(diff)}개 필드 변경')
            phase_times['postprocess_keyfields'] = time.time() - tp

        # ─── [5] 최종 결과 ───
        total_time = time.time() - t0

        input_meta = sm.get_input_metadata() or {}
        preproc_meta = sm.get_preprocessed_meta() or {}

        final = {
            'document_id': doc_id,
            'processed_at': datetime.now().isoformat(timespec='seconds'),
            'pipeline_version': '1.0.0',

            # 분류
            'document_type': classification.doc_type,
            'classification': {
                'confidence': classification.confidence,
                'matched_keywords': classification.matched_keywords,
                'needs_vlm_fallback': classification.needs_vlm_fallback,
            },

            # 파싱 결과
            'parse': parse_result.to_dict(),

            # OCR 품질 지표
            'ocr_quality': {
                'engine': ocr_result.get('engine'),
                'n_pages': ocr_result.get('n_pages', 0),
                'total_blocks': ocr_result.get('total_blocks', 0),
                'total_chars': ocr_result.get('total_chars', 0),
                'avg_confidence': ocr_result.get('avg_confidence', 0),
                'preprocess_mode': self.preprocess_mode,
            },

            # 원본 텍스트 (전체)
            'full_text': ocr_result['full_text'],

            # traceability (파일 경로 추적)
            'traceability': {
                'input_file': str(input_meta.get('stored_path', '')),
                'input_sha256': input_meta.get('sha256'),
                'preprocessed_dir': str(sm.preproc_dir),
                'ocr_raw': str(sm.intermediate_dir / 'ocr_raw.json'),
                'image_size': (
                    f'{preproc_meta.get("image_width")}x'
                    f'{preproc_meta.get("image_height")}'
                ),
                'dpi': self.dpi,
            },

            # 수행 시간
            'phase_times': phase_times,
            'total_time_seconds': total_time,
        }

        # 저장
        result_path = sm.save_result(final)
        sm.log(f'[5] 최종 결과 저장: {result_path}')
        sm.log(f'총 처리 시간: {total_time:.2f}초')

        return {
            'document_id': doc_id,
            'status': 'ok',
            'result_path': str(result_path),
            'summary': {
                'document_type': final['document_type'],
                'n_pages': final['ocr_quality']['n_pages'],
                'ocr_confidence': final['ocr_quality']['avg_confidence'],
                'parse_confidence': parse_result.confidence,
                'warnings': parse_result.warnings,
                'total_time': total_time,
            },
        }

    def process_batch(self, pdf_dir: Path,
                      skip_existing: bool = True,
                      limit: Optional[int] = None) -> list[dict]:
        pdf_dir = Path(pdf_dir)
        pdfs = []
        for ext in (['*.pdf'] + [f'*{e}' for e in IMAGE_EXTS]):
            pdfs.extend(pdf_dir.glob(ext))
            pdfs.extend(pdf_dir.glob(ext.upper()))
        pdfs = sorted(list(set(pdfs)))

        if limit:
            pdfs = pdfs[:limit]

        print(f'=== 배치 처리: {len(pdfs)}개 파일 (PDF/이미지) ===\n')
        results = []
        for i, p in enumerate(pdfs, 1):
            try:
                r = self.process(p, skip_existing=skip_existing)
                results.append(r)
                status = r['status']
                if status == 'ok':
                    s = r['summary']
                    print(f'[{i:3d}/{len(pdfs)}] {p.name}: '
                          f'{s["document_type"]} '
                          f'({s["n_pages"]}p, '
                          f'OCR={s["ocr_confidence"]:.2f}, '
                          f'Parse={s["parse_confidence"]:.2f}, '
                          f'{s["total_time"]:.1f}s)')
                else:
                    print(f'[{i:3d}/{len(pdfs)}] {p.name}: {status}')
            except Exception as e:
                print(f'[{i:3d}/{len(pdfs)}] {p.name}: ERROR - {e}')
                results.append({
                    'document_id': p.stem,
                    'status': 'error',
                    'error': str(e),
                })
        return results


def main():
    p = argparse.ArgumentParser(description='OCR 파이프라인')
    p.add_argument('target', nargs='?', help='PDF 파일 경로')
    p.add_argument('--doc-id', help='문서 ID')
    p.add_argument('--batch', metavar='DIR', help='폴더 내 모든 PDF 배치 처리')
    p.add_argument('--limit', type=int, default=None)
    p.add_argument('--vlm', action='store_true', help='VLM 재OCR 적용')
    p.add_argument('--use-router', action='store_true', help='라우팅 활성화')
    p.add_argument('--hybrid-ocr', action='store_true', help='하이브리드 OCR 활성화')
    
    args = p.parse_args()
    
    pipeline = OCRPipeline(
        use_vlm=args.vlm,
        use_router=args.use_router,
        use_hybrid_ocr=args.hybrid_ocr,
    )

    if args.batch:
        pipeline.process_batch(Path(args.batch), limit=args.limit)
    elif args.target:
        pipeline.process(Path(args.target), doc_id=args.doc_id)
    else:
        p.print_help()


if __name__ == '__main__':
    main()
