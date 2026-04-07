import pytest
import sqlite3
from unittest.mock import Mock, patch, MagicMock, call, PropertyMock
from click.testing import CliRunner
from cli_interface import (
    cli, _add_snippet, _get_snippet, _list_snippets,
    _search_snippets, _delete_snippet, _initialize_database,
    DB_PATH
)


@pytest.fixture
def mock_cursor():
    """Create a mock cursor with default return values."""
    cursor = Mock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None
    cursor.rowcount = 0
    cursor.execute = Mock(return_value=None)
    return cursor


@pytest.fixture
def mock_connection(mock_cursor):
    """Create a mock database connection with cursor."""
    connection = Mock()
    connection.cursor.return_value = mock_cursor
    connection.commit = Mock(return_value=None)
    connection.close = Mock(return_value=None)
    return connection


@pytest.fixture
def runner():
    """Create a Click testing runner."""
    return CliRunner()


@pytest.fixture
def mock_db_connection(mock_connection):
    """Patch sqlite3.connect to return our mock connection."""
    with patch('sqlite3.connect', return_value=mock_connection):
        yield mock_connection


@pytest.fixture
def mock_fuzz_partial_ratio():
    """Mock fuzzywuzzy.fuzz.partial_ratio for search tests."""
    with patch('fuzzywuzzy.fuzz.partial_ratio') as mock_func:
        mock_func.return_value = 60
        yield mock_func


@pytest.fixture
def sample_snippet_data():
    """Sample snippet data for testing."""
    return (1, 'test-snippet', 'tag1,tag2', 'def hello(): print("world")', '2024-01-01 00:00:00')


@pytest.fixture
def sample_list_data():
    """Sample list data with multiple snippets."""
    return [
        (1, 'snippet-a', 'tag1', 'code A'),
        (2, 'snippet-b', 'tag2', 'code B'),
        (3, 'snippet-c', 'tag3', 'code C'),
    ]


class TestInitializeDatabase:
    """Tests for _initialize_database function."""

    @patch('cli_interface.sqlite3.connect')
    @patch('cli_interface.CONSOLE')
    def test_initialize_database_success(self, mock_console, mock_connect, mock_cursor, mock_connection):
        """Test successful database initialization."""
        mock_connect.return_value = mock_connection
        
        result = _initialize_database()
        
        mock_cursor.execute.assert_called()
        mock_connection.commit.assert_called()
        mock_connection.close.assert_called()
        assert result is None

    @patch('cli_interface.sqlite3.connect')
    @patch('cli_interface.CONSOLE')
    def test_initialize_database_error(self, mock_console, mock_connect):
        """Test database initialization with error."""
        mock_connect.side_effect = sqlite3.Error("Connection failed")
        
        result = _initialize_database()
        
        mock_console.print.assert_called()
        assert result is None

    @patch('cli_interface.sqlite3.connect')
    @patch('cli_interface.CONSOLE')
    def test_initialize_database_cursor_error(self, mock_console, mock_connect, mock_cursor, mock_connection):
        """Test database initialization with cursor error."""
        mock_connect.return_value = mock_connection
        mock_cursor.execute.side_effect = sqlite3.Error("Query failed")
        
        result = _initialize_database()
        
        mock_console.print.assert_called()
        assert result is None


class TestAddSnippet:
    """Tests for _add_snippet function."""

    @patch('sqlite3.connect')
    def test_add_snippet_success(self, mock_connect, mock_cursor, mock_connection):
        """Test successful snippet addition."""
        mock_connect.return_value = mock_connection
        
        result = _add_snippet('test-name', 'tag1,tag2', 'print("hello")')
        
        assert result is True
        mock_cursor.execute.assert_called_once()
        mock_connection.commit.assert_called()

    @patch('sqlite3.connect')
    def test_add_snippet_integrity_error(self, mock_connect, mock_cursor, mock_connection):
        """Test snippet addition with integrity error (duplicate name)."""
        mock_connect.return_value = mock_connection
        mock_cursor.execute.side_effect = sqlite3.IntegrityError("duplicate")
        
        result = _add_snippet('existing-name', 'tag1', 'code')
        
        assert result is False
        mock_cursor.execute.assert_called_once()

    @patch('sqlite3.connect')
    def test_add_snippet_db_error(self, mock_connect, mock_cursor, mock_connection):
        """Test snippet addition with database error."""
        mock_connect.return_value = mock_connection
        mock_cursor.execute.side_effect = sqlite3.Error("DB error")
        
        result = _add_snippet('test-name', 'tag1', 'code')
        
        assert result is False
        mock_cursor.execute.assert_called_once()


class TestGetSnippet:
    """Tests for _get_snippet function."""

    @patch('sqlite3.connect')
    def test_get_snippet_found(self, mock_connect, mock_cursor, mock_connection, sample_snippet_data):
        """Test retrieving existing snippet."""
        mock_connect.return_value = mock_connection
        mock_cursor.fetchone.return_value = sample_snippet_data
        
        result = _get_snippet('test-snippet')
        
        assert result is not None
        assert result[1] == 'test-snippet'
        mock_cursor.execute.assert_called()

    @patch('sqlite3.connect')
    def test_get_snippet_not_found(self, mock_connect, mock_cursor, mock_connection):
        """Test retrieving non-existent snippet."""
        mock_connect.return_value = mock_connection
        mock_cursor.fetchone.return_value = None
        
        result = _get_snippet('non-existent')
        
        assert result is None

    @patch('sqlite3.connect')
    def test_get_snippet_db_error(self, mock_connect, mock_cursor, mock_connection):
        """Test retrieving snippet with database error."""
        mock_connect.return_value = mock_connection
        mock_cursor.fetchone.side_effect = sqlite3.Error("Query failed")
        
        result = _get_snippet('test-snippet')
        
        assert result is None
        mock_cursor.fetchone.assert_called()


class TestListSnippets:
    """Tests for _list_snippets function."""

    @patch('sqlite3.connect')
    def test_list_snippets_empty(self, mock_connect, mock_cursor, mock_connection):
        """Test listing snippets when database is empty."""
        mock_connect.return_value = mock_connection
        mock_cursor.fetchall.return_value = []
        
        result = _list_snippets()
        
        assert result == []
        mock_cursor.execute.assert_called()

    @patch('sqlite3.connect')
    def test_list_snippets_with_data(self, mock_connect, mock_cursor, mock_connection, sample_list_data):
        """Test listing snippets with data."""
        mock_connect.return_value = mock_connection
        mock_cursor.fetchall.return_value = sample_list_data
        
        result = _list_snippets()
        
        assert len(result) == 3
        assert result[0][1] == 'snippet-a'
        mock_cursor.execute.assert_called()

    @patch('sqlite3.connect')
    def test_list_snippets_db_error(self, mock_connect, mock_cursor, mock_connection):
        """Test listing snippets with database error."""
        mock_connect.return_value = mock_connection
        mock_cursor.fetchall.side_effect = sqlite3.Error("Query failed")
        
        result = _list_snippets()
        
        assert result == []
        mock_cursor.fetchall.assert_called()


class TestSearchSnippets:
    """Tests for _search_snippets function."""

    @patch('sqlite3.connect')
    @patch('fuzzywuzzy.fuzz.partial_ratio')
    def test_search_snippets_matches(self, mock_fuzz, mock_connect, mock_cursor, mock_connection, sample_list_data):
        """Test searching snippets with matches."""
        mock_connect.return_value = mock_connection
        mock_cursor.fetchall.return_value = sample_list_data
        mock_fuzz.return_value = 75
        
        result = _search_snippets('snippet')
        
        assert len(result) == 3
        assert result[0][1] == 'snippet-a'
        mock_cursor.fetchall.assert_called()

    @patch('sqlite3.connect')
    @patch('fuzzywuzzy.fuzz.partial_ratio')
    def test_search_snippets_no_matches(self, mock_fuzz, mock_connect, mock_cursor, mock_connection):
        """Test searching snippets with no matches."""
        mock_connect.return_value = mock_connection
        mock_cursor.fetchall.return_value = sample_list_data
        mock_fuzz.return_value = 30
        
        result = _search_snippets('unrelated')
        
        assert result == []
        mock_fuzz.assert_called()

    @patch('sqlite3.connect')
    @patch('fuzzywuzzy.fuzz.partial_ratio')
    def test_search_snippets_db_error(self, mock_fuzz, mock_connect, mock_cursor, mock_connection):
        """Test searching snippets with database error."""
        mock_connect.return_value = mock_connection
        mock_cursor.fetchall.side_effect = sqlite3.Error("Query failed")
        
        result = _search_snippets('test')
        
        assert result == []
        mock_fuzz.assert_not_called()


class TestDeleteSnippet:
    """Tests for _delete_snippet function."""

    @patch('sqlite3.connect')
    def test_delete_snippet_success(self, mock_connect, mock_cursor, mock_connection):
        """Test successful snippet deletion."""
        mock_connect.return_value = mock_connection
        mock_cursor.rowcount = 1
        
        result = _delete_snippet('test-snippet')
        
        assert result is True
        mock_cursor.execute.assert_called()
        mock_connection.commit.assert_called()

    @patch('sqlite3.connect')
    def test_delete_snippet_not_found(self, mock_connect, mock_cursor, mock_connection):
        """Test deleting non-existent snippet."""
        mock_connect.return_value = mock_connection
        mock_cursor.rowcount = 0
        
        result = _delete_snippet('non-existent')
        
        assert result is False
        mock_cursor.execute.assert_called()

    @patch('sqlite3.connect')
    def test_delete_snippet_db_error(self, mock_connect, mock_cursor, mock_connection):
        """Test deleting snippet with database error."""
        mock_connect.return_value = mock_connection
        mock_cursor.execute.side_effect = sqlite3.Error("Query failed")
        
        result = _delete_snippet('test-snippet')
        
        assert result is False
        mock_connection.commit.assert_not_called()


class TestCliCommands:
    """Tests for Click CLI commands."""

    @patch('cli_interface._initialize_database')
    @patch('cli_interface._add_snippet')
    def test_cli_add_command_success(self, mock_add, mock_init, runner):
        """Test add command with successful addition."""
        mock_add.return_value = True
        result = runner.invoke(cli, ['add', 'test-name', '--tags', 'tag1', '--code', 'print("hi")'])
        
        assert result.exit_code == 0
        assert 'added successfully' in result.output
        mock_add.assert_called_once()

    @patch('cli_interface._initialize_database')
    @patch('cli_interface._add_snippet')
    def test_cli_add_command_failure(self, mock_add, mock_init, runner):
        """Test add command with failed addition."""
        mock_add.return_value = False
        result = runner.invoke(cli, ['add', 'test-name', '--code', 'code content'])
        
        assert result.exit_code == 0
        assert 'Failed to add' in result.output

    @patch('cli_interface._list_snippets')
    def test_cli_list_snippets_empty(self, mock_list, runner):
        """Test list command with no snippets."""
        mock_list.return_value = []
        result = runner.invoke(cli, ['list'])
        
        assert result.exit_code == 0
        assert 'No snippets found' in result.output

    @patch('cli_interface._list_snippets')
    def test_cli_list_snippets_with_data(self, mock_list, runner, sample_list_data):
        """Test list command with snippets."""
        mock_list.return_value = sample_list_data
        result = runner.invoke(cli, ['list'])
        
        assert result.exit_code == 0
        assert 'snippet-a' in result.output
        assert 'snippet-b' in result.output

    @patch('cli_interface._search_snippets')
    def test_cli_search_command_matches(self, mock_search, runner):
        """Test search command with matches."""
        mock_search.return_value = [(1, 'test-snippet', 'tag', 'code', 80)]
        result = runner.invoke(cli, ['search', 'test'])
        
        assert result.exit_code == 0
        assert '80' in result.output

    @patch('cli_interface._search_snippets')
    def test_cli_search_command_no_matches(self, mock_search, runner):
        """Test search command with no matches."""
        mock_search.return_value = []
        result = runner.invoke(cli, ['search', 'nonexistent'])
        
        assert result.exit_code == 0
        assert 'No matches found' in result.output

    @patch('cli_interface._get_snippet')
    def test_cli_get_command_found(self, mock_get, runner):
        """Test get command with existing snippet."""
        mock_get.return_value = (1, 'test-snippet', 'tag1', 'code', '2024-01-01')
        result = runner.invoke(cli, ['get', 'test-snippet'])
        
        assert result.exit_code == 0
        assert 'Snippet: test-snippet' in result.output

    @patch('cli_interface._get_snippet')
    def test_cli_get_command_not_found(self, mock_get, runner):
        """Test get command with non-existent snippet."""
        mock_get.return_value = None
        result = runner.invoke(cli, ['get', 'nonexistent'])
        
        assert result.exit_code == 0
        assert 'not found' in result.output

    @patch('cli_interface._delete_snippet')
    def test_cli_delete_command_success(self, mock_delete, runner):
        """Test delete command with successful deletion."""
        mock_delete.return_value = True
        result = runner.invoke(cli, ['delete', 'test-snippet'])
        
        assert result.exit_code == 0
        assert 'deleted successfully' in result.output

    @patch('cli_interface._delete_snippet')
    def test_cli_delete_command_failure(self, mock_delete, runner):
        """Test delete command with failed deletion."""
        mock_delete.return_value = False
        result = runner.invoke(cli, ['delete', 'nonexistent'])
        
        assert result.exit_code == 0
        assert 'could not be deleted' in result.output


class TestCliGroup:
    """Tests for CLI group functionality."""

    def test_cli_group_help(self, runner):
        """Test CLI group help command."""
        result = runner.invoke(cli, ['--help'])
        
        assert result.exit_code == 0
        assert 'Dev Snippet Keeper' in result.output
        assert 'add' in result.output
        assert 'list' in result.output
        assert 'search' in result.output

    @patch('cli_interface._initialize_database')
    def test_cli_group_invocation(self, mock_init, runner):
        """Test CLI group basic invocation."""
        result = runner.invoke(cli, ['--help'])
        
        assert result.exit_code == 0
        mock_init.assert_called_once()

    def test_cli_group_invalid_command(self, runner):
        """Test CLI with invalid command."""
        result = runner.invoke(cli, ['invalid-command'])
        
        assert result.exit_code != 0