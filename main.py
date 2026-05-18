"""
################################################################################
# 무역서류 법리 분석 통합 엔트리포인트 (main.py)
# 
# [개발자 가이드]
# - 이 파일은 전체 시스템의 실행 및 모듈 제어를 담당합니다.
# - OCR(최연호), LegalAgent(허수빈), VLM/LoRA 어댑터(정영석) 모듈을 조율합니다.
# - CLI 옵션을 통해 OCR 전용, 법리 질문 전용, 통합 분석 모드를 지원합니다.
# - 모듈 임포트 시 상대 경로 문제를 방지하기 위해 `_setup_paths()` 함수를 사용합니다.
# 
# [주의사항]
# - 실제 작동하는 코드 및 비즈니스 로직은 수정하지 마십시오.
# - 경로 설정 관련 코드는 통합 폴더 구조를 기반으로 작성되어 있으니 주의하십시오.
################################################################################
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# ════════════════════════════════════════════════════════════════
# 경로 설정 — 통합 폴더 기준 (최상위가 본 main.py 위치)
# ════════════════════════════════════════════════════════════════
ROOT = Path(__file__).resolve().parent

# main.py를 모듈로 임포트할 때는 sys.path를 건드리지 않도록 수정
def _setup_paths():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

OUTPUT_DIR = ROOT / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)


def step(msg: str, verbose: bool = True):
    if verbose:
        print(f'\n[{time.strftime("%H:%M:%S")}] {msg}')


def run_ocr(pdf_path: Path, use_vlm: bool = True, verbose: bool = True) -> dict:
    """OCR 파이프라인 실행 → 풀 결과 dict 반환.

    OCRPipeline.process() 의 반환은 summary 만 포함 — 실 결과는 result_path 파일에 저장됨.
    이 함수는 result_path 파일을 다시 읽어 풀 dict 를 반환.
    """
    _setup_paths()
    step(f'[1/3] OCR — {pdf_path.name}', verbose)

    # ocr 패키지 형태로 임포트하여 상대 경로 문제를 해결
    from ocr.pipeline import OCRPipeline

    # [지능형 자동 모드 활성화]
    # 텍스트 PDF면 ODL, 스캔 PDF면 하이브리드(ODL+Gemma), 이미지면 VLM/Paddle을 자동으로 선택합니다.
    pipeline = OCRPipeline(
        storage_base=ROOT / 'ocr_storage',
        use_vlm=use_vlm,
        use_router=True,       # 텍스트 PDF 판별 및 라우팅 활성화
        use_hybrid_ocr=True,   # 하이브리드(ODL + Gemma) 모드 활성화
    )
    summary = pipeline.process(pdf_path)

    if summary.get('status') != 'ok':
        if summary.get('status') == 'skipped':
            step(f'  ⚠ 기존 결과 재사용: {summary.get("result_path")}', verbose)
        else:
            raise RuntimeError(f'OCR 실패: {summary}')

    # 풀 결과 dict 로드
    result_path = Path(summary['result_path'])
    with open(result_path, encoding='utf-8') as f:
        full_result = json.load(f)

    doc_type = full_result.get('document_type', 'unknown')
    n_fields = len(full_result.get('parse', {}).get('key_fields', {}))
    step(f'  분류: {doc_type}', verbose)
    step(f'  추출 필드: {n_fields}개', verbose)

    return full_result


def run_legal_agent_query(query: str, verbose: bool = True) -> dict:
    """LegalAgent 자연어 질문 모드."""
    step(f'[LegalAgent] 자연어 질문 분석', verbose)

    from src.agent import LegalAgent  # 수빈님 패키지

    agent = LegalAgent()
    result = agent.run(query)
    return result


def run_legal_agent_document(structured_json: dict, verbose: bool = True) -> dict:
    """LegalAgent 서류 사전 분석 모드 (LC + Invoice 정합성 등)."""
    step('[2/3] LegalAgent — 법령 검색 + 법리 판정', verbose)

    from src.agent import LegalAgent

    agent = LegalAgent()
    json_str = json.dumps(structured_json, ensure_ascii=False, indent=2)
    result = agent.analyze_document(json_str)
    return result


def save_result(result: dict, output_path: Path, verbose: bool = True):
    """최종 결과 저장."""
    step(f'[3/3] 결과 저장 — {output_path}', verbose)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)


def print_verdict(result: dict):
    """최종 판정 요약 출력."""
    print('\n' + '═' * 60)
    print('⚖️  최종 법적 판단')
    print('═' * 60)

    if 'prep_analysis' in result and result['prep_analysis']:
        print('\n📋 [1단계: 서류 사전 분석]')
        print(result['prep_analysis'])

    if 'final_judgment' in result:
        print('\n⚖️  [최종 판정]')
        print(result['final_judgment'])

    print('═' * 60)


# ════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(
        prog='mu',
        description='무역서류 법리 분석 통합 엔트리포인트',
    )
    p.add_argument('input', nargs='?', help='입력 PDF/이미지 경로 또는 자연어 질문')
    p.add_argument('--output', default=str(OUTPUT_DIR / 'result.json'),
                   help='결과 저장 경로 (기본: ./output/result.json)')
    p.add_argument('--legal-only', metavar='QUERY',
                   help='OCR 건너뛰고 자연어 질문만 LegalAgent 에 전달')
    p.add_argument('--doc-only', metavar='PATH',
                   help='PDF OCR + 서류 정합성 (analyze_document) 만 실행')
    p.add_argument('--no-vlm', action='store_true',
                   help='VLM 재검증 비활성 (속도↑)')
    p.add_argument('--verbose', '-v', action='store_true', default=True,
                   help='단계별 진행 로그')
    p.add_argument('--quiet', '-q', action='store_true',
                   help='조용히 실행 (--verbose 와 반대)')
    args = p.parse_args()

    verbose = args.verbose and not args.quiet
    start = time.time()

    # ── 모드 분기 ────────────────────────────────────────
    if args.legal_only:
        # 자연어 법률 질문만
        result = run_legal_agent_query(args.legal_only, verbose=verbose)
        print_verdict(result)
        save_result(result, Path(args.output), verbose=verbose)

    elif args.doc_only:
        # PDF → OCR → 서류 정합성 검토
        pdf_path = Path(args.doc_only)
        if not pdf_path.exists():
            sys.exit(f'❌ 입력 파일이 없습니다: {pdf_path}')
        ocr_result = run_ocr(pdf_path, use_vlm=not args.no_vlm, verbose=verbose)
        legal_result = run_legal_agent_document(ocr_result, verbose=verbose)

        combined = {
            'input_file': str(pdf_path),
            'ocr_result': ocr_result,
            'legal_analysis': legal_result,
            'elapsed_sec': round(time.time() - start, 2),
        }
        print_verdict(legal_result)
        save_result(combined, Path(args.output), verbose=verbose)

    elif args.input:
        # 기본 모드 — PDF → OCR → LegalAgent (서류 분석)
        in_path = Path(args.input)
        if not in_path.exists():
            sys.exit(f'❌ 입력 파일이 없습니다: {in_path}')

        ocr_result = run_ocr(in_path, use_vlm=not args.no_vlm, verbose=verbose)
        legal_result = run_legal_agent_document(ocr_result, verbose=verbose)

        combined = {
            'input_file': str(in_path),
            'ocr_result': ocr_result,
            'legal_analysis': legal_result,
            'elapsed_sec': round(time.time() - start, 2),
        }
        print_verdict(legal_result)
        save_result(combined, Path(args.output), verbose=verbose)

    else:
        p.print_help()
        sys.exit(0)

    if verbose:
        print(f'\n⏱  총 소요 시간: {time.time() - start:.2f}초')


if __name__ == '__main__':
    _setup_paths()
    main()
