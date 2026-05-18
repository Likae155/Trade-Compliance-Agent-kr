from .llm_engine_v2 import get_engine_v2
import os

class LLMManager:
    """
    모델 설정을 관리하는 클래스. 
    V2 엔진을 사용하여 GGUF 모델(e2b finetuned)을 호출합니다.
    """
    def __init__(self, fast_model="gemma4-e2b-ft-gguf:latest", heavy_model="gemma4-e2b-ft-gguf:latest"):
        # V2 엔진에서 일반용(finetuned) 모델 로드 (싱글턴)
        # get_engine_v2() 호출 시 'general' 타입이면 'ocr' 모델이 있을 경우 닫아줍니다.
        self.engine = get_engine_v2(model_type="general")

    def get_fast_llm(self):
        # invoke() 호환성을 위해 엔진 자체를 반환
        return self.engine

    def get_heavy_llm(self):
        return self.engine
