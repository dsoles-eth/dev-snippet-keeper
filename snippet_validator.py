from typing import List, Optional, Tuple, Any
from fuzzywuzzy import fuzz
from rich.text import Text
from rich.style import Style
import sqlite3
import ast
import hashlib
from pathlib import Path

class ValidationError(Exception):
    """Exception raised when a snippet validation fails."""
    def __init__(self, message: str, code: Optional[int] = None):
        self.message = message
        self.code = code
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"[ValidationError] {self.message}"

class SnippetValidator:
    """
    Validator class for ensuring code snippets are valid before saving.
    
    This class handles syntax validation, language support checks, and duplicate
    detection within a SQLite database. It utilizes rich for formatted output
    and fuzzywuzzy for language suggestions.
    """
    
    SUPPORTED_LANGUAGES = {
        "python": {"extensions": [".py"], "validator": "python_syntax"},
        "javascript": {"extensions": [".js"], "validator": "structural"},
        "bash": {"extensions": [".sh"], "validator": "structural"},
        "sql": {"extensions": [".sql"], "validator": "structural"},
        "markdown": {"extensions": [".md"], "validator": "structural"},
    }

    LANGUAGE_SYNONYMS = {
        "py": "python",
        "js": "javascript",
        "sh": "bash",
        "md": "markdown",
    }

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the SnippetValidator.
        
        Args:
            db_path: Path to the SQLite database file. If None, database features are skipped.
        """
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        if self.db_path:
            self._init_database()

    def _init_database(self) -> None:
        """Initialize SQLite connection and tables if not present."""
        try:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("CREATE TABLE IF NOT EXISTS snippets (id INTEGER PRIMARY KEY, name TEXT UNIQUE, lang TEXT, content TEXT)")
            self._conn.commit()
        except sqlite3.Error as e:
            raise ValidationError(f"Database initialization failed: {e}", code=500)

    def validate_language_support(self, language: str) -> Tuple[bool, str]:
        """
        Check if a language is supported by the validator.
        
        Args:
            language: The programming language identifier (e.g., 'python', 'py').
            
        Returns:
            A tuple containing (is_supported: bool, corrected_name: str).
        """
        try:
            normalized_language = language.lower().strip()
            if normalized_language in self.SUPPORTED_LANGUAGES:
                return True, normalized_language
            
            corrected = self.LANGUAGE_SYNONYMS.get(normalized_language)
            if corrected:
                return True, corrected

            best_match = self._fuzzy_find_language(normalized_language)
            if best_match:
                return True, best_match
            else:
                return False, ""

        except Exception as e:
            return False, f"Error validating language: {str(e)}"

    def validate_syntax(self, content: str, language: str) -> Tuple[bool, Optional[str]]:
        """
        Validate the syntax of a code snippet based on its language.
        
        Args:
            content: The code snippet string to validate.
            language: The programming language identifier.
            
        Returns:
            A tuple (is_valid: bool, error_message: Optional[str]).
        """
        try:
            if not content or len(content) == 0:
                raise ValidationError("Snippet content cannot be empty.", code=400)
            
            if language == "python":
                try:
                    ast.parse(content)
                    return True, None
                except SyntaxError as e:
                    return False, f"Syntax error in Python code: {e.msg} at line {e.lineno}"
            
            elif language in ["javascript", "bash", "sql", "markdown"]:
                # Structural checks for non-Python languages
                if "\x00" in content:
                    return False, "Snippet contains null bytes."
                if len(content) > 50000:
                    return False, "Snippet too large for validation."
                return True, None
            
            else:
                return False, f"Unsupported language for syntax validation: {language}"

        except ValidationError:
            raise
        except Exception as e:
            return False, f"Unexpected validation error: {str(e)}"

    def _fuzzy_find_language(self, user_input: str) -> Optional[str]:
        """
        Use fuzzywuzzy to find the closest matching supported language.
        
        Args:
            user_input: The potentially misspelled language input.
            
        Returns:
            The corrected language string or None if no match above threshold.
        """
        threshold = 80
        for lang in self.SUPPORTED_LANGUAGES.keys():
            if fuzz.ratio(user_input, lang) >= threshold:
                return lang
        return None

    def check_uniqueness(self, name: str) -> Tuple[bool, str]:
        """
        Check if a snippet name is already taken in the database.
        
        Args:
            name: The unique name identifier for the snippet.
            
        Returns:
            A tuple (is_unique: bool, message: str).
        """
        if not self._conn:
            return True, "Database not connected; uniqueness check skipped."
        
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT name FROM snippets WHERE LOWER(name) = LOWER(?)", (name,))
            result = cursor.fetchone()
            
            if result:
                return False, f"Snippet name '{name}' already exists."
            return True, "Snippet name is available."
        except sqlite3.Error as e:
            return False, f"Database check failed: {str(e)}"

    def format_validation_result(
        self, 
        is_valid: bool, 
        language: str, 
        message: str
    ) -> Text:
        """
        Format validation results for terminal display using Rich.
        
        Args:
            is_valid: Boolean indicating overall validation status.
            language: The language of the snippet.
            message: The validation message or status.
            
        Returns:
            A Rich Text object styled for console output.
        """
        result = Text()
        
        if is_valid:
            style = Style(color="green", bold=True)
            result.append(f"[OK] ", style=style)
            result.append(f"Snippet ({language}) validated successfully.\n")
            if message:
                result.append(f"Info: {message}\n")
        else:
            style = Style(color="red", bold=True)
            result.append("[ERROR] ", style=style)
            result.append(f"Snippet validation failed.\n")
            result.append(f"Language: {language}\n")
            result.append(f"Reason: {message}\n")
            
        return result

    def validate_snippet(
        self, 
        content: str, 
        name: str, 
        language: str
    ) -> Tuple[bool, str, Optional[Text]]:
        """
        Perform a complete validation suite on a snippet.
        
        Args:
            content: The code snippet content.
            name: The snippet name/title.
            language: The programming language.
            
        Returns:
            A tuple (is_valid: bool, error_message: str, formatted_output: Optional[Text]).
        """
        try:
            # Step 1: Language Support
            lang_supported, corrected_lang = self.validate_language_support(language)
            if not lang_supported:
                error_msg = f"Unsupported language: {language}. Did you mean {corrected_lang}?"
                return False, error_msg, None

            # Step 2: Syntax Check
            is_syntax_valid, syntax_msg = self.validate_syntax(content, corrected_lang)
            if not is_syntax_valid:
                formatted = self.format_validation_result(False, corrected_lang, syntax_msg)
                return False, syntax_msg, formatted

            # Step 3: Uniqueness Check
            if self._conn:
                is_unique, unique_msg = self.check_uniqueness(name)
                if not is_unique:
                    formatted = self.format_validation_result(False, corrected_lang, unique_msg)
                    return False, unique_msg, formatted
            
            formatted = self.format_validation_result(True, corrected_lang, "All checks passed.")
            return True, "Snippet ready to save.", formatted

        except ValidationError as ve:
            formatted = self.format_validation_result(False, "unknown", str(ve))
            return False, str(ve), formatted
        except Exception as e:
            formatted = self.format_validation_result(False, "unknown", str(e))
            return False, str(e), formatted

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            try:
                self._conn.close()
                self._conn = None
            except sqlite3.Error:
                pass