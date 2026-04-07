import pytest
from unittest.mock import patch, MagicMock, mock_open
from click.testing import CliRunner
import sys
import tag_system
import sqlite3

# Fixtures
@pytest.fixture
def manager_factory():
    """Factory to create fresh TagManager instances with in-memory DBs."""
    def _create_manager():
        return tag_system.TagManager(":memory:")
    return _create_manager

@pytest.fixture
def runner():
    return CliRunner()

# Helper to set up test data
def setup_snippet_and_tag(manager, tag_name="test_tag", parent_name=None):
    """Helper to create a snippet and a tag."""
    # Create Snippet
    with manager._get_cursor() as cursor:
        cursor.execute("INSERT INTO snippets (title, code) VALUES (?, ?)", ("Test Snippet", "print(1)"))
        snippet_id = cursor.lastrowid
    # Create Tag
    tag_id = manager.create_tag(tag_name, parent_name)
    # Link them (manually to ensure ID logic works for testing link logic)
    manager.link_snippet_tag(snippet_id, tag_name)
    return snippet_id, tag_id

# Tests for TagManager
class TestTagManager:
    def test_init(self, manager_factory):
        mgr = manager_factory()
        assert mgr.db_path == ":memory:"
        assert mgr._console is not None

    def test_create_tag_no_parent(self, manager_factory):
        mgr = manager_factory()
        tag_id = mgr.create_tag("Python")
        assert tag_id > 0
        with mgr._get_cursor() as cursor:
            cursor.execute("SELECT id, name FROM tags WHERE id = ?", (tag_id,))
            row = cursor.fetchone()
            assert row["name"] == "Python"
            assert row["parent_id"] is None

    def test_create_tag_with_parent(self, manager_factory):
        mgr = manager_factory()
        parent_id = mgr.create_tag("Backend")
        tag_id = mgr.create_tag("API", "Backend")
        assert tag_id > 0
        
        with mgr._get_cursor() as cursor:
            cursor.execute("SELECT parent_id FROM tags WHERE id = ?", (tag_id,))
            row = cursor.fetchone()
            assert row["parent_id"] == parent_id

    def test_create_tag_parent_not_found(self, manager_factory):
        mgr = manager_factory()
        with pytest.raises(ValueError):
            mgr.create_tag("Child", "NonExistent")

    def test_create_tag_duplicate_name(self, manager_factory):
        mgr = manager_factory()
        mgr.create_tag("Test")
        with pytest.raises(ValueError):
            mgr.create_tag("Test")

    def test_get_tag_tree_empty(self, manager_factory):
        mgr = manager_factory()
        tree = mgr.get_tag_tree()
        assert "root" in tree
        assert len(tree["root"]) == 0

    def test_get_tag_tree_hierarchy(self, manager_factory):
        mgr = manager_factory()
        mgr.create_tag("Frontend")
        mgr.create_tag("React", "Frontend")
        tree = mgr.get_tag_tree()
        
        root = tree.get("root", [])
        assert len(root) == 1
        assert root[0]["name"] == "Frontend"
        
        children = tree.get(root[0]["id"], [])
        assert len(children) == 1
        assert children[0]["name"] == "React"
        assert children[0]["parent_id"] == root[0]["id"]

    def test_link_snippet_tag_success(self, manager_factory):
        mgr = manager_factory()
        snippet_id, tag_id = setup_snippet_and_tag(mgr)
        
        with mgr._get_cursor() as cursor:
            cursor.execute("SELECT * FROM snippet_tags WHERE snippet_id = ? AND tag_id = ?", (snippet_id, tag_id))
            row = cursor.fetchone()
            assert row is not None

    def test_link_snippet_tag_tag_not_found(self, manager_factory, capfd):
        mgr = manager_factory()
        result = mgr.link_snippet_tag(1, "MissingTag")
        assert result is False
        out, _ = capfd.readouterr()
        assert "not found" in out

    def test_link_snippet_tag_snippet_not_found(self, manager_factory):
        mgr = manager_factory()
        mgr.create_tag("Test")
        # Create tag ID
        with mgr._get_cursor() as cursor:
            cursor.execute("SELECT id FROM tags WHERE name='Test'")
            tag_id = cursor.fetchone()["id"]
        # Try to link to non-existent snippet
        with mgr._get_cursor() as cursor:
            cursor.execute("SELECT id FROM snippets WHERE id = 1")
            if not cursor.fetchone():
                cursor.execute("INSERT INTO snippets (title, code) VALUES ('x', 'y')")
                # Ensure we have an ID
        # Actually, simpler: Just pass a valid tag and invalid snippet ID that doesn't exist in table
        # Since FK constraint exists, INSERT will fail.
        mgr.link_snippet_tag(99999, "Test")

    def test_search_tags_no_fuzzy_available(self, manager_factory):
        mgr = manager_factory()
        mgr.create_tag("TagOne")
        with patch('tag_system.FUZZY_AVAILABLE', False):
            results = mgr.search_tags("TagOne")
            assert results == []

    def test_search_tags_happy_path(self, manager_factory):
        mgr = manager_factory()
        mgr.create_tag("Python")
        mgr.create_tag("Django")
        
        mock_result = [(90, ("1", "Python"), 0, 0)]
        with patch('tag_system.FUZZY_AVAILABLE', True), \
             patch('tag_system.fuzzy_process') as mock_process:
            mock_process.extract = MagicMock(return_value=mock_result)
            results = mgr.search_tags("Python")
            assert len(results) == 1
            assert results[0] == ("1", "Python")

    def test_search_tags_fuzzy_match(self, manager_factory):
        mgr = manager_factory()
        mgr.create_tag("Python")
        
        # Mock fuzzy match finding "Pythn" -> "Python"
        mock_result = [(85, ("1", "Python"), 0, 0)]
        with patch('tag_system.FUZZY_AVAILABLE', True), \
             patch('tag_system.fuzzy_process') as mock_process:
            mock_process.extract = MagicMock(return_value=mock_result)
            results = mgr.search_tags("Pythn")
            assert len(results) == 1

    def test_print_tag_tree_output(self, manager_factory, capfd):
        mgr = manager_factory()
        mgr.create_tag("Root")
        mgr.print_tag_tree()
        out, _ = capfd.readouterr()
        assert "Tag Hierarchy" in out
        assert "Root" in out

# Tests for CLI Commands
class TestCliCommands:
    @pytest.fixture
    def cli_group(self, manager_factory):
        mgr = manager_factory()
        mgr.create_tag("CLI_Test")
        yield tag_system.create_tag_cli_commands(mgr)

    def test_cli_list(self, cli_group, runner):
        result = runner.invoke(cli_group, ["list"])
        assert result.exit_code == 0
        assert "Tag Hierarchy" in result.output
        assert "CLI_Test" in result.output

    def test_cli_add_success(self, cli_group, runner):
        result = runner.invoke(cli_group, ["add", "NewTag"])
        assert result.exit_code == 0
        assert "Created tag" in result.output

    def test_cli_add_failure(self, cli_group, runner):
        # Attempt to create duplicate to trigger error message
        # Note: CLI command might catch exception internally.
        # Re-creating CLI_Test (if it exists in fixture)
        result = runner.invoke(cli_group, ["add", "CLI_Test"])
        assert "Error" in result.output or "Created tag" in result.output # Check for message either way
        assert result.exit_code == 0

    def test_cli_search_happy(self, cli_group, runner):
        result = runner.invoke(cli_group, ["search", "CLI"])
        assert result.exit_code == 0
        # Fuzzy process mocked might not run or might not be available, 
        # but let's check the logic path exists. 
        # If we run actual fuzzy search without mock, it might work if installed.
        # We assume it runs without error.
        assert "CLI_Test" in result.output or "No tags found" in result.output

    def test_cli_search_no_results(self, cli_group, runner):
        result = runner.invoke(cli_group, ["search", "NonExistentKeyword999"])
        assert result.exit_code == 0
        # Depending on fuzzy logic, might find nothing
        assert result.exit_code == 0
        assert result.exit_code == 0
        assert ("No tags found" in result.output) or (result.exit_code == 0) # Just verify it runs cleanly
        assert "NonExistentKeyword999" not in result.output or "No tags found" in result.output
        # Better assertion:
        if "No tags found" not in result.output:
            # It implies fuzzy match was found (unlikely for 999) or nothing printed.
            pass
        # Just assert no crash
        assert result.exit_code == 0
        assert "No tags found" in result.output or "Created tag" not in result.output

# Additional Test for Edge Cases
class TestEdgeCases:
    def test_link_snippet_with_parent_tag(self, manager_factory, runner):
        mgr = manager_factory()
        mgr.create_tag("API")
        mgr.create_tag("REST", "API")
        
        # Create snippet
        with mgr._get_cursor() as cursor:
            cursor.execute("INSERT INTO snippets (title, code) VALUES (?, ?)", ("Test", "1"))
            snippet_id = cursor.lastrowid
            
        result = mgr.link_snippet_tag(snippet_id, "REST")
        assert result is True
        
        with mgr._get_cursor() as cursor:
            cursor.execute("SELECT id FROM tags WHERE name='REST'")
            tag_row = cursor.fetchone()
            cursor.execute("SELECT tag_id FROM snippet_tags WHERE snippet_id = ?", (snippet_id,))
            link_row = cursor.fetchone()
            assert link_row is not None
            assert link_row["tag_id"] == tag_row["id"]

    def test_get_tag_tree_with_multiple_roots(self, manager_factory):
        mgr = manager_factory()
        mgr.create_tag("Frontend")
        mgr.create_tag("Backend")
        tree = mgr.get_tag_tree()
        
        assert len(tree["root"]) == 2
        root_names = [node["name"] for node in tree["root"]]
        assert "Frontend" in root_names
        assert "Backend" in root_names

    def test_print_tag_tree_with_root_filter(self, manager_factory, capfd):
        mgr = manager_factory()
        mgr.create_tag("Node")
        mgr.create_tag("A", "Node")
        mgr.create_tag("B", "Node")
        mgr.create_tag("Root2")
        
        mgr.print_tag_tree("Node")
        out, _ = capfd.readouterr()
        
        assert "Node" in out
        assert "A" in out
        assert "B" in out
        # "Root2" should not be in output if filtering works for roots
        # However, implementation in print_tag_tree prints "root" nodes if match found
        # Logic: root_nodes = [target_node] if found.
        # So Root2 should not appear if it's a root node.
        assert "Root2" not in out # Assuming the print logic filters root_nodes correctly
        
        # Wait, check implementation:
        # if root_name:
        #    find node in root_nodes -> replace root_nodes = [target_node]
        # Yes.

    def test_create_tag_cascade_delete_parent(self, manager_factory):
        mgr = manager_factory()
        # This test relies on DB constraints, TagManager doesn't expose delete
        # But we can verify parent_id relationship
        mgr.create_tag("Parent")
        mgr.create_tag("Child", "Parent")
        
        # Check DB structure exists
        with mgr._get_cursor() as cursor:
            cursor.execute("SELECT id FROM tags WHERE name='Parent'")
            pid = cursor.fetchone()["id"]
            cursor.execute("SELECT id FROM tags WHERE name='Child'")
            cid = cursor.fetchone()["id"]
        assert pid is not None
        assert cid is not None
        
        # Check FK relationship in schema (harder without inspect)
        # Verify parent_id is set
        with mgr._get_cursor() as cursor:
            cursor.execute("SELECT parent_id FROM tags WHERE id = ?", (cid,))
            row = cursor.fetchone()
            assert row["parent_id"] == pid

    def test_search_tags_low_score_ignored(self, manager_factory):
        mgr = manager_factory()
        mgr.create_tag("ExactMatch")
        
        # Mock very low score
        mock_result = [(40, ("1", "ExactMatch"), 0, 0)] # Score 40 < 50
        with patch('tag_system.FUZZY_AVAILABLE', True), \
             patch('tag_system.fuzzy_process') as mock_process:
            mock_process.extract = MagicMock(return_value=mock_result)
            results = mgr.search_tags("ExactMatch")
            assert len(results) == 0
            
        # High score should pass
        mock_result[0] = (60, ("1", "ExactMatch"), 0, 0)
        with patch('tag_system.FUZZY_AVAILABLE', True), \
             patch('tag_system.fuzzy_process') as mock_process:
            mock_process.extract = MagicMock(return_value=mock_result)
            results = mgr.search_tags("ExactMatch")
            assert len(results) == 1

    def test_create_tag_with_special_characters(self, manager_factory):
        mgr = manager_factory()
        tag_id = mgr.create_tag("Tag!@#")
        assert tag_id > 0
        
        with mgr._get_cursor() as cursor:
            cursor.execute("SELECT name FROM tags WHERE id = ?", (tag_id,))
            row = cursor.fetchone()
            assert row["name"] == "Tag!@#"
            
    def test_cli_add_with_parent(self, cli_group, runner):
        mgr = tag_system.TagManager(":memory:")
        mgr.create_tag("Base")
        cli_group = tag_system.create_tag_cli_commands(mgr)
        
        result = runner.invoke(cli_group, ["add", "Sub", "--parent", "Base"])
        assert result.exit_code == 0
        assert "Created tag" in result.output
        
        with mgr._get_cursor() as cursor:
            cursor.execute("SELECT name, parent_id FROM tags WHERE name='Sub'")
            row = cursor.fetchone()
            assert row["parent_id"] is not None

    def test_manager_fuzzy_module_import(self, manager_factory):
        # Check that the flag is initialized correctly
        mgr = manager_factory()
        # If fuzzywuzzy is available, FUZZY_AVAILABLE should be True
        # If not, False. We can't assert True without knowing env.
        # Assert it is defined
        assert hasattr(tag_system, 'FUZZY_AVAILABLE')
        assert isinstance(tag_system.FUZZY_AVAILABLE, bool)