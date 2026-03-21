"""
bookmark_generator.py의 단위 테스트
"""
import pytest
from bookmark_generator import (
    _normalize_title,
    _chunk_pages,
    _merge_and_dedupe,
    TITLE_MAX_LENGTH,
    DEFAULT_CHUNK_SIZE,
)


class TestNormalizeTitle:
    """_normalize_title 함수 테스트"""
    
    def test_normal_title(self):
        """일반적인 제목 정규화"""
        assert _normalize_title("테스트 제목") == "테스트 제목"
    
    def test_title_with_whitespace(self):
        """공백 제거"""
        assert _normalize_title("  테스트 제목  ") == "테스트 제목"
    
    def test_title_none(self):
        """None 입력"""
        assert _normalize_title(None) is None
    
    def test_title_empty_string(self):
        """빈 문자열"""
        assert _normalize_title("") is None
    
    def test_title_nan_string(self):
        """'nan' 문자열"""
        assert _normalize_title("nan") is None
        assert _normalize_title("NaN") is None
        assert _normalize_title("NAN") is None
    
    def test_title_too_long(self):
        """50자 이상의 제목 자르기"""
        long_title = "a" * 100
        result = _normalize_title(long_title)
        assert len(result) <= TITLE_MAX_LENGTH
        assert result == "a" * TITLE_MAX_LENGTH
    
    def test_title_with_trailing_space_after_truncate(self):
        """자르기 후 후행 공백 제거"""
        title = "a" * 49 + " test test test"
        result = _normalize_title(title)
        assert not result.endswith(" ")


class TestChunkPages:
    """_chunk_pages 함수 테스트"""
    
    def test_chunk_pages_empty_list(self):
        """빈 페이지 리스트"""
        result = _chunk_pages([])
        assert result == []
    
    def test_chunk_pages_single_page(self):
        """단일 페이지"""
        pages = [{"page": 1, "text": "test"}]
        result = _chunk_pages(pages)
        assert len(result) == 1
        assert len(result[0]) == 1
    
    def test_chunk_pages_multiple_pages_small_text(self):
        """작은 텍스트의 여러 페이지"""
        pages = [
            {"page": i, "text": "short text"}
            for i in range(5)
        ]
        result = _chunk_pages(pages, max_chars=1000)
        # 모든 페이지가 한 청크에 포함되어야 함
        assert len(result) == 1
        assert len(result[0]) == 5
    
    def test_chunk_pages_with_large_text(self):
        """큰 텍스트로 청크 분할"""
        large_text = "a" * (DEFAULT_CHUNK_SIZE // 2)
        pages = [
            {"page": 1, "text": large_text},
            {"page": 2, "text": large_text},
        ]
        result = _chunk_pages(pages)
        # 두 개의 청크로 분할되어야 함
        assert len(result) == 2
    
    def test_chunk_pages_preserves_page_numbers(self):
        """페이지 번호가 보존되는지 검증"""
        pages = [
            {"page": i, "text": "text"}
            for i in range(1, 4)
        ]
        result = _chunk_pages(pages)
        # 원본 페이지 번호가 유지되는지 확인
        for chunk in result:
            for page in chunk:
                assert page["page"] in [1, 2, 3]


class TestMergeAndDedupe:
    """_merge_and_dedupe 함수 테스트"""
    
    def test_dedupe_identical_entries(self):
        """동일한 항목 중복 제거"""
        candidates = [
            {"page": 1, "level": 1, "title": "제목"},
            {"page": 1, "level": 1, "title": "제목"},
        ]
        result = _merge_and_dedupe(candidates)
        assert len(result) == 1
    
    def test_dedupe_different_entries(self):
        """다른 항목 유지"""
        candidates = [
            {"page": 1, "level": 1, "title": "제목1"},
            {"page": 1, "level": 1, "title": "제목2"},
            {"page": 2, "level": 1, "title": "제목1"},
        ]
        result = _merge_and_dedupe(candidates)
        assert len(result) == 3
    
    def test_merge_sorts_by_page_and_level(self):
        """페이지와 레벨로 정렬"""
        candidates = [
            {"page": 2, "level": 1, "title": "제목2"},
            {"page": 1, "level": 2, "title": "제목1.1"},
            {"page": 1, "level": 1, "title": "제목1"},
        ]
        result = _merge_and_dedupe(candidates)
        
        # 정렬 순서 검증
        assert result[0]["page"] == 1
        assert result[0]["level"] == 1
        assert result[1]["page"] == 1
        assert result[1]["level"] == 2
        assert result[2]["page"] == 2
    
    def test_dedupe_filters_invalid_data(self):
        """유효하지 않은 데이터 필터링"""
        candidates = [
            {"page": 1, "level": 1, "title": "유효"},
            {"page": 0, "level": 1, "title": "유효하지 않은 페이지"},  # page <= 0
            {"page": 1, "level": 0, "title": "유효하지 않은 레벨"},  # level < 1
            {"page": 1, "level": 1, "title": "nan"},  # 정규화되면 None
            {"page": 1, "level": 1, "title": ""},  # 빈 제목
        ]
        result = _merge_and_dedupe(candidates)
        assert len(result) == 1
        assert result[0]["title"] == "유효"
    
    def test_dedupe_with_missing_fields(self):
        """필드 누락 처리"""
        candidates = [
            {"page": 1, "title": "제목"},  # level 누락
            {"level": 1, "title": "제목"},  # page 누락
        ]
        result = _merge_and_dedupe(candidates)
        # 필드 누락으로 인해 필터링되어야 함
        assert len(result) == 0
    
    def test_dedupe_with_invalid_types(self):
        """유효하지 않은 타입 처리"""
        candidates = [
            {"page": "1", "level": 1, "title": "제목1"},  # page가 문자열이지만 변환 가능
            {"page": 1, "level": "1", "title": "제목2"},  # level이 문자열이지만 변환 가능
        ]
        result = _merge_and_dedupe(candidates)
        # 타입 변환이 가능하므로 2개 항목이 모두 유지됨
        assert len(result) == 2


class TestNormalizeTitleEdgeCases:
    """_normalize_title 함수의 엣지 케이스 테스트"""
    
    def test_title_with_special_characters(self):
        """특수 문자가 포함된 제목"""
        title = "제목!@#$%^&*()"
        result = _normalize_title(title)
        assert result == title
    
    def test_title_with_unicode(self):
        """유니코드 문자 포함"""
        title = "📚 책 제목 📖"
        result = _normalize_title(title)
        assert result == title
    
    def test_title_numeric_string(self):
        """숫자만 포함한 문자열"""
        assert _normalize_title("123") == "123"
    
    def test_title_only_whitespace(self):
        """공백만 포함"""
        assert _normalize_title("   ") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
