import click
import sqlite3
from typing import List, Tuple, Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from fuzzywuzzy import fuzz

DB_PATH: str = "snippets.db"
CONSOLE: Console = Console()

def _initialize_database() -> None:
    """
    Initialize the SQLite database and create the snippets table if it does not exist.
    """
    try:
        conn: sqlite3.Connection = sqlite3.connect(DB_PATH)
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS snippets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                tags TEXT,
                code TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        CONSOLE.print(f"[red]Database initialization error:[/red] {e}")
        raise


def _add_snippet(name: str, tags: str, code: str) -> bool:
    """
    Add a new code snippet to the database.

    Args:
        name: The unique name identifier for the snippet.
        tags: Comma-separated tags for the snippet.
        code: The actual code content to be stored.

    Returns:
        bool: True if successful, False otherwise.
    """
    try:
        conn: sqlite3.Connection = sqlite3.connect(DB_PATH)
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO snippets (name, tags, code) VALUES (?, ?, ?)",
            (name, tags, code)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError as e:
        CONSOLE.print(f"[red]Error:[/red] Snippet '{name}' already exists. ({e})")
        return False
    except sqlite3.Error as e:
        CONSOLE.print(f"[red]Database error:[/red] {e}")
        return False


def _get_snippet(name: str) -> Optional[Tuple[int, str, str, str, str]]:
    """
    Retrieve a specific snippet by name.

    Args:
        name: The unique name identifier of the snippet.

    Returns:
        tuple or None: Snippet details if found, None otherwise.
    """
    try:
        conn: sqlite3.Connection = sqlite3.connect(DB_PATH)
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, tags, code, created_at FROM snippets WHERE name = ?",
            (name,)
        )
        result: Tuple = cursor.fetchone()
        conn.close()
        return result
    except sqlite3.Error as e:
        CONSOLE.print(f"[red]Database error:[/red] {e}")
        return None


def _list_snippets() -> List[Tuple[int, str, str, str]]:
    """
    Retrieve all snippets sorted by creation date.

    Returns:
        list: List of tuples containing id, name, tags, and code.
    """
    try:
        conn: sqlite3.Connection = sqlite3.connect(DB_PATH)
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, tags, code FROM snippets ORDER BY created_at DESC"
        )
        results: List[Tuple] = cursor.fetchall()
        conn.close()
        return results
    except sqlite3.Error as e:
        CONSOLE.print(f"[red]Database error:[/red] {e}")
        return []


def _search_snippets(query: str) -> List[Tuple[int, str, str, str]]:
    """
    Search snippets using fuzzy matching on the name and tags.

    Args:
        query: The search query string.

    Returns:
        list: List of matching snippet details.
    """
    try:
        conn: sqlite3.Connection = sqlite3.connect(DB_PATH)
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute("SELECT id, name, tags, code FROM snippets")
        all_snippets: List[Tuple] = cursor.fetchall()
        conn.close()
        
        matches: List[Tuple] = []
        for row in all_snippets:
            name: str = row[1]
            tags: str = row[2]
            score: int = max(fuzz.partial_ratio(query, name), fuzz.partial_ratio(query, tags))
            if score > 50:
                matches.append(row)
        
        return matches
    except sqlite3.Error as e:
        CONSOLE.print(f"[red]Database error:[/red] {e}")
        return []


def _delete_snippet(name: str) -> bool:
    """
    Delete a snippet by name.

    Args:
        name: The unique name identifier of the snippet.

    Returns:
        bool: True if deleted, False otherwise.
    """
    try:
        conn: sqlite3.Connection = sqlite3.connect(DB_PATH)
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM snippets WHERE name = ?",
            (name,)
        )
        conn.commit()
        if cursor.rowcount > 0:
            conn.close()
            return True
        conn.close()
        return False
    except sqlite3.Error as e:
        CONSOLE.print(f"[red]Database error:[/red] {e}")
        return False


@click.group()
def cli() -> None:
    """Dev Snippet Keeper: Store, search, and retrieve code snippets locally."""
    _initialize_database()


@cli.command()
@click.argument('name')
@click.option('--tags', default='', help='Comma-separated tags')
@click.option('--code', '-c', help='Snippet code content')
@cli.pass_context
def add(ctx: click.Context, name: str, tags: str, code: str) -> None:
    """
    Add a new code snippet.

    NAME: Unique identifier for the snippet.
    """
    if not code:
        # Read code from stdin if not provided via -c
        code = ctx.get_parameter_source().get('code') if ctx.get_parameter_source().get('code') else click.prompt('Code content')
    
    success: bool = _add_snippet(name, tags, code)
    if success:
        CONSOLE.print(f"[green]Snippet '{name}' added successfully.[/green]")
    else:
        CONSOLE.print(f"[red]Failed to add snippet '{name}'.[/red]")


@cli.command()
def list_snippets() -> None:
    """List all stored snippets."""
    snippets: List[Tuple] = _list_snippets()
    
    if not snippets:
        CONSOLE.print(Panel("[yellow]No snippets found.[/yellow]", title="List"))
        return

    table: Table = Table(title="Snippet List")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="blue")
    table.add_column("Tags", style="magenta")
    table.add_column("Code", style="green")

    for row in snippets:
        table.add_row(str(row[0]), row[1], row[2], row[3][:50] + "...")

    CONSOLE.print(table)


@cli.command()
@click.argument('query')
def search(query: str) -> None:
    """
    Search for snippets using fuzzy matching.

    QUERY: The keyword or phrase to search for.
    """
    matches: List[Tuple] = _search_snippets(query)
    
    if not matches:
        CONSOLE.print(Panel(f"[yellow]No matches found for '{query}'.[/yellow]", title="Search"))
        return

    table: Table = Table(title="Search Results")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="blue")
    table.add_column("Tags", style="magenta")
    table.add_column("Score", style="yellow")

    conn: sqlite3.Connection = sqlite3.connect(DB_PATH)
    cursor: sqlite3.Cursor = conn.cursor()
    for row in matches:
        cursor.execute("SELECT code FROM snippets WHERE id = ?", (row[0],))
        code: str = cursor.fetchone()[0]
        score: int = max(fuzz.partial_ratio(query, row[1]), fuzz.partial_ratio(query, row[2]))
        table.add_row(str(row[0]), row[1], row[2], str(score))
    conn.close()

    CONSOLE.print(table)


@cli.command()
@click.argument('name')
def get(name: str) -> None:
    """
    Retrieve a specific snippet.

    NAME: Unique identifier of the snippet to retrieve.
    """
    result: Optional[Tuple] = _get_snippet(name)
    if result:
        panel: Panel = Panel(
            f"[bold blue]Name:[/bold blue] {result[1]}\n"
            f"[bold magenta]Tags:[/bold magenta] {result[2]}\n"
            f"[bold cyan]Created:[/bold cyan] {result[4]}\n"
            f"[bold green]Code:[/bold green]\n{result[3]}",
            title=f"Snippet: {result[1]}"
        )
        CONSOLE.print(panel)
    else:
        CONSOLE.print(Panel(f"[red]Snippet '{name}' not found.[/red]", title="Get"))


@cli.command()
@click.argument('name')
def delete(name: str) -> None:
    """
    Delete a specific snippet.

    NAME: Unique identifier of the snippet to delete.
    """
    success: bool = _delete_snippet(name)
    if success:
        CONSOLE.print(f"[green]Snippet '{name}' deleted successfully.[/green]")
    else:
        CONSOLE.print(f"[red]Snippet '{name}' not found or could not be deleted.[/red]")


if __name__ == '__main__':
    cli()