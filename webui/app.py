import streamlit as st

# [최상단 필수] 페이지 설정
st.set_page_config(page_title="TradeLex", layout="wide")

import os
import io
import mimetypes
import json
import re
import sys
import time
import requests
import subprocess
import atexit
from pathlib import Path
from datetime import datetime
import warnings
import logging

# transformers의 내부 경고 메시지 숨기기
warnings.filterwarnings("ignore", category=UserWarning, module="transformers")
# 로깅 레벨을 WARNING 이상으로 설정하여 INFO/DEBUG 메시지 제거
logging.getLogger("transformers").setLevel(logging.WARNING)

# 2. transformers 라이브러리 전용 로그 설정
try:
    from transformers import logging as tf_logging
    # 로그 레벨을 ERROR로 설정하여 WARNING, INFO 메시지를 모두 차단합니다.
    tf_logging.set_verbosity_error() 
except ImportError:
    pass

# [Refactored] OCR 통합 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OCR_PATH = PROJECT_ROOT / "ocr"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(OCR_PATH) not in sys.path:
    sys.path.insert(0, str(OCR_PATH))

# ─── [NEW] Ollama 서버 자동 관리 로직 ───
def ensure_ollama():
    """Ollama 서버가 꺼져 있으면 자동으로 실행하고, 앱 종료 시 함께 종료합니다."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=2)
        if resp.status_code == 200:
            return None  # 이미 실행 중
    except:
        print("🚀 Ollama 서버가 꺼져 있습니다. 자동 실행을 시작합니다...")
        proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        atexit.register(lambda: proc.terminate())

        with st.spinner("🛠️ AI 엔진(Ollama) 부팅 중... (약 5~10초 소요)"):
            for _ in range(10):
                time.sleep(1)
                try:
                    if requests.get("http://localhost:11434/api/tags", timeout=1).status_code == 200:
                        break
                except:
                    continue
        return proc

ensure_ollama()

# late imports
from security.sanitizer import sanitize_text
from core.secure_store import LocalSecureStore
from core.engine_proxy import run_analysis_stream, get_engine
import main

# 캐싱 로직
@st.cache_resource
def get_cached_engine():
    return get_engine()

# PDF 생성 함수 (팀원 개선 버전: 통계 + 조항별 리포트)
def generate_pdf_report(report_data, source_filename):
    try:
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()

        font_path = "C:/Windows/Fonts/malgun.ttf"
        if os.path.exists(font_path):
            pdf.add_font("Malgun", "", font_path)
            pdf.set_font("Malgun", size=16)
        else:
            pdf.set_font("Arial", style='B', size=16)

        pdf.cell(0, 15, "TradeLex 법률 분석 결과 보고서", ln=True, align='C')
        pdf.set_font(size=10)
        pdf.cell(0, 10, f"생성 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True, align='R')
        pdf.cell(0, 10, f"대상 문서: {source_filename}", ln=True)
        pdf.ln(5)

        analyses = report_data.get("analysis", [])
        risk_counts = {"위험": 0, "주의": 0, "적합": 0}
        for item in analyses:
            lvl = item.get("risk_level", "적합")
            if lvl in risk_counts: risk_counts[lvl] += 1

        pdf.set_font(size=12)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(0, 10, f"전체 분석 통계: 위험({risk_counts['위험']}) / 주의({risk_counts['주의']}) / 적합({risk_counts['적합']})", ln=True, fill=True)
        pdf.ln(5)

        for item in analyses:
            lvl = item.get("risk_level", "적합")
            pdf.set_font(size=11)
            pdf.cell(0, 10, f"[{lvl}] {item.get('clause')}", ln=True)
            pdf.set_font(size=10)
            pdf.multi_cell(0, 8, f"요약: {item.get('summary')}")
            pdf.multi_cell(0, 8, f"의견: {item.get('commentary')}")
            pdf.ln(3)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(2)

        return pdf.output()
    except Exception as e:
        return f"PDF 생성 오류: {e}".encode('utf-8')

DEFAULT_SYSTEM_PROMPT = """당신은 국제 무역 법률 전문 변호사입니다. 
제공된 무역 서류와 검색된 법령 조문을 바탕으로, 전문적이고 권위 있는 '법률 검토 보고서'를 작성하십시오.
답변은 반드시 대한민국 강행법규를 최우선으로 고려해야 하며, 실무적인 수정 권고안을 포함해야 합니다.
보고서는 논리적인 문장으로 구성하십시오."""

# 세션 초기화
if "store" not in st.session_state:
    key_path = str(PROJECT_ROOT / "webui" / "secret.key")
    st.session_state.store = LocalSecureStore(key_file=key_path)

if "current_report" not in st.session_state: st.session_state.current_report = None
if "system_prompt" not in st.session_state: st.session_state.system_prompt = DEFAULT_SYSTEM_PROMPT

# 테마 스타일 (팀원 개선: 보고서 글자 크기 조정)
st.markdown("""
    <style>
    html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
    .stMarkdown { font-size: 0.95rem; }
    h1 { font-size: 1.8rem !important; }
    h2 { font-size: 1.5rem !important; }
    h3 { font-size: 1.2rem !important; }
    .risk-card { padding: 22px; border-radius: 12px; margin-bottom: 15px; border-left: 8px solid; background-color: var(--secondary-background-color); }
    .card-title { font-size: 1.15rem; font-weight: 700; margin-bottom: 8px; color: var(--text-color); }
    .card-summary { font-size: 1.0rem; font-weight: 600; margin-bottom: 6px; color: #8ab4f8; }
    .card-comment { font-size: 0.95rem; line-height: 1.6; color: var(--text-color); }
    .risk-high { border-color: #ef4444; } .risk-mid { border-color: #f59e0b; } .risk-low { border-color: #10b981; }
    .expert-summary { padding: 24px; background-color: var(--secondary-background-color); border-radius: 14px; border: 1px solid #444; margin-bottom: 30px; line-height: 1.7; font-style: italic; font-size: 1.05rem; }
    @media print { [data-testid="stSidebar"], .stButton, .stDownloadButton, .stFileUploader { display: none !important; } .stApp { background-color: white !important; color: black !important; } }
    </style>
""", unsafe_allow_html=True)

# [MERGED] 이미지 MIME 타입 허용 확장 (우리 수정)
def is_allowed_file(filename):
    mime, _ = mimetypes.guess_type(filename)
    allowed_mimes = ['text/plain', 'application/json', 'application/pdf',
                     'image/png', 'image/jpeg', 'image/bmp', 'image/webp']
    return mime in allowed_mimes

# 메뉴 제어용 세션 상태 초기화 (팀원 개선)
if "menu_choice" not in st.session_state: st.session_state.menu_choice = "🔍 법리 분석"

# 메뉴
with st.sidebar:
    st.title("⚖️ TradeLex")
    menu_options = ["🔍 법리 분석", "📂 분석 기록", "⚙️ 시스템 설정"]
    current_idx = menu_options.index(st.session_state.menu_choice)
    menu = st.radio("메뉴", menu_options, index=current_idx)
    st.session_state.menu_choice = menu

    st.divider()
    if "engine_started" not in st.session_state:
        with st.status("🛠️ 엔진 로딩...", expanded=True) as status:
            get_cached_engine(); st.session_state.engine_started = True; status.update(label="✅ 엔진 활성화됨", state="complete")
    else: st.success("✅ 엔진 활성화됨")

# 🔍 법리 분석
if menu == "🔍 법리 분석":
    st.header("🔍 신규 법리 분석")
    col_input, col_output = st.columns([1, 1])

    with col_input:
        st.subheader("📄 계약서 데이터")
        # [MERGED] 이미지 파일도 업로드 가능하도록 확장 (우리 수정)
        uploaded_files = st.file_uploader("무역 서류 업로드 (PDF, 이미지, TXT, JSON 여러 장 가능)",
                                         type=['txt', 'json', 'pdf', 'png', 'jpg', 'jpeg', 'bmp', 'webp'],
                                         label_visibility="collapsed", accept_multiple_files=True)

        if uploaded_files:
            if st.button("🚀 텍스트 추출 시작", use_container_width=True, type="primary"):
                all_contents = []
                with st.status("📄 여러 문서 분석 중 (OCR)...", expanded=True) as status:
                    for uf in uploaded_files:
                        if not is_allowed_file(uf.name):
                            st.error(f"지원되지 않는 형식입니다: {uf.name}")
                            continue
                        
                        filename = uf.name
                        st.write(f"처리 중: {filename}")
                        is_ocr_target = filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp"))
                        if is_ocr_target:
                            try:
                                temp_filename = f"web_{int(time.time())}_{filename}"
                                temp_pdf_path = PROJECT_ROOT / "ocr_storage" / "input" / temp_filename
                                temp_pdf_path.parent.mkdir(exist_ok=True, parents=True)
                                with open(temp_pdf_path, "wb") as f: f.write(uf.getbuffer())

                                full_ocr_data = main.run_ocr(temp_pdf_path, use_vlm=True)
                                
                                parse_data = full_ocr_data.get("parse", {})
                                key_fields = parse_data.get("key_fields", {})
                                if not key_fields:
                                    key_fields = parse_data.get("type_specific", {}).get("key_fields", {})
                                
                                items = parse_data.get("items", [])
                                if not items:
                                    items = parse_data.get("type_specific", {}).get("items", [])
                                    
                                simplified_data = {
                                    "document_type": full_ocr_data.get("document_type", "unknown"),
                                    "key_fields": key_fields,
                                    "items": items,
                                    "text": full_ocr_data.get("full_text", "") if isinstance(full_ocr_data.get("full_text"), str) else " ".join(full_ocr_data.get("full_text", []))
                                }
                                all_contents.append({"filename": filename, "data": simplified_data})
                            except Exception as e:
                                st.error(f"[{filename}] OCR 처리 중 오류: {e}")
                        else:
                            try:
                                content_str = uf.getvalue().decode("utf-8")
                            except UnicodeDecodeError:
                                content_str = uf.getvalue().decode("cp949", errors="ignore")
                            
                            try:
                                content_data = json.loads(content_str)
                                all_contents.append({"filename": filename, "data": content_data})
                            except json.JSONDecodeError:
                                all_contents.append({"filename": filename, "text": content_str})
                    
                    status.update(label="✅ 모든 문서 추출 및 병합 완료", state="complete")
                
                if all_contents:
                    # 팀원 개선: 타임스탬프를 포함하여 고유한 파일명 생성 (덮어쓰기 방지)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    save_name = f"Analysis_{timestamp}"
                    
                    merged_content = json.dumps(all_contents, ensure_ascii=False, indent=2)
                    st.session_state.store.save(save_name, sanitize_text(merged_content), category="docs")
                    st.session_state.current_content = sanitize_text(merged_content)
                    st.session_state.current_filename = save_name
                    st.session_state.current_report = None
                    st.success(f"✅ 문서 업로드 완료: {save_name}")
                    st.rerun()

        files = st.session_state.store.list_files(category="docs")
        selected_file = st.selectbox("기존 문서 선택", files) if files else None

        c1, c2 = st.columns(2)
        if c1.button("로드", key="btn_load") and selected_file:
            try:
                st.session_state.current_content = st.session_state.store.load(selected_file, category="docs")
                st.session_state.current_filename = selected_file
                st.session_state.current_report = st.session_state.store.load(selected_file, category="reports")
                st.rerun()
            except Exception as e:
                st.error(f"⚠️ 파일을 불러올 수 없습니다. 암호화 키가 변경되었을 수 있습니다. (오류: {e})")
                # 팀원 개선: 로드 실패 시 삭제 버튼 제공
                if st.button("해당 기록 삭제"):
                    st.session_state.store.wipe(selected_file, category="docs")
                    st.rerun()
        if c2.button("삭제", type="primary", key="btn_del") and selected_file:
            st.session_state.store.wipe(selected_file, category="docs"); st.rerun()

        # 파일 로드 상태 확인 및 버튼 렌더링 강제화 (팀원 개선)
        if "current_content" in st.session_state and st.session_state.current_content:
            with st.expander("📄 병합된 본문 확인"):
                try:
                    data_obj = json.loads(st.session_state.current_content)
                    if isinstance(data_obj, list):
                        for item in data_obj:
                            st.markdown(f"**📑 {item.get('filename', 'Unknown')}**")
                            st.json(item)
                            st.divider()
                    else:
                        st.json(data_obj)
                except:
                    st.text_area("본문", value=st.session_state.current_content, height=200, disabled=True)

            if not st.session_state.get("start_analysis", False):
                if st.button("🚀 분석 시작", use_container_width=True, type="primary"):
                    st.session_state.start_analysis = True
                    st.rerun()
            else:
                st.info("분석이 진행 중입니다...")


    with col_output:
        st.subheader("⚖️ 전문 법리 검토 보고서")

        # 분석 진행 중인 상태 표시 (팀원 개선)
        if "start_analysis" in st.session_state and st.session_state.start_analysis:
            with st.status("검토 보고서 작성 중...", expanded=True) as status:
                thought_placeholder = st.empty()
                full_resp = ""
                for chunk in run_analysis_stream(st.session_state.current_content, st.session_state.system_prompt):
                    full_resp += chunk
                    thought_placeholder.markdown(full_resp)

                st.session_state.current_report = full_resp
                # 팀원 개선: 타임스탬프 추가로 파일 덮어쓰기 방지
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_filename = f"{st.session_state.current_filename}_{timestamp}"
                st.session_state.store.save(save_filename, full_resp, category="reports")

                status.update(label="✅ 법리 검토 보고서 작성이 완료되었습니다.", state="complete")
                del st.session_state.start_analysis  # 팀원 개선: del 방식
                st.rerun()

        if st.session_state.current_report:
            st.markdown(st.session_state.current_report)

            st.divider()
            c1, c2 = st.columns(2)
            if c1.button("🔄 재분석"):
                st.session_state.current_report = None
                st.rerun()

            report_bytes = st.session_state.current_report.encode('utf-8')
            c2.download_button("📥 보고서 다운로드 (TXT)", data=report_bytes, file_name=f"Legal_Report_{st.session_state.current_filename}.txt")

# 📂 분석 기록 (팀원 개선: 바로보기 기능)
elif menu == "📂 분석 기록":
    st.header("📂 지난 분석 기록")
    files = st.session_state.store.list_files(category="docs")
    if not files: st.info("기록 없음")
    else:
        with st.expander("⚠️ 기록 관리"):
            if st.button("🗑️ 모든 기록 삭제", type="primary", use_container_width=True):
                for f in files: st.session_state.store.wipe(f, category="docs")
                st.rerun()
        st.divider()
        for f in files:
            with st.expander(f"📄 {f}"):
                c1, c2 = st.columns(2)
                if c1.button("기록 보기", key=f"l_{f}"):
                    try:
                        st.session_state.view_content = st.session_state.store.load(f, category="docs")
                        st.session_state.view_report = st.session_state.store.load(f, category="reports")
                    except Exception as e:
                        st.error(f"⚠️ 로드 실패: {e}")
                if c2.button("삭제", key=f"d_{f}"): st.session_state.store.wipe(f, category="docs"); st.rerun()

        # 분석 기록 탭 내에서 바로 확인 (팀원 개선)
        if "view_content" in st.session_state and st.session_state.view_content:
            st.divider()
            st.subheader(f"기록 확인: 파일명")
            with st.expander("📄 본문"):
                st.text_area("내용", value=st.session_state.view_content, height=200, disabled=True)
            if st.session_state.get("view_report"):
                st.subheader("⚖️ 지난 검토 결과")
                st.markdown(st.session_state.view_report)

# ⚙️ 시스템 설정
elif menu == "⚙️ 시스템 설정":
    st.header("⚙️ 시스템 환경 설정")
    st.session_state.system_prompt = st.text_area("AI 프롬프트", value=st.session_state.system_prompt, height=300)
    if st.button("초기화"): st.session_state.system_prompt = DEFAULT_SYSTEM_PROMPT; st.rerun()
