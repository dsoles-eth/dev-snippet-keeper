import sqlite3
import hashlib
import secrets
from datetime import datetime
from typing import List, Dict, Optional, Any
import click
from rich.console import Console
from rich.table import Table
from fuzzywuzzy import fuzz
from fuzzywuzzy import process

# Configuration constants
DEFAULT_DB_NAME = "snippets.sqlite"
DEFAULT_PASSWORD_SALT = b"dev_snippet_keeper_salt_2023"

console = Console()


def derive_key(password: str, salt: bytes) -> bytes:
    """Derives a 32-byte key from a password using PBKDF2-HMAC-SHA256."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        100000,
        dklen=32
    )


def xor_bytes(data: bytes, key: bytes) -> bytes:
    """Encrypts/Decrypts bytes using simple XOR with a repeating key."""
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def encrypt_content(content: str, password: str, salt: bytes) -> bytes:
    """Encrypts text content with a derived key."""
    key = derive_key(password, salt)
    data = content.encode("utf-8")
    iv = secrets.token_bytes(16)
    # Append IV to encrypted data for decryption later
    return iv + xor_bytes(data, key)


def decrypt_content(data: bytes, password: str, salt: bytes) -> Optional[str]:
    """Decrypts content from bytes."""
    try:
        if len(data) < 17:
            return None
        iv = data[:16]
        cipher_text = data[16:]
        key = derive_key(password, salt)
        decrypted = xor_bytes(cipher_text, key)
        return decrypted.decode("utf-8")
    except Exception:
        return None


class SnippetStorage:
    """Manages local SQLite database operations for storing and retrieving code snippets."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection: Optional[sqlite3.Connection] = None

    def init_connection(self) -> None:
        """Initializes the database connection and creates tables if they don't exist."""
        try:
            dir_path = os.path.dirname(self.db_path)
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
            
            self.connection = sqlite3.connect(self.db_path)
            cursor = self.connection.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS snippets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    language TEXT DEFAULT 'text',
                    content BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            self.connection.commit()
        except sqlite3.Error as e:
            console.print(f"[red]Database error: {e}[/red]")
            raise e

    def _get_cursor(self) -> sqlite3.Cursor:
        if not self.connection:
            self.init_connection()
        return self.connection.cursor()

    def store_snippet(
        self,
        title: str,
        description: str,
        content: str,
        language: str,
        password: str
    ) -> int:
        """Stores a new code snippet in the database."""
        try:
            salt = DEFAULT_PASSWORD_SALT
            encrypted = encrypt_content(content, password, salt)
            now = datetime.now().isoformat()
            
            cursor = self._get_cursor()
            cursor.execute("""
                INSERT INTO snippets (title, description, language, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (title, description, language, encrypted, now, now))
            self.connection.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            console.print(f"[red]Error storing snippet: {e}[/red]")
            return -1

    def get_snippet(self, id: int, password: str) -> Optional[Dict[str, Any]]:
        """Retrieves a snippet by ID, decrypting the content."""
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT id, title, description, language, content, created_at, updated_at FROM snippets WHERE id = ?", (id,))
            row = cursor.fetchone()
            if not row:
                return None

            salt = DEFAULT_PASSWORD_SALT
            content_bytes = row[4]
            decrypted_content = decrypt_content(content_bytes, password, salt)
            
            return {
                "id": row[0],
                "title": row[1],
                "description": row[2],
                "language": row[3],
                "content": decrypted_content,
                "created_at": row[5],
                "updated_at": row[6]
            }
        except sqlite3.Error as e:
            console.print(f"[red]Error retrieving snippet: {e}[/red]")
            return None

    def list_snippets(self) -> List[Dict[str, Any]]:
        """Lists all snippet metadata without decrypting content."""
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT id, title, description, language, created_at FROM snippets")
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "title": r[1],
                    "description": r[2],
                    "language": r[3],
                    "created_at": r[4]
                } for r in rows
            ]
        except sqlite3.Error as e:
            console.print(f"[red]Error listing snippets: {e}[/red]")
            return []

    def delete_snippet(self, id: int) -> bool:
        """Deletes a snippet by ID."""
        try:
            cursor = self._get_cursor()
            cursor.execute("DELETE FROM snippets WHERE id = ?", (id,))
            self.connection.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            console.print(f"[red]Error deleting snippet: {e}[/red]")
            return False

    def search_snippets(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Searches snippets by title or description using fuzzy matching."""
        try:
            cursor = self._get_cursor()
            cursor.execute("SELECT id, title, description, language, created_at FROM snippets")
            rows = cursor.fetchall()
            
            snippets_list = [
                {
                    "id": r[0],
                    "title": r[1],
                    "description": r[2],
                    "language": r[3],
                    "created_at": r[4]
                } for r in rows
            ]
            
            search_texts = [f"{s['title']} {s['description']}" for s in snippets_list]
            scores = [fuzz.partial_ratio(query.lower(), text.lower()) for text in search_texts]
            
            results = []
            for i, score in enumerate(scores):
                if score > 50:  # Threshold for relevance
                    snippets_list[i]["score"] = score
                    results.append(snippets_list[i])
            
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]
        except sqlite3.Error as e:
            console.print(f"[red]Error searching snippets: {e}[/red]")
            return []


def _pass_storage(func):
    """Decorator to pass SnippetStorage instance to Click commands."""
    @click.pass_context
    def wrapper(ctx, *args, **kwargs):
        storage = ctx.obj.get("storage")
        if not storage:
            storage = SnippetStorage(ctx.obj["db_path"])
            ctx.obj["storage"] = storage
        return func(storage, *args, **kwargs)
    return wrapper


@click.group()
@click.option("--db-path", default="~/.snippet_keeper/snippets.sqlite", help="Path to the SQLite database.")
@click.pass_context
def cli(ctx, db_path: str):
    """Dev Snippet Keeper: A privacy-focused CLI tool for storing code snippets."""
    db_path = click.get_path_helper(db_path)
    ctx.obj = {"db_path": db_path}


@cli.command()
@click.pass_obj
def init_storage(storage_obj: Dict):
    """Initialize the database connection."""
    try:
        storage = SnippetStorage(storage_obj["db_path"])
        storage.init_connection()
        console.print("[green]Database initialized successfully.[/green]")
    except Exception as e:
        console.print(f"[red]Failed to initialize database: {e}[/red]")


@cli.command()
@click.option("--title", prompt=True, help="Snippet title.")
@click.option("--language", prompt=True, default="text", help="Language tag (e.g., python, sql).")
@click.option("--desc", prompt=True, help="Snippet description.")
@click.option("--password", prompt=True, hide_input=True, help="Encryption password for content.")
@click.pass_obj
@click.pass_storage
def add(storage: SnippetStorage, obj: Dict, title: str, language: str, desc: str, password: str):
    """Add a new code snippet to storage."""
    try:
        console.print("[dim]Enter your code (type 'EOF' on a new line to finish):[/dim]")
        lines = []
        while True:
            try:
                line = input()
                if line.strip() == "EOF":
                    break
                lines.append(line)
            except EOFError:
                break
        content = "\n".join(lines)
        
        if not content.strip():
            console.print("[yellow]Warning: Snippet content is empty.[/yellow]")
            return

        snippet_id = storage.store_snippet(title, desc, content, language, password)
        if snippet_id > 0:
            console.print(f"[green]Snippet saved with ID: {snippet_id}[/green]")
        else:
            console.print("[red]Failed to save snippet.[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.option("--password", prompt=True, hide_input=True, help="Password to decrypt content.")
@click.pass_obj
@click.pass_storage
def show(storage: SnippetStorage, obj: Dict, password: str):
    """Display a snippet by ID."""
    try:
        snippet_id = Prompt.ask("Snippet ID", type=int)
        snippet = storage.get_snippet(snippet_id, password)
        if snippet:
            table = Table(title="Snippet Details")
            table.add_column("Key", style="cyan")
            table.add_column("Value", style="green")
            table.add_row("ID", str(snippet["id"]))
            table.add_row("Title", snippet["title"])
            table.add_row("Language", snippet["language"])
            table.add_row("Description", snippet["description"] or "N/A")
            table.add_row("Created", snippet["created_at"])
            table.add_row("Updated", snippet["updated_at"])
            table.add_row("Content", snippet["content"][:50] + "..." if len(snippet["content"]) > 50 else snippet["content"])
            console.print(table)
        else:
            console.print("[yellow]Snippet not found.[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.pass_obj
@click.pass_storage
def list_snippets(storage: SnippetStorage, obj: Dict):
    """List all stored snippets."""
    try:
        snippets = storage.list_snippets()
        if not snippets:
            console.print("[yellow]No snippets found.[/yellow]")
            return
        
        table = Table(title="Stored Snippets")
        table.add_column("ID", style="dim")
        table.add_column("Title", style="bold")
        table.add_column("Language", style="yellow")
        table.add_column("Description", style="green")
        
        for s in snippets:
            table.add_row(
                str(s["id"]),
                s["title"],
                s["language"],
                s["description"][:30] + "..." if len(str(s["description"])) > 30 else s["description"]
            )
        
        console.print(table)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.argument("query")
@click.option("--limit", default=10, help="Maximum number of results.")
@click.pass_obj
@click.pass_storage
def search(storage: SnippetStorage, obj: Dict, query: str, limit: int):
    """Search snippets using fuzzy matching."""
    try:
        results = storage.search_snippets(query, limit)
        if not results:
            console.print("[yellow]No matching snippets found.[/yellow]")
            return
        
        table = Table(title="Search Results")
        table.add_column("ID", style="dim")
        table.add_column("Match Score", style="bold magenta")
        table.add_column("Title", style="bold")
        table.add_column("Description", style="green")
        
        for r in results:
            table.add_row(
                str(r["id"]),
                f"{r['score']}%",
                r["title"],
                r["description"][:40] + "..." if len(str(r["description"])) > 40 else r["description"]
            )
        
        console.print(table)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.argument("id", type=int)
@click.pass_obj
@click.pass_storage
def delete(storage: SnippetStorage, obj: Dict, id: int):
    """Delete a snippet by ID."""
    try:
        confirm = Prompt.ask("Are you sure you want to delete this snippet? [y/N]")
        if confirm.lower() != "y":
            console.print("[yellow]Cancelled.[/yellow]")
            return
        
        if storage.delete_snippet(id):
            console.print(f"[green]Snippet {id} deleted successfully.[/green]")
        else:
            console.print("[red]Snippet not found or could not be deleted.[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")