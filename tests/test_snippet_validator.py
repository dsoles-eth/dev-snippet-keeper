import pytest
from unittest.mock import patch, MagicMock, Mock
from snippet_validator import SnippetValidator, ValidationError
import sqlite3
import sys

# --- Fixtures for Mocking Dependencies ---

@pytest.fixture(autouse=True)
def mock_dependencies():
    """
    Global mock setup to prevent real DB operations and ensure isolation.
    Patches modules in the 'snippet_validator' namespace.
    """
    with patch('snippet_validator.sqlite3') as mock_sqlite:
        # Setup sqlite3 mock
        mock_cursor = MagicMock()
        mock_connection = MagicMock()
        mock_sqlite.connect.return_value = mock_connection
        mock_sqlite.Error = sqlite3.Error  # Keep original Error for validation checks if needed
        
        # Setup cursor behavior
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        
        yield mock_sqlite, mock_connection, mock_cursor

    with patch('snippet_validator.fuzz') as mock_fuzz:
        yield mock_fuzz
    # Note: The context manager approach above is for individual patches. 
    # Better to use nested context managers or a single fixture.
    # Refined fixture below:

@pytest.fixture
def patched_snippet_validator():
    """
    Fixture to patch all external dependencies in the snippet_validator namespace.
    Yields a configured mock environment.
    """
    with patch('snippet_validator.sqlite3') as mock_sqlite_module:
        mock_connection = MagicMock()
        mock_sqlite_module.connect.return_value = mock_connection
        mock_sqlite_module.Error = sqlite3.Error
        mock_sqlite_module.Error = Exception  # Generic error for tests
        
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_connection.commit = MagicMock()
        
        with patch('snippet_validator.fuzz') as mock_fuzz:
            mock_fuzz.ratio.return_value = 85
            
            with patch('snippet_validator.ast') as mock_ast:
                mock_ast.parse.return_value = None
                
                with patch('snippet_validator.Text') as mock_text:
                    mock_text_instance = MagicMock()
                    mock_text_instance.append = MagicMock()
                    mock_text.return_value = mock_text_instance
                    
                    with patch('snippet_validator.Style') as mock_style:
                        mock_style_instance = MagicMock()
                        mock_style.return_value = mock_style_instance
                        
                        yield {
                            'sqlite3': mock_sqlite_module,
                            'connection': mock_connection,
                            'cursor': mock_cursor,
                            'fuzz': mock_fuzz,
                            'ast': mock_ast,
                            'Text': mock_text,
                            'Style': mock_style
                        }

@pytest.fixture
def validator_instance(patched_snippet_validator):
    """
    Creates a SnippetValidator instance with mocked dependencies.
    """
    validator = SnippetValidator(db_path=None)
    # For tests requiring DB, we attach the mocked connection
    validator._conn = patched_snippet_validator['connection']
    return validator

@pytest.fixture
def validator_with_db(patched_snippet_validator):
    """
    Creates a SnippetValidator instance that expects a database connection.
    """
    # Mock db_path to prevent file creation
    with patch('snippet_validator.sqlite3.connect', return_value=patched_snippet_validator['connection']):
        validator = SnippetValidator(db_path=":memory:")
    return validator

# --- Test Cases for SnippetValidator ---

class TestInit:
    def test_init_with_db_path(self, patched_snippet_validator, validator_with_db):
        """Test initialization with a database path."""
        validator = validator_with_db
        assert validator.db_path == ":memory:"
        assert validator._conn is not None

    def test_init_without_db_path(self):
        """Test initialization without a database path."""
        with patch('snippet_validator.sqlite3.connect'):
            validator = SnippetValidator()
        assert validator.db_path is None
        assert validator._conn is None

    def test_init_db_init_error(self, patched_snippet_validator):
        """Test initialization raises ValidationError on DB error."""
        patched_snippet_validator['sqlite3'].connect.side_effect = Exception("DB Error")
        with pytest.raises(ValidationError):
            SnippetValidator(db_path="test.db")

class TestValidateLanguageSupport:
    def test_language_supported_python(self, validator_instance):
        """Test validating a supported language."""
        is_supported, lang = validator_instance.validate_language_support("python")
        assert is_supported is True
        assert lang == "python"

    def test_language_supported_synonym(self, validator_instance):
        """Test validating a language using a synonym."""
        is_supported, lang = validator_instance.validate_language_support("py")
        assert is_supported is True
        assert lang == "python"

    def test_language_unsupported_fuzzy(self, validator_instance):
        """Test fuzzy matching for a misspelled language."""
        is_supported, lang = validator_instance.validate_language_support("pythoon")
        # Default mock returns 85 ratio, so should match python
        assert is_supported is True
        assert lang == "python"

    def test_language_unsupported_not_found(self, validator_instance):
        """Test unsupported language with no fuzzy match."""
        with patch.object(validator_instance, '_fuzzy_find_language', return_value=None):
            validator_instance.fuzzywuzzy_mock = MagicMock() # Just to ensure isolation
            # Force fuzzywuzzy mock to return 0 ratio
            validator_instance.fuzz = MagicMock()
            validator_instance.fuzz.ratio.return_value = 50
            
            is_supported, lang = validator_instance.validate_language_support("xyzabc")
            assert is_supported is False
            assert lang == ""

class TestValidateSyntax:
    def test_syntax_python_valid(self, validator_instance, patched_snippet_validator):
        """Test valid Python syntax."""
        content = "print('hello')"
        is_valid, msg = validator_instance.validate_syntax(content, "python")
        assert is_valid is True
        assert msg is None
        patched_snippet_validator['ast'].parse.assert_called_once_with(content)

    def test_syntax_python_invalid(self, validator_instance, patched_snippet_validator):
        """Test invalid Python syntax."""
        content = "if True"
        patched_snippet_validator['ast'].parse.side_effect = SyntaxError("unexpected EOF")
        is_valid, msg = validator_instance.validate_syntax(content, "python")
        assert is_valid is False
        assert msg is not None
        assert "Syntax error" in msg

    def test_syntax_non_python_valid(self, validator_instance):
        """Test non-Python syntax validation passes structural checks."""
        content = "echo test"
        is_valid, msg = validator_instance.validate_syntax(content, "bash")
        assert is_valid is True
        assert msg is None

    def test_syntax_empty_content(self, validator_instance):
        """Test empty content raises validation error."""
        with pytest.raises(ValidationError):
            validator_instance.validate_syntax("", "python")

    def test_syntax_null_bytes(self, validator_instance):
        """Test null bytes in content."""
        content = "print(\x00)"
        is_valid, msg = validator_instance.validate_syntax(content, "bash")
        assert is_valid is False
        assert "null bytes" in msg

    def test_syntax_unsupported_language(self, validator_instance):
        """Test unsupported language in syntax validation."""
        is_valid, msg = validator_instance.validate_syntax("code", "rust")
        assert is_valid is False
        assert "Unsupported language" in msg

class TestFuzzyFindLanguage:
    def test_fuzzy_match_found(self, validator_instance):
        """Test fuzzy match is found within threshold."""
        # Patch fuzz.ratio to return 90 for target
        with patch('snippet_validator.fuzz.ratio', return_value=90):
            result = validator_instance._fuzzy_find_language("pythoon")
            assert result == "python"

    def test_fuzzy_match_no_threshold(self, validator_instance):
        """Test fuzzy match below threshold."""
        with patch('snippet_validator.fuzz.ratio', return_value=50):
            result = validator_instance._fuzzy_find_language("xyz")
            assert result is None

    def test_fuzzy_match_exact(self, validator_instance):
        """Test exact match logic in validation flow handles fuzzy correctly."""
        # This tests the integration via validate_language_support primarily, 
        # but covers the logic of _fuzzy_find_language.
        # We verify it returns None if nothing matches in loop.
        with patch('snippet_validator.fuzz.ratio', return_value=0):
            result = validator_instance._fuzzy_find_language("unknown")
            assert result is None

class TestCheckUniqueness:
    def test_name_unique_no_db(self, validator_instance):
        """Test uniqueness check skipped when no DB."""
        validator_instance._conn = None
        is_unique, msg = validator_instance.check_uniqueness("test_name")
        assert is_unique is True
        assert "not connected" in msg

    def test_name_duplicate(self, validator_instance):
        """Test duplicate name detection."""
        mock_result = ("test_name",)
        validator_instance._conn.cursor.return_value.fetchone.return_value = mock_result
        is_unique, msg = validator_instance.check_uniqueness("test_name")
        assert is_unique is False
        assert "already exists" in msg

    def test_name_unique_db(self, validator_instance):
        """Test unique name detection in DB."""
        validator_instance._conn.cursor.return_value.fetchone.return_value = None
        is_unique, msg = validator_instance.check_uniqueness("unique_name")
        assert is_unique is True
        assert "available" in msg

    def test_db_check_error(self, validator_instance):
        """Test handling DB errors during uniqueness check."""
        from snippet_validator import ValidationError # Ensure import is valid
        
        # Re-import locally for testing if needed, but accessing module via patch is better
        validator_instance._conn.cursor.side_effect = Exception("DB Error")
        is_unique, msg = validator_instance.check_uniqueness("test")
        assert is_unique is False
        assert "Database check failed" in msg

class TestFormatValidationResult:
    def test_result_success(self, validator_instance):
        """Test formatting a success result."""
        result = validator_instance.format_validation_result(True, "python", "info")
        assert result is not None
        # Check append was called
        assert result.append.called is True # Mock behavior check

    def test_result_error(self, validator_instance):
        """Test formatting an error result."""
        result = validator_instance.format_validation_result(False, "python", "Error msg")
        assert result is not None
        assert result.append.called is True

    def test_result_no_message(self, validator_instance):
        """Test formatting result with no message."""
        result = validator_instance.format_validation_result(True, "bash", "")
        assert result is not None

class TestValidateSnippet:
    def test_full_validation_success(self, validator_instance):
        """Test full validation suite passes."""
        validator_instance.fuzz.ratio.return_value = 100
        validator_instance.ast.parse.return_value = None
        validator_instance._conn.cursor.return_value.fetchone.return_value = None
        
        is_valid, msg, text = validator_instance.validate_snippet("code", "name", "python")
        assert is_valid is True
        assert msg == "Snippet ready to save."

    def test_language_validation_fail(self, validator_instance):
        """Test failing language support."""
        validator_instance.fuzz.ratio.return_value = 0
        is_valid, msg, _ = validator_instance.validate_snippet("code", "name", "rust")
        assert is_valid is False
        assert "Unsupported language" in msg

    def test_syntax_validation_fail(self, validator_instance):
        """Test failing syntax check."""
        validator_instance.fuzz.ratio.return_value = 100
        validator_instance.ast.parse.side_effect = SyntaxError("fail")
        
        is_valid, msg, text = validator_instance.validate_snippet("code", "name", "python")
        assert is_valid is False
        assert msg is not None
        assert text is not None

    def test_uniqueness_validation_fail(self, validator_instance):
        """Test failing uniqueness check."""
        validator_instance.fuzz.ratio.return_value = 100
        validator_instance.ast.parse.return_value = None
        validator_instance._conn.cursor.return_value.fetchone.return_value = ("dup",)
        
        is_valid, msg, _ = validator_instance.validate_snippet("code", "name", "python")
        assert is_valid is False
        assert "already exists" in msg

    def test_no_db_uniqueness_skip(self, validator_instance):
        """Test uniqueness check skipped when DB not available."""
        validator_instance._conn = None
        validator_instance.fuzz.ratio.return_value = 100
        validator_instance.ast.parse.return_value = None
        
        is_valid, msg, _ = validator_instance.validate_snippet("code", "name", "python")
        assert is_valid is True

    def test_exception_handling(self, validator_instance):
        """Test general exception handling."""
        validator_instance.fuzz.ratio.side_effect = Exception("Random Error")
        is_valid, msg, _ = validator_instance.validate_snippet("code", "name", "python")
        assert is_valid is False
        assert "Random Error" in msg

class TestClose:
    def test_close_normal(self, patched_snippet_validator, validator_instance):
        """Test closing connection normally."""
        validator_instance._conn = patched_snippet_validator['connection']
        validator_instance.close()
        assert validator_instance._conn is None
        patched_snippet_validator['connection'].close.assert_called_once()

    def test_close_none(self):
        """Test closing when connection is None."""
        validator = SnippetValidator()
        validator.close() # Should not raise

    def test_close_error(self, patched_snippet_validator):
        """Test closing with connection error."""
        patched_snippet_validator['connection'].close.side_effect = Exception("Close Error")
        validator = SnippetValidator()
        validator._conn = patched_snippet_validator['connection']
        # Should handle error internally
        validator.close()
        assert validator._conn is None

# Run the tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])