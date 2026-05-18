"""
Step 2: PDF → 이미지 변환

- pypdfium2 사용 (Poppler 불필요)
- DPI 200, PNG, 페이지별 개별 저장
- 출력: ocr_storage/preprocessed/{doc_id}/page_NN.png + meta.json

사용법:
    # 단일 PDF
    python pdf_to_image.py path/to/file.pdf doc_id
    # 기본 (첫 번째 샘플만)
    python pdf_to_image.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image


# ────────────────────────────────────────────────────────────
# 설정
# ────────────────────────────────────────────────────────────
DEFAULT_DPI = 200
OUTPUT_FORMAT = 'PNG'
OUTPUT_ROOT = Path('ocr_storage/preprocessed')


def convert_pdf_to_images(
    pdf_path: Path,
    doc_id: str,
    output_root: Path = OUTPUT_ROOT,
    dpi: int = DEFAULT_DPI,
) -> dict:
    """
    단일 PDF → 페이지별 PNG 이미지.

    Args:
        pdf_path: PDF 파일 경로
        doc_id: 문서 식별자 (출력 폴더명)
        output_root: 저장 루트 (기본: ocr_storage/preprocessed)
        dpi: 렌더링 DPI (기본: 200)

    Returns:
        변환 결과 메타데이터 dict
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f'PDF 파일 없음: {pdf_path}')

    # 출력 폴더
    out_dir = output_root / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # PDF 로드
    pdf = pdfium.PdfDocument(str(pdf_path))
    n_pages = len(pdf)

    # DPI → scale 변환 (pypdfium2는 scale을 받음, 기본 72 DPI 기준)
    scale = dpi / 72.0

    page_files = []
    first_size = None

    for i in range(n_pages):
        page = pdf[i]
        # 렌더링
        bitmap = page.render(scale=scale)
        pil_img: Image.Image = bitmap.to_pil()

        # 페이지 번호는 1부터 시작 (page_01, page_02, ...)
        fname = f'page_{i+1:02d}.png'
        out_path = out_dir / fname
        pil_img.save(out_path, OUTPUT_FORMAT, optimize=True)

        if first_size is None:
            first_size = pil_img.size  # (width, height)

        page_files.append({
            'file': fname,
            'width': pil_img.width,
            'height': pil_img.height,
            'size_bytes': out_path.stat().st_size,
        })

        # 메모리 해제
        page.close()

    pdf.close()

    # 메타데이터
    meta = {
        'document_id': doc_id,
        'source_pdf': str(pdf_path),
        'source_pdf_size': pdf_path.stat().st_size,
        'pages': n_pages,
        'dpi': dpi,
        'format': OUTPUT_FORMAT,
        'scale': scale,
        'image_width': first_size[0] if first_size else None,
        'image_height': first_size[1] if first_size else None,
        'page_files': page_files,
        'converted_at': datetime.now().isoformat(timespec='seconds'),
        'output_dir': str(out_dir),
    }

    # meta.json 저장
    meta_path = out_dir / 'meta.json'
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    return meta


# ────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    if len(sys.argv) >= 3:
        pdf_path = Path(sys.argv[1])
        doc_id = sys.argv[2]
    else:
        # 기본: 첫 번째 TS 샘플
        pdf_path = Path('generated_pdfs/TS/수입_수출계약서_0001.pdf')
        doc_id = '수입_수출계약서_0001'

    print(f'[IN]  {pdf_path}')
    print(f'[ID]  {doc_id}')

    meta = convert_pdf_to_images(pdf_path, doc_id)

    print(f'[OK]  {meta["pages"]}페이지 변환 완료')
    print(f'      이미지 크기: {meta["image_width"]} x {meta["image_height"]} @ {meta["dpi"]} DPI')
    total_bytes = sum(pf['size_bytes'] for pf in meta['page_files'])
    print(f'      총 용량: {total_bytes/1024:.1f} KB')
    print(f'[OUT] {meta["output_dir"]}')
