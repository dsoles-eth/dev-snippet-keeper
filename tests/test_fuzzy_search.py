import pytest
import sqlite3
from unittest.mock import MagicMock, patch
from fuzzy_search import SnippetSearcher

@pytest.fixture
def mock_conn():
    conn = MagicMock()
    cursor_mock = MagicMock()
    conn.cursor.return_value = cursor_mock
    return conn

@pytest.fixture
def searcher(mock_conn):
    with patch('fuzzy_search.Console') as mock_console_class:
        mock_console_instance = MagicMock()
        mock_console_class.return_value = mock_console_instance
        return SnippetSearcher(mock_conn)

@pytest.fixture
def fuzzywuzzy_mock():
    with patch('fuzzy_search.fuzz') as mock_fuzz:
        mock_fuzz.ratio.return_value = 85
        yield mock_fuzz

class TestSnippetSearcherInit:
    def test_init_with_valid_connection(self, mock_conn):
        searcher = SnippetSearcher(mock_conn)
        assert searcher.conn is mock_conn
        assert hasattr(searcher, 'console')

    def test_init_with_none_connection_raises_error(self):
        with pytest.raises(ValueError, match="Database connection cannot be None."):
            SnippetSearcher(None)

    def test_init_sets_console_instance(self, mock_conn):
        with patch('fuzzy_search.Console') as mock_class:
            SnippetSearcher(mock_conn)
            mock_class.assert_called_once()

class TestSnippetSearcherSanitization:
    def test_sanitize_removes_special_chars(self, searcher):
        query = "Python & C++ #Code"
        result = searcher._sanitize_query(query)
        assert "&" not in result
        assert "#" not in result
        assert "Python" in result
        assert "Code" in result

    def test_sanitize_empty_string(self, searcher):
        result = searcher._sanitize_query("")
        assert result == ""

    def test_sanitize_whitespace_only(self, searcher):
        result = searcher._sanitize_query("   ")
        assert result == ""

class TestSnippetSearcherSearch:
    def test_search_snippets_happy_path(self, searcher, fuzzywuzzy_mock):
        cursor = searcher.conn.cursor.return_value
        cursor.fetchall.return_value = [(1, "Test Snippet", "Code content", "python")]
        
        results = searcher.search_snippets("python", limit=5)
        
        assert len(results) == 1
        assert results[0]["id"] == 1
        assert results[0]["score"] == 85
        cursor.execute.assert_called()
        assert "LIKE" in cursor.execute.call_args[0][0]

    def test_search_snippets_invalid_query_type(self, searcher):
        with pytest.raises(TypeError, match="Query must be a string"):
            searcher.search_snippets(123)

    def test_search_snippets_database_error(self, searcher):
        searcher.conn.cursor.return_value.execute.side_effect = sqlite3.DatabaseError("Simulated SQL Error")
        
        with pytest.raises(RuntimeError, match="SQLite error during search:"):
            searcher.search_snippets("test")

class TestSnippetSearcherDisplay:
    def test_display_results_with_content(self, searcher):
        results = [
            {
                "id": 1, 
                "title": "Python Snippet", 
                "content": "print('hello')", 
                "tags": "python", 
                "score": 90
            }
        ]
        searcher.display_search_results(results, "python")
        searcher.console.print.assert_called()

    def test_display_results_empty_list(self, searcher):
        results = []
        searcher.display_search_results(results, "python")
        searcher.console.print.assert_called()

    def test_display_results_content_truncation(self, searcher):
        results = [
            {
                "id": 1, 
                "title": "Test", 
                "content": "x" * 100, 
                "tags": "", 
                "score": 50
            }
        ]
        searcher.display_search_results(results, "test")
        
        call_args = searcher.console.print.call_args
        if call_args:
            text_obj = call_args[0][0]
            assert ".." in text_obj.plain
            assert len(text_obj.plain) < 1000 # Ensure basic formatting exists