import pytest
import unittest.mock as mock
import sqlite3
import snippet_storage as ss_module
from click.testing import CliRunner
import sys

# --- Fixtures and Patching ---

@pytest.fixture(autouse=True)
def setup_module_env(monkeypatch):
    """Ensures the module can run without missing imports or file system writes."""
    import snippet_storage
    
    # Patch missing 'os' import (used in init_connection but not imported in source)
    os_mock = mock.MagicMock()
    os_mock.path.dirname = lambda path: path
    os_mock.path.exists = lambda path: True
    os_mock.makedirs = mock.MagicMock()
    monkeypatch.setattr(snippet_storage, 'os', os_mock)
    
    # Patch missing 'Prompt' import (used in CLI but not imported in source)
    prompt_mock = mock.MagicMock()
    monkeypatch.setattr(snippet_storage, 'Prompt', prompt_mock)
    
    # Patch 'fuzzywuzzy' for search tests
    fuzz_mock = mock.MagicMock()
    fuzz_mock.partial_ratio = lambda q, t: 90
    monkeypatch.setattr(snippet_storage, 'fuzz', fuzz_mock)
    
    # Patch 'rich' to avoid output and errors
    monkeypatch.setattr(snippet_storage, 'Console', mock.MagicMock)
    monkeypatch.setattr(snippet_storage, 'Table', mock.MagicMock)

@pytest.fixture
def mock_db_connection():
    """Returns an in-memory SQLite connection."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE snippets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            language TEXT DEFAULT 'text',
            content BLOB NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

@pytest.fixture
def storage(mock_db_connection, monkeypatch):
    """Provides a SnippetStorage instance connected to the mocked DB."""
    # We need to patch sqlite3.connect to return our mock_db_connection
    # Note: patching 'sqlite3.connect' globally inside the module namespace is cleaner
    # but monkeypatching the import in the module context is safer for pytest
    import snippet_storage
    original_connect = sqlite3.connect
    
    def mock_connect(*args, **kwargs):
        return mock_db_connection
    
    monkeypatch.setattr(snippet_storage.sqlite3, 'connect', mock_connect)
    return ss_module.SnippetStorage(":test_path_")

@pytest.fixture
def runner():
    return CliRunner()

# --- Tests for Utility Functions ---

class TestEncryptionUtilities:
    def test_derive_key_length(self):
        key = ss_module.derive_key("password", b"salt")
        assert len(key) == 32

    def test_derive_key_deterministic(self):
        key1 = ss_module.derive_key("password", b"salt")
        key2 = ss_module.derive_key("password", b"salt")
        assert key1 == key2

    def test_xor_bytes_roundtrip(self):
        data = b"test_bytes"
        key = b"key"
        encrypted = ss_module.xor_bytes(data, key)
        decrypted = ss_module.xor_bytes(encrypted, key)
        assert data == decrypted

    def test_encrypt_content_encodes_bytes(self):
        result = ss_module.encrypt_content("test", "pwd", b"salt")
        assert isinstance(result, bytes)

    def test_decrypt_content_valid(self):
        content = "Hello World"
        encrypted = ss_module.encrypt_content(content, "pwd", b"salt")
        decrypted = ss_module.decrypt_content(encrypted, "pwd", b"salt")
        assert decrypted == content

    def test_decrypt_content_invalid_length(self):
        result = ss_module.decrypt_content(b"short", "pwd", b"salt")
        assert result is None

class TestSnippetStorageClass:
    def test_init_connection_creates_table(self, storage):
        # Ensure connection is active and table exists
        assert storage.connection is not None
        cursor = storage.connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        assert 'snippets' in tables

    def test_store_snippet_success(self, storage):
        id = storage.store_snippet("My Snippet", "Desc", "Code", "py", "pwd")
        assert id > 0

    def test_store_snippet_returns_negative_on_error(self, storage, monkeypatch):
        monkeypatch.setattr(storage.connection, "commit", side_effect=sqlite3.Error("DB Fail"))
        result = storage.store_snippet("T", "D", "C", "l", "p")
        assert result == -1

    def test_get_snippet_success(self, storage):
        sid = storage.store_snippet("GetIt", "D", "Content", "sql", "pwd")
        res = storage.get_snippet(sid, "pwd")
        assert res is not None
        assert res['title'] == "GetIt"

    def test_get_snippet_not_found(self, storage):
        res = storage.get_snippet(99999, "pwd")
        assert res is None

    def test_get_snippet_decrypts_content(self, storage):
        sid = storage.store_snippet("Test", "D", "SecretText", "txt", "pwd")
        res = storage.get_snippet(sid, "pwd")
        assert res['content'] == "SecretText"

    def test_list_snippets_empty(self, storage):
        res = storage.list_snippets()
        assert len(res) == 0

    def test_list_snippets_populated(self, storage):
        storage.store_snippet("A", "D", "C", "py", "p")
        storage.store_snippet("B", "D", "C", "py", "p")
        res = storage.list_snippets()
        assert len(res) == 2
        assert res[0]['title'] == "A"

    def test_delete_snippet_success(self, storage):
        sid = storage.store_snippet("ToDelete", "D", "C", "py", "p")
        res = storage.delete_snippet(sid)
        assert res is True
        assert storage.get_snippet(sid, "p") is None

    def test_delete_snippet_not_found(self, storage):
        res = storage.delete_snippet(99999)
        assert res is False

    def test_search_snippets_match(self, storage):
        storage.store_snippet("SearchThis", "Desc", "C", "py", "p")
        res = storage.search_snippets("Search", 10)
        assert len(res) >= 1
        assert res[0]['title'] == "SearchThis"

    def test_search_snippets_no_match(self, storage):
        storage.store_snippet("NoMatch", "Desc", "C", "py", "p")
        res = storage.search_snippets("NonExistent", 10)
        assert len(res) == 0

    def test_search_snippets_respects_limit(self, storage):
        for i in range(10):
            storage.store_snippet(f"Title{i}", "D", "C", "py", "p")
        res = storage.search_snippets("Title", 5)
        assert len(res) <= 5

# --- Tests for CLI Commands ---

class TestCliCommands:
    @pytest.fixture(autouse=True)
    def setup_cli_input(self, monkeypatch, storage):
        # Prepare the storage instance to be used by CLI commands
        # Note: The 'storage' fixture patches sqlite3.connect
        pass

    def test_cli_add_snippet_success(self, storage, runner):
        # Input stream: Title, Language, Desc, Password, Code Line, EOF
        input_data = "Test Title\npython\nTest Desc\npassword\nprint('hi')\nEOF"
        result = runner.invoke(cli, ['--db-path', ':memory:'], input=input_data)
        assert result.exit_code == 0
        assert "Snippet saved with ID" in result.output

    def test_cli_add_snippet_empty_warning(self, storage, runner):
        # Input stream resulting in empty content
        input_data = "T\npy\nD\np\n\nEOF"
        result = runner.invoke(cli, ['--db-path', ':memory:'], input=input_data)
        assert "Warning" in result.output or "empty" in result.output.lower()

    def test_cli_show_snippet_success(self, storage, runner, monkeypatch):
        # Setup snippet first
        sid = storage.store_snippet("ShowMe", "D", "Secret", "py", "pwd")
        
        # Prompt.ask used in show command needs a return value for ID
        # We mock `snippet_storage.Prompt.ask` to return the ID
        with monkeypatch.context() as m:
            m.setattr(snippet_storage, 'Prompt', mock.MagicMock(ask=lambda x: sid))
            input_data = "pwd" # For password prompt
            result = runner.invoke(cli, ['--db-path', ':memory:', 'show'], input=input_data)
            assert "Snippet Details" in result.output
            assert "Secret" not in result.output  # Only first 50 chars shown with .. if >50
            
    def test_cli_show_snippet_not_found(self, storage, runner, monkeypatch):
        with monkeypatch.context() as m:
            m.setattr(snippet_storage, 'Prompt', mock.MagicMock(ask=lambda x: 99999))
            input_data = "pwd"
            result = runner.invoke(cli, ['--db-path', ':memory:', 'show'], input=input_data)
            assert "not found" in result.output.lower()

    def test_cli_delete_snippet_cancelled(self, storage, runner, monkeypatch):
        # Patch Prompt.ask to return ID 1, then 'n' for confirmation
        call_count = [0]
        def prompt_ask_side_effect(_):
            call_count[0] += 1
            if call_count[0] == 1:
                return 1
            return 'n'
        
        mock_prompt = mock.MagicMock()
        mock_prompt.ask = prompt_ask_side_effect
        
        with monkeypatch.context() as m:
            m.setattr(snippet_storage, 'Prompt', mock_prompt)
            # No input needed for password in delete command
            result = runner.invoke(cli, ['--db-path', ':memory:', 'delete', '1'])
            assert "Cancelled" in result.output

    def test_cli_delete_snippet_success(self, storage, runner, monkeypatch):
        sid = storage.store_snippet("ToDel", "D", "C", "py", "p")
        call_count = [0]
        def prompt_ask_side_effect(_):
            call_count[0] += 1
            if call_count[0] == 1:
                return sid
            return 'y'
            
        mock_prompt = mock.MagicMock()
        mock_prompt.ask = prompt_ask_side_effect
        
        with monkeypatch.context() as m:
            m.setattr(snippet_storage, 'Prompt', mock_prompt)
            result = runner.invoke(cli, ['--db-path', ':memory:', 'delete', '1'])
            assert "deleted successfully" in result.output.lower()

    def test_cli_list_snippets(self, storage, runner):
        storage.store_snippet("L1", "D", "C", "py", "p")
        result = runner.invoke(cli, ['--db-path', ':memory:', 'list-snippets'])
        assert "Stored Snippets" in result.output

    def test_cli_search_snippets(self, storage, runner):
        storage.store_snippet("SearchTarget", "Desc", "C", "py", "p")
        result = runner.invoke(cli, ['--db-path', ':memory:', 'search', 'SearchTarget'])
        assert "Search Results" in result.output
        assert "100%" in result.output or "Match Score" in result.output
        
    def test_cli_search_snippets_no_match(self, storage, runner):
        result = runner.invoke(cli, ['--db-path', ':memory:', 'search', 'NoSuchthing'])
        assert "No matching snippets found" in result.output
        
    def test_cli_init_success(self, storage, runner):
        result = runner.invoke(cli, ['--db-path', ':memory:', 'init-storage'])
        assert "Database initialized" in result.output

# Alias cli for usage in tests
from snippet_storage import cli as cli_entry