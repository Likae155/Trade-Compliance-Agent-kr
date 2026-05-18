# mu (TradeLex) — 지능형 무역 서류 법리 분석 시스템

> **mu**는 국제 무역 서류에 특화된 고정밀 로컬 기반 법률 분석 에이전트입니다. 최첨단 **ODL+VLM 하이브리드 OCR** 기술과 **파인튜닝된 Gemma 4 E2B** 모델을 결합하여 법적 리스크 탐지, 수치 정합성 검증, 전문 법률 보고서 생성을 자동화합니다.

---

## 🌟 주요 기술 특징

- **하이브리드 OCR 엔진**: 고속 텍스트 추출(ODL)과 시각적 보정(Gemma VLM)을 결합한 지능형 인식 시스템.
- **구조적 데이터 추출**: 좌표 기반 행 클러스터링(Row Clustering)을 통한 복잡한 표 복원 및 문맥 기반 당사자(Parties) 식별.
- **결정론적 수치 검증**: 산술 연산(수량 * 단가 = 총액) 및 서류 간 데이터 일치 여부를 100% 정확도로 검증.
- **로컬 우선(Local-First) 아키텍처**: Ollama를 통한 완전 오프라인 구동으로 기업 내부 데이터의 보안과 프라이버시 보장.
- **고도화된 워크플로우**: LangGraph 기반의 4노드 자가 교정 루프(PREP → Retrieve → Grade → Resolve).

---

## 📂 저장소 구조 및 컴포넌트 안내

### 1. `ocr/` — 비전 파이프라인 (The Vision Pipeline)
입력된 이미지 및 PDF를 구조화된 데이터로 변환하는 시스템의 관문입니다.
- **`pipeline.py`**: 전체 OCR 흐름을 제어하는 오케스트레이터. 파일 입력부터 최종 JSON 출력까지 관리.
- **`ocr_router.py`**: 텍스트 PDF(ODL)와 스캔 이미지(VLM) 사이의 지능형 라우팅 및 하이브리드 병합 수행.
- **`vlm_verify.py`**: Gemma VLM을 사용하여 저신뢰도 텍스트를 검증하고 시각적 레이아웃 정보를 보정.
- **`ocr_engine.py`**: 이미지 전처리 및 레거시 OCR 엔진과의 인터페이스 래퍼.
- **`parsers/`**: 문서 타입별 특화 파싱 로직.
    - **`contract.py`**: 좌표 기반 표 복원 및 서문(Preamble) 분석을 통한 계약서 전용 파서.
    - **`bl.py`, `lc.py`, `invoice_like.py`**: 선하증권, 신용장, 송장 등 서류별 맞춤형 데이터 추출.
- **`preprocess.py`**: VLM 인식률 극대화를 위한 적응형 이미지 필터링(Grayscale, Sharpening 등).

### 2. `src/` — 추론 엔진 (The Reasoning Engine)
추출된 데이터를 바탕으로 법률적 판단과 LLM 오케스트레이션을 수행합니다.
- **`agent.py`**: LangGraph 워크플로우 정의. 자가 교정 및 RAG 기반 추론 로직 구현.
- **`llm_engine_v2.py`**: `api/chat` 기반의 Ollama 통합 클라이언트. 멀티모달 데이터 및 JSON 모드 지원.
- **`validators.py`**: 수치 검증기. 엄격한 산술 연산 정합성 및 날짜 논리 체크 수행.
- **`engine.py`**: 법령 DB 검색 엔진. 벡터 검색(ChromaDB)과 키워드 검색의 하이브리드 방식.
- **`prompts.py`**: 파인튜닝 지침(**INSTRUCTION_A/B**)이 포함된 최적화된 골든 프롬프트 관리.

### 3. `webui/` — 사용자 인터페이스
사용자 친화적인 대시보드와 상호작용 환경을 제공합니다.
- **`app.py`**: Streamlit 기반 메인 애플리케이션. 다중 문서 업로드 및 분석 리포트 출력.
- **`core/engine_proxy.py`**: UI의 요청을 백엔드 LegalAgent로 전달하는 중계 역할.
- **`core/secure_store.py`**: 로컬 AES-256 암호화를 통한 세션 데이터 및 분석 이력 보안 저장.

### 4. 기타 주요 폴더
- **`config/`**: 사용자 정의 법률 검토 원칙(`user_preferences.md`) 등 설정 파일.
- **`database/`**: 법령 벡터 DB(Law-Graph) 및 에러 케이스 로그 보관.
- **`models/`**: VLM 엔진 설정(`Modelfile_OCR`) 등 모델 관련 구성 파일.

---

## 🚀 시작하기

### 사전 준비: Ollama 설정

1. **Ollama 설치**: [https://ollama.com/download](https://ollama.com/download)
2. **분석용 모델 다운로드**:
   ```bash
   ollama pull gemma4:e2b
   ```
3. **특수 모델 배치**: OCR 전용 모델(`gemma4:e4b` 등)은 별도 배포 링크를 통해 제공됩니다. 다운로드 후 Ollama 모델 디렉토리에 배치하십시오.

### 설치 방법

```bash
# 가상환경 생성
conda create -n tradelex python=3.11 -y
conda activate tradelex

# Java 설치
conda install -c conda-forge openjdk=21 -y
# 의존성 설치
pip install -r requirements.txt
```

### 실행 방법

**A. CLI 통합 실행 (OCR + 분석)**
```bash
python main.py 경로/to/계약서.pdf
```

**B. 웹 대시보드 실행**
```bash
streamlit run webui/app.py
```

---

## 🔒 운영 원칙 및 보안

- **외부 API 차단**: 모든 데이터는 사용자 PC를 벗어나지 않으며 로컬에서만 처리됩니다.
- **데이터 무결성**: OCR 결과의 임의 수정(Hallucination)을 금지하며, 정규화를 통해서만 파서 호환성을 확보합니다.
- **추적성(Traceability)**: 모든 중간 처리 과정과 이미지를 로컬에 기록하여 사후 감사가 가능합니다.

---

## 👥 팀 정보

- **최연호**: 리드 파이프라인 아키텍트, OCR 및 구조적 파서 개발.
- **허수빈**: 법률 로직 설계, LangGraph 및 RAG 시스템 개발.
- **정영석**: 모델 스페셜리스트, Gemma 파인튜닝 및 데이터셋 엔지니어.

---
*최종 업데이트: 2026-05-15 | 버전 2.3 (구조적 고도화 반영)*
