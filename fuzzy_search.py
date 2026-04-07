import sqlite3
import re
from typing import List, Dict, Any
from fuzzywuzzy.fuzz import fuzz
from rich.console import Console
from rich.text import Text

class SnippetSearcher:
    """
    Encapsulates logic for searching code snippets using fuzzy matching algorithms
    and formats results using the Rich library. Requires a valid SQLite database
    connection to the snippets table.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        """
        Initialize the search engine with a database connection.

        Args:
            connection: An active sqlite3.Connection object pointing to the
                        database containing the 'snippets' table.
        """
        self.conn = connection
        self.console = Console()
        if not self.conn:
            raise ValueError("Database connection cannot be None.")

    def _sanitize_query(self, query: str) -> str:
        """
        Sanitizes the search query to remove special characters for SQL safety 
        and fuzzy matching normalization.

        Args:
            query: The raw user input string.

        Returns:
            str: The sanitized and normalized query string.
        """
        if not query:
            return ""
        # Remove characters that might cause issues in SQL or matching
        clean_query = re.sub(r"[^a-zA-Z0-9\s\-]+", " ", query)
        return clean_query.strip()

    def search_snippets(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Executes a fuzzy search across the snippets table. It first filters using
        SQL LIKE for performance, then applies fuzzywuzzy scoring to rank results.

        Args:
            query: The string keyword to search for in title, content, and tags.
            limit: The maximum number of results to return.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing snippet data
                                  and a fuzzy match score.
        """
        if not isinstance(query, str):
            raise TypeError("Query must be a string")

        normalized_query = self._sanitize_query(query)
        if not normalized_query:
            return []

        try:
            results = []
            search_pattern = f"%{normalized_query}%"
            
            # Ensure connection is valid before executing
            cursor = self.conn.cursor()
            
            # Query the database for potential matches
            sql_statement = """
                SELECT id, title, content, tags 
                FROM snippets 
                WHERE title LIKE ? 
                   OR content LIKE ? 
                   OR tags LIKE ?
            """
            cursor.execute(sql_statement, (search_pattern, search_pattern, search_pattern))
            rows = cursor.fetchall()

            for row in rows:
                snippet_id, title, content, tags = row
                
                # Combine fields for a comprehensive search score
                combined_text = f"{title} {content} {tags}"
                
                # Calculate fuzzy match ratio (0-100)
                score = fuzz.ratio(normalized_query, combined_text)
                
                results.append({
                    "id": snippet_id,
                    "title": title,
                    "content": content,
                    "tags": tags,
                    "score": score
                })

            # Sort by score descending
            results.sort(key=lambda x: x["score"], reverse=True)
            
            return results[:limit]

        except sqlite3.DatabaseError as db_err:
            raise RuntimeError(f"SQLite error during search: {db_err}") from db_err
        except Exception as e:
            raise RuntimeError(f"Unexpected error during search: {e}") from e

    def display_search_results(self, results: List[Dict[str, Any]], query: str) -> None:
        """
        Formats and prints search results to the terminal using Rich styling.

        Args:
            results: The list of snippet results returned by search_snippets.
            query: The original query string for context in the output header.
        """
        if not results:
            text = Text()
            text.append(f"No snippets found matching \"{query}\".", style="italic grey")
            self.console.print(text)
            return

        output_text = Text()
        output_text.append(f"Search Results for \"{query}\":\n", style="bold blue")

        for i, snippet in enumerate(results, start=1):
            score = snippet.get("score", 0)
            title = snippet.get("title", "Untitled")
            tags = snippet.get("tags", "")
            
            # Build the result line
            output_text.append(f"{i}. ", style="bold")
            output_text.append(f"[{title}]", style="bold green")
            
            if tags:
                output_text.append(f" | Tags: {tags}", style="yellow")
            
            output_text.append(f"\n   Match Score: {score}%\n", style="dim")
            
            # Preview content
            content_preview = snippet.get("content", "")[:80]
            if len(snippet.get("content", "")) > 80:
                content_preview += "..."
            output_text.append(f"   {content_preview}\n", style="italic grey")
            output_text.append("-" * 40 + "\n", style="dim")

        self.console.print(output_text)