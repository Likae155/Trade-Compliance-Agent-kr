import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Union, Dict, Any

try:
    from llama_cpp import Llama
except ImportError:
    print("⚠️ llama-cpp-python is not installed. Please install it to use this engine.")
    Llama = None

class GemmaLLMEngine:
    """
    Gemma-4-E2B GGUF 모델을 위한 통합 추론 엔진.
    llama-cpp-python을 직접 사용하여 하드웨어 최속화 및 멀티모달(Vision)을 지원합니다.
    """
    
    def __init__(
        self, 
        model_path: Optional[str] = None,
        mmproj_path: Optional[str] = None,
        n_ctx: int = 4096,
        n_gpu_layers: int = -1,
        verbose: bool = False
    ):
        self.root_dir = Path(__file__).parent.parent.resolve()
        self.model_path = model_path or str(self.root_dir / "models" / "gemma-4-e2b-it.Q4_K_M.gguf")
        self.mmproj_path = mmproj_path or str(self.root_dir / "models" / "gemma-4-e2b-it.BF16-mmproj.gguf")
        
        self.n_ctx = n_ctx
        self.verbose = verbose
        
        # 하드웨어 감지 및 설정 최적화
        self.gpu_detected = self._detect_gpu()
        self.n_gpu_layers = n_gpu_layers if self.gpu_detected else 0
        
        self.model = None
        self._init_model()

    def _detect_gpu(self) -> bool:
        """NVIDIA GPU 존재 여부 확인"""
        try:
            if platform.system() == "Windows":
                # Windows에서는 nvidia-smi가 경로에 없을 수 있으므로 간단한 체크
                output = subprocess.check_output(['nvidia-smi'], stderr=subprocess.STDOUT)
                return True
            else:
                subprocess.check_output(['nvidia-smi'])
                return True
        except:
            return False

    def _init_model(self):
        if Llama is None:
            return
            
        if not os.path.exists(self.model_path):
            print(f"⚠️ 모델 파일을 찾을 수 없습니다: {self.model_path}")
            return

        try:
            # Gemma 전용 설정 및 하드웨어 가속 적용
            self.model = Llama(
                model_path=self.model_path,
                chat_format="gemma", # Gemma 포맷 지정
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                verbose=self.verbose,
                # 멀티모달(Vision) 지원을 위한 mmproj 설정
                clip_model_path=self.mmproj_path if os.path.exists(self.mmproj_path) else None
            )
            print(f"✅ Gemma 모델 로드 완료 (GPU 가속: {'ON' if self.n_gpu_layers != 0 else 'OFF'})")
        except Exception as e:
            print(f"❌ 모델 로드 중 오류 발생: {e}")

    def format_prompt(self, user_text: str, system_text: Optional[str] = None) -> str:
        """Gemma-4-E2B 전용 턴 기반 프롬프트 포맷팅"""
        prompt = ""
        if system_text:
            # Gemma는 공식적으로 system role을 지원하지 않는 경우가 많으므로 user 턴에 포함하거나 커스텀 토큰 사용
            # 여기서는 일반적인 Gemma-2-it 스타일을 따름
            prompt += f"<|turn|>user\n{system_text}\n\n{user_text}<|turn|>\n<|turn|>model\n"
        else:
            prompt += f"<|turn|>user\n{user_text}<|turn|>\n<|turn|>model\n"
        return prompt

    def invoke(self, prompt: str, stop: List[str] = ["<|turn|>"], max_tokens: int = 2048, temperature: float = 0.1) -> Any:
        """LangChain 호환을 위한 invoke 메서드"""
        if self.model is None:
            raise RuntimeError("Model is not initialized.")
            
        # 프롬프트에 이미 Gemma 토큰이 포함되어 있는지 확인
        if "<|turn|>" not in prompt:
            formatted_prompt = self.format_prompt(prompt)
        else:
            formatted_prompt = prompt
            
        res = self.model(
            formatted_prompt,
            max_tokens=max_tokens,
            stop=stop,
            temperature=temperature,
            echo=False
        )
        
        # LangChain의 AIMessage와 유사한 구조를 가진 SimpleNamespace 또는 Dict 반환
        class Response:
            def __init__(self, content):
                self.content = content
        
        return Response(res["choices"][0]["text"].strip())

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """OpenAI 스타일 메시지 리스트 처리"""
        if self.model is None:
            return "Error: Model not initialized"
            
        # llama-cpp-python의 create_chat_completion 사용
        res = self.model.create_chat_completion(
            messages=messages,
            **kwargs
        )
        return res["choices"][0]["message"]["content"]

    def vision_ocr(self, image_b64: str, prompt: str = "이미지 내용을 OCR 해줘.") -> str:
        """멀티모달 이미지를 포함한 OCR/분석"""
        if self.model is None or not os.path.exists(self.mmproj_path):
            return "Error: Vision model (mmproj) not loaded"
            
        # llama-cpp-python의 vision 처리는 특정 포맷이 필요함
        # 여기서는 OpenAI Vision API 스타일을 흉내냄
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                ]
            }
        ]
        
        # Gemma-4-E2B-it GGUF가 llava-1-5 포맷을 지원한다고 가정 (notebook 참고)
        res = self.model.create_chat_completion(
            messages=messages,
            chat_format="llava-1-5", # 비전 모드
            max_tokens=2048
        )
        return res["choices"][0]["message"]["content"]

# 전역 싱글턴 인스턴스 (메모리 절약)
_engine = None

def get_gemma_engine():
    global _engine
    if _engine is None:
        _engine = GemmaLLMEngine()
    return _engine
