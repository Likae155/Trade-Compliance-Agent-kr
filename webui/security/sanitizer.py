import re

def sanitize_text(text: str) -> str:
    """텍스트 데이터 정제 및 위험 문자 제거"""
    if not text:
        return ""
    
    # 제어 문자 제거 (개행, 탭 등 제외)
    # 00-08, 0B-0C, 0E-1F
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    
    # 과도한 공백 및 중복 개행 정제
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()
