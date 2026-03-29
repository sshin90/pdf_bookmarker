import os
import json
import re
import hashlib
import logging
import time
from openai import OpenAI
from tenacity import (
    Retrying,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
)
from pdf_processor import extract_text_from_pdf

logger = logging.getLogger(__name__)

# 상수 정의
DEFAULT_CHUNK_SIZE = 60000  # 한 청크의 최대 문자 수
TARGET_MAX_CHUNKS = 8  # 목표 청크 개수
MAX_CHUNK_SIZE = 500000  # 최대 청크 크기
TITLE_MAX_LENGTH = 50  # 제목 최대 길이
AVERAGE_TEXT_THRESHOLD = 20  # 텍스트 인식 여부 판별 기준
TEMPERATURE = 0.1  # LLM 온도(창의성)
FALLBACK_MODEL = "openrouter/free"


def _should_fallback_model(msg: str) -> bool:
    lower_msg = msg.lower()
    return (
        "not a valid model id" in lower_msg
        or "no endpoints found for" in lower_msg
        or ("error code: 404" in lower_msg and "model" in lower_msg)
        # 429는 재시도 후에도 실패할 경우에만 최종적으로 fallback 처리하기 위해 별도 관리
    )

def _is_rate_limit_error(e: Exception) -> bool:
    """
    OpenRouter 또는 업스트림의 429(Rate Limit) 에러인지 확인합니다.
    """
    s = str(e).lower()
    return "429" in s or "rate limit" in s or "too many requests" in s or "resource_exhausted" in s

def get_openrouter_client():
    """
    OpenRouter API 클라이언트를 가져옵니다.
    
    Returns:
        OpenAI: OpenRouter API 클라이언트
        
    Raises:
        ValueError: OPENROUTER_API_KEY 환경 변수가 없음
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        logger.error("OPENROUTER_API_KEY 환경 변수가 설정되지 않았습니다.")
        raise ValueError("OPENROUTER_API_KEY 환경 변수가 설정되지 않았습니다.")
    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/sshin90/pdf_bookmarker", # 앱 정보 제공 (선택)
            "X-Title": "PDF Bookmarker",
        }
    )

def _normalize_title(title: str) -> str | None:
    """
    제목을 정규화합니다.
    
    Args:
        title: 원본 제목 텍스트
        
    Returns:
        정규화된 제목 또는 None
    """
    if title is None:
        return None
    s = str(title).strip()
    if not s:
        return None
    if s.lower() == "nan":
        return None
    # 제목은 TOC에 과도하게 길지 않게 유지
    if len(s) > TITLE_MAX_LENGTH:
        s = s[:TITLE_MAX_LENGTH].rstrip()
    return s

def _chunk_pages(pages: list[dict], max_chars: int = DEFAULT_CHUNK_SIZE) -> list[list[dict]]:
    """
    텍스트를 일정 글자 수 단위로 분할합니다.
    - 토큰 예측이 어려워 characters 기반 휴리스틱 사용
    - 각 청크에는 원본 페이지 번호가 포함됩니다.
    """
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_len = 0

    def approx_entry_len(p: dict) -> int:
        # 구분자 길이 포함 대략치
        return len(p.get("text", "")) + 40

    for p in pages:
        entry_len = approx_entry_len(p)
        if current and (current_len + entry_len) > max_chars:
            chunks.append(current)
            current = []
            current_len = 0
        current.append(p)
        current_len += entry_len

    if current:
        chunks.append(current)
    
    logger.debug(f"청크 분할 완료: {len(chunks)}개 청크 (max_chars={max_chars})")
    return chunks

def _build_chunks_adaptive(
    pages: list[dict],
    target_max_chunks: int = TARGET_MAX_CHUNKS,
    start_max_chars: int = DEFAULT_CHUNK_SIZE,
    max_max_chars: int = MAX_CHUNK_SIZE,
) -> list[list[dict]]:
    """
    목표 청크 수를 만족하도록 max_chars를 키워서(청크 개수↓),
    Gemini 호출 횟수(=청크 수)를 줄입니다.
    """
    max_chars = start_max_chars
    iteration = 0
    for _ in range(8):
        chunks = _chunk_pages(pages, max_chars=max_chars)
        if len(chunks) <= target_max_chunks:
            logger.info(f"적응형 청킹 완료: {len(chunks)}개 청크 (반복: {iteration}회)")
            return chunks
        max_chars = int(max_chars * 1.5)
        iteration += 1
        if max_chars > max_max_chars:
            logger.warning(f"최대 청크 크기 도달: {max_chars}")
            break
    chunks = _chunk_pages(pages, max_chars=max_chars)
    logger.info(f"적응형 청킹 완료: {len(chunks)}개 청크 (max_chars={max_chars})")
    return chunks

def _retry_seconds_from_message(msg: str) -> float | None:
    """
    LLM 에러 메시지에서 재시도 대기 시간을 추출합니다.
    
    Args:
        msg: 에러 메시지
        
    Returns:
        float | None: 재시도 대기 시간(초) 또는 None
    """
    # 예: "Please retry in 40.835011848s."
    m = re.search(r"retry in\s*([0-9]+(?:\.[0-9]+)?)s", msg, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None

def _format_llm_error(e: Exception) -> str:
    """
    OpenRouter API 에러를 사용자 친화적인 메시지로 포맷합니다.
    
    Args:
        e: 예외 객체
        
    Returns:
        str: 포맷된 에러 메시지
    """
    s = str(e)
    if _should_fallback_model(s):
        return (
            "선택한 모델이 현재 OpenRouter에서 사용 불가합니다. "
            "앱에서 다른 모델을 선택하거나 openrouter/free를 사용해 주세요. "
            f"(원문: {s})"
        )
    if "429" in s and "RESOURCE_EXHAUSTED" in s:
        retry_seconds = _retry_seconds_from_message(s)
        retry_text = (
            f"약 {retry_seconds:.0f}초 후 재시도 가능" if retry_seconds is not None else "잠시 후 재시도 필요"
        )
        return (
            "OpenRouter API 호출 한도(쿼터)가 초과되었습니다. "
            "특히 무료 모델 요청 한도를 초과한 경우가 많습니다. "
            "플랜/빌링에서 쿼터를 늘리거나, 일일 한도 리셋까지 기다린 뒤 다시 시도하세요. "
            f"{retry_text}."
        )
    return f"LLM 호출 중 오류가 발생했습니다: {s}"

def _get_cache_path(pdf_bytes: bytes, cache_dir: str, model_name: str) -> str:
    """
    PDF의 해시 값을 기반으로 캐시 파일 경로를 생성합니다.
    
    Args:
        pdf_bytes: PDF 파일의 바이트 데이터
        cache_dir: 캐시 디렉토리 경로
        
    Returns:
        str: 캐시 파일 경로
    """
    model_key = model_name.encode("utf-8", errors="ignore")
    h = hashlib.sha256(pdf_bytes + b"::" + model_key).hexdigest()
    return os.path.join(cache_dir, f"bookmarks_{h}.json")

def _merge_and_dedupe(candidates: list[dict]) -> list[dict]:
    """
    중복된 북마크를 제거하고 병합합니다.
    
    Args:
        candidates: 북마크 후보 목록
        
    Returns:
        정렬되고 중복이 제거된 북마크 목록
    """
    dedup: dict[tuple[int, str, int], dict] = {}
    for c in candidates:
        try:
            page = int(c["page"])
            level = int(c["level"])
            title = _normalize_title(c.get("title"))
        except (ValueError, KeyError, TypeError):
            continue

        if page <= 0 or level < 1 or not title:
            continue

        key = (page, title, level)
        # 동일 키는 1개만 유지
        if key not in dedup:
            dedup[key] = {"page": page, "level": level, "title": title}

    merged = list(dedup.values())
    merged.sort(key=lambda x: (x["page"], x["level"], x["title"]))
    logger.debug(f"중복 제거 완료: {len(candidates)} -> {len(merged)}개 항목")
    return merged

def generate_bookmarks_for_pdf(
    pdf_bytes: bytes = None,
    extracted_pages: list[dict] = None,
    model_name: str = FALLBACK_MODEL,
    return_meta: bool = False,
    on_status_update: callable = None,
) -> list[dict] | dict:
    """
    PDF 텍스트를 추출(또는 이미 추출된 페이지 사용)한 뒤,
    대용량 문서를 청크 단위로 생성->병합하여 중첩 북마크(level)까지 생성합니다.
    
    Args:
        pdf_bytes: PDF 파일의 바이트 데이터 (선택)
        extracted_pages: 이미 추출된 페이지 데이터 (선택)
        
    Returns:
        list[dict]: 생성된 북마크 목록
        
    Raises:
        ValueError: pdf_bytes와 extracted_pages가 모두 None인 경우
        RuntimeError: OpenRouter API 호출 실패
    """
    if extracted_pages is None:
        if pdf_bytes is None:
            logger.error("pdf_bytes 또는 extracted_pages 중 하나는 반드시 제공되어야 합니다.")
            raise ValueError("pdf_bytes 또는 extracted_pages 중 하나는 반드시 제공되어야 합니다.")
        logger.info("PDF에서 텍스트 추출 시작")
        pages = extract_text_from_pdf(pdf_bytes)
    else:
        logger.info(f"사전 추출된 페이지 사용: {len(extracted_pages)}페이지")
        pages = extracted_pages

    if not pages:
        logger.warning("추출된 페이지가 없습니다.")
        return []

    logger.info(f"북마크 생성 시작: {len(pages)}페이지, 총 {sum(len(p.get('text', '')) for p in pages)}자")
    client = get_openrouter_client()

    # 동일 PDF에 대한 중복 LLM 호출을 줄이기 위한 로컬 캐시
    cache_dir = os.path.join(os.path.dirname(__file__), ".cache")
    cache_path = None
    requested_model = model_name
    effective_model = model_name
    fallback_used = False
    if pdf_bytes is not None:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            cache_path = _get_cache_path(pdf_bytes, cache_dir, model_name)
            if os.path.exists(cache_path):
                logger.info(f"캐시에서 북마크 로드: {cache_path}")
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if isinstance(cached, list):
                    logger.info(f"캐시 북마크 반환: {len(cached)}개 항목")
                    if return_meta:
                        return {
                            "bookmarks": cached,
                            "requested_model": requested_model,
                            "effective_model": effective_model,
                            "fallback_used": fallback_used,
                        }
                    return cached
        except Exception as e:
            logger.warning(f"캐시 로드 실패: {str(e)}")
            cache_path = None

    # 청크 단위 생성이므로 청크별로 너무 많은 항목을 내지 않게 유도합니다.
    prompt = """
당신은 PDF 문서를 분석해 TOC(북마크) 계층 구조를 추출하는 AI입니다.

아래 텍스트는 여러 페이지가 섞여 있을 수 있으며, 각 페이지는 다음 구분자로 표시됩니다.
- --- PAGE N START ---
- --- PAGE N END ---

[출력 규칙]
1) response_schema에 맞춰 JSON으로만 출력합니다(모델이 강제하는 파싱을 따름).
2) 각 북마크 항목은 반드시 다음 필드를 포함합니다:
   - page: 원문에서 표시된 페이지 번호(정확히)
   - level: 중첩 깊이(1부터 시작). 1은 최상위(장/섹션), 2는 그 하위(절), 3은 더 하위(세부)로 사용.
   - title: 50자 이내 핵심 제목(원문을 최대한 살림)
3) 계층(level)은 "장 -> 절 -> 세부" 흐름이 자연스러우면 높여도 됩니다.
4) 한 청크에서는 너무 많은 항목을 만들지 말고, 문서 골격을 보여주는 핵심만 뽑습니다.
5) 제목이 애매하거나 확신이 없으면 해당 항목을 생략하는 것을 허용합니다.

[목차 추출 가이드라인]
1. 프레젠테이션(파워포인트 등): 각 슬라이드의 상단 제목(헤딩/슬라이드 제목)을 우선 북마크로 만드세요.
2. 일반 줄글 문서: 새로운 장/절이 시작되는 지점을 우선 포함하세요.
3. 공통: title 길이는 50자 이내, page는 구분자에 나온 값을 정확히 사용하세요.
"""

    # 무료 티어에서 429가 자주 나오는 것을 막기 위해 호출 횟수(=청크 수)를 줄입니다.
    chunks = _build_chunks_adaptive(pages, target_max_chunks=TARGET_MAX_CHUNKS, start_max_chars=DEFAULT_CHUNK_SIZE)
    candidates: list[dict] = []
    if on_status_update:
        on_status_update(f"⏳ 분석 준비 완료: 총 {len(chunks)}개 구획으로 나누어 분석을 시작합니다.")

    for idx, chunk_pages in enumerate(chunks, 1):
        if on_status_update:
            on_status_update(f"🔄 분석 중 ({idx}/{len(chunks)}): AI가 문서 내용을 파악하고 있습니다...")
        full_text = ""
        for page_data in chunk_pages:
            current_text = page_data["text"]
            page_num = page_data["page"]
            full_text += (
                f"\n\n--- PAGE {page_num} START ---\n{current_text}\n"
                f"--- PAGE {page_num} END ---\n"
            )

        request_messages = [
            {
                "role": "system",
                "content": (
                    "당신은 PDF TOC(북마크) 추출기입니다. "
                    "반드시 JSON 객체로만 응답하고 최상위 키는 bookmarks여야 합니다."
                ),
            },
            {"role": "user", "content": prompt},
            {"role": "user", "content": full_text},
        ]

        def call_openai_with_retry(m: str, msgs: list):
            # tenacity를 사용해 429 에러 시 지수 백오프로 재시도
            try:
                for attempt in Retrying(
                    stop=stop_after_attempt(5),
                    wait=wait_exponential(multiplier=1, min=4, max=60),
                    retry=retry_if_exception(_is_rate_limit_error),
                    before_sleep=lambda retry_state: (
                        on_status_update(
                            f"⚠️ 과부하로 인해 재시도 중... ({retry_state.attempt_number}회차, "
                            f"{retry_state.next_action.sleep:.1f}초 후 다시 시도)"
                        ) if on_status_update else None
                    ),
                    reraise=True
                ):
                    with attempt:
                        logger.debug(f"청크 {idx}/{len(chunks)} OpenRouter 호출 중... (모델={m})")
                        res = client.chat.completions.create(
                            model=m,
                            temperature=TEMPERATURE,
                            response_format={"type": "json_object"},
                            messages=msgs,
                        )
                        return res
            except Exception as e:
                raise e

        try:
            response = call_openai_with_retry(effective_model, request_messages)
            logger.debug(f"청크 {idx}/{len(chunks)} OpenRouter 응답 수신 완료")
        except Exception as e:
            err_msg = str(e)
            # 만약 일반적인 모델 부재/오류거나, 재시도 끝에 429로 실패했다면 fallback 시도
            if (_should_fallback_model(err_msg) or _is_rate_limit_error(e)) and effective_model != FALLBACK_MODEL:
                logger.warning(
                    f"선택 모델({effective_model}) 오류 또는 할당 초과로 fallback 모델로 시도합니다: -> {FALLBACK_MODEL}"
                )
                if on_status_update:
                    on_status_update(f"🔄 모델 전환 중: {effective_model} -> {FALLBACK_MODEL} (이전 오류: 429)")
                
                try:
                    fallback_used = True
                    effective_model = FALLBACK_MODEL
                    response = call_openai_with_retry(effective_model, request_messages)
                except Exception as fallback_error:
                    logger.error(f"청크 {idx} OpenRouter fallback 호출 최종 실패: {str(fallback_error)}")
                    raise RuntimeError(_format_llm_error(fallback_error)) from fallback_error
            else:
                logger.error(f"청크 {idx} OpenRouter 호출 실패: {err_msg}")
                raise RuntimeError(_format_llm_error(e)) from e

        content = (response.choices[0].message.content or "").strip()
        if not content:
            logger.warning(f"청크 {idx}: 응답 본문이 비어 있습니다.")
            continue

        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            logger.warning(f"청크 {idx}: JSON 파싱 실패")
            continue

        bookmarks = result.get("bookmarks") if isinstance(result, dict) else None
        if not isinstance(bookmarks, list):
            logger.warning(f"청크 {idx}: 응답에 북마크가 없습니다.")
            continue

        chunk_bookmarks = []
        for bm in bookmarks:
            if not isinstance(bm, dict):
                continue
            candidates.append(
                {
                    "page": bm.get("page"),
                    "level": bm.get("level"),
                    "title": bm.get("title"),
                }
            )
            chunk_bookmarks.append(str(bm.get("title", "")))
        logger.info(f"청크 {idx}: {len(chunk_bookmarks)}개 북마크 추출")
        if on_status_update:
            on_status_update(f"✅ {idx}/{len(chunks)} 구획 분석 성공 ({len(chunk_bookmarks)}개 항목 발견)")

    merged = _merge_and_dedupe(candidates)
    logger.info(f"최종 북마크: {len(merged)}개 항목")

    # 캐시 저장(가능한 경우)
    if cache_path is not None:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            logger.info(f"북마크 캐시 저장됨: {cache_path}")
        except Exception as e:
            logger.warning(f"캐시 저장 실패: {str(e)}")

    if return_meta:
        return {
            "bookmarks": merged,
            "requested_model": requested_model,
            "effective_model": effective_model,
            "fallback_used": fallback_used,
        }
    return merged
