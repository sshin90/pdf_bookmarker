"""
pdf_processor.py의 단위 테스트
"""
import pytest
import fitz
from pdf_processor import read_existing_bookmarks, extract_text_from_pdf, apply_bookmarks


def create_sample_pdf_bytes():
    """테스트용 샘플 PDF를 생성합니다."""
    doc = fitz.open()
    
    # 첫 번째 페이지 추가
    page1 = doc.new_page()
    page1.insert_text((50, 50), "PDF 테스트 문서", fontsize=14)
    page1.insert_text((50, 100), "이것은 테스트용 PDF입니다.", fontsize=10)
    
    # 두 번째 페이지 추가
    page2 = doc.new_page()
    page2.insert_text((50, 50), "두 번째 페이지", fontsize=14)
    page2.insert_text((50, 100), "여기는 페이지 2입니다.", fontsize=10)
    
    output = doc.write()
    doc.close()
    return output


def test_extract_text_from_pdf():
    """extract_text_from_pdf 함수 테스트"""
    pdf_bytes = create_sample_pdf_bytes()
    pages = extract_text_from_pdf(pdf_bytes)
    
    # 기본 검증
    assert isinstance(pages, list)
    assert len(pages) == 2
    
    # 각 페이지 검증
    for i, page in enumerate(pages):
        assert 'page' in page
        assert 'text' in page
        assert page['page'] == i + 1
        assert isinstance(page['text'], str)
    
    # 페이지 번호 검증 (1-indexed)
    assert pages[0]['page'] == 1
    assert pages[1]['page'] == 2
    
    # 텍스트 내용 검증
    assert len(pages[0]['text']) > 0
    assert len(pages[1]['text']) > 0


def test_extract_text_from_pdf_invalid_pdf():
    """invalid PDF를 전달했을 때 예외 발생 검증"""
    invalid_bytes = b"This is not a PDF"
    
    # PyMuPDF는 ValueError 또는 다른 예외를 발생시킬 수 있음
    with pytest.raises((ValueError, Exception)):
        extract_text_from_pdf(invalid_bytes)


def test_apply_bookmarks_empty_list():
    """빈 북마크 리스트로 apply_bookmarks 테스트"""
    pdf_bytes = create_sample_pdf_bytes()
    result = apply_bookmarks(pdf_bytes, [])
    
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_apply_bookmarks_single_bookmark():
    """단일 북마크로 apply_bookmarks 테스트"""
    pdf_bytes = create_sample_pdf_bytes()
    bookmarks = [
        {"page": 1, "level": 1, "title": "첫 번째 장"}
    ]
    
    result = apply_bookmarks(pdf_bytes, bookmarks)
    
    # 결과 검증
    assert isinstance(result, bytes)
    assert len(result) > 0
    
    # 북마크가 실제로 추가되었는지 검증
    result_doc = fitz.open(stream=result, filetype="pdf")
    toc = result_doc.get_toc()
    result_doc.close()
    
    assert len(toc) == 1
    assert toc[0][0] == 1  # level
    assert toc[0][1] == "첫 번째 장"  # title
    assert toc[0][2] == 1  # page


def test_apply_bookmarks_multiple_bookmarks():
    """여러 북마크로 apply_bookmarks 테스트"""
    pdf_bytes = create_sample_pdf_bytes()
    bookmarks = [
        {"page": 1, "level": 1, "title": "제1장"},
        {"page": 1, "level": 2, "title": "1.1절"},
        {"page": 2, "level": 1, "title": "제2장"},
    ]
    
    result = apply_bookmarks(pdf_bytes, bookmarks)
    
    # 결과 검증
    result_doc = fitz.open(stream=result, filetype="pdf")
    toc = result_doc.get_toc()
    result_doc.close()
    
    assert len(toc) == 3
    # 페이지 번호 순서대로 정렬되는지 검증
    assert toc[0][2] == 1  # 첫 번째 페이지들
    assert toc[1][2] == 1
    assert toc[2][2] == 2  # 두 번째 페이지


def test_apply_bookmarks_with_invalid_data():
    """유효하지 않은 데이터는 필터링되는지 검증"""
    pdf_bytes = create_sample_pdf_bytes()
    bookmarks = [
        {"page": 1, "level": 1, "title": "유효한 북마크"},
        {"page": -1, "level": 1, "title": "유효하지 않은 페이지"},  # 유효하지 않음
        {"page": 1, "level": 0, "title": "유효하지 않은 레벨"},  # 유효하지 않음
        {"page": 1, "level": 1, "title": ""},  # 빈 제목
        {"page": 1, "level": 1, "title": "nan"},  # 'nan' 문자열
    ]
    
    result = apply_bookmarks(pdf_bytes, bookmarks)
    
    result_doc = fitz.open(stream=result, filetype="pdf")
    toc = result_doc.get_toc()
    result_doc.close()
    
    # 유효한 북마크만 1개여야 함
    assert len(toc) == 1
    assert toc[0][1] == "유효한 북마크"


def test_read_existing_bookmarks_empty():
    """북마크가 없는 PDF 테스트"""
    pdf_bytes = create_sample_pdf_bytes()
    bookmarks = read_existing_bookmarks(pdf_bytes)
    
    assert isinstance(bookmarks, list)
    assert len(bookmarks) == 0


def test_read_existing_bookmarks_with_bookmarks():
    """북마크가 있는 PDF 테스트"""
    # 먼저 북마크를 추가한 PDF 생성
    pdf_bytes = create_sample_pdf_bytes()
    bookmarks_to_add = [
        {"page": 1, "level": 1, "title": "첫 번째 장"},
        {"page": 2, "level": 1, "title": "두 번째 장"},
    ]
    pdf_with_bookmarks = apply_bookmarks(pdf_bytes, bookmarks_to_add)
    
    # 북마크 읽기
    read_bookmarks = read_existing_bookmarks(pdf_with_bookmarks)
    
    assert len(read_bookmarks) == 2
    assert read_bookmarks[0][1] == "첫 번째 장"
    assert read_bookmarks[1][1] == "두 번째 장"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
