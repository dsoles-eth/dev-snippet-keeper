![Python Version](https://img.shields.io/badge/Python-3.9+-blue.svg?logo=python)
![License](https://img.shields.io/badge/License-MIT-blue.svg)
![GitHub Stars](https://img.shields.io/github/stars/your-username/dev-snippet-keeper?style=social)

# Dev Snippet Keeper

A privacy-focused command-line interface (CLI) tool for storing, searching, and inserting reusable code snippets locally. Built with Python, `dev-snippet-keeper` eliminates the need for cloud-based gists by keeping your code safe within an encrypted SQLite database on your machine. Perfect for developers who prioritize security and offline access.

## Features

*   **Local & Encrypted Storage:** All snippets are stored securely in a local SQLite database with encryption support.
*   **Fuzzy Search:** Quickly locate snippets using fuzzy matching algorithms against code content, tags, or descriptions.
*   **Rich CLI Interface:** Built with `Rich` for beautiful, readable output and interactive prompts.
*   **Clipboard Integration:** One-command copying of snippets directly to your OS clipboard.
*   **Syntax Validation:** Ensures code snippets are syntactically correct before saving to prevent corruption.
*   **Hierarchical Tagging:** Organize snippets using a flexible tag system for advanced filtering.
*   **Export & Import:** Seamlessly back up your collection to JSON or import snippets from external tools.

## Installation

You can install the package directly from PyPI using pip:

```bash
pip install dev-snippet-keeper
```

**Requirements:**
*   Python 3.9+
*   pip

## Quick Start

Here is a typical workflow to get you started:

```bash
# Initialize the local database (first time only)
dev-snippet-keeper init

# Add a Python function snippet
dev-snippet-keeper add \
  --content "def hello(name): return f'Hello {name}'" \
  --lang python \
  --tags python,utils,greeting

# Search for a snippet
dev-snippet-keeper search "hello"

# Copy a snippet to your clipboard
dev-snippet-keeper get --id 1 --copy
```

## Usage

The CLI offers a variety of commands to manage your code repository. Run `dev-snippet-keeper --help` to see all available options.

### Managing Snippets

**Add a new snippet:**

```bash
dev-snippet-keeper add --content "def factorial(n): return 1 if n <= 1 else n * factorial(n-1)" --lang python --tags math,recursion
```

**List all snippets:**

```bash
dev-snippet-keeper list --all
```

**List snippets by tag:**

```bash
dev-snippet-keeper list --tag python
```

### Searching and Retrieving

**Find snippets:**

```bash
# Fuzzy search across title, tags, and code
dev-snippet-keeper search "math"

# Search by exact ID
dev-snippet-keeper search --id 102
```

**Retrieve and Copy:**

```bash
# Retrieve and output to terminal
dev-snippet-keeper get --id 102

# Retrieve and copy to system clipboard automatically
dev-snippet-keeper get --id 102 --copy
```

### Data Management

**Export your collection:**

```bash
dev-snippet-keeper export --format json --output my_snippets.json
```

**Import from a JSON file:**

```bash
dev-snippet-keeper import --file my_snippets.json
```

## Architecture

The project is modularized to ensure maintainability and extensibility.

| Module | Responsibility |
| :--- | :--- |
| **snippet_storage** | Handles CRUD operations for storing code snippets in a local encrypted SQLite database. |
| **fuzzy_search** | Implements fuzzy search algorithms to find snippets by tags, keywords, or code content. |
| **cli_interface** | Uses Click to provide user-friendly commands for adding, listing, and retrieving snippets. |
| **clipboard_manager** | Integrates with the OS clipboard to copy selected snippets automatically to the user's clipboard. |
| **snippet_validator** | Ensures code snippets are valid before saving, checking for syntax errors in specific languages. |
| **tag_system** | Manages hierarchical tagging for better organization and filtering of snippets. |
| **export_utils** | Allows exporting collections of snippets to JSON or importing snippets from other tools. |

## Contributing

Contributions are welcome! Here is how you can help:

1.  Fork the repository.
2.  Create a feature branch (`git checkout -b feature/AmazingFeature`).
3.  Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4.  Push to the branch (`git push origin feature/AmazingFeature`).
5.  Open a Pull Request.

Please ensure your code passes linting and covers new functionality with tests.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.