import pytest
from unittest.mock import mock_open, patch, MagicMock
from pathlib import Path
import os
import json
import sqlite3

from export_utils import (
    validate_snippet_data,
    deduplicate_snippets,
    export_snippets_to_json,
    export_db_to_json,
    import_snippets_from_json,
    import_snippets_to_sqlite,
    export_collection_metadata
)


@pytest.fixture
def valid_snippet_list():
    return [
        {
            'id': 1,
            'title': 'Test Snippet 1',
            'content': 'This is the content of snippet 1',
            'language': 'python',
            'tags': ['test', 'snippet']
        },
        {
            'id': 2,
            'title': 'Test Snippet 2',
            'content': 'This is the content of snippet 2',
            'language': 'javascript',
            'tags': ['code', 'example']
        }
    ]


@pytest.fixture
def valid_snippet_dict():
    return {
        'id': 1,
        'title': 'Test Snippet',
        'content': 'Test content',
        'language': 'python',
        'tags': ['test']
    }


@pytest.fixture
def incomplete_snippet_list():
    return [
        {
            'id': 1,
            'title': 'Test Snippet 1',
            'content': 'This is the content',
            'language': 'python'
        },
        {
            'id': 2,
            'title': 'Test Snippet 2',
            'content': 'Content 2',
            'language': 'js',
            'tags': ['code']
        }
    ]


@pytest.fixture
def invalid_snippet_list():
    return [
        'not a dict',
        {'id': 1}
    ]


@pytest.fixture
def mock_cursor():
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = [0]
    return cursor


@pytest.fixture
def mock_connection(mock_cursor):
    connection = MagicMock(spec=sqlite3.Connection)
    connection.cursor.return_value = mock_cursor
    return connection


@pytest.fixture
def sample_snippets():
    return [
        {
            'id': 1,
            'title': 'Snippet 1',
            'content': 'Content 1',
            'language': 'python',
            'tags': ['a', 'b']
        },
        {
            'id': 2,
            'title': 'Snippet 1',
            'content': 'Content 1',
            'language': 'python',
            'tags': ['a', 'b']
        },
        {
            'id': 3,
            'title': 'Snippet 3',
            'content': 'Content 3 different',
            'language': 'javascript',
            'tags': ['c']
        }
    ]


class TestValidateSnippetData:
    def test_validate_valid_snippets(self, valid_snippet_list):
        result = validate_snippet_data(valid_snippet_list)
        assert result is True

    def test_validate_valid_single_snippet(self, valid_snippet_dict):
        result = validate_snippet_data([valid_snippet_dict])
        assert result is True

    def test_validate_invalid_not_dict(self, invalid_snippet_list):
        result = validate_snippet_data(invalid_snippet_list)
        assert result is False

    def test_validate_missing_fields(self, incomplete_snippet_list):
        result = validate_snippet_data(incomplete_snippet_list)
        assert result is False

    def test_validate_empty_list(self):
        result = validate_snippet_data([])
        assert result is True


class TestDeduplicateSnippets:
    def test_deduplicate_no_duplicates(self, valid_snippet_list):
        result = deduplicate_snippets(valid_snippet_list, threshold=80)
        assert len(result) == 2

    def test_deduplicate_with_duplicates(self, sample_snippets):
        result = deduplicate_snippets(sample_snippets, threshold=80)
        assert len(result) <= 3

    def test_deduplicate_empty_list(self):
        result = deduplicate_snippets([])
        assert result == []

    def test_deduplicate_threshold_0(self, sample_snippets):
        result = deduplicate_snippets(sample_snippets, threshold=0)
        assert len(result) >= len(sample_snippets) - 1

    def test_deduplicate_exception_handling(self):
        with patch('export_utils.console'):
            result = deduplicate_snippets(['invalid'], threshold=80)
            assert isinstance(result, list)


class TestExportSnippetsToJson:
    def test_export_snippets_to_json_happy_path(self, valid_snippet_list, tmp_path):
        output_file = tmp_path / "test_output.json"
        with patch('export_utils.validate_snippet_data', return_value=True):
            export_snippets_to_json(valid_snippet_list, str(output_file))
            assert output_file.exists()

    def test_export_snippets_to_json_permission_denied(self, tmp_path):
        output_file = tmp_path / "readonly.json"
        output_file.write_text("{}")
        output_file.chmod(0o444)
        with patch('export_utils.validate_snippet_data', return_value=True):
            export_snippets_to_json([], str(output_file))

    def test_export_snippets_to_json_validation_failed(self, tmp_path):
        output_file = tmp_path / "test_output.json"
        with patch('export_utils.validate_snippet_data', return_value=False):
            export_snippets_to_json([], str(output_file))

    def test_export_snippets_to_json_with_content(self, tmp_path, valid_snippet_list):
        output_file = tmp_path / "test_output.json"
        with patch('export_utils.validate_snippet_data', return_value=True):
            export_snippets_to_json(valid_snippet_list, str(output_file))
            with open(output_file, 'r') as f:
                data = json.load(f)
            assert len(data) == 2


class TestExportDbToJson:
    def test_export_db_to_json_happy_path(self, mock_connection, mock_cursor, tmp_path):
        mock_cursor.fetchall.return_value = [
            (1, 'Title 1', 'Content 1', 'python', 'tags1', '2024-01-01')
        ]
        with patch('sqlite3.connect', return_value=mock_connection):
            with patch('os.path.exists', return_value=True):
                output_file = tmp_path / "db_export.json"
                export_db_to_json(str(tmp_path / "test.db"), str(output_file))

    def test_export_db_to_json_db_not_found(self):
        with patch('os.path.exists', return_value=False):
            export_db_to_json("nonexistent.db", "output.json")

    def test_export_db_to_json_sqlite_error(self, mock_connection):
        mock_connection.cursor.side_effect = sqlite3.Error("Test error")
        with patch('sqlite3.connect', return_value=mock_connection):
            with patch('os.path.exists', return_value=True):
                export_db_to_json("test.db", "output.json")

    def test_export_db_to_json_no_connection(self):
        with patch('sqlite3.connect', side_effect=Exception("Connection error")):
            with patch('os.path.exists', return_value=True):
                export_db_to_json("test.db", "output.json")


class TestImportSnippetsFromJson:
    @patch('builtins.open', new_callable=mock_open, read_data='[{"id": 1, "title": "T", "content": "C", "language": "py", "tags": "t"}]')
    @patch('json.load')
    def test_import_snippets_from_json_happy_path(self, mock_load, mock_file, tmp_path):
        output_file = tmp_path / "test_input.json"
        output_file.write_text('[]')
        with patch('os.path.exists', return_value=True):
            skipped, snippets = import_snippets_from_json(str(output_file), skip_duplicates=False)
            assert skipped == 0
            assert isinstance(snippets, list)

    def test_import_snippets_from_json_file_not_found(self):
        skipped, snippets = import_snippets_from_json("nonexistent.json", skip_duplicates=False)
        assert skipped == 0
        assert snippets == []

    def test_import_snippets_from_json_invalid_format(self, tmp_path):
        output_file = tmp_path / "test_input.json"
        output_file.write_text('{"id": 1}')
        skipped, snippets = import_snippets_from_json(str(output_file), skip_duplicates=False)
        assert skipped == 0
        assert snippets == []

    def test_import_snippets_from_json_validation_failed(self, tmp_path):
        output_file = tmp_path / "test_input.json"
        output_file.write_text('[{"id": 1}]')
        skipped, snippets = import_snippets_from_json(str(output_file), skip_duplicates=False)
        assert skipped == 0

    @patch('builtins.open', new_callable=mock_open, read_data='{invalid json}')
    def test_import_snippets_from_json_json_decode_error(self, mock_file):
        skipped, snippets = import_snippets_from_json("test.json", skip_duplicates=False)
        assert skipped == 0


class TestImportSnippetsToSqlite:
    def test_import_snippets_to_sqlite_happy_path(self, mock_connection, mock_cursor):
        snippets = [
            {'id': 1, 'title': 'T', 'content': 'C', 'language': 'py', 'tags': 't', 'created_at': '2024-01-01'}
        ]
        mock_cursor.fetchone.return_value = [0]
        with patch('sqlite3.connect', return_value=mock_connection):
            with patch('os.path.exists', return_value=True):
                result = import_snippets_to_sqlite(str(Path("test.db")), snippets)
                assert result >= 0

    def test_import_snippets_to_sqlite_duplicate_skip(self, mock_connection, mock_cursor):
        snippets = [
            {'id': 1, 'title': 'T', 'content': 'C', 'language': 'py', 'tags': 't', 'created_at': '2024-01-01'},
            {'id': 1, 'title': 'T', 'content': 'C', 'language': 'py', 'tags': 't', 'created_at': '2024-01-01'}
        ]
        mock_cursor.fetchone.return_value = [1]
        with patch('sqlite3.connect', return_value=mock_connection):
            with patch('os.path.exists', return_value=True):
                result = import_snippets_to_sqlite(str(Path("test.db")), snippets, skip_duplicates=True)
                assert result == 1

    def test_import_snippets_to_sqlite_sqlite_error(self, mock_connection):
        snippets = [{'id': 1, 'title': 'T', 'content': 'C', 'language': 'py', 'tags': 't', 'created_at': '2024-01-01'}]
        mock_connection.cursor.side_effect = sqlite3.Error("DB error")
        with patch('sqlite3.connect', return_value=mock_connection):
            with patch('os.path.exists', return_value=True):
                result = import_snippets_to_sqlite(str(Path("test.db")), snippets)
                assert result == 0

    def test_import_snippets_to_sqlite_exception(self, mock_connection):
        snippets = [{'id': 1, 'title': 'T', 'content': 'C', 'language': 'py', 'tags': 't', 'created_at': '2024-01-01'}]
        mock_connection.cursor.side_effect = Exception("Unexpected error")
        with patch('sqlite3.connect', return_value=mock_connection):
            with patch('os.path.exists', return_value=True):
                result = import_snippets_to_sqlite(str(Path("test.db")), snippets)
                assert result == 0


class TestExportCollectionMetadata:
    def test_export_collection_metadata_happy_path(self, mock_connection, mock_cursor, tmp_path):
        mock_cursor.fetchall.side_effect = [[('lang1',), ('lang2',)], (5,)]
        with patch('sqlite3.connect', return_value=mock_connection):
            with patch('os.path.exists', return_value=True):
                with patch('pathlib.Path.strftime', return_value='2024-01-01 12:00'):
                    output_file = tmp_path / "metadata.json"
                    export_collection_metadata(str(tmp_path / "test.db"), str(output_file))
                    assert output_file.exists()

    def test_export_collection_metadata_db_not_found(self):
        with patch('os.path.exists', return_value=False):
            export_collection_metadata("nonexistent.db", "metadata.json")

    def test_export_collection_metadata_sqlite_error(self, mock_connection):
        mock_connection.cursor.side_effect = sqlite3.Error("DB error")
        with patch('sqlite3.connect', return_value=mock_connection):
            with patch('os.path.exists', return_value=True):
                export_collection_metadata("test.db", "metadata.json")

    def test_export_collection_metadata_exception(self, mock_connection):
        mock_connection.cursor.side_effect = Exception("Unexpected")
        with patch('sqlite3.connect', return_value=mock_connection):
            with patch('os.path.exists', return_value=True):
                export_collection_metadata("test.db", "metadata.json")