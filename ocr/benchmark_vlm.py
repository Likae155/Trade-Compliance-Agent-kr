"""
Step 3.9.4/5: VLM 벤치마크 실행기

동일 테스트 세트에 대해 여러 VLM 모델을 순차 실행하고,
공통 지표로 비교.

지표:
  1. 조항 회수율 (원본 JSON GT 대비)
  2. 텍스트 일치율 (키워드 hit ratio)
  3. 처리 속도 (초/페이지)
  4. VRAM 사용량 (nvidia-smi)
  5. 특정 케이스 성공 여부 (번호 리스트 양식 등)

출력: `vlm_benchmark_report.json`
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from vlm_verify import OllamaVLM, check_ollama


OUTPUT_DIR = Path('ocr_storage/vlm_benchmark')
TEST_SET_PATH = Path('vlm_test_set.json')
JSON_ROOT = Path('05.계약 법률 문서 서식 데이터/01.원천데이터')


# ────────────────────────────────────────────────────────────
# GT (정답) 로드
# ────────────────────────────────────────────────────────────
def load_ground_truth(doc_id: str) -> dict:
    """원본 JSON에서 정답 정보 추출."""
    for folder in ['TS_무역_수출_입계약_국제거래', 'VS_무역_수출_입계약_국제거래']:
        jp = JSON_ROOT / folder / f'{doc_id}.json'
        if jp.exists():
            data = json.loads(jp.read_text(encoding='utf-8'))
            break
    else:
        return {}

    doc = data['document']
    articles = sorted(set(
        s.get('article') for s in doc['sub_documents']
        if s.get('article') is not None
    ))
    # 각 조항의 제목 (키워드 역할)
    article_titles = {}
    for s in doc['sub_documents']:
        if s.get('is_article_title') and s.get('article') is not None:
            text = ' '.join(c.get('text', '') for c in s.get('contents', []))
            article_titles[s['article']] = text.strip()

    # 본문 키워드 (다양한 sub_document 텍스트에서 추출)
    all_texts = []
    for s in doc['sub_documents'][:50]:
        if s.get('type') == 'TEXT':
            for c in s.get('contents', []):
                t = (c.get('text') or '').strip()
                if t and len(t) > 10:
                    all_texts.append(t)

    return {
        'doc_id': doc_id,
        'title': doc.get('title'),
        'n_articles': len(articles),
        'articles': articles,
        'article_titles': article_titles,
        'sample_texts': all_texts[:20],
    }


# ────────────────────────────────────────────────────────────
# 응답 평가
# ────────────────────────────────────────────────────────────
def evaluate_response(response: str, gt: dict) -> dict:
    """VLM 응답을 GT와 대조해서 지표 계산."""
    if not response:
        return {
            'article_recall': 0,
            'article_hits': 0,
            'article_total': gt.get('n_articles', 0),
            'missed_articles': gt.get('articles', []),
            'keyword_recall': 0,
            'keyword_hits': 0,
            'keyword_total': len(gt.get('sample_texts', [])),
            'response_length': 0,
        }

    # 조항 회수율 (GT의 article_titles 중 찾은 비율)
    article_hits = 0
    missed_articles = []
    for art_no, title in gt['article_titles'].items():
        # 제목 일부라도 매칭되면 hit
        norm_title = ''.join(title.split())
        norm_resp = ''.join(response.split())
        # 제N조 표기가 응답에 있거나, 제목 일부가 매칭되면 hit
        article_marker = f'제{art_no}조'
        if article_marker in response or norm_title[:15] in norm_resp:
            article_hits += 1
        else:
            missed_articles.append(art_no)
    recall_pct = (article_hits / gt['n_articles']) * 100 if gt['n_articles'] else 0

    # 본문 샘플 텍스트 매칭
    norm_resp = ''.join(response.split())
    keyword_hits = 0
    for t in gt['sample_texts']:
        probe = ''.join(t.split())[:30]
        if probe and probe in norm_resp:
            keyword_hits += 1
    kw_pct = (keyword_hits / len(gt['sample_texts'])) * 100 if gt['sample_texts'] else 0

    return {
        'article_recall': recall_pct,
        'article_hits': article_hits,
        'article_total': gt['n_articles'],
        'missed_articles': missed_articles,
        'keyword_recall': kw_pct,
        'keyword_hits': keyword_hits,
        'keyword_total': len(gt['sample_texts']),
        'response_length': len(response),
    }


# ────────────────────────────────────────────────────────────
# GPU 사용량 측정
# ────────────────────────────────────────────────────────────
def get_gpu_memory() -> dict:
    """nvidia-smi로 현재 GPU 메모리 사용량."""
    try:
        out = subprocess.run(
            ['nvidia-smi',
             '--query-gpu=memory.used,memory.total',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=5,
        )
        used, total = out.stdout.strip().split(',')
        return {
            'used_mb': int(used.strip()),
            'total_mb': int(total.strip()),
            'used_pct': int(used.strip()) / int(total.strip()) * 100,
        }
    except Exception as e:
        return {'error': str(e)}


# ────────────────────────────────────────────────────────────
# 모델별 벤치마크
# ────────────────────────────────────────────────────────────
def benchmark_model(model_name: str, test_set: list[dict]) -> dict:
    """한 모델에 대해 모든 테스트 문서의 첫 페이지 OCR."""
    print(f'\n{"="*70}')
    print(f'BENCHMARK: {model_name}')
    print('=' * 70)

    vlm = OllamaVLM(model=model_name)
    vram_before = get_gpu_memory()

    doc_results = []
    total_t0 = time.time()

    for entry in test_set:
        category = entry['category']
        doc = entry['doc']
        doc_id = doc['doc_id']

        # 첫 페이지만 테스트 (속도 고려)
        page_path = Path(f'ocr_storage/preprocessed/{doc_id}/page_01.png')
        if not page_path.exists():
            print(f'[SKIP] {doc_id} — 이미지 없음')
            continue

        # GT 로드
        gt = load_ground_truth(doc_id)
        if not gt:
            print(f'[SKIP] {doc_id} — GT 없음')
            continue

        print(f'\n[{category}] {doc_id} (GT 조항 {gt["n_articles"]}개)')
        t0 = time.time()
        result = vlm.full_page_audit(page_path)
        elapsed = time.time() - t0

        # 평가
        eval_metrics = evaluate_response(result.response, gt)

        print(f'  시간: {elapsed:.1f}초, 응답 {len(result.response)}자')
        print(f'  조항 회수: {eval_metrics["article_recall"]:.0f}% '
              f'({eval_metrics["article_hits"]}/{eval_metrics["article_total"]})')
        print(f'  키워드 매칭: {eval_metrics["keyword_recall"]:.0f}% '
              f'({eval_metrics["keyword_hits"]}/{eval_metrics["keyword_total"]})')

        doc_results.append({
            'category': category,
            'doc_id': doc_id,
            'gt': gt,
            'elapsed_seconds': elapsed,
            'response_length': len(result.response),
            'response': result.response,
            'error': result.error,
            'eval': eval_metrics,
        })

    total_time = time.time() - total_t0
    vram_after = get_gpu_memory()

    # 집계
    if doc_results:
        avg_recall = sum(r['eval']['article_recall'] for r in doc_results) / len(doc_results)
        avg_keyword = sum(r['eval']['keyword_recall'] for r in doc_results) / len(doc_results)
        avg_time = sum(r['elapsed_seconds'] for r in doc_results) / len(doc_results)
    else:
        avg_recall = avg_keyword = avg_time = 0

    summary = {
        'model': model_name,
        'n_docs': len(doc_results),
        'total_time_seconds': total_time,
        'avg_time_per_page': avg_time,
        'avg_article_recall': avg_recall,
        'avg_keyword_recall': avg_keyword,
        'vram_before': vram_before,
        'vram_after': vram_after,
        'doc_results': doc_results,
    }

    print(f'\n{"="*70}')
    print(f'{model_name} 요약:')
    print(f'  평균 조항 회수율: {avg_recall:.1f}%')
    print(f'  평균 키워드 매칭: {avg_keyword:.1f}%')
    print(f'  평균 페이지 당: {avg_time:.1f}초')
    print(f'  VRAM (후): {vram_after.get("used_mb")}MB / {vram_after.get("total_mb")}MB')

    return summary


# ────────────────────────────────────────────────────────────
# 메인
# ────────────────────────────────────────────────────────────
def main():
    # Ollama 상태
    status = check_ollama()
    if not status.get('ok'):
        print(f'❌ Ollama 에러: {status.get("error")}')
        sys.exit(1)

    print(f'Ollama 모델: {status["models"]}')

    # 테스트 세트 로드
    if not TEST_SET_PATH.exists():
        print(f'테스트 세트 없음: {TEST_SET_PATH}')
        sys.exit(1)
    test_set = json.loads(TEST_SET_PATH.read_text(encoding='utf-8'))
    print(f'테스트 세트: {len(test_set)}개 문서')

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 테스트할 모델 (CLI에서 받거나 기본값)
    if len(sys.argv) >= 2:
        models_to_test = sys.argv[1:]
    else:
        models_to_test = []
        if status.get('has_gemma4_e4b'):
            models_to_test.append('gemma4:e4b')
        if status.get('has_qwen25vl_7b'):
            models_to_test.append('qwen2.5vl:7b')

    if not models_to_test:
        print('테스트할 모델 없음. Ollama에 gemma4:e4b 또는 qwen2.5vl:7b를 pull하세요.')
        sys.exit(1)

    print(f'테스트 모델: {models_to_test}\n')

    # 모델별 순차 실행
    all_results = []
    for model in models_to_test:
        summary = benchmark_model(model, test_set)
        all_results.append(summary)
        # 개별 결과 저장
        out_path = OUTPUT_DIR / f'{model.replace(":", "_")}_result.json'
        out_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        print(f'저장: {out_path}')

    # 최종 비교
    print(f'\n{"="*70}')
    print('최종 비교')
    print('=' * 70)
    print(f'{"모델":<20} {"조항회수":>10} {"키워드":>8} {"속도":>10} {"VRAM":>10}')
    print('-' * 70)
    for r in all_results:
        vram_str = f'{r["vram_after"].get("used_mb", "?")}MB'
        print(f'{r["model"]:<20} '
              f'{r["avg_article_recall"]:>9.1f}% '
              f'{r["avg_keyword_recall"]:>7.1f}% '
              f'{r["avg_time_per_page"]:>9.1f}s '
              f'{vram_str:>10}')

    # 전체 리포트 저장
    report_path = OUTPUT_DIR / '_vlm_comparison_report.json'
    report_path.write_text(
        json.dumps({
            'test_set_size': len(test_set),
            'models_tested': models_to_test,
            'results': all_results,
        }, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print(f'\n종합 리포트: {report_path}')


if __name__ == '__main__':
    main()
