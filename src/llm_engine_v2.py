"""
################################################################################
# Ollama 기반 통합 추론 엔진 (src/llm_engine_v2.py)
# 
# [개발자 가이드]
# - Ollama API를 사용하여 로컬 LLM 모델(Gemma4 시리즈)을 관리 및 호출합니다.
# - OCR용 모델(E4B)과 일반 법률 분석용 모델(E2B FT)을 동적으로 로드/언로드합니다.
# - 로컬 메모리 자원 최적화를 위해 모델 전환 시 이전 모델을 명시적으로 언로드(keep_alive: 0)합니다.
# 
# [주의사항]
# - 모델명 매핑(model_names)이 Ollama에 설치된 버전과 일치하는지 확인하십시오.
# - 호출 시 타임아웃(timeout) 설정을 분석 작업의 복잡도에 따라 조정할 수 있습니다.
################################################################################
"""
import os
import requests
import json
import time
from typing import List, Optional, Union, Dict, Any

class OllamaEngineV2:
    """
    Ollama API를 사용하는 통합 추론 엔진 V2.
    OCR용(E4B)과 일반용(E2B Finetuned) 모델을 구분하여 관리하며,
    메모리 확보를 위해 사용하지 않는 모델을 명시적으로 언로드합니다.
    """
    
    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host.rstrip('/')
        # Ollama 모델명 매핑 (E2B-OCR 반영)
        self.model_names = {
            "ocr": "gemma4:e2b-ocr",
            "general": "gemma4-e2b-ft-gguf"
        }
        self.current_model = None

    def _unload_model(self, model_name: str):
        """Ollama에서 모델을 명시적으로 언로드 (keep_alive: 0)"""
        try:
            # generate나 chat API를 사용해 keep_alive를 0으로 설정하면 언로드됨
            requests.post(
                f"{self.host}/api/generate",
                json={"model": model_name, "keep_alive": 0},
                timeout=5
            )
            print(f"🗑️ Ollama 모델 언로드 완료: {model_name}")
        except Exception as e:
            print(f"⚠️ 모델 언로드 중 오류 (무시 가능): {e}")

    def load_model(self, model_type: str):
        """특정 타입의 모델을 로드하기 전 다른 모델을 언로드 (이미 로드된 경우 스킵)"""
        target_model = self.model_names.get(model_type)
        if not target_model:
            raise ValueError(f"Unknown model type: {model_type}")

        # [Optimized] 이미 요청한 모델이 로드되어 있다면 언로드 없이 즉시 반환
        if self.current_model == target_model:
            return

        # OCR 시작 전에는 메모리 확보를 위해 기존 모델(주로 general)을 확실히 언로드
        if model_type == "ocr":
            print(f"🚀 OCR 시작 전 메모리 확보를 위해 기존 모델을 언로드합니다.")
            # target_model(ocr)을 제외한 다른 모델들을 언로드
            for name, m in self.model_names.items():
                if name != "ocr":
                    self._unload_model(m)
        
        # 일반 모델 전환 시 기존 모델(주로 ocr) 언로드
        elif self.current_model and self.current_model != target_model:
            self._unload_model(self.current_model)

        self.current_model = target_model
        print(f"✅ 사용 모델 설정: {target_model}")

    def invoke(self, prompt: str, system: Optional[str] = None, temperature: float = 0.0, max_tokens: int = -1) -> Any:
        if not self.current_model:
            self.load_model("general")
            
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.current_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": 8192
            }
        }
        
        try:
            resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=600)
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "").strip()
            
            class Response:
                def __init__(self, content):
                    self.content = content
            return Response(content)
        except Exception as e:
            print(f"❌ Ollama 호출 중 오류: {e}")
            raise

    def vision_ocr(self, image_b64: str, prompt: str = "OCR this image.", system: Optional[str] = None, temperature: float = 0.0, max_tokens: int = -1) -> str:
        """Ollama Vision API를 사용한 OCR (api/chat 기반)"""
        if self.current_model != self.model_names["ocr"]:
            self.load_model("ocr")
            
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({
            "role": "user",
            "content": prompt,
            "images": [image_b64]
        })

        payload = {
            "model": self.current_model,
            "messages": messages,
            "stream": False,
            "format": "json", # 구조화 출력 강제
            "options": {
                "temperature": temperature,
                "num_predict": 4096,
                "num_ctx": 8192
            }
        }
        
        try:
            resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=600)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "").strip()
        except Exception as e:
            return json.dumps({"error": str(e), "content": ""})

    def format_prompt(self, user_text: str, system_text: Optional[str] = None) -> str:
        """Ollama는 내부적으로 템플릿을 처리하므로 기본 포맷 반환"""
        return user_text # 실제로는 API의 system 필드 활용 권장

# 전역 엔진 인스턴스 (Ollama는 서버가 상태를 관리하므로 클라이언트는 하나면 됨)
_engine = None

def get_engine_v2(model_type: str = "general"):
    global _engine
    if _engine is None:
        _engine = OllamaEngineV2()
    
    # 요청된 타입에 맞춰 모델 전환 및 언로드 수행
    _engine.load_model(model_type)
    return _engine
