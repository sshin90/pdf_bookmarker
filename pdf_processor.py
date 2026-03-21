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
    
    Args:
        pdf_bytes: PDF 파일의 바이트 데이터
        bookmarks_list: 북마크 목록 [{'page': 1, 'level': 1, 'title': '...'}, ...]
        
    Returns:
        bytes: 북마크가 적용된 PDF 바이트 데이터
        
    Raises:
        ValueError: 유효하지 않은 PDF 파일
        MemoryError: 파일이 너무 큼
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # PyMuPDF의 TOC 형식: [level, title, page] (page is 1-indexed)
        new_toc = []
        valid_count = 0
        
        for bm in bookmarks_list:
            try:
                p = int(bm.get("page"))
                level = int(bm.get("level", 1))
                title_raw = bm.get("title")
                title = "" if title_raw is None else str(title_raw).strip()

                if title.lower() == "nan":
                    title = ""

                if title and p > 0 and level >= 1:
                    new_toc.append([level, title, p])
                    valid_count += 1
            except (ValueError, TypeError) as e:
                logger.warning(f"북마크 처리 중 오류: {str(e)}")
                continue

        # page 오름차순(같은 page면 level 오름차순)이 자연스럽습니다.
        new_toc.sort(key=lambda x: (x[2], x[0]))
        
        doc.set_toc(new_toc)
        
        out_pdf = doc.write()
        doc.close()
        
        logger.info(f"북마크 적용 완료: {valid_count}개 항목 추가")
        return out_pdf
    except (fitz.FileDataError, fitz.FileNotFoundError, fitz.EmptyFileError) as e:
        logger.error(f"유효하지 않은 PDF 파일: {str(e)}")
        raise ValueError(f"유효하지 않은 PDF 파일입니다: {str(e)}") from e
    except MemoryError as e:
        logger.error(f"메모리 부족: {str(e)}")
        raise MemoryError(f"파일이 너무 커서 처리할 수 없습니다: {str(e)}") from e
    except Exception as e:
        logger.error(f"북마크 적용 중 오류: {str(e)}")
        raise
