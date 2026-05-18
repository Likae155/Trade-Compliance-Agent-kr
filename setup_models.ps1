# Ollama 모델 자동 등록 스크립트 (Windows용)

Write-Host "🚀 Ollama 모델 등록 및 업데이트를 시작합니다..." -ForegroundColor Cyan

# 1. OCR용 모델 등록 (HuggingFace 직접 연동)
# Modelfile_OCR 내부에 hf.co 경로가 지정되어 있어 Ollama가 직접 다운로드합니다.
Write-Host "📦 OCR 모델 등록 중 (HuggingFace에서 직접 다운로드): gemma4:e2b-ocr..." -ForegroundColor Yellow
ollama create gemma4:e2b-ocr -f models/Modelfile_OCR

# ==========================================
# 사용자 설정 (본인의 구글 드라이브 파일 ID 입력)
# ==========================================
$GOOGLE_DRIVE_FILE_ID = "1cJP0Dw5dDaqjN8IDq5lXPDe-S_K290A5"
$MODEL_PATH = "models/gemma-4-e2b-it.Q4_K_M.gguf"
$MODELFILE_PATH = "models/finetuned_model/Modelfile_FT"
$OLLAMA_MODEL_NAME = "gemma4-e2b-ft-gguf:latest"

# 1. 저장할 폴더가 없으면 생성
$TargetDir = Split-Path $MODEL_PATH
if (-not (Test-Path $TargetDir)) {
    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
}

# 2. 모델 파일 존재 여부 확인 및 다운로드
if (-not (Test-Path $MODEL_PATH)) {
    Write-Host "🌐 구글 드라이브에서 모델 파일 다운로드 중 (약 3.3GB)..." -ForegroundColor Cyan
    
    # 대용량 파일 다운로드용 확인 토큰 추출 및 다운로드 URL 구성
    $BaseUrl = "https://docs.google.com/uc?export=download&id=$GOOGLE_DRIVE_FILE_ID"
    try {
        # 1차 요청으로 대용량 경고 페이지의 토큰 확인
        $Response = Invoke-WebRequest -Uri $BaseUrl -SessionVariable Session -UserAgent "Mozilla/5.0" -MaximumRedirection 0 -ErrorAction SilentlyContinue
        $Token = ""
        if ($Response.Headers.Location -match "confirm=([a-zA-Z0-9_]+)") {
            $Token = $Matches[1]
        }
        
        # 토큰이 적용된 최종 다운로드 URL
        $DownloadUrl = $BaseUrl
        if ($Token -ne "") {
            $DownloadUrl = "$BaseUrl&confirm=$Token"
        }

        # 파일 다운로드 시작
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $MODEL_PATH -WebSession $Session
        Write-Host "✅ 다운로드 완료: $MODEL_PATH" -ForegroundColor Green
    } 
    catch {
        Write-Host "❌ 다운로드 실패. 네트워크 상태나 파일 ID를 확인하십시오." -ForegroundColor Red
        Exit
    }
} else {
    Write-Host "✨ 이미 모델 파일이 로컬에 존재합니다." -ForegroundColor Green
}
Write-Host "`n✅ 모델 등록 절차가 완료되었습니다!" -ForegroundColor Green
Write-Host "확인 명령어: ollama list"
