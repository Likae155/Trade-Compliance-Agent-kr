"""
################################################################################
# PaddleOCR 엔진 래퍼 (ocr/ocr_engine.py)
# 
# [개발자 가이드]
# - PaddleOCR 엔진을 감싸서 OCR 이미지 처리 및 표준 결과 스키마를 생성합니다.
# - 이미지 전처리 파이프라인(preprocess.py)을 통합하여 OCR 인식률을 최적화합니다.
# - 결과값은 {blocks, raw_text, avg_confidence, ...} 구조로 표준화됩니다.
# 
# [주의사항]
# - 모델 초기화가 싱글톤으로 구현되어 있으므로, 언어 설정(`lang`) 변경 시 주의하십시오.
# - OCR 결과 리턴 구조(BBox, Text, Score)가 PaddleOCR 버전에 따라 바뀔 수 있으므로 
#   구조 파싱 로직 변경 시 유의하십시오.
################################################################################
"""
"""
Step 3.3: OCR 엔진 래퍼
...
"""
import io
import json
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

from .preprocess import (
    load_image, save_image, get_blob_image,
    preprocess_default, preprocess_aggressive, preprocess_light,
)



# ────────────────────────────────────────────────────────────
# 표준 결과 스키마
# ────────────────────────────────────────────────────────────
# OCRBlock: 단일 텍스트 블록
# {
#   'text': '제1조 (계약의 목적)',
#   'confidence': 0.97,
#   'bbox': [[x1,y1],[x2,y2],[x3,y3],[x4,y4]],   # 4점 폴리곤
#   'bbox_aabb': (x_min, y_min, x_max, y_max),    # 축 정렬 박스
# }
#
# OCRPageResult:
# {
#   'image_path': '...',
#   'preprocess': 'aggressive',
#   'width': 1654, 'height': 2339,
#   'blocks': [OCRBlock, ...],
#   'raw_text': '...',   # 블록 순서대로 합친 텍스트
#   'avg_confidence': 0.82,
#   'low_confidence_ratio': 0.15,
# }


class OCREngine:
    """PaddleOCR 래퍼 싱글톤."""

    _instance_cache: dict = {}

    def __init__(self, lang: str = 'korean',
                 preprocess: str = 'light',
                 use_gpu: bool = True):
        """
        Args:
            lang: PaddleOCR 언어 모델 ('korean', 'en' 등)
            preprocess: 'none'/'light'/'default'/'aggressive'
            use_gpu: GPU 사용 여부 (현재 PaddleOCR 3.x는 자동 감지)
        """
        self.lang = lang
        self.preprocess_mode = preprocess

        # 싱글톤: 같은 lang은 재사용
        if lang not in OCREngine._instance_cache:
            if PaddleOCR is None:
                # ODL/VLM 기반으로 작동하므로 Paddle 부재 시 로그를 출력하지 않음
                OCREngine._instance_cache[lang] = None
            else:
                OCREngine._instance_cache[lang] = PaddleOCR(lang=lang)
        self._ocr = OCREngine._instance_cache[lang]

    # ────────────────────────────────────────
    # 전처리 적용
    # ────────────────────────────────────────
    def _apply_preprocess(self, img: np.ndarray) -> np.ndarray:
        mode = self.preprocess_mode
        if mode == 'none':
            return img
        elif mode == 'light':
            return preprocess_light(img)
        elif mode == 'default':
            return preprocess_default(img)
        elif mode == 'aggressive':
            return preprocess_aggressive(img)
        else:
            raise ValueError(f'Unknown preprocess mode: {mode}')

    # ────────────────────────────────────────
    # 결과 표준화
    # ────────────────────────────────────────
    @staticmethod
    def _normalize_result(raw: dict, image_path: str,
                          width: int, height: int,
                          preprocess: str) -> dict:
        """PaddleOCR 원시 결과 → 표준 스키마."""
        texts = raw.get('rec_texts', [])
        scores = raw.get('rec_scores', [])
        polys = raw.get('rec_polys', [])

        blocks = []
        for t, s, poly in zip(texts, scores, polys):
            # poly: np.ndarray shape (4, 2)
            poly_list = poly.tolist() if hasattr(poly, 'tolist') else list(poly)
            xs = [p[0] for p in poly_list]
            ys = [p[1] for p in poly_list]
            bbox_aabb = (int(min(xs)), int(min(ys)),
                         int(max(xs)), int(max(ys)))

            blocks.append({
                'text': t,
                'confidence': float(s),
                'bbox': poly_list,
                'bbox_aabb': list(bbox_aabb),
            })

        # 읽기 순서 정렬: 위 → 아래, 왼쪽 → 오른쪽
        blocks.sort(key=lambda b: (b['bbox_aabb'][1], b['bbox_aabb'][0]))

        avg_conf = sum(s for s in scores) / len(scores) if scores else 0
        low_conf = sum(1 for s in scores if s < 0.7)
        low_conf_ratio = low_conf / len(scores) if scores else 0

        return {
            'image_path': image_path,
            'preprocess': preprocess,
            'width': width,
            'height': height,
            'blocks': blocks,
            'raw_text': '\n'.join(b['text'] for b in blocks),
            'avg_confidence': avg_conf,
            'low_confidence_ratio': low_conf_ratio,
            'n_blocks': len(blocks),
            'n_low_confidence': low_conf,
        }

    # ────────────────────────────────────────
    # 페이지(이미지) 단위 OCR
    # ────────────────────────────────────────
    def ocr_image(self, image_path: str | Path,
                    save_preprocessed_to: Optional[Path] = None) -> dict:
            """단일 이미지 OCR. 전처리 포함. (LayoutAnalyzer 폐기 버전)"""
            image_path = Path(image_path)
            img = load_image(image_path)
            h, w = img.shape[:2]

            # 1. 전처리
            if self.preprocess_mode != 'none':
                processed = self._apply_preprocess(img)
                if save_preprocessed_to:
                    save_image(processed, save_preprocessed_to)
            else:
                processed = img

            # PaddleOCR은 3채널 이미지 기대. 그레이스케일(2D)이면 3채널로 확장
            if len(processed.shape) == 2:
                processed = cv2.cvtColor(processed, cv2.COLOR_GRAY2BGR)

            # 2. OCR 실행
            if self._ocr is None:
                raise RuntimeError("PaddleOCR is not initialized. Please install paddleocr.")
                
            # [수정] PaddleOCR 2.7.x 안정 버전 규격에 맞게 ocr() 호출
            raw_list = self._ocr.ocr(processed, cls=True)
            if not raw_list or not raw_list[0]:
                return self._normalize_result(
                    {}, str(image_path), w, h, self.preprocess_mode
                )
            # raw_list = [ [ [bbox], [[text, score]] ] ]

            # [수정] ocr() 리턴 구조 [[[bbox], [text, score]], ...] 에서 데이터 추출
            ocr_data = {
                'rec_texts': [line[1][0] for line in raw_list[0]],
                'rec_scores': [line[1][1] for line in raw_list[0]],
                'rec_polys': [line[0] for line in raw_list[0]]
            }

            result = self._normalize_result(
                raw_list[0], str(image_path), w, h, self.preprocess_mode
            )

            # [수정] ocr() 리턴 구조 [[[bbox], [text, score]], ...] 에서 데이터 추출
            ocr_data = {
                'rec_texts': [line[1][0] for line in raw_list[0]],
                'rec_scores': [line[1][1] for line in raw_list[0]],
                'rec_polys': [line[0] for line in raw_list[0]]
            }

            result = self._normalize_result(
                ocr_data, str(image_path), w, h, self.preprocess_mode
            )
         

            # 3. [수정] Recursive XY Cut 대신 단순 Y축 정렬 수행
            # VLM(Gemma)이 위에서 아래로 읽는 흐름을 유지할 수 있도록 정렬합니다.
            # bbox_aabb: (x_min, y_min, x_max, y_max) 중 index 1(y_min) 기준
            sorted_blocks = sorted(result['blocks'], key=lambda x: x['bbox_aabb'][1])
            result['blocks'] = sorted_blocks
            
            # 4. raw_text 구성 (레이아웃 경고 태그 제거)
            result['raw_text'] = '\n'.join(b['text'] for b in sorted_blocks)
            
            return result
    # ────────────────────────────────────────
    # 문서(폴더) 단위 OCR
    # ────────────────────────────────────────
    def ocr_document_dir(self, doc_dir: str | Path,
                          save_preprocessed: bool = False) -> dict:
        """
        ocr_storage/preprocessed/{doc_id}/ 폴더의 모든 page_*.png를 OCR.
        """
        doc_dir = Path(doc_dir)
        doc_id = doc_dir.name
        pages = sorted(doc_dir.glob('page_*.png'))
        if not pages:
            raise ValueError(f'페이지 이미지 없음: {doc_dir}')

        page_results = []
        preproc_dir = doc_dir / '_preprocessed' if save_preprocessed else None

        for p in pages:
            pre_path = (preproc_dir / p.name) if preproc_dir else None
            result = self.ocr_image(p, save_preprocessed_to=pre_path)
            result['page_number'] = int(p.stem.split('_')[-1])
            page_results.append(result)

        # 전체 문서 요약
        all_blocks = sum(len(r['blocks']) for r in page_results)
        all_chars = sum(len(r['raw_text']) for r in page_results)
        avg_conf = (
            sum(r['avg_confidence'] * r['n_blocks'] for r in page_results)
            / all_blocks if all_blocks else 0
        )

        return {
            'document_id': doc_id,
            'n_pages': len(pages),
            'preprocess': self.preprocess_mode,
            'total_blocks': all_blocks,
            'total_chars': all_chars,
            'avg_confidence': avg_conf,
            'pages': page_results,
            'full_text': '\n\n'.join(r['raw_text'] for r in page_results),
        }


# ────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys

    if len(sys.argv) >= 2:
        doc_dir = Path(sys.argv[1])
    else:
        doc_dir = Path('ocr_storage/preprocessed/수입_수출계약서_0001')

    preprocess_mode = sys.argv[2] if len(sys.argv) >= 3 else 'aggressive'

    print(f'[DOC] {doc_dir}')
    print(f'[PREPROCESS] {preprocess_mode}')

    engine = OCREngine(preprocess=preprocess_mode)
    result = engine.ocr_document_dir(doc_dir)

    # 한글 콘솔 출력
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print(f'\n=== {result["document_id"]} ===')
    print(f'페이지: {result["n_pages"]}')
    print(f'총 블록: {result["total_blocks"]}')
    print(f'총 글자: {result["total_chars"]:,}')
    print(f'평균 신뢰도: {result["avg_confidence"]:.3f}')

    # 저장
    out_path = doc_dir / '_ocr_result.json'
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    print(f'\n저장: {out_path}')
