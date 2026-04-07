import sqlite3
import click
from typing import List, Dict, Optional, Tuple, Any, Iterator
from contextlib import contextmanager
from rich.console import Console
from rich.table import Table
from fuzzywuzzy import process
import fuzzywuzzy

try:
    FUZZY_AVAILABLE = True
    from fuzzywuzzy import process as fuzzy_process
except ImportError:
    FUZZY_AVAILABLE = False
    fuzzy_process = None


class TagManager:
    """
    Manages hierarchical tagging system for code snippets using SQLite.
    Supports creating tags with parent-child relationships, linking tags to snippets,
    and searching for tags using fuzzy matching.
    """

    def __init__(self, db_path: str = "snippets.db"):
        """
        Initialize the TagManager with a path to the SQLite database.

        Args:
            db_path: The file path for the SQLite database.
        """
        self.db_path = db_path
        self._console = Console()
        self._init_db()

    @contextmanager
    def _get_cursor(self) -> Iterator[sqlite3.Cursor]:
        """Context manager for database connections and commits."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init_db(self) -> None:
        """
        Initializes the database schema for tags and snippet-tag relationships.
        Creates a 'tags' table with hierarchical support (parent_id) and a 
        'snippet_tags' junction table for many-to-many relationships.
        """
        try:
            with self._get_cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tags (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        parent_id INTEGER,
                        FOREIGN KEY (parent_id) REFERENCES tags(id) ON DELETE CASCADE
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS snippet_tags (
                        snippet_id INTEGER,
                        tag_id INTEGER,
                        PRIMARY KEY (snippet_id, tag_id),
                        FOREIGN KEY (snippet_id) REFERENCES snippets(id) ON DELETE CASCADE,
                        FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS snippets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        code TEXT NOT NULL
                    );
                """)
        except sqlite3.Error as e:
            self._console.print(f"[red]Database initialization error: {e}[/red]")
            raise

    def create_tag(self, name: str, parent_name: Optional[str] = None) -> int:
        """
        Creates a new tag. If parent_name is provided, it links the new tag to an existing parent.

        Args:
            name: The name of the tag to create.
            parent_name: Optional name of an existing parent tag.

        Returns:
            The ID of the newly created tag.

        Raises:
            Exception: If the tag creation fails or parent name is not found.
        """
        try:
            with self._get_cursor() as cursor:
                if parent_name:
                    cursor.execute("SELECT id FROM tags WHERE name = ?", (parent_name,))
                    parent_row = cursor.fetchone()
                    if not parent_row:
                        raise ValueError(f"Parent tag '{parent_name}' not found.")
                    parent_id = parent_row["id"]
                else:
                    parent_id = None

                # Check for duplicate tag names in hierarchy
                cursor.execute(
                    "SELECT id FROM tags WHERE name = ? AND (parent_id = ? OR parent_id IS NULL AND ? IS NULL)",
                    (name, parent_id, parent_id)
                )
                if cursor.fetchone():
                    raise ValueError(f"Tag '{name}' already exists in this context.")

                cursor.execute(
                    "INSERT INTO tags (name, parent_id) VALUES (?, ?)",
                    (name, parent_id)
                )
                return cursor.lastrowid
        except sqlite3.Error as e:
            self._console.print(f"[red]Error creating tag: {e}[/red]")
            raise ValueError(f"Failed to create tag: {e}")

    def get_tag_tree(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Retrieves the hierarchical structure of tags.

        Returns:
            A dictionary where keys are parent IDs (or "root" for top level) 
            and values are lists of child tag dictionaries.
        """
        try:
            with self._get_cursor() as cursor:
                cursor.execute("SELECT id, name, parent_id FROM tags")
                rows = cursor.fetchall()
                
                tag_map = {row["id"]: {"id": row["id"], "name": row["name"], "parent_id": row["parent_id"]} for row in rows}
                tree: Dict[str, List[Dict[str, Any]]] = {}
                
                # Build child lists mapping
                for tag_id, data in tag_map.items():
                    parent_id = data["parent_id"]
                    if parent_id is None:
                        tree.setdefault("root", []).append(data)
                    else:
                        tree.setdefault(parent_id, []).append(data)
                
                return tree
        except sqlite3.Error as e:
            self._console.print(f"[red]Error retrieving tag tree: {e}[/red]")
            raise

    def link_snippet_tag(self, snippet_id: int, tag_name: str) -> bool:
        """
        Links an existing tag to a code snippet.

        Args:
            snippet_id: The ID of the snippet.
            tag_name: The name of the tag to link.

        Returns:
            True if linked successfully, False if tag not found.
        """
        try:
            with self._get_cursor() as cursor:
                cursor.execute("SELECT id FROM tags WHERE name = ?", (tag_name,))
                tag_row = cursor.fetchone()
                if not tag_row:
                    self._console.print(f"[yellow]Tag '{tag_name}' not found.[/yellow]")
                    return False
                
                cursor.execute(
                    "INSERT OR IGNORE INTO snippet_tags (snippet_id, tag_id) VALUES (?, ?)",
                    (snippet_id, tag_row["id"])
                )
                return True
        except sqlite3.Error as e:
            self._console.print(f"[red]Error linking snippet tag: {e}[/red]")
            return False

    def search_tags(self, query: str, limit: int = 10) -> List[Tuple[int, str]]:
        """
        Searches for tags using fuzzy matching.

        Args:
            query: The search query string.
            limit: Maximum number of results to return.

        Returns:
            List of tuples containing (tag_id, tag_name).
        """
        results = []
        if not FUZZY_AVAILABLE or fuzzy_process is None:
            self._console.print("[yellow]FuzzyWuzzy not available. Returning exact matches.[/yellow]")
            return results
        
        try:
            with self._get_cursor() as cursor:
                cursor.execute("SELECT id, name FROM tags")
                tags = cursor.fetchall()
                
                tag_list = [(row["id"], row["name"]) for row in tags]
                
                # extract returns list of (score, value, index, start)
                best_matches = fuzzy_process.extract(query, tag_list, limit=limit)
                
                # Filter matches above 50% similarity and extract just (id, name)
                results = [match[1] for match in best_matches if match[0] > 50]
                return results
        except sqlite3.Error as e:
            self._console.print(f"[red]Error searching tags: {e}[/red]")
            return []

    def print_tag_tree(self, root_name: Optional[str] = None) -> None:
        """
        Prints the tag tree to the console using Rich formatting.

        Args:
            root_name: Optional name of the root tag to highlight.
        """
        tree_data = self.get_tag_tree()
        root_nodes = tree_data.get("root", [])
        
        # If filtering by root_name, we might need to find the specific node in tree_data
        if root_name:
            target_node = None
            for node in root_nodes:
                if node['name'] == root_name:
                    target_node = node
                    break
            if target_node:
                root_nodes = [target_node]
        
        self._console.print(f"[bold]Tag Hierarchy:[/bold]")
        if not root_nodes:
            self._console.print("  No tags found.")
            return

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Hierarchy Level", style="dim")
        table.add_column("Tag Name", style="cyan")
        table.add_column("ID", style="grey58")

        def _traverse(nodes: List[Dict], tree: Dict[str, List], indent: int = 0):
            for node in nodes:
                name = node['name']
                tag_id = node['id']
                table.add_row(
                    " " * indent + "└─ ",
                    name,
                    str(tag_id)
                )
                
                # Check for children in the tree dict
                if tag_id in tree:
                    _traverse(tree[tag_id], tree, indent + 1)

        _traverse(root_nodes, tree_data)
        self._console.print(table)


def create_tag_cli_commands(tag_manager: Optional[TagManager] = None) -> click.Group:
    """
    Creates a Click group containing CLI commands for tag management.

    Args:
        tag_manager: An optional TagManager instance. If None, a default one is created.

    Returns:
        A click.Group containing the tag commands.
    """
    if tag_manager is None:
        tag_manager = TagManager()

    @click.group("tags")
    def tags_group():
        """Commands related to tag management."""
        pass

    @tags_group.command()
    def list():
        """List all tags in the hierarchical tree."""
        tag_manager.print_tag_tree()

    @tags_group.command()
    @click.argument("name")
    @click.option("--parent", help="Name of the parent tag")
    def add(name: str, parent: Optional[str]):
        """Create a new tag."""
        try:
            tag_id = tag_manager.create_tag(name, parent)
            click.echo(f"Created tag '{name}' with ID {tag_id}")
        except Exception as e:
            click.echo(f"Error: {e}")

    @tags_group.command()
    @click.argument("query")
    @click.option("--limit", default=10, type=int, help="Max results")
    def search(query: str, limit: int):
        """Search for tags using fuzzy matching."""
        results = tag_manager.search_tags(query, limit)
        if results:
            for tag_id, name in results:
                click.echo(f"ID: {tag_id} - {name}")
        else:
            click.echo("No tags found matching query.")

    return tags_group