import fitz  # PyMuPDF
import io
import logging

logger = logging.getLogger(__name__)

def read_existing_bookmarks(pdf_bytes: bytes) -> list:
    """
    주어진 PDF 바이트 배열에서 기존 북마크 리스트를 추출합니다.
    
    Args:
        pdf_bytes: PDF 파일의 바이트 데이터
        
    Returns: 
        list[list[int, str, int]]: [[level, title, page_number], ...]
        
    Raises:
        ValueError: 유효하지 않은 PDF 파일
        MemoryError: 파일이 너무 큼
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        toc = doc.get_toc()
        doc.close()
        logger.info(f"기존 북마크 추출 완료: {len(toc)}개 항목")
        return toc
    except (fitz.FileDataError, fitz.FileNotFoundError, fitz.EmptyFileError) as e:
        logger.error(f"유효하지 않은 PDF 파일: {str(e)}")
        raise ValueError(f"유효하지 않은 PDF 파일입니다: {str(e)}") from e
    except MemoryError as e:
        logger.error(f"메모리 부족: {str(e)}")
        raise MemoryError(f"파일이 너무 커서 처리할 수 없습니다: {str(e)}") from e
    except Exception as e:
        logger.error(f"예상치 못한 오류: {str(e)}")
        raise

def extract_text_from_pdf(pdf_bytes: bytes) -> list[dict[str, int | str]]:
    """
    각 페이지의 텍스트를 추출합니다.
    
    Args:
        pdf_bytes: PDF 파일의 바이트 데이터
        
    Returns: 
        list[dict]: [{'page': 1, 'text': '...'}, ...]
        
    Raises:
        ValueError: 유효하지 않은 PDF 파일
        MemoryError: 파일이 너무 큼
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        total_pages = len(doc)
        
        for i, page in enumerate(doc):
            try:
                text = page.get_text("text").strip()
                pages.append({
                    'page': i + 1,  # 1-indexed for the UI
                    'text': text
                })
            except Exception as e:
                logger.warning(f"페이지 {i + 1} 텍스트 추출 실패: {str(e)}")
                pages.append({'page': i + 1, 'text': ''})
        
        doc.close()
        logger.info(f"텍스트 추출 완료: {total_pages}페이지, 총 {sum(len(p['text']) for p in pages)}자")
        return pages
    except (fitz.FileDataError, fitz.FileNotFoundError, fitz.EmptyFileError) as e:
        logger.error(f"유효하지 않은 PDF 파일: {str(e)}")
        raise ValueError(f"유효하지 않은 PDF 파일입니다: {str(e)}") from e
    except MemoryError as e:
        logger.error(f"메모리 부족: {str(e)}")
        raise MemoryError(f"파일이 너무 커서 처리할 수 없습니다: {str(e)}") from e
    except Exception as e:
        logger.error(f"예상치 못한 오류: {str(e)}")
        raise

def apply_bookmarks(pdf_bytes: bytes, bookmarks_list: list[dict]) -> bytes:
    """
    새로운 북마크 정보를 받아 PDF에 삽입하고 새로운 PDF 바이트 배열을 반환합니다.
    TOC 계층 구조를 정규화하고 유효한 페이지 범위만 포함하여 저장 시 오류를 방지합니다.
    """
    doc = None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        
        # 1. 유효한 북마크 필터링 및 정렬
        valid_items = []
        for bm in bookmarks_list:
            try:
                p = int(bm.get("page", 0))
                level = int(bm.get("level", 1))
                title_raw = bm.get("title")
                title = "" if title_raw is None else str(title_raw).strip()

                if title.lower() == "nan":
                    title = ""

                if title and 1 <= p <= total_pages and level >= 1:
                    valid_items.append([level, title, p])
            except (ValueError, TypeError):
                continue

        valid_items.sort(key=lambda x: (x[2], x[0]))
        
        # 2. TOC 계층 구조 정규화 (MuPDF 저장 오류 방지)
        normalized_toc = []
        current_max_attainable_level = 0
        
        for level, title, page in valid_items:
            if not normalized_toc:
                level = 1
            elif level > current_max_attainable_level + 1:
                level = current_max_attainable_level + 1
            
            normalized_toc.append([level, title, page])
            current_max_attainable_level = level

        # 3. TOC 적용
        try:
            doc.set_toc(normalized_toc)
            logger.info(f"TOC 적용됨: {len(normalized_toc)}개 항목")
        except Exception as e:
            logger.error(f"set_toc 실패: {str(e)}")
            # TOC 적용 자체가 실패하면 더 이상 진행 불가하므로 예외 발생
            raise ValueError(f"북마크 구조를 PDF에 적용하는 중 오류가 발생했습니다: {str(e)}")

        # 4. 안전한 방식으로 PDF 저장 (다중 단계 시도)
        # 1단계: 표준 최적화 저장
        bio = io.BytesIO()
        try:
            doc.save(bio, garbage=3, deflate=True)
            logger.info("표준 저장 완료 (garbage=3)")
        except Exception as e1:
            logger.warning(f"1단계 저장 실패: {str(e1)}")
            # 2단계: 강력한 청소 및 복구 옵션 사용 (FzErrorSyntax 방지 목적)
            bio = io.BytesIO()
            try:
                doc.save(bio, garbage=4, deflate=True, clean=True)
                logger.info("2단계 저장 완료 (garbage=4, clean=True)")
            except Exception as e2:
                logger.warning(f"2단계 저장 실패: {str(e2)}")
                # 3단계: 최소한의 옵션으로 저장 가도 시도
                bio = io.BytesIO()
                try:
                    doc.save(bio, garbage=1)
                    logger.info("3단계 저장 완료 (garbage=1)")
                except Exception as e3:
                    logger.error(f"모든 저장 단계 실패: {str(e3)}")
                    raise RuntimeError(f"PDF 저장 중 치명적인 오류가 발생했습니다: {str(e3)}")
            
        out_pdf = bio.getvalue()
        logger.info(f"북마크 적용 완료: {len(normalized_toc)}개 항목")
        return out_pdf

    except Exception as e:
        logger.error(f"북마크 적용 중 오류 발생: {str(e)}")
        raise
    finally:
        if doc:
            doc.close()
            logger.debug("PDF 문서 닫음")

