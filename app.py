import streamlit as st
import os
import logging
from dotenv import load_dotenv
import pandas as pd
from pdf_processor import read_existing_bookmarks, apply_bookmarks, extract_text_from_pdf
from bookmark_generator import generate_bookmarks_for_pdf

__version__ = "0.2.0"

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - v' + __version__ + ' - %(message)s'
)
logger = logging.getLogger(__name__)


load_dotenv()

# Streamlit Cloud에서는 .env 대신 st.secrets를 주로 사용하므로 폴백 지원
if not os.environ.get("OPENROUTER_API_KEY"):
    try:
        secret_key = st.secrets.get("OPENROUTER_API_KEY", "")
        if isinstance(secret_key, str) and secret_key.strip():
            os.environ["OPENROUTER_API_KEY"] = secret_key.strip()
    except Exception:
        pass

st.set_page_config(page_title="PDF 자동 북마크 생성기", layout="wide")

MODEL_OPTIONS = [
    "openrouter/free",
    "google/gemini-2.0-flash-001",
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

# 접근성: 본문/헤딩 글꼴 크기 명시 적용 및 데이터 테이블 가독성 보정
st.markdown(
    """
    <style>
    /* 본문 기본 크기: 16px */
    html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] *:not(h1):not(h2):not(h3):not(h1 *):not(h2 *):not(h3 *) {
        font-size: 16px !important;
        line-height: 1.6 !important;
    }

    /* 헤딩 크기 고정 적용 */
    [data-testid="stAppViewContainer"] h1,
    [data-testid="stAppViewContainer"] h1 * {
        font-size: 32px !important;
        line-height: 1.3 !important;
    }

    [data-testid="stAppViewContainer"] h2,
    [data-testid="stAppViewContainer"] h2 * {
        font-size: 28px !important;
        line-height: 1.35 !important;
    }

    [data-testid="stAppViewContainer"] h3,
    [data-testid="stAppViewContainer"] h3 * {
        font-size: 24px !important;
        line-height: 1.4 !important;
    }

    /* 데이터 테이블(st.dataframe, st.data_editor) 내부 텍스트 크기: 16px */
    [data-testid="stDataFrame"], [data-testid="stDataEditor"],
    [data-testid="stDataFrame"] *, [data-testid="stDataEditor"] * {
        font-size: 16px !important;
    }
    /* 테이블 헤더 및 셀 패딩 조정 */
    th, td {
        padding: 12px !important;
        line-height: 1.5 !important;
    }
    /* 버튼 크기 조정 */
    .stButton>button, .stDownloadButton>button {
        min-height: 48px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title(f"📚 PDF 자동 북마크(목차) 생성기 v{__version__}")
st.write("PDF 파일을 업로드하시면 텍스트 문맥을 분석하여 알맞은 북마크(목차)를 제안합니다.")
selected_model = st.selectbox(
    "사용할 AI 모델(모두 무료)을 선택하세요 (권장: openrouter/free)",
    MODEL_OPTIONS,
    index=0,
)

uploaded_file = st.file_uploader("PDF 파일을 업로드해주세요.", type=["pdf"])

if "bookmarks" not in st.session_state:
    st.session_state.bookmarks = None
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None
if "extracted_pages" not in st.session_state:
    st.session_state.extracted_pages = None

if uploaded_file is not None:
    st.session_state.pdf_filename = uploaded_file.name
    if st.session_state.pdf_bytes != uploaded_file.getvalue():
        st.session_state.pdf_bytes = uploaded_file.getvalue()
        st.session_state.bookmarks = None
        st.session_state.extracted_pages = None
        st.session_state.current_df = None
        
    st.info(f"업로드 완료: {uploaded_file.name}")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if st.button("기존 북마크 확인", use_container_width=True):
            with st.spinner("기존 북마크를 확인중입니다..."):
                try:
                    logger.info("기존 북마크 확인 시작")
                    existing = read_existing_bookmarks(st.session_state.pdf_bytes)
                    if not existing:
                        st.warning("이 문서에는 북마크가 없습니다.")
                        logger.info("기존 북마크 없음")
                    else:
                        st.success(f"총 {len(existing)}개의 기존 북마크를 찾았습니다.")
                        st.dataframe(pd.DataFrame(existing, columns=["Level", "Title", "Page"]))
                        logger.info(f"기존 북마크 {len(existing)}개 표시")
                except ValueError as e:
                    st.error(f"⚠️ 유효하지 않은 PDF 파일입니다: {str(e)}")
                    logger.error(f"유효하지 않은 PDF: {str(e)}")
                except MemoryError as e:
                    st.error(f"⚠️ 파일이 너무 커서 처리할 수 없습니다: {str(e)}")
                    logger.error(f"메모리 부족: {str(e)}")
                except Exception as e:
                    st.error(f"⚠️ 북마크 확인 중 오류가 발생했습니다: {str(e)}")
                    logger.error(f"북마크 확인 중 오류: {str(e)}", exc_info=True)
                    
    with col2:
        if st.button("AI 목차 자동 분석 및 생성", type="primary", use_container_width=True):
            if not os.environ.get("OPENROUTER_API_KEY"):
                st.error("환경 변수(OPENROUTER_API_KEY)가 설정되지 않았습니다.")
                logger.error("OPENROUTER_API_KEY 환경 변수 미설정")
            else:
                logger.info("AI 북마크 생성 시작")
                progress_container = st.container()
                
                with progress_container:
                    st.info("📊 진행 중: PDF 텍스트 추출 중입니다...")
                    
                    # 먼저 텍스트 추출을 통해 스캔 문서(이미지) 여부 판별
                    try:
                        extracted_pages = extract_text_from_pdf(st.session_state.pdf_bytes)
                        st.session_state.extracted_pages = extracted_pages
                        
                        total_pages = len(extracted_pages)
                        total_text_length = sum(len(p['text']) for p in extracted_pages)
                        logger.info(f"텍스트 추출 완료: {total_pages}페이지, {total_text_length}자")
                        
                        # 페이지당 평균 텍스트가 20자 미만이면 이미지/스캔본일 확률이 높음
                        if total_pages > 0 and (total_text_length / total_pages) < 20:
                            st.error("⚠️ 경고: PDF에서 인식된 텍스트가 거의 없습니다.")
                            st.warning("스캔본이거나 텍스트 레이어가 없는 이미지 형태의 문서일 가능성이 높습니다. 먼저 외부 OCR(광학 문자 인식) 프로그램을 통해 문서를 '텍스트 검색 가능한 형식'으로 변환한 뒤 다시 시도해 주세요.")
                            logger.warning(f"스캔본 감지: 평균 텍스트 길이 = {total_text_length / total_pages if total_pages > 0 else 0}")
                        else:
                            model_status = st.empty()
                            model_status.info(f"📊 진행 중: OpenRouter 모델({selected_model})이 문서를 분석 중입니다...")
                            
                            try:
                                generation_result = generate_bookmarks_for_pdf(
                                    extracted_pages=st.session_state.extracted_pages,
                                    pdf_bytes=st.session_state.pdf_bytes,
                                    model_name=selected_model,
                                    return_meta=True,
                                    on_status_update=model_status.warning,
                                )
                                generated = generation_result.get("bookmarks", [])
                                effective_model = generation_result.get("effective_model", selected_model)
                                fallback_used = bool(generation_result.get("fallback_used", False))
                                if fallback_used and effective_model != selected_model:
                                    model_status.warning(
                                        f"⚠️ 선택 모델({selected_model})이 사용 불가하여 fallback 모델({effective_model})로 분석했습니다."
                                    )
                                else:
                                    model_status.info(f"✅ 분석 완료: 실제 사용 모델은 {effective_model} 입니다.")
                                logger.info(
                                    f"AI 북마크 생성 완료: {len(generated)}개 항목 (requested={selected_model}, effective={effective_model})"
                                )
                            except Exception as e:
                                st.error("AI 목차(북마크) 생성에 실패했습니다.")
                                st.caption(str(e))
                                logger.error(f"AI 생성 실패: {str(e)}", exc_info=True)
                                with st.expander("기술 정보 보기"):
                                    st.exception(e)
                                generated = []

                            if generated:
                                st.session_state.bookmarks = generated
                                st.success("✅ 북마크 생성이 완료되었습니다! 아래에서 검토 및 수정해 주세요.")
                                logger.info(f"최종 북마크: {len(generated)}개")
                            else:
                                st.error("북마크 생성 결과가 비어 있습니다.")
                                st.warning("텍스트 품질이 낮거나, 문서 구조를 북마크로 해석하기 어려운 경우일 수 있습니다.")
                                logger.warning("생성된 북마크가 없음")
                                
                    except ValueError as e:
                        st.error(f"⚠️ 유효하지 않은 PDF 파일입니다: {str(e)}")
                        logger.error(f"유효하지 않은 PDF: {str(e)}")
                    except MemoryError as e:
                        st.error(f"⚠️ 파일이 너무 커서 처리할 수 없습니다: {str(e)}")
                        logger.error(f"메모리 부족: {str(e)}")
                    except Exception as e:
                        st.error(f"⚠️ 예상치 못한 오류가 발생했습니다: {str(e)}")
                        logger.error(f"예상치 못한 오류: {str(e)}", exc_info=True)
                        with st.expander("기술 정보 보기"):
                            st.exception(e)

# 사용자 검토 및 에디터 화면
if st.session_state.bookmarks is not None:
    st.subheader("📝 생성된 북마크 검토 및 수정")
    # UI에는 level 숫자를 숨기고,
    # 대신 "들여쓰기된 프리뷰(표시용)" + "+/- 버튼(실제 level 조정)"으로 중첩 구조를 이해/편집합니다.
    # 주의: title에는 들여쓰기 공백을 절대 추가하지 않습니다. (PDF TOC에는 원본 title만 저장)
    bookmarks_state = st.session_state.bookmarks or []

    # 기본값 정리
    for bm in bookmarks_state:
        if "level" not in bm or bm.get("level") is None:
            bm["level"] = 1
        if bm.get("page") is None:
            bm["page"] = 1
        if bm.get("title") is None:
            bm["title"] = ""

    # page/title/level과 함께 미리보기(들여쓰기)도 표에 포함
    # session_state를 사용해서 실시간 미리보기 업데이트
    if 'current_df' not in st.session_state or st.session_state.current_df is None:
        st.session_state.current_df = pd.DataFrame(
            [
                {
                    "page": bm.get("page"),
                    "level": bm.get("level", 1),
                    "title": bm.get("title"),
                    "preview": "        " * (max(1, bm.get("level", 1)) - 1) + (bm.get("title") or ""),
                }
                for bm in bookmarks_state
            ]
        )

    st.markdown(
        """
        <style>
        /* data_editor 도구 모음 버튼 텍스트 확대 */
        div[data-testid=stDataFrame] button,
        div[data-testid=stDataFrame] select,
        div[data-testid=stDataFrame] input {
            transform: scale(1.6) !important;
            transform-origin: left top !important;
            min-height: 28px !important;
            min-width: 90px !important;
            font-size: 1.1rem !important;
            margin: 0.1rem 0.2rem !important;
        }

        div[data-testid=stDataFrame] .stButton>button,
        div[data-testid=stDataFrame] .css-1xlx62d.egzxvld1 {
            padding: 0.2rem 0.4rem !important;
            margin: 0 0.2rem !important;
        }

        /* 도구모음(Download, Search 등) 항상 보이도록 */
        [data-testid="stElementToolbar"] {
            opacity: 1 !important;
            visibility: visible !important;
            background-color: transparent !important;
        }

        /* 표와 툴바가 겹치지 않도록 여백 확보 */
        div[data-testid=stDataFrame] {
            margin-top: 0.6rem !important;
            padding-top: 2rem !important;
        }

        /* 데이터 테이블 관련 중복 스타일 제거 (상단에서 통합 관리) */

        /* 테이블 내부 과도한 스크롤 제거: 전체 행을 페이지에 보이게 */
        div[data-testid="stDataFrame"] .ag-body-viewport,
        div[data-testid="stDataFrame"] .ag-body-viewport-wrapper,
        div[data-testid="stDataFrame"] .ag-center-cols-viewport,
        div[data-testid="stDataFrame"] .ag-center-cols-clipper,
        div[data-testid="stDataFrame"] .ag-root-wrapper,
        div[data-testid="stDataFrame"] .ag-root {
            max-height: none !important;
            height: auto !important;
            overflow: visible !important;
        }

        /* 테이블 텍스트 크기 중복 정의 제거 */

        /* 툴바 분리 공간 */
        div[data-testid=stDataFrame] .css-1xxxc8i {
            gap: 0.4rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    edited_df = st.data_editor(
        st.session_state.current_df,
        num_rows="dynamic",
        use_container_width=True,
        disabled=False,
        column_config={
            "page": st.column_config.NumberColumn(
                "페이지 번호", min_value=1, step=1, required=True, width="small"
            ),
            "level": st.column_config.NumberColumn(
                "중첩 레벨", min_value=1, step=1, required=True, width="small"
            ),
            "title": st.column_config.TextColumn("북마크 제목", required=True, width="medium"),
            "preview": st.column_config.TextColumn(
                "미리보기", disabled=True, help="수정 불가; 레벨 변화에 따라 자동 갱신됩니다.", width="large"
            ),
        },
    )

    # edited_df를 사용해서 미리보기를 실시간 업데이트
    if edited_df is not None:
        updated_df = edited_df.copy()
        updated_df['preview'] = updated_df.apply(
            lambda row: "        " * (max(1, int(row.get("level", 1))) - 1) + str(row.get("title", "")),
            axis=1
        )
        st.session_state.current_df = updated_df

    edited_records = edited_df.to_dict("records") if edited_df is not None else []

    # 편집된 page/title/level을 적용 (title은 strip만 수행)
    merged = []
    for rec in edited_records:
        try:
            page = int(rec.get("page"))
            level = int(rec.get("level", 1) or 1)
        except Exception:
            continue

        title_raw = rec.get("title")
        title = "" if title_raw is None else str(title_raw).strip()
        if title.lower() == "nan":
            title = ""

        if title and page > 0 and level >= 1:
            merged.append({"page": page, "level": level, "title": title})

    st.session_state.bookmarks = merged

    # 최종 출력 섹션은 편집 북마크가 있을 때 항상 보이게 유지
    if st.session_state.get("pdf_bytes") is not None and st.session_state.get("bookmarks"):
        st.markdown("---")
        st.subheader("💾 최종 파일 내보내기")

        # 1) 기본 파일명 생성 (예: example.pdf -> example_bookmarked.pdf)
        import os
        filename_source = uploaded_file.name if uploaded_file is not None else st.session_state.get("pdf_filename", "document.pdf")
        base_name, ext = os.path.splitext(filename_source)
        if ext == "":
            ext = ".pdf"
        default_filename = f"{base_name}_bookmarked{ext}"

        # 2) 파일명 수정 가능한 입력창 제공
        download_filename = st.text_input(
            "아래 칸에서 파일 이름을 자유롭게 수정한 뒤 다운로드 버튼을 눌러주세요.",
            value=default_filename,
        )

        # 3) 실시간으로 변경된 북마크 정보를 반영한 PDF 생성
        final_bookmarks = st.session_state.bookmarks or []
        try:
            new_pdf_data = apply_bookmarks(st.session_state.pdf_bytes, final_bookmarks)
            
            st.download_button(
                label="📥 북마크가 적용된 PDF 다운로드",
                data=new_pdf_data,
                file_name=download_filename,
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )
        except Exception as e:
            st.error(f"PDF 생성 중 오류가 발생했습니다: {str(e)}")
            logger.error(f"PDF 생성 오류: {str(e)}", exc_info=True)
    else:
        st.warning("PDF 파일을 업로드하고 북마크를 생성하면 다운로드 버튼이 나타납니다.")
