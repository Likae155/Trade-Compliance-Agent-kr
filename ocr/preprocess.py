"""
Step 3.1: 이미지 전처리 모듈

OCR 품질 개선을 위한 이미지 전처리 파이프라인.

함수별 역할:
    - to_grayscale: 컬러 → 그레이스케일
    - enhance_contrast: CLAHE로 대비 향상
    - sharpen: Unsharp Mask로 텍스트 엣지 선명화
    - denoise: 가우시안 블러로 노이즈 제거
    - binarize_otsu: Otsu 이진화 (흑백 2색)
    - binarize_adaptive: 적응형 이진화
    - deskew: 기울기 보정 (현재 PDF 생성본엔 불필요)
    - preprocess_default: 기본 파이프라인 (추천)
    - preprocess_aggressive: 강력 파이프라인 (저품질 이미지용)

OCR 결과에 따라 적절한 파이프라인 선택.
"""
import cv2
import numpy as np
from pathlib import Path


# ────────────────────────────────────────────────────────────
# 기본 전처리 함수들
# ────────────────────────────────────────────────────────────
def to_grayscale(img: np.ndarray) -> np.ndarray:
    """컬러 이미지 → 그레이스케일. 이미 그레이면 그대로."""
    if len(img.shape) == 2:
        return img
    if img.shape[2] == 4:  # RGBA
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def enhance_contrast(img: np.ndarray, clip_limit: float = 2.0,
                     tile_size: int = 8) -> np.ndarray:
    """
    CLAHE (Contrast Limited Adaptive Histogram Equalization).
    전역 히스토그램 평활화보다 자연스러운 대비 향상.
    """
    gray = to_grayscale(img)
    clahe = cv2.createCLAHE(clipLimit=clip_limit,
                            tileGridSize=(tile_size, tile_size))
    return clahe.apply(gray)


def sharpen(img: np.ndarray, amount: float = 1.0,
            radius: float = 1.0) -> np.ndarray:
    """
    Unsharp Mask로 선명도 향상.
    우리 케이스(PDF 렌더링 anti-aliasing)에 가장 효과적.

    amount: 0~2 범위. 1.0이 기본.
    radius: 블러 반경. 1~2가 적절.
    """
    gray = to_grayscale(img)
    blurred = cv2.GaussianBlur(gray, (0, 0), radius)
    sharpened = cv2.addWeighted(gray, 1 + amount, blurred, -amount, 0)
    return np.clip(sharpened, 0, 255).astype(np.uint8)


def denoise(img: np.ndarray, method: str = 'gaussian',
            ksize: int = 3) -> np.ndarray:
    """
    노이즈 제거.
    method: 'gaussian' (가벼운) / 'median' (점노이즈) / 'bilateral' (엣지 보존)
    """
    gray = to_grayscale(img)
    if method == 'gaussian':
        return cv2.GaussianBlur(gray, (ksize, ksize), 0)
    elif method == 'median':
        return cv2.medianBlur(gray, ksize)
    elif method == 'bilateral':
        return cv2.bilateralFilter(gray, 5, 50, 50)
    else:
        raise ValueError(f'Unknown denoise method: {method}')


def binarize_otsu(img: np.ndarray) -> np.ndarray:
    """
    Otsu 이진화 (자동 threshold).
    배경이 깨끗한 문서에 적합. 과도한 손실 주의.
    """
    gray = to_grayscale(img)
    _, binary = cv2.threshold(gray, 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def binarize_adaptive(img: np.ndarray, block_size: int = 31,
                      c: int = 10) -> np.ndarray:
    """
    적응형 이진화.
    영역별로 다른 threshold. 조명 불균일한 이미지에 유리.
    """
    gray = to_grayscale(img)
    return cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block_size, c
    )


def get_adaptive_kernel(img: np.ndarray, h_ratio: float = 0.015, v_ratio: float = 0.005) -> np.ndarray:
    """
    이미지 해상도(DPI)에 비례하는 가변 커널 생성.
    행간이 붙는 것을 방지하기 위해 수평(h_ratio)을 수직(v_ratio)보다 크게 설정.
    """
    h, w = img.shape[:2]
    kw = max(3, int(w * h_ratio))
    kh = max(1, int(h * v_ratio))
    # 수평으로 긴 커널 생성 (다단 구분 및 행 보호)
    return np.ones((kh, kw), np.uint8)


def precision_deskew(img: np.ndarray) -> np.ndarray:
    """
    Hough Transform 기반 정밀 기울기 보정 (0.1도 단위).
    XY Cut의 정밀도를 위해 전단 필수 배치.
    """
    gray = to_grayscale(img)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
    
    if lines is None:
        return img

    angles = []
    for line in lines:
        rho, theta = line[0]
        angle = (theta * 180 / np.pi) - 90
        if -45 < angle < 45:
            angles.append(angle)
    
    if not angles:
        return img
        
    median_angle = np.median(angles)
    if abs(median_angle) < 0.1:
        return img
        
    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w // 2, h // 2), median_angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def deskew(img: np.ndarray) -> np.ndarray:
    """기존 deskew 호환성 유지"""
    return precision_deskew(img)


# ────────────────────────────────────────────────────────────
# 조합 파이프라인
# ────────────────────────────────────────────────────────────
def preprocess_default(img: np.ndarray) -> np.ndarray:
    """
    기본 전처리 파이프라인.
    우리 ReportLab 생성 이미지에 최적화:
      1. Grayscale
      2. CLAHE (가벼운 대비 향상)
      3. Unsharp Mask (엣지 선명화)
    """
    img = to_grayscale(img)
    img = enhance_contrast(img, clip_limit=2.0, tile_size=8)
    img = sharpen(img, amount=0.8, radius=1.0)
    return img


def preprocess_aggressive(img: np.ndarray) -> np.ndarray:
    """
    강력 전처리 (DPI 가변형).
    1. Precision Deskew
    2. Denoise (Bilateral)
    3. CLAHE
    4. Sharpen
    5. Adaptive 이진화
    """
    img = precision_deskew(img)
    img = to_grayscale(img)
    img = denoise(img, method='bilateral', ksize=5) # 엣지 보존 노이즈 제거
    img = enhance_contrast(img, clip_limit=3.0, tile_size=8)
    img = sharpen(img, amount=1.2, radius=1.0)
    img = binarize_adaptive(img, block_size=31, c=10)
    return img


def get_blob_image(img: np.ndarray) -> np.ndarray:
    """
    XY Cut용 텍스트 덩어리(Blob) 이미지 생성.
    DPI 비례 커널을 사용하여 단은 연결하고 행은 분리 유지.
    """
    gray = to_grayscale(img)
    # 반전 (글자가 흰색이어야 팽창 가능)
    inv = cv2.bitwise_not(gray)
    kernel = get_adaptive_kernel(inv)
    dilated = cv2.dilate(inv, kernel, iterations=1)
    # 다시 반전하여 검은 덩어리로 반환
    return cv2.bitwise_not(dilated)


def preprocess_light(img: np.ndarray) -> np.ndarray:
    """
    경량 전처리 (그레이스케일만).
    원본이 이미 좋은 품질일 때.
    """
    return to_grayscale(img)


# ────────────────────────────────────────────────────────────
# 파일 기반 편의 함수
# ────────────────────────────────────────────────────────────
def load_image(path: str | Path) -> np.ndarray:
    """이미지 파일 → numpy array (BGR)."""
    # 한글 경로 대응: np.fromfile로 읽고 cv2.imdecode
    arr = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f'이미지 로드 실패: {path}')
    return img


def save_image(img: np.ndarray, path: str | Path) -> None:
    """numpy array → 이미지 파일. 한글 경로 대응."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise ValueError(f'이미지 인코딩 실패: {path}')
    buf.tofile(str(path))


def preprocess_file(input_path: str | Path, output_path: str | Path,
                    method: str = 'default') -> dict:
    """파일 단위 전처리."""
    img = load_image(input_path)
    original_shape = img.shape

    methods = {
        'default': preprocess_default,
        'aggressive': preprocess_aggressive,
        'light': preprocess_light,
    }
    if method not in methods:
        raise ValueError(f'Unknown method: {method}. Options: {list(methods)}')

    processed = methods[method](img)
    save_image(processed, output_path)

    return {
        'input': str(input_path),
        'output': str(output_path),
        'method': method,
        'original_shape': original_shape,
        'processed_shape': processed.shape,
    }


# ────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        # 기본 테스트
        input_path = 'ocr_storage/preprocessed/수입_수출계약서_0001/page_01.png'
        output_path = 'ocr_storage/_preprocessed_test/page_01_default.png'
        method = 'default'
    else:
        input_path = sys.argv[1]
        output_path = sys.argv[2]
        method = sys.argv[3] if len(sys.argv) > 3 else 'default'

    info = preprocess_file(input_path, output_path, method)
    print(f'[IN]  {info["input"]}')
    print(f'[OUT] {info["output"]}')
    print(f'[METHOD] {info["method"]}')
    print(f'[SHAPE] {info["original_shape"]} -> {info["processed_shape"]}')
