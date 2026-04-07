import os
import sys
import sqlite3
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from fuzzywuzzy import process as fuzzy_process
from fuzzywuzzy import fuzz

# Global Rich Console for CLI output
console = Console()

DB_NAME = "snippets.db"
DEFAULT_DB_PATH = Path.home() / ".dev_snippet_keeper" / DB_NAME


class ClipboardManager:
    """
    Manages code snippets storage, retrieval, and clipboard operations.

    Attributes:
        db_path (Path): Path to the SQLite database file.

    Methods:
        init_db: Initializes the database schema if it doesn't exist.
        add_snippet: Adds a new snippet to the database.
        get_snippets: Retrieves snippets based on search criteria.
        delete_snippet: Removes a snippet from the database.
        copy_to_clipboard: Copies snippet content to the OS clipboard.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the ClipboardManager with a database path.

        Args:
            db_path: Optional path to the database. Defaults to ~/.dev_snippet_keeper/snippets.db.
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self._ensure_db_dir()

    def _ensure_db_dir(self) -> None:
        """
        Ensure the directory for the database file exists.
        
        Creates the parent directory if it does not exist.
        """
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            console.print(f"[red]Error creating directory: {e}[/red]")
            raise e

    def _connect(self) -> sqlite3.Connection:
        """
        Establish a connection to the SQLite database.

        Returns:
            sqlite3.Connection: A database connection object.

        Raises:
            sqlite3.Error: If the connection fails.
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            console.print(f"[red]Database connection error: {e}[/red]")
            raise e

    def init_db(self) -> None:
        """
        Initialize the database schema with tables for snippets and tags.
        """
        try:
            with self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS snippets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        tags TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.commit()
            console.print("[green]Database initialized successfully.[/green]")
        except sqlite3.Error as e:
            console.print(f"[red]Failed to initialize database: {e}[/red]")
            raise e

    def add_snippet(self, title: str, content: str, tags: Optional[str] = None) -> int:
        """
        Add a new code snippet to the database.

        Args:
            title: The title of the snippet.
            content: The actual code content.
            tags: Optional comma-separated tags for categorization.

        Returns:
            int: The ID of the newly created snippet.
        """
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO snippets (title, content, tags)
                    VALUES (?, ?, ?)
                    """,
                    (title, content, tags)
                )
                conn.commit()
                new_id = cursor.lastrowid
            return new_id
        except sqlite3.Error as e:
            console.print(f"[red]Failed to add snippet: {e}[/red]")
            raise e

    def get_snippets(self, query: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Retrieve snippets from the database, optionally filtering by search query.

        Args:
            query: Search string for fuzzy matching on title or tags.
            limit: Maximum number of results to return.

        Returns:
            List[Dict[str, Any]]: List of snippet dictionaries.
        """
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    SELECT id, title, content, tags, created_at, updated_at
                    FROM snippets
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,)
                )
                rows = cursor.fetchall()
                
                results = []
                for row in rows:
                    item = dict(row)
                    
                    # Fuzzy search filtering if query is provided
                    if query:
                        title_score = fuzz.ratio(item['title'].lower(), query.lower())
                        tags_score = fuzz.ratio((item['tags'] or "").lower(), query.lower())
                        best_score = max(title_score, tags_score)
                        
                        if best_score < 50:
                            continue
                        item['score'] = best_score

                    results.append(item)
                return results
        except sqlite3.Error as e:
            console.print(f"[red]Failed to retrieve snippets: {e}[/red]")
            raise e

    def delete_snippet(self, snippet_id: int) -> bool:
        """
        Delete a snippet by ID.

        Args:
            snippet_id: The unique identifier of the snippet to delete.

        Returns:
            bool: True if deleted successfully, False otherwise.
        """
        try:
            with self._connect() as conn:
                cursor = conn.execute("DELETE FROM snippets WHERE id = ?", (snippet_id,))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            console.print(f"[red]Failed to delete snippet: {e}[/red]")
            raise e

    def set_clipboard_content(self, text: str) -> None:
        """
        Copy text content to the operating system clipboard.

        Args:
            text: The text to copy.

        Raises:
            RuntimeError: If clipboard access is not possible on this platform.
        """
        platform = sys.platform
        try:
            if platform.startswith("linux"):
                # Check for xclip or xsel
                try:
                    subprocess.run(["which", "xclip"], check=True, capture_output=True)
                    cmd = ["xclip", "-selection", "clipboard"]
                    subprocess.run(cmd, input=text, text=True, check=True, timeout=5)
                    return
                except subprocess.CalledProcessError:
                    pass
                
                try:
                    subprocess.run(["which", "xsel"], check=True, capture_output=True)
                    cmd = ["xsel", "--clipboard", "--input"]
                    subprocess.run(cmd, input=text, text=True, check=True, timeout=5)
                    return
                except subprocess.CalledProcessError:
                    pass
                    
                # Fallback to wl-copy for Wayland
                try:
                    subprocess.run(["which", "wl-copy"], check=True, capture_output=True)
                    cmd = ["wl-copy"]
                    subprocess.run(cmd, input=text, text=True, check=True, timeout=5)
                    return
                except subprocess.CalledProcessError:
                    raise RuntimeError("No supported clipboard tool found on Linux (xclip, xsel, wl-copy).")
                    
            elif platform.startswith("darwin"):
                cmd = ["pbcopy"]
                subprocess.run(cmd, input=text, text=True, check=True, timeout=5)
                
            elif platform == "win32":
                # Use PowerShell for Windows to handle multiline text safely
                temp_file_path = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8")
                try:
                    temp_file_path.write(text)
                    temp_file_path.close()
                    # PowerShell command to read temp file content and set clipboard
                    ps_command = f'[System.IO.File]::ReadAllText("{temp_file_path.name}") | Set-Clipboard'
                    subprocess.run(
                        ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
                        check=True,
                        timeout=5
                    )
                except subprocess.SubprocessError as e:
                    raise RuntimeError(f"Failed to write to clipboard on Windows: {e}")
                finally:
                    if os.path.exists(temp_file_path.name):
                        try:
                            os.unlink(temp_file_path.name)
                        except OSError:
                            pass
            else:
                raise RuntimeError(f"Unsupported platform: {platform}")
                
        except subprocess.TimeoutExpired:
            console.print("[red]Clipboard operation timed out.[/red]")
            raise e
        except Exception as e:
            console.print(f"[red]Clipboard error: {e}[/red]")
            raise e

    def get_clipboard_content(self) -> str:
        """
        Read content from the operating system clipboard.

        Returns:
            str: The current content of the clipboard.

        Raises:
            RuntimeError: If clipboard access is not possible on this platform.
        """
        platform = sys.platform
        try:
            if platform.startswith("linux"):
                try:
                    subprocess.run(["which", "xclip"], check=True, capture_output=True)
                    cmd = ["xclip", "-selection", "clipboard", "-o"]
                    return subprocess.check_output(cmd, text=True, timeout=5)
                except subprocess.CalledProcessError:
                    pass
                try:
                    subprocess.run(["which", "xsel"], check=True, capture_output=True)
                    cmd = ["xsel", "--clipboard", "--output"]
                    return subprocess.check_output(cmd, text=True, timeout=5)
                except subprocess.CalledProcessError:
                    pass
                try:
                    subprocess.run(["which", "wl-paste"], check=True, capture_output=True)
                    cmd = ["wl-paste"]
                    return subprocess.check_output(cmd, text=True, timeout=5)
                except subprocess.CalledProcessError:
                    raise RuntimeError("No supported clipboard tool found on Linux (xclip, xsel, wl-paste).")
            elif platform.startswith("darwin"):
                return subprocess.check_output(["pbpaste"], text=True, timeout=5)
            elif platform == "win32":
                return subprocess.check_output(
                    ["powershell", "-Command", "Get-Clipboard"],
                    text=True,
                    timeout=5
                )
            else:
                raise RuntimeError(f"Unsupported platform: {platform}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Clipboard read timed out.")
        except Exception as e:
            raise RuntimeError(f"Clipboard read error: {e}")


# Define Click Commands
@click.group()
def cli():
    """Dev Snippet Keeper - CLI tool for storing and reusing code snippets."""
    pass

@cli.command()
@click.argument("title")
@click.argument("content", type=click.STRING, nargs=-1)
@click.option("--tags", "-t", help="Comma-separated tags")
def add(title: str, content: List[str], tags: Optional[str]) -> None:
    """
    Add a new snippet to the keeper.
    
    Title is the first argument. Content can follow as arguments or pasted after the title.
    """
    manager = ClipboardManager()
    manager.init_db()
    
    if not content:
        console.print("[yellow]No content provided. Please pipe or type content.[/yellow]")
        return

    full_content = " ".join(content)
    snippet_id = manager.add_snippet(title, full_content, tags)
    console.print(f"[green]Snippet added with ID: {snippet_id}[/green]")

@cli.command()
@click.option("--query", "-q", help="Search query for fuzzy matching")
@click.option("--limit", "-l", default=10, help="Maximum results")
def list_snippets(query: str, limit: int) -> None:
    """
    List existing snippets with optional fuzzy search.
    """
    manager = ClipboardManager()
    manager.init_db()
    
    snippets = manager.get_snippets(query=query, limit=limit)
    
    if not snippets:
        console.print("[yellow]No snippets found matching criteria.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim", width=3)
    table.add_column("Title")
    table.add_column("Tags")
    table.add_column("Created")
    table.add_column("Score", justify="right", style="cyan")

    for s in snippets:
        tags = s['tags'] or ""
        created = s['created_at'].split()[0] if s.get('created_at') else "N/A"
        score = f"{s.get('score', 100)}" if s.get('score') else ""
        table.add_row(str(s['id']), s['title'], tags, created, score)

    console.print(table)

@cli.command()
@click.argument("id", type=int)
@click.option("--copy/--no-copy", default=True, help="Copy snippet to clipboard")
def get(id: int, copy: bool) -> None:
    """
    Retrieve a specific snippet by ID.
    """
    manager = ClipboardManager()
    snippets = manager.get_snippets(limit=100)
    
    found = next((s for s in snippets if s['id'] == id), None)
    
    if not found:
        console.print(f"[red]Snippet ID {id} not found.[/red]")
        return

    console.print(Panel(found['content'], title=f"Snippet ID: {id}", subtitle=found['title']))

    if copy:
        try:
            manager.set_clipboard_content(found['content'])
            console.print(f"[green]Snippet copied to clipboard successfully.[/green]")
        except RuntimeError as e:
            console.print(f"[red]Failed to copy to clipboard: {e}[/red]")


@cli.command()
@click.argument("id", type=int)
def delete(id: int) -> None:
    """
    Delete a snippet by ID.
    """
    manager = ClipboardManager()
    if manager.delete_snippet(id):
        console.print(f"[green]Snippet ID {id} deleted.[/green]")
    else:
        console.print(f"[red]Snippet ID {id} not found.[/red]")

# Note: Do not include `if __name__ == '__main__': cli()` here
# This module is designed to be imported by a CLI entry point script (e.g., main.py)
# or used as a library, adhering to the constraint of not including the entry point block
# unless this file is explicitly the CLI entry point.