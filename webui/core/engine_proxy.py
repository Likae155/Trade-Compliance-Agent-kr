import streamlit as st
import os
import traceback
import requests
import json
import sys
from pathlib import Path

# [Refactored Path] 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import LegalAgent

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
# 리팩토링 버전에 맞춘 모델명
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4-e2b-ft-gguf:latest")


class LegalAgentEngine:
    def __init__(self, model_name=OLLAMA_MODEL, host=OLLAMA_HOST):
        try:
            self.model_name = model_name
            self.host = host
            # 헬스체크
            r = requests.get(f"{host}/api/tags", timeout=5)
            r.raise_for_status()
            
            # 최적화된 LegalAgent 초기화
            self.agent = LegalAgent(fast_model=model_name, heavy_model=model_name)
            self.is_ready = True
        except Exception as e:
            self.is_ready = False
            self.error_msg = str(e)

    def run_analysis_stream(self, text, system_prompt=None):
        """웹 UI에서 호출하는 분석 엔트리포인트 (안정적인 동기 호출 방식)"""
        if not self.is_ready:
            yield f"❌ 엔진 로드 실패: {self.error_msg}"
            return

        try:
            # CPU 환경에서의 안정성을 위해 스트리밍 대신 완결된 결과를 한 번에 가져옵니다.
            is_json = text.strip().startswith('{') and text.strip().endswith('}')
            
            if is_json:
                # [RAG + 파인튜닝] 전체 워크플로우 실행 (최대 10분 대기)
                result = self.agent.analyze_document(text, user_instruction=system_prompt)
            else:
                # 일반 질문에 대해 RAG 실행
                result = self.agent.run(text, user_instruction=system_prompt)
            
            final_report = result.get("final_judgment", "판정 결과가 생성되지 않았습니다.")
            
            # UI에 결과 전달
            yield final_report
            
        except Exception as e:
            yield f"❌ 분석 중 오류 발생: {str(e)}\n\n{traceback.format_exc()}"


# 전역 엔진 인스턴스
_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = LegalAgentEngine()
    return _engine


def run_analysis_stream(text, system_prompt=None):
    engine = get_engine()
    return engine.run_analysis_stream(text, system_prompt)
