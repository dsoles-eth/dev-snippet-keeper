import json
import sqlite3
import os
import shutil
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from fuzzywuzzy import fuzz

console = Console()

SnippetData = Dict[str, Any]


def validate_snippet_data(data: List[SnippetData]) -> bool:
    """
    Validates that the list of snippets contains the required fields.

    Args:
        data: A list of dictionaries representing snippets.

    Returns:
        True if all snippets are valid, False otherwise.
    """
    required_fields = {'id', 'title', 'content', 'language', 'tags'}
    for i, snippet in enumerate(data):
        if not isinstance(snippet, dict):
            console.print(f"[red]Error[/red]: Snippet at index {i} is not a dictionary.")
            return False
        missing_fields = required_fields - set(snippet.keys())
        if missing_fields:
            console.print(f"[red]Error[/red]: Snippet at index {i} missing fields: {missing_fields}")
            return False
    return True


def deduplicate_snippets(snippets: List[SnippetData], threshold: int = 80) -> List[SnippetData]:
    """
    Removes duplicate snippets based on fuzzy string matching of titles and content.

    Args:
        snippets: A list of snippet dictionaries.
        threshold: Fuzzy matching score threshold (0-100).

    Returns:
        A new list of snippets with duplicates removed.
    """
    if not snippets:
        return snippets

    unique_snippets: List[SnippetData] = []
    seen_content_hashes: List[str] = []

    try:
        for snippet in snippets:
            content_match = False
            for seen_hash in seen_content_hashes:
                # Simple hash comparison for content is safer, but using fuzzywuzzy as requested
                score = fuzz.ratio(str(snippet.get('content', '')), seen_hash)
                if score >= threshold:
                    content_match = True
                    break
            
            # Also check title
            if not content_match:
                for title_hash in [s.get('title', '') for s in unique_snippets]:
                    score = fuzz.ratio(snippet.get('title', ''), title_hash)
                    if score >= threshold:
                        content_match = True
                        break

            if not content_match:
                unique_snippets.append(snippet)
                seen_content_hashes.append(snippet.get('content', ''))
                
            # Check title specifically for duplicates
            if not content_match:
                for s in unique_snippets:
                    if s.get('title') == snippet.get('title') and s.get('language') == snippet.get('language'):
                        content_match = True
                        break
            
            if not content_match:
                unique_snippets.append(snippet)
                seen_content_hashes.append(snippet.get('content', ''))

        return unique_snippets

    except Exception as e:
        console.print(f"[red]Error during deduplication:[/red] {e}")
        return snippets


def export_snippets_to_json(snippets: List[SnippetData], output_path: str) -> None:
    """
    Exports a list of snippets to a JSON file.

    Args:
        snippets: A list of snippet dictionaries.
        output_path: The file path where the JSON will be saved.
    """
    output_file = Path(output_path)
    
    try:
        if not validate_snippet_data(snippets):
            console.print("[red]Validation failed.[/red] Snippets not exported.")
            return

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(snippets, f, indent=2, ensure_ascii=False)
        
        console.print(f"[green]Successfully exported {len(snippets)} snippets to {output_path}[/green]")

    except PermissionError:
        console.print(f"[red]Permission denied:[/red] Cannot write to {output_path}")
    except IOError as e:
        console.print(f"[red]IO Error:[/red] {e}")
    except Exception as e:
        console.print(f"[red]Unexpected error during export:[/red] {e}")


def export_db_to_json(db_path: str, output_path: str) -> None:
    """
    Exports all snippets from a SQLite database to a JSON file.

    Args:
        db_path: The path to the SQLite database file.
        output_path: The path for the output JSON file.
    """
    connection: Optional[sqlite3.Connection] = None
    try:
        if not os.path.exists(db_path):
            console.print(f"[red]Database file not found:[/red] {db_path}")
            return

        connection = sqlite3.connect(db_path)
        cursor = connection.cursor()
        
        console.print("[yellow]Reading snippets from database...[/yellow]")
        cursor.execute("SELECT id, title, content, language, tags, created_at FROM snippets")
        rows = cursor.fetchall()

        snippets: List[SnippetData] = []
        for row in rows:
            snippets.append({
                'id': row[0],
                'title': row[1],
                'content': row[2],
                'language': row[3],
                'tags': row[4],
                'created_at': row[5]
            })

        export_snippets_to_json(snippets, output_path)

    except sqlite3.Error as e:
        console.print(f"[red]Database error:[/red] {e}")
    except Exception as e:
        console.print(f"[red]Unexpected error during DB export:[/red] {e}")
    finally:
        if connection:
            connection.close()


def import_snippets_from_json(input_path: str, skip_duplicates: bool = True) -> Tuple[int, List[SnippetData]]:
    """
    Imports snippets from a JSON file.

    Args:
        input_path: The path to the input JSON file.
        skip_duplicates: Whether to remove duplicates during import.

    Returns:
        A tuple of (number_of_skipped_dups, list_of_valid_snippets).
    """
    input_file = Path(input_path)
    
    try:
        if not input_file.exists():
            console.print(f"[red]File not found:[/red] {input_path}")
            return (0, [])

        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, list):
            console.print("[red]Invalid JSON format:[/red] Expected a list of snippets.")
            return (0, [])

        if not validate_snippet_data(data):
            return (0, [])

        skipped = 0
        if skip_duplicates:
            console.print("[yellow]Deduplicating snippets...[/yellow]")
            data = deduplicate_snippets(data)

        console.print(f"[green]Imported {len(data)} snippets from {input_path}[/green]")
        return (skipped, data)

    except json.JSONDecodeError as e:
        console.print(f"[red]JSON decode error:[/red] {e}")
        return (0, [])
    except Exception as e:
        console.print(f"[red]Unexpected error during import:[/red] {e}")
        return (0, [])


def import_snippets_to_sqlite(db_path: str, snippets: List[SnippetData], skip_duplicates: bool = True) -> int:
    """
    Imports a list of snippets into a SQLite database, handling ID conflicts.

    Args:
        db_path: The path to the SQLite database file.
        snippets: A list of snippet dictionaries.
        skip_duplicates: Whether to skip snippets with existing IDs.

    Returns:
        Number of snippets successfully added.
    """
    connection: Optional[sqlite3.Connection] = None
    added_count = 0

    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        connection = conn
        
        cursor = connection.cursor()
        
        console.print("[yellow]Creating table if not exists...[/yellow]")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS snippets (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                language TEXT,
                tags TEXT,
                created_at TIMESTAMP
            )
        ''')

        console.print("[yellow]Importing snippets...[/yellow]")
        for snippet in snippets:
            try:
                # Check existing ID
                cursor.execute('SELECT COUNT(*) FROM snippets WHERE id = ?', (snippet['id'],))
                count = cursor.fetchone()[0]

                if count > 0:
                    if skip_duplicates:
                        continue
                    # Update if not skipping duplicates
                    cursor.execute('''
                        UPDATE snippets SET title=?, content=?, language=?, tags=?, created_at=? 
                        WHERE id=?
                    ''', (
                        snippet['title'],
                        snippet['content'],
                        snippet['language'],
                        snippet['tags'],
                        snippet['created_at'],
                        snippet['id']
                    ))
                else:
                    cursor.execute('''
                        INSERT INTO snippets (id, title, content, language, tags, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        snippet['id'],
                        snippet['title'],
                        snippet['content'],
                        snippet['language'],
                        snippet['tags'],
                        snippet['created_at']
                    ))
                added_count += 1
            except sqlite3.IntegrityError:
                console.print(f"[yellow]Skipping snippet ID {snippet.get('id')} due to constraint violation[/yellow]")
                continue

        connection.commit()
        console.print(f"[green]Successfully imported {added_count} snippets into {db_path}[/green]")

    except sqlite3.Error as e:
        console.print(f"[red]Database error:[/red] {e}")
        if connection:
            connection.rollback()
    except Exception as e:
        console.print(f"[red]Unexpected error during import:[/red] {e}")
        if connection:
            connection.rollback()
    finally:
        if connection:
            connection.close()
            
    return added_count


def export_collection_metadata(db_path: str, output_path: str) -> None:
    """
    Exports metadata (summary) about the collection to a JSON file.

    Args:
        db_path: The path to the SQLite database file.
        output_path: The path for the output JSON file.
    """
    connection: Optional[sqlite3.Connection] = None
    try:
        if not os.path.exists(db_path):
            console.print(f"[red]Database file not found:[/red] {db_path}")
            return

        connection = sqlite3.connect(db_path)
        cursor = connection.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM snippets")
        total_snippets = cursor.fetchone()[0]
        
        cursor.execute("SELECT DISTINCT language FROM snippets")
        languages = [row[0] for row in cursor.fetchall()]
        
        cursor.execute("SELECT COUNT(DISTINCT id) FROM snippets")
        unique_snippets = cursor.fetchone()[0]
        
        metadata = {
            'total_snippets': total_snippets,
            'unique_snippets': unique_snippets,
            'languages': languages,
            'generated_at': Path(output_path).strftime('%Y-%m-%d %H:%M')
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)

        console.print(f"[green]Exported collection metadata to {output_path}[/green]")

    except sqlite3.Error as e:
        console.print(f"[red]Database error:[/red] {e}")
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {e}")
    finally:
        if connection:
            connection.close()