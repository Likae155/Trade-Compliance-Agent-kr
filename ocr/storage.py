"""
Step 3.10.1: 저장 관리 모듈

이전 아키텍처 설계대로 로컬 저장 구조 관리.

폴더 구조:
    ocr_storage/
    ├── input/{doc_id}/
    │   ├── original.pdf             (원본)
    │   └── metadata.json            (업로드 정보)
    │
    ├── preprocessed/{doc_id}/
    │   ├── page_NN.png              (200 DPI 이미지)
    │   └── meta.json                (변환 정보)
    │
    ├── intermediate/{doc_id}/
    │   ├── layout.json              (레이아웃 분석 — 추후)
    │   ├── ocr_raw.json             (OCR 원시 결과)
    │   ├── stamps/*.png             (잘라낸 도장 이미지 — 추후)
    │   └── signatures/*.png         (잘라낸 서명 이미지 — 추후)
    │
    ├── output/{doc_id}/
    │   ├── result.json              (구조화된 최종 JSON)
    │   └── report.txt               (사람이 읽기 좋은 요약 — 옵션)
    │
    └── logs/{doc_id}/
        └── pipeline.log             (단계별 로그)

핵심: 모든 저장은 로컬에만. 외부 전송 없음.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_BASE = Path('ocr_storage')


class StorageManager:
    """단일 document에 대한 저장 인터페이스."""

    def __init__(self, document_id: str, base_path: Path = DEFAULT_BASE):
        self.doc_id = document_id
        self.base = Path(base_path)
        # 하위 디렉토리들
        self.input_dir = self.base / 'input' / document_id
        self.preproc_dir = self.base / 'preprocessed' / document_id
        self.intermediate_dir = self.base / 'intermediate' / document_id
        self.output_dir = self.base / 'output' / document_id
        self.logs_dir = self.base / 'logs' / document_id

    def ensure_dirs(self) -> None:
        """필요한 하위 디렉토리 생성."""
        for d in [self.input_dir, self.preproc_dir,
                  self.intermediate_dir, self.output_dir, self.logs_dir]:
            d.mkdir(parents=True, exist_ok=True)

    # ────────────────────────────────────────────────────────
    # 입력 저장
    # ────────────────────────────────────────────────────────
    def save_input(self, source_path: Path) -> Path:
        """
        원본 PDF 보관 (복사).
        원본 해시도 계산해서 metadata에 기록.
        """
        self.input_dir.mkdir(parents=True, exist_ok=True)
        source_path = Path(source_path)
        # 원본 파일명 유지하지 않고 'original.pdf'로 통일 (확장자는 원본 따라감)
        dest = self.input_dir / f'original{source_path.suffix}'
        shutil.copy2(source_path, dest)

        # 해시 계산
        h = hashlib.sha256()
        with open(source_path, 'rb') as f:
            while chunk := f.read(65536):
                h.update(chunk)

        metadata = {
            'document_id': self.doc_id,
            'original_filename': source_path.name,
            'stored_path': str(dest),
            'size_bytes': source_path.stat().st_size,
            'sha256': h.hexdigest(),
            'uploaded_at': datetime.now().isoformat(timespec='seconds'),
        }
        (self.input_dir / 'metadata.json').write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        return dest

    def get_input_metadata(self) -> dict | None:
        """저장된 입력 메타데이터 조회."""
        p = self.input_dir / 'metadata.json'
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding='utf-8'))

    # ────────────────────────────────────────────────────────
    # 전처리 이미지 (이미 pdf_to_image.py가 이 위치에 저장)
    # ────────────────────────────────────────────────────────
    def preprocessed_exists(self) -> bool:
        return self.preproc_dir.exists() and bool(
            list(self.preproc_dir.glob('page_*.png'))
        )

    def list_preprocessed_pages(self) -> list[Path]:
        if not self.preprocessed_exists():
            return []
        return sorted(self.preproc_dir.glob('page_*.png'))

    def get_preprocessed_meta(self) -> dict | None:
        p = self.preproc_dir / 'meta.json'
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding='utf-8'))

    # ────────────────────────────────────────────────────────
    # 중간 결과
    # ────────────────────────────────────────────────────────
    def save_ocr_raw(self, ocr_result: dict) -> Path:
        """OCR 원시 결과 (파싱 전)."""
        self.intermediate_dir.mkdir(parents=True, exist_ok=True)
        p = self.intermediate_dir / 'ocr_raw.json'
        p.write_text(
            json.dumps(ocr_result, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        return p

    def save_layout(self, layout_data: dict) -> Path:
        """레이아웃 분석 결과."""
        self.intermediate_dir.mkdir(parents=True, exist_ok=True)
        p = self.intermediate_dir / 'layout.json'
        p.write_text(
            json.dumps(layout_data, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        return p

    def save_cropped(self, category: str, idx: int,
                     image_bytes: bytes, ext: str = '.png') -> Path:
        """
        도장·서명·표 등 잘라낸 이미지 저장.
        category: 'stamps' / 'signatures' / 'tables'
        """
        cat_dir = self.intermediate_dir / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        p = cat_dir / f'{category}_{idx:03d}{ext}'
        p.write_bytes(image_bytes)
        return p

    # ────────────────────────────────────────────────────────
    # 최종 결과
    # ────────────────────────────────────────────────────────
    def save_result(self, result: dict) -> Path:
        """구조화된 최종 결과."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        p = self.output_dir / 'result.json'
        p.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        return p

    def get_result(self) -> dict | None:
        p = self.output_dir / 'result.json'
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding='utf-8'))

    # ────────────────────────────────────────────────────────
    # 로그
    # ────────────────────────────────────────────────────────
    def log(self, message: str, level: str = 'INFO') -> None:
        """파이프라인 로그 append."""
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        p = self.logs_dir / 'pipeline.log'
        ts = datetime.now().isoformat(timespec='milliseconds')
        with open(p, 'a', encoding='utf-8') as f:
            f.write(f'[{ts}] [{level}] {message}\n')
        # 터미널에도 출력 (디버깅 및 사용자 확인용)
        print(f"  {message}")

    # ────────────────────────────────────────────────────────
    # 정리·제거 (사용자 요청 시)
    # ────────────────────────────────────────────────────────
    def clean(self, keep_input: bool = True) -> None:
        """
        이 문서의 모든 저장 데이터 제거.
        keep_input=True면 원본 input/ 폴더만 유지.
        """
        for d in [self.preproc_dir, self.intermediate_dir,
                  self.output_dir, self.logs_dir]:
            if d.exists():
                shutil.rmtree(d)
        if not keep_input and self.input_dir.exists():
            shutil.rmtree(self.input_dir)

    # ────────────────────────────────────────────────────────
    # 요약
    # ────────────────────────────────────────────────────────
    def summary(self) -> dict:
        """이 문서의 현재 저장 상태 요약."""
        return {
            'document_id': self.doc_id,
            'input': self.input_dir.exists(),
            'preprocessed': {
                'exists': self.preprocessed_exists(),
                'n_pages': len(self.list_preprocessed_pages()),
            },
            'intermediate': {
                'ocr_raw': (self.intermediate_dir / 'ocr_raw.json').exists(),
                'layout': (self.intermediate_dir / 'layout.json').exists(),
            },
            'output': (self.output_dir / 'result.json').exists(),
        }


# ────────────────────────────────────────────────────────────
# CLI: 저장 상태 확인
# ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    doc_id = sys.argv[1] if len(sys.argv) >= 2 else '수입_수출계약서_0001'
    sm = StorageManager(doc_id)
    summary = sm.summary()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
