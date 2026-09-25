"""Bitmod CLI — command-line interface for Bitmod.

Usage:
    bitmod init                    Interactive first-time setup
    bitmod init --auto             Non-interactive setup with defaults
    bitmod doctor                  Check system health and dependencies
    bitmod ingest <file_or_dir>    Ingest files into the data index
    bitmod ingest -                Ingest from stdin
    bitmod query "question"        Query with cache stats
    bitmod serve                   Start local API server (auto-provisions if needed)
    bitmod proxy                   Start gateway proxy (reverse proxy to LLM providers)
    bitmod status                  Show system status
    bitmod cache stats             Show cache performance statistics
    bitmod cache recent            Show recently cached queries
    bitmod cache search "query"    Search cache for matching entries
    bitmod cache clear             Invalidate all cached answers
    bitmod migrate                 Run database migrations
    bitmod migrate --status        Show migration status
    bitmod migrate --target N      Migrate to specific version
    bitmod backup list             List backup sessions
    bitmod backup show <id>        Show session entries
    bitmod backup context <id>     Build context from session history
    bitmod backup export <id>      Export session to file
    bitmod backup import --file f  Import session from file
    bitmod backup delete <id>      Delete a session
    bitmod update                  Check for new versions
    bitmod completions <shell>     Generate shell completion script (bash/zsh/fish)

Global flags:
    --format json                  Machine-readable JSON output
    --quiet                        Suppress non-essential output
    --verbose                      Set log level to INFO
    --debug                        Set log level to DEBUG

All imports are lazy to keep startup under 100ms.
"""

from __future__ import annotations

import argparse
import json as _json_mod
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Output mode globals (set in main() from --format and --quiet flags)
# ---------------------------------------------------------------------------

_OUTPUT_FORMAT: str = "text"  # "text" or "json"
_QUIET: bool = False

# ---------------------------------------------------------------------------
# Color helpers (no external deps)
# ---------------------------------------------------------------------------


def _supports_color() -> bool:
    """Check if the terminal supports ANSI color codes."""
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    import os

    return os.getenv("NO_COLOR") is None and os.getenv("TERM") != "dumb"


_COLOR = _supports_color()

# Unicode symbols extracted for f-string compatibility (Python 3.10)
_CHECK = "\u2713"
_CROSS = "\u2717"
_WARN = "\u26a0"


def _c(code: str, text: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def _green(text: str) -> str:
    return _c("32", text)


def _yellow(text: str) -> str:
    return _c("33", text)


def _cyan(text: str) -> str:
    return _c("36", text)


def _dim(text: str) -> str:
    return _c("2", text)


def _bold(text: str) -> str:
    return _c("1", text)


def _red(text: str) -> str:
    return _c("31", text)


def _blue(text: str) -> str:
    return _c("38;5;69", text)


def _orange(text: str) -> str:
    return _c("38;5;208", text)


# ---------------------------------------------------------------------------
# Output helpers (JSON mode + quiet mode)
# ---------------------------------------------------------------------------


def _print(*args, **kwargs) -> None:
    """Print that respects --quiet flag. Use for non-essential output."""
    if not _QUIET:
        print(*args, **kwargs)


def _json_output(data: dict) -> None:
    """Emit a JSON object to stdout and exit. Used when --format json is set."""
    print(_json_mod.dumps(data, indent=2, default=str))


def _is_json() -> bool:
    return _OUTPUT_FORMAT == "json"


# ---------------------------------------------------------------------------
# Port availability check
# ---------------------------------------------------------------------------


def _check_port_available(host: str, port: int) -> bool:
    """Return True if the port is available. On failure, print an error with PID info."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        sock.connect((host if host != "0.0.0.0" else "127.0.0.1", port))  # noqa: S104
        sock.close()
    except (ConnectionRefusedError, OSError):
        return True
    # Port is in use — try to find the PID
    pid_info = ""
    try:
        import subprocess

        result = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=5)  # noqa: S603, S607
        if result.stdout.strip():
            pid_info = f" (PID: {result.stdout.strip().splitlines()[0]})"
    except Exception:  # noqa: S110
        pass
    print(f"{_red('x')} Port {port} is already in use{pid_info}.")
    print(f"  {_dim('Use -p/--port to specify a different port.')}")
    return False


# ---------------------------------------------------------------------------
# bitmod init
# ---------------------------------------------------------------------------


def _prompt(label: str, options: list[tuple[str, str]], default: int = 0) -> str:
    """Interactive prompt with numbered options. Returns the selected value."""
    print(f"\n  {_bold(label)}")
    for i, (value, desc) in enumerate(options):
        marker = _green(">") if i == default else " "
        num = _cyan(str(i + 1))
        print(f"    {marker} {num}) {value}  {_dim(desc)}")

    while True:
        try:
            choice = input(f"\n  Choose [{default + 1}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return options[default][0]
        if not choice:
            return options[default][0]
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx][0]
        except ValueError:
            pass
        print(f"    {_red('Invalid choice. Try again.')}")


def _prompt_str(label: str, default: str = "") -> str:
    """Prompt for a string value."""
    try:
        val = input(f"  {label} [{default}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return val or default


def _prompt_yn(label: str, default: bool = False) -> bool:
    """Prompt for yes/no. Returns True for yes."""
    hint = "Y/n" if default else "y/N"
    try:
        val = input(f"  {label} [{hint}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if not val:
        return default
    return val in ("y", "yes")


# Provider metadata used by both init wizard and _collect_api_keys
_LLM_PROVIDERS = [
    ("ollama", "Ollama", "Local inference, no API key needed"),
    ("anthropic", "Claude", "Anthropic (requires ANTHROPIC_API_KEY)"),
    ("openai", "GPT-4 / ChatGPT", "OpenAI (requires OPENAI_API_KEY)"),
    ("openai_compatible", "OpenAI-Compatible", "Groq, Together, vLLM, LM Studio, etc."),
    ("gemini", "Google Gemini", "Requires GEMINI_API_KEY"),
    ("xai", "Grok (xAI)", "Requires XAI_API_KEY"),
    ("mistral", "Mistral", "Requires MISTRAL_API_KEY"),
    ("azure_openai", "Azure OpenAI", "Requires AZURE_OPENAI_API_KEY + endpoint"),
    ("bedrock", "AWS Bedrock", "Uses AWS credentials (boto3)"),
    ("perplexity", "Perplexity", "Requires PERPLEXITY_API_KEY"),
    ("openrouter", "OpenRouter", "Requires OPENROUTER_API_KEY"),
    ("huggingface", "HuggingFace", "Requires HF_API_KEY"),
]

_MODEL_DEFAULTS = {
    "ollama": "llama3.2",
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "gemini": "gemini-2.0-flash",
    "xai": "grok-3",
    "mistral": "mistral-large-latest",
    "openai_compatible": "llama-3.3-70b-versatile",
    "azure_openai": "gpt-4o",
    "bedrock": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "perplexity": "llama-3.1-sonar-large-128k-online",
    "openrouter": "anthropic/claude-sonnet-4-20250514",
    "huggingface": "meta-llama/Llama-3.2-3B-Instruct",
}

# Map provider key -> (env var name, prompt label)
_API_KEY_MAP = {
    "anthropic": ("ANTHROPIC_API_KEY", "Anthropic API key"),
    "openai": ("OPENAI_API_KEY", "OpenAI API key"),
    "gemini": ("GEMINI_API_KEY", "Gemini API key"),
    "xai": ("XAI_API_KEY", "xAI API key"),
    "mistral": ("MISTRAL_API_KEY", "Mistral API key"),
    "azure_openai": ("AZURE_OPENAI_API_KEY", "Azure OpenAI API key"),
    "perplexity": ("PERPLEXITY_API_KEY", "Perplexity API key"),
    "openrouter": ("OPENROUTER_API_KEY", "OpenRouter API key"),
    "huggingface": ("HF_API_KEY", "HuggingFace API key"),
    "cohere": ("COHERE_API_KEY", "Cohere API key"),
}


def _collect_api_keys(provider: str) -> list[tuple[str, str]]:
    """Prompt for API keys/URLs for a provider. Returns list of (env_var, value) pairs."""
    pairs: list[tuple[str, str]] = []

    if provider == "openai_compatible":
        base_url = _prompt_str("Base URL (e.g. https://api.groq.com/openai/v1)", "")
        if base_url:
            pairs.append(("BITMOD_LLM_BASE_URL", base_url))
        key = _prompt_str("API key", "")
        if key:
            pairs.append(("BITMOD_LLM_API_KEY", key))
        return pairs

    if provider == "azure_openai":
        key = _prompt_str("Azure OpenAI API key", "")
        if key:
            pairs.append(("AZURE_OPENAI_API_KEY", key))
        endpoint = _prompt_str("Azure endpoint URL", "")
        if endpoint:
            pairs.append(("AZURE_OPENAI_ENDPOINT", endpoint))
        return pairs

    if provider == "bedrock":
        print(f"    {_dim('Uses AWS credentials from environment (AWS_ACCESS_KEY_ID, etc.)')}")
        return pairs

    if provider == "ollama":
        return pairs

    if provider in _API_KEY_MAP:
        env_var, label = _API_KEY_MAP[provider]
        key = _prompt_str(label, "")
        if key:
            pairs.append((env_var, key))

    return pairs


def _print_banner() -> None:
    """Print the Bitmod welcome banner with ASCII wordmark."""
    print()
    b, o = _blue, _orange
    print(f"  {b('██████╗ ██╗████████╗')}{o('███╗   ███╗ ██████╗ ██████╗')}")
    print(f"  {b('██╔══██╗██║╚══██╔══╝')}{o('████╗ ████║██╔═══██╗██╔══██╗')}")
    print(f"  {b('██████╔╝██║   ██║   ')}{o('██╔████╔██║██║   ██║██║  ██║')}")
    print(f"  {b('██╔══██╗██║   ██║   ')}{o('██║╚██╔╝██║██║   ██║██║  ██║')}")
    print(f"  {b('██████╔╝██║   ██║   ')}{o('██║ ╚═╝ ██║╚██████╔╝██████╔╝')}")
    print(f"  {b('╚═════╝ ╚═╝   ╚═╝   ')}{o('╚═╝     ╚═╝ ╚═════╝ ╚═════╝')}")
    print()
    print(f"  {_dim('Modular AI Data Infrastructure')}")
    print(f"  {_dim('Compute once, serve forever.')}")
    print()


def cmd_init(args: argparse.Namespace) -> int:
    """Create bitmod.yaml config and initialize database via interactive setup."""
    config_path = Path(args.config)

    # Check for --auto flag (non-interactive quick setup)
    if getattr(args, "auto", False):
        return _cmd_init_auto(args)

    if config_path.exists() and not args.force:
        print(f"{_yellow('!')} {config_path} already exists. Use --force to overwrite.")
        return 1

    _print_banner()
    print(f"{_bold('Bitmod Setup')}")
    print(f"{_dim('Configure your AI data infrastructure. Press Enter for defaults.')}")

    # --- LLM Provider ---
    llm = _prompt("LLM Provider", [(key, desc) for key, _display, desc in _LLM_PROVIDERS], default=0)

    # Model selection
    default_model = _MODEL_DEFAULTS.get(llm, "llama3.2")
    llm_model = _prompt_str("Model", default_model)

    # API keys for primary LLM
    env_pairs: list[tuple[str, str]] = _collect_api_keys(llm)

    # --- Fallback LLM ---
    use_fallback = _prompt_yn("Configure a fallback LLM?", default=False)
    fallback_llm = ""
    fallback_model = ""
    if use_fallback:
        # Build fallback list excluding the primary
        fallback_options = [(key, desc) for key, _display, desc in _LLM_PROVIDERS if key != llm]
        fallback_llm = _prompt("Fallback LLM", fallback_options, default=0)
        fallback_model = _prompt_str("Fallback model", _MODEL_DEFAULTS.get(fallback_llm, "llama3.2"))
        env_pairs.extend(_collect_api_keys(fallback_llm))

    # --- Embedding Provider ---
    embed = _prompt(
        "Embedding Provider",
        [
            ("ollama", "Ollama (nomic-embed-text, local, no API key)"),
            ("local", "Sentence Transformers (local, requires pip install)"),
            ("openai", "OpenAI text-embedding-3-small"),
            ("cohere", "Cohere embed-v4.0"),
        ],
        default=0,
    )

    embed_defaults = {
        "ollama": ("nomic-embed-text", "768"),
        "local": ("sentence-transformers/all-MiniLM-L6-v2", "384"),
        "openai": ("text-embedding-3-small", "1536"),
        "cohere": ("embed-v4.0", "1024"),
    }
    embed_model, embed_dims = embed_defaults.get(embed, ("nomic-embed-text", "768"))

    # Embedding provider API keys
    if embed in ("openai", "cohere"):
        env_pairs.extend(_collect_api_keys(embed))

    # --- Database Backend ---
    _local_db_options = [
        ("sqlite", "SQLite — zero config, auto-creates, best for dev/single-node"),
        ("postgresql", "PostgreSQL — needs URL, auto-creates tables + pgvector"),
        ("mysql", "MySQL — needs URL, auto-creates tables + FULLTEXT indexes"),
        ("mongodb", "MongoDB — needs URL, auto-creates collections"),
    ]
    _cloud_db_options = [
        ("aws_rds_pg", "AWS RDS PostgreSQL — managed, auto-creates tables + pgvector"),
        ("aws_rds_mysql", "AWS RDS MySQL — managed, auto-creates tables"),
        ("aws_aurora", "AWS Aurora PostgreSQL — serverless, auto-creates tables"),
        ("aws_documentdb", "AWS DocumentDB — managed, auto-creates collections"),
        ("azure_pg", "Azure PostgreSQL — managed, auto-creates tables + pgvector"),
        ("azure_mysql", "Azure MySQL — managed, auto-creates tables"),
        ("azure_cosmos", "Azure Cosmos DB — managed, auto-creates collections"),
        ("gcp_cloudsql_pg", "GCP Cloud SQL PostgreSQL — managed, auto-creates tables"),
        ("gcp_cloudsql_my", "GCP Cloud SQL MySQL — managed, auto-creates tables"),
        ("gcp_firestore", "GCP Firestore — managed, auto-creates collections"),
    ]
    db_options = list(_local_db_options)
    # Ask if user wants cloud options
    show_cloud = False
    try:
        _cloud_answer = input(f"\n  {_dim('Show cloud database options? [y/N]:')} ").strip().lower()
        show_cloud = _cloud_answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        pass
    if show_cloud:
        db_options.extend(_cloud_db_options)
    db_choice = _prompt("Database", db_options, default=0)

    # Map cloud choices to the actual backend adapter
    db_adapter_map = {
        "sqlite": "sqlite",
        "postgresql": "postgresql",
        "mysql": "mysql",
        "mongodb": "mongodb",
        "aws_rds_pg": "postgresql",
        "aws_rds_mysql": "mysql",
        "aws_aurora": "postgresql",
        "aws_documentdb": "mongodb",
        "azure_pg": "postgresql",
        "azure_mysql": "mysql",
        "azure_cosmos": "mongodb",
        "gcp_cloudsql_pg": "postgresql",
        "gcp_cloudsql_my": "mysql",
        "gcp_firestore": "mongodb",
    }
    db = db_adapter_map[db_choice]

    # Default connection URL hints per cloud choice
    db_url_defaults = {
        "postgresql": "postgresql://bitmod:password@localhost:5432/bitmod",
        "mysql": "mysql+pymysql://bitmod:password@localhost:3306/bitmod",
        "aws_rds_pg": "postgresql://bitmod:password@your-instance.region.rds.amazonaws.com:5432/bitmod",
        "aws_rds_mysql": "mysql+pymysql://bitmod:password@your-instance.region.rds.amazonaws.com:3306/bitmod",
        "aws_aurora": "postgresql://bitmod:password@your-cluster.cluster-xxx.region.rds.amazonaws.com:5432/bitmod",
        "azure_pg": "postgresql://bitmod:password@your-server.postgres.database.azure.com:5432/bitmod?sslmode=require",
        "azure_mysql": "mysql+pymysql://bitmod:password@your-server.mysql.database.azure.com:3306/bitmod?ssl_ca=/path/to/cert",
        "gcp_cloudsql_pg": "postgresql://bitmod:password@/bitmod?host=/cloudsql/project:region:instance",
        "gcp_cloudsql_my": "mysql+pymysql://bitmod:password@/bitmod?unix_socket=/cloudsql/project:region:instance",
    }
    mongodb_url_defaults = {
        "mongodb": "mongodb://localhost:27017",
        "aws_documentdb": "mongodb://bitmod:password@your-cluster.region.docdb.amazonaws.com:27017/?tls=true&retryWrites=false",
        "azure_cosmos": "mongodb://your-account:key@your-account.mongo.cosmos.azure.com:10255/?ssl=true&retrywrites=false",
        "gcp_firestore": "mongodb://localhost:27017",
    }

    db_url = ""
    mongodb_url = ""
    mongodb_db = ""
    if db == "postgresql" and db_choice != "sqlite":
        db_url = _prompt_str("Connection URL", db_url_defaults.get(db_choice, db_url_defaults["postgresql"]))
    elif db == "mysql":
        db_url = _prompt_str("Connection URL", db_url_defaults.get(db_choice, db_url_defaults["mysql"]))
    elif db == "mongodb":
        mongodb_url = _prompt_str("MongoDB URL", mongodb_url_defaults.get(db_choice, "mongodb://localhost:27017"))
        mongodb_db = _prompt_str("Database name", "bitmod")

    # --- Vector Store ---
    vector_store = _prompt(
        "Vector Store",
        [
            ("", "Use database backend (default — no extra service)"),
            ("chroma", "ChromaDB (local, file-based)"),
            ("qdrant", "Qdrant (requires server)"),
            ("pinecone", "Pinecone (cloud, requires API key)"),
        ],
        default=0,
    )

    vec_extra_lines: list[str] = []
    if vector_store == "chroma":
        chroma_path = _prompt_str("ChromaDB data path", "./chroma_data")
        vec_extra_lines.append(f"# chroma_path: {chroma_path}")
    elif vector_store == "qdrant":
        qdrant_url = _prompt_str("Qdrant URL", "http://localhost:6333")
        vec_extra_lines.append(f"# qdrant_url: {qdrant_url}")
        qdrant_key = _prompt_str("Qdrant API key (optional)", "")
        if qdrant_key:
            env_pairs.append(("BITMOD_QDRANT_API_KEY", qdrant_key))
    elif vector_store == "pinecone":
        pinecone_key = _prompt_str("Pinecone API key", "")
        if pinecone_key:
            env_pairs.append(("BITMOD_PINECONE_API_KEY", pinecone_key))
        pinecone_index = _prompt_str("Pinecone index name", "bitmod")
        vec_extra_lines.append(f"# pinecone_index: {pinecone_index}")

    # --- Backup (always on) ---
    backup_path = "./bitmod_backup"

    # --- Build config ---
    print(f"\n{_dim('─' * 50)}")
    print(f"{_bold('Configuration Summary')}")
    print(f"  LLM:          {_cyan(llm)} / {llm_model}")
    if fallback_llm:
        print(f"  Fallback:     {_cyan(fallback_llm)} / {fallback_model}")
    print(f"  Embedding:    {_cyan(embed)} / {embed_model}")
    db_label = db_choice if db_choice == db else f"{db_choice} ({db})"
    print(f"  Database:     {_cyan(db_label)}")
    if vector_store:
        print(f"  Vector Store: {_cyan(vector_store)}")
    print(f"  Backup:       {_cyan(backup_path)}")
    print()

    lines = [
        "# Bitmod Configuration",
        "# Generated by: bitmod init",
        "# Docs: https://github.com/DeepanjayNandal/bitmod",
        "",
        "# LLM Provider",
        f"llm_primary: {llm}",
        f"llm_primary_model: {llm_model}",
    ]

    if fallback_llm:
        lines.append(f"llm_fallback: {fallback_llm}")
        lines.append(f"llm_fallback_model: {fallback_model}")

    lines += [
        "",
        "# Embedding Provider",
        f"embedding_provider: {embed}",
        f"embedding_model: {embed_model}",
        f"embedding_dimensions: {int(embed_dims)}",
        "",
        "# Database",
        f"db_backend: {db}",
    ]
    if db == "sqlite":
        lines.append("db_sqlite_path: bitmod.db")
    elif db in ("postgresql", "mysql") and db_url:
        lines.append(f"db_url: {db_url}")
    elif db == "mongodb":
        if mongodb_url:
            lines.append(f"db_mongodb_url: {mongodb_url}")
        if mongodb_db:
            lines.append(f"db_mongodb_db: {mongodb_db}")

    if vector_store:
        lines += [
            "",
            "# Vector Store",
            f"vector_store: {vector_store}",
        ]
        lines.extend(vec_extra_lines)

    lines += [
        "",
        "# Backup — persistent context window (always on)",
        f"backup_path: {backup_path}",
    ]

    lines += [
        "",
        "# API server",
        "gateway_port: 8000",
    ]

    config_text = "\n".join(lines) + "\n"
    config_path.write_text(config_text)
    print(f"{_green('+')} Created {config_path}")

    # Write .env with all collected API keys
    if env_pairs:
        env_path = Path(".env")
        env_lines = []
        if env_path.exists():
            env_lines = env_path.read_text().splitlines()
        added = []
        for env_var, value in env_pairs:
            key_prefix = f"{env_var}="
            if not any(line.startswith(key_prefix) for line in env_lines):
                env_lines.append(f"{env_var}={value}")
                added.append(env_var)
        if added:
            env_path.write_text("\n".join(env_lines) + "\n")
            print(f"{_green('+')} Saved to .env: {', '.join(added)}")
            # Warn about .gitignore
            gitignore = Path(".gitignore")
            has_dotenv = False
            if gitignore.exists():
                has_dotenv = ".env" in gitignore.read_text().splitlines()
            if not has_dotenv:
                print(f"\n  {_yellow('!')} .env contains API keys. Make sure .env is in your .gitignore!")
                if not gitignore.exists():
                    print(f"  {_dim('Creating .gitignore with .env entry...')}")
                    gitignore.write_text(".env\n")
                    print(f"  {_green('+')} Created .gitignore")
                else:
                    with open(gitignore, "a") as gf:
                        gf.write("\n.env\n")
                    print(f"  {_green('+')} Added .env to .gitignore")

    # Initialize the database
    from bitmod.api import Bitmod

    bm = Bitmod(config_path=str(config_path))
    backend = bm._get_backend()
    bm.close()

    if db == "sqlite":
        print(f"{_green('+')} Initialized SQLite database")

    # Run migrations
    try:
        from bitmod.migrations import MigrationRunner

        runner = MigrationRunner(backend)
        with backend.session() as session:
            applied = runner.migrate(session)
            if applied:
                print(f"{_green('+')} Applied {len(applied)} migration(s)")
    except Exception:  # noqa: S110 — migrations are best-effort during init
        pass

    # Generate API key
    try:
        from bitmod.auth import APIKeyManager

        manager = APIKeyManager(backend)
        api_key, _record = manager.create_key(
            name="default-admin",
            owner="system",
            scopes=["read", "write", "admin"],
        )
        print(f"{_green('+')} API key generated")
        print()
        print(f"  {_bold('Your API Key:')} {_cyan(api_key)}")
        print(f"  {_dim('Save this key -- it will not be shown again.')}")
    except Exception:  # noqa: S110 — API key generation is best-effort
        pass

    # Provider-specific next steps
    print()
    if llm == "ollama":
        print(f"  {_yellow('!')} Make sure Ollama is running: {_cyan('ollama serve')}")
        print(f"  {_yellow('!')} Pull the model: {_cyan(f'ollama pull {llm_model}')}")
    if fallback_llm == "ollama":
        print(f"  {_yellow('!')} Pull fallback model: {_cyan(f'ollama pull {fallback_model}')}")
    if embed == "ollama":
        print(f"  {_yellow('!')} Pull embedding model: {_cyan(f'ollama pull {embed_model}')}")
    if embed == "local":
        print(f"  {_yellow('!')} Install embeddings: {_cyan('pip install sentence-transformers')}")
    if vector_store == "qdrant":
        print(f"  {_yellow('!')} Start Qdrant: {_cyan('docker run -p 6333:6333 qdrant/qdrant')}")
    if vector_store == "pinecone":
        print(f"  {_yellow('!')} Create your Pinecone index at {_cyan('https://app.pinecone.io')}")

    print()
    print(f"  {_bold('Next steps:')}")
    print(f"    {_cyan('bitmod ingest <file_or_dir>')}  Ingest your data")
    print(f"    {_cyan('bitmod query <question>')}       Query your data")
    print(f"    {_cyan('bitmod serve')}                  Start API server")
    print(f"    {_cyan('docker compose up')}             Run full stack with Docker")

    return 0


def _cmd_init_auto(args: argparse.Namespace) -> int:
    """Non-interactive quick setup using defaults or ~/.bitmod/."""
    from bitmod.setup import (
        DEFAULT_CONFIG_PATH,
        DEFAULT_DATA_DIR,
        DEFAULT_DB_PATH,
        check_dependencies,
        download_embedding_model,
        ensure_data_directory,
        generate_api_key,
        generate_default_config,
        initialize_database,
    )

    _print_banner()
    print(f"{_bold('Auto Setup')}")
    print(f"{_dim('Setting up BitMod with default configuration...')}")
    print()

    data_dir = DEFAULT_DATA_DIR
    db_path = DEFAULT_DB_PATH
    config_path = DEFAULT_CONFIG_PATH

    # 1. Data directory
    ensure_data_directory(data_dir)
    print(f"  {_green(_CHECK)} Data directory: {data_dir}")

    # 2. Database
    initialize_database(db_path)
    print(f"  {_green(_CHECK)} Database initialized: {db_path}")

    # 3. Config
    if not Path(config_path).exists() or getattr(args, "force", False):
        generate_default_config(config_path, data_dir)
        print(f"  {_green(_CHECK)} Config created: {config_path}")
    else:
        print(f"  {_green(_CHECK)} Config exists: {config_path}")

    # 4. API key
    try:
        api_key = generate_api_key(db_path)
        print(f"  {_green(_CHECK)} API key generated")
        print()
        print(f"  {_bold('Your API Key:')} {_cyan(api_key)}")
        print(f"  {_dim('Save this key -- it will not be shown again.')}")
    except Exception as exc:
        print(f"  {_yellow('!')} API key generation failed: {exc}")

    # 5. Dependencies
    print()
    deps = check_dependencies()
    avail = [name for name, info in deps.items() if info["available"]]
    missing = [name for name, info in deps.items() if not info["available"]]
    print(f"  {_bold('Dependencies:')}")
    print(f"    Available: {_green(', '.join(avail) if avail else 'none')}")
    if missing:
        print(f"    Missing:   {_dim(', '.join(missing))}")

    # 6. Embedding model
    if deps.get("embeddings", {}).get("available", False):
        print()
        print(f"  {_dim('Downloading embedding model...')}")
        if download_embedding_model():
            print(f"  {_green(_CHECK)} Embedding model ready")
        else:
            print(f"  {_yellow('!')} Embedding model download failed (will download on first use)")

    # Summary
    print()
    print(f"  {_bold('Next steps:')}")
    print(f"    {_cyan('bitmod ingest <file_or_dir>')}  Ingest your data")
    print(f"    {_cyan('bitmod query <question>')}       Query your data")
    print(f"    {_cyan('bitmod serve')}                  Start API server")
    print(f"    {_cyan('bitmod doctor')}                 Check system health")
    print()

    return 0


# ---------------------------------------------------------------------------
# bitmod doctor
# ---------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check system health: database, dependencies, LLM providers, embeddings."""
    import os

    from bitmod.setup import check_dependencies, check_llm_provider

    # Collect all checks into a structured result for JSON output
    checks: dict = {
        "data_directory": {"ok": False, "path": ""},
        "database": {"ok": False, "backend": "", "detail": ""},
        "config": {"ok": False, "path": ""},
        "dependencies": {},
        "llm_providers": {},
        "embeddings": {"ok": False, "detail": ""},
        "migrations": {"ok": False, "detail": ""},
    }
    issues = 0

    # 1. Data directory
    data_dir = os.path.expanduser("~/.bitmod")
    checks["data_directory"]["path"] = data_dir
    if os.path.isdir(data_dir):
        checks["data_directory"]["ok"] = True
    else:
        issues += 1

    # 2. Database connectivity
    try:
        from bitmod.config import load_config

        _cfg = load_config(None)
        _db_backend = _cfg.db.backend
    except Exception:
        _db_backend = os.getenv("BITMOD_DB_BACKEND", "sqlite")
    checks["database"]["backend"] = _db_backend

    db_path = ""
    if _db_backend == "postgresql":
        try:
            from bitmod.config import load_config as _lc

            _cfg2 = _lc(None)
            _db_url = _cfg2.db.url or os.getenv("DATABASE_URL", "")
        except Exception:
            _db_url = os.getenv("DATABASE_URL", "")
        if not _db_url:
            checks["database"]["detail"] = "DATABASE_URL not set"
            issues += 1
        else:
            try:
                from urllib.parse import urlparse as _urlparse

                _parsed = _urlparse(_db_url)
                _host = _parsed.hostname or "localhost"
                _port = _parsed.port or 5432
                import socket

                _sock = socket.create_connection((_host, _port), timeout=3)
                _sock.close()
                checks["database"]["ok"] = True
                checks["database"]["detail"] = f"{_host}:{_port}"
            except Exception as e:
                checks["database"]["detail"] = str(e)
                issues += 1
    else:
        try:
            from bitmod.config import load_config as _lc2

            _cfg3 = _lc2(None)
            db_path = _cfg3.db.sqlite_path
        except Exception:
            db_path = os.getenv("BITMOD_SQLITE_PATH", os.path.join(data_dir, "bitmod.db"))
        if os.path.isfile(db_path):
            try:
                import sqlite3

                conn = sqlite3.connect(db_path)
                conn.execute("SELECT 1")
                tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                table_names = [t[0] for t in tables]
                conn.close()
                checks["database"]["ok"] = True
                checks["database"]["detail"] = f"{db_path} ({len(table_names)} tables)"
            except Exception as e:
                checks["database"]["detail"] = str(e)
                issues += 1
        else:
            local_db = "bitmod.db"
            if os.path.isfile(local_db):
                checks["database"]["ok"] = True
                checks["database"]["detail"] = f"./{local_db} (local)"
            else:
                checks["database"]["detail"] = f"not found: {db_path}"
                issues += 1

    # 3. Config file
    config_candidates = [
        Path("bitmod.yaml"),
        Path(os.path.expanduser("~/.bitmod/bitmod.yaml")),
    ]
    for c in config_candidates:
        if c.is_file():
            checks["config"]["ok"] = True
            checks["config"]["path"] = str(c)
            break

    # 4. Dependencies
    deps = check_dependencies()
    for name, info in sorted(deps.items()):
        checks["dependencies"][name] = {
            "available": info["available"],
            "description": info["description"],
        }

    # 5. LLM providers
    try:
        from bitmod.config import load_config

        cfg = load_config(None)
        primary = cfg.llm.resolve_provider()
        fallback = cfg.llm.fallback
        primary_model = cfg.llm.resolve_model()
        fallback_model = cfg.llm.fallback_model
    except Exception:
        primary = "ollama"
        fallback = "ollama"
        primary_model = "llama3.2"
        fallback_model = "llama3.2"

    for label, provider, model in [
        ("primary", primary, primary_model),
        ("fallback", fallback, fallback_model),
    ]:
        result = check_llm_provider(provider, model)
        ok = result["reachable"] and not result.get("error")
        checks["llm_providers"][label] = {
            "provider": provider,
            "model": model,
            "ok": ok,
            "reachable": result["reachable"],
            "error": result.get("error", ""),
        }
        if not ok:
            issues += 1

    # 6. Embeddings
    if deps.get("embeddings", {}).get("available", False):
        checks["embeddings"]["ok"] = True
        checks["embeddings"]["detail"] = "sentence-transformers installed"
    else:
        checks["embeddings"]["detail"] = "sentence-transformers not installed"

    # 7. Migrations
    try:
        from bitmod.adapters.db_sqlite import SQLiteBackend
        from bitmod.migrations import MigrationRunner

        _mig_path = db_path if (db_path and os.path.isfile(db_path)) else "bitmod.db"
        backend = SQLiteBackend(_mig_path)
        backend.initialize()
        runner = MigrationRunner(backend)
        with backend.session() as session:
            pending = runner.get_pending(session)
            current = runner.get_current_version(session)
            if pending:
                checks["migrations"]["detail"] = f"version {current}, {len(pending)} pending"
                issues += 1
            else:
                checks["migrations"]["ok"] = True
                checks["migrations"]["detail"] = f"version {current}"
    except Exception as e:
        checks["migrations"]["detail"] = str(e)

    checks["issues"] = issues
    checks["healthy"] = issues == 0

    # JSON output
    if _is_json():
        _json_output(checks)
        return 0 if issues == 0 else 1

    # Text output
    _print_banner()
    print(f"{_bold('BitMod Doctor')}")
    print(f"{_dim('Checking system health...')}")
    print()

    # Data dir
    if checks["data_directory"]["ok"]:
        print(f"  {_green(_CHECK)} Data directory: {data_dir}")
    else:
        print(f"  {_red(_CROSS)} Data directory missing: {data_dir}")
        print(f"    {_dim('Run: bitmod init --auto')}")

    # Database
    if checks["database"]["ok"]:
        print(f"  {_green(_CHECK)} Database: {checks['database']['detail']}")
    else:
        print(f"  {_red(_CROSS)} Database: {checks['database']['detail']}")

    # Config
    if checks["config"]["ok"]:
        print(f"  {_green(_CHECK)} Config: {checks['config']['path']}")
    else:
        print(f"  {_yellow(_WARN)} No config file found (using defaults)")

    # Dependencies
    print()
    print(f"  {_bold('Dependencies:')}")
    for name, info in sorted(checks["dependencies"].items()):
        if info["available"]:
            print(f"    {_green(_CHECK)} {name:15s} {_dim(info['description'])}")
        else:
            desc = info["description"] + " (not installed)"
            print(f"    {_dim(_CROSS)} {name:15s} {_dim(desc)}")

    # LLM Providers
    print()
    print(f"  {_bold('LLM Providers:')}")
    for label, info in checks["llm_providers"].items():
        display = label.title()
        tag = f"{info['provider']}/{info['model']}"
        if info["ok"]:
            print(f"    {_green(_CHECK)} {display}: {tag}")
        elif info["reachable"]:
            print(f"    {_yellow(_WARN)} {display}: {tag}")
            if info["error"]:
                print(f"      {_dim(info['error'])}")
        else:
            print(f"    {_red(_CROSS)} {display}: {tag}")
            print(f"      {_dim(info.get('error') or 'Not reachable')}")

    # Embeddings
    print()
    print(f"  {_bold('Embeddings:')}")
    if checks["embeddings"]["ok"]:
        print(f"    {_green(_CHECK)} {checks['embeddings']['detail']}")
    else:
        print(f"    {_dim(_CROSS)} {checks['embeddings']['detail']}")
        print(f"      {_dim('Install: pip install sentence-transformers')}")

    # Migrations
    print()
    print(f"  {_bold('Migrations:')}")
    if checks["migrations"]["ok"]:
        print(f"    {_green(_CHECK)} Schema up to date ({checks['migrations']['detail']})")
    else:
        detail = checks["migrations"]["detail"]
        if "pending" in detail:
            print(f"    {_yellow(_WARN)} {detail}")
            print(f"      {_dim('Run: bitmod migrate')}")
        else:
            print(f"    {_dim(_CROSS)} Cannot check migrations: {detail}")

    # Summary
    print()
    if issues == 0:
        print(f"  {_green(_CHECK)} {_bold('All checks passed.')}")
    else:
        print(f"  {_yellow(_WARN)} {_bold(f'{issues} issue(s) found.')}")

    return 0 if issues == 0 else 1


# ---------------------------------------------------------------------------
# bitmod ingest
# ---------------------------------------------------------------------------


def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest files or directories into Bitmod.

    Automatically handles: format detection, text extraction, section splitting,
    chunking, embedding generation, tag inference, and block generation.
    The user just points at files — everything else is invisible.
    Supports stdin via: echo "text" | bitmod ingest -
    """
    from bitmod.api import Bitmod

    # Stdin piping support: bitmod ingest -
    if args.path == "-":
        if sys.stdin.isatty():
            print(f"{_red('x')} No input on stdin. Pipe data: echo 'text' | bitmod ingest -")
            return 1
        stdin_text = sys.stdin.read()
        if not stdin_text.strip():
            print(f"{_red('x')} Empty input on stdin.")
            return 1

        bm = Bitmod(config_path=args.config)
        kwargs: dict = {}
        if args.document_type:
            kwargs["document_type"] = args.document_type
        if args.source:
            kwargs["source"] = args.source
        if args.title:
            kwargs["title"] = args.title

        start = time.monotonic()
        result = bm.ingest(stdin_text, **kwargs)
        elapsed = time.monotonic() - start

        if _is_json():
            _json_output(
                {
                    "document_id": result.document_id,
                    "title": result.title,
                    "source_format": result.source_format,
                    "sections": result.sections,
                    "chunks": result.chunks,
                    "embedded": result.embedded,
                    "elapsed_s": round(elapsed, 1),
                    "errors": result.errors,
                }
            )
            bm.close()
            return 0

        _print(f"  {_green('+')} {result.title}")
        _print(f"    {result.sections} sections, {result.chunks} chunks")
        _print(f"    {_dim(f'{result.source_format} | {elapsed:.1f}s | id: {result.document_id}')}")
        bm.close()
        return 0

    target = Path(args.path)
    if not target.exists():
        print(f"{_red('x')} Path not found: {args.path}")
        return 1

    bm = Bitmod(config_path=args.config)

    # Auto-detect what we're ingesting and show a clear summary
    supported = {".txt", ".md", ".csv", ".json", ".html", ".htm", ".pdf", ".docx", ".doc"}
    if target.is_dir():
        files = [f for f in sorted(target.rglob("*")) if f.is_file() and f.suffix.lower() in supported]
        if not files:
            print(f"{_yellow('!')} No supported files found in {target}/")
            print(f"  {_dim('Supported: ' + ', '.join(sorted(supported)))}")
            bm.close()
            return 1

        # Group by format for display
        by_ext: dict[str, int] = {}
        for f in files:
            ext = f.suffix.lower()
            by_ext[ext] = by_ext.get(ext, 0) + 1
        format_summary = ", ".join(f"{count} {ext}" for ext, count in sorted(by_ext.items()))
        if not _is_json():
            _print(f"{_cyan('>')} Ingesting {len(files)} file(s) from {target}/")
            _print(f"  {_dim(format_summary)}")
    else:
        size = target.stat().st_size
        if size < 1024:
            size_str = f"{size:,} bytes"
        elif size < 1048576:
            size_str = f"{size / 1024:.1f} KB"
        else:
            size_str = f"{size / 1048576:.1f} MB"
        if not _is_json():
            _print(f"{_cyan('>')} Ingesting {target.name} ({size_str})")

    # Show what will happen automatically
    if not _is_json():
        _print(f"  {_dim('Auto: parse -> split -> chunk -> embed -> tag -> store')}")
        _print()

    start = time.monotonic()

    kwargs = {}
    if args.document_type:
        kwargs["document_type"] = args.document_type
    if args.source:
        kwargs["source"] = args.source
    if args.title:
        kwargs["title"] = args.title
    if args.metadata:
        meta = {}
        for pair in args.metadata:
            if "=" in pair:
                k, v = pair.split("=", 1)
                meta[k.strip()] = v.strip()
            else:
                if not _is_json():
                    _print(f"{_yellow('!')} Ignoring malformed metadata: {pair} (expected key=value)")
        if meta:
            kwargs["metadata"] = meta

    result = bm.ingest(str(target), **kwargs)
    elapsed = time.monotonic() - start

    if _is_json():
        _json_output(
            {
                "document_id": result.document_id,
                "title": result.title,
                "source_format": result.source_format,
                "sections": result.sections,
                "chunks": result.chunks,
                "embedded": result.embedded,
                "elapsed_s": round(elapsed, 1),
                "errors": result.errors,
            }
        )
        bm.close()
        return 0

    # Clean, concise result — focus on what the user cares about
    embed_status = _green("embedded") if result.embedded else _yellow("not embedded")
    _print(f"  {_green('+')} {result.title}")
    _print(f"    {result.sections} sections, {result.chunks} chunks, {embed_status}")
    _print(f"    {_dim(f'{result.source_format} | {elapsed:.1f}s | id: {result.document_id}')}")

    if result.errors:
        _print()
        for err in result.errors:
            _print(f"    {_red('x')} {err}")

    bm.close()
    return 0


# ---------------------------------------------------------------------------
# bitmod query
# ---------------------------------------------------------------------------


def cmd_query(args: argparse.Namespace) -> int:
    """Query via the full 9-layer pipeline (gateway -> chat service).

    Falls back to bm.query() (exact cache + LLM only) if the server isn't running.
    """
    question = args.question

    if not _is_json():
        _print(f"{_cyan('?')} {question}")
        _print()

    filters = {}
    if args.jurisdiction:
        filters["jurisdiction"] = args.jurisdiction
    if args.document_type:
        filters["document_type"] = args.document_type

    # Determine gateway URL
    import os

    gateway_url = os.getenv("BITMOD_URL", "http://localhost:8000")

    start = time.monotonic()
    try:
        data = _query_via_chat_service(gateway_url, question, filters)
    except Exception as e:
        elapsed = time.monotonic() - start
        if _is_json():
            _json_output({"error": str(e), "gateway_url": gateway_url, "elapsed_s": round(elapsed, 2)})
            return 1
        print(f"  {_red('Error:')} {e}")
        print(f"  {_dim(f'Gateway URL: {gateway_url}  ({elapsed:.1f}s)')}")
        print()
        return 1
    elapsed = time.monotonic() - start

    if data is None:
        if _is_json():
            return _cmd_query_offline(args, question, filters)
        # Fallback: server not running (connection refused), use direct API
        _print(f"  {_yellow('!')} Server not reachable — using offline mode (exact cache + LLM only)")
        _print(f"  {_dim('Start the full pipeline: bitmod serve')}")
        _print()
        return _cmd_query_offline(args, question, filters)

    # Parse response (matches ChatResponse schema from chat service)
    cached = data.get("cached", False)
    cache_key = data.get("cache_key", "")
    answer = data.get("answer", "")
    model_used = data.get("model_used", "")
    generation_ms = data.get("generation_ms", 0)
    sources = data.get("sources", [])
    pipeline_trace = data.get("pipeline_trace", [])
    tu = data.get("token_usage") or {}

    if _is_json():
        _json_output(
            {
                "answer": answer,
                "cached": cached,
                "cache_key": cache_key,
                "model_used": model_used,
                "generation_ms": generation_ms,
                "elapsed_s": round(elapsed, 2),
                "sources": sources,
                "pipeline_trace": pipeline_trace,
                "token_usage": tu,
            }
        )
        return 0

    # Determine cache layer from pipeline trace
    cache_layer = ""
    for step in pipeline_trace:
        if step.get("action") == "HIT":
            cache_layer = step.get("mechanism", "")
            break
    if not cache_layer:
        cache_layer = "llm_generation" if not cached else "cache"

    # Cache status
    if cached:
        cache_tag = _green("HIT")
    else:
        cache_tag = _yellow("MISS")

    _print(f"  {_dim('cache:')} {cache_tag} {_dim('(' + cache_layer + ')')}")
    model_str = model_used or "n/a"
    _print(f"  {_dim('model:')} {model_str}  {_dim('gen:')} {generation_ms}ms  {_dim('wall:')} {elapsed:.2f}s")
    if cache_key:
        _print(f"  {_dim('key:')}   {cache_key[:16]}...")

    # Pipeline trace — show every layer decision
    if pipeline_trace:
        _print()
        _print(f"  {_bold('Pipeline')} {_dim('(' + str(len(pipeline_trace)) + ' steps):')}")
        for step in pipeline_trace:
            _print_pipeline_step(step)

    # Token usage
    if tu:
        _print_token_usage(tu, cached)

    _print()

    # Answer — always printed even in quiet mode
    print(answer)

    # Sources
    if sources:
        _print()
        _print(f"  {_dim('Sources:')}")
        for src in sources[:8]:
            if isinstance(src, dict):
                _print_source(src)

    return 0


def _gateway_auth_headers() -> dict[str, str]:
    """Credentials for a gateway call, empty when none configured.

    The gateway reads its allowlist from BITMOD_API_KEYS and accepts one of
    those keys as `Authorization: ApiKey <key>` (see core/bitmod/auth.py).
    Clients name the single key they send BITMOD_API_KEY, which is the
    convention the README curl examples already use.

    Returns {} when unset so a gateway with auth disabled keeps working with no
    configuration at all; the caller surfaces the 401 if one comes back.
    """
    import os

    key = os.getenv("BITMOD_API_KEY", "")
    return {"Authorization": f"ApiKey {key}"} if key else {}


def _query_via_chat_service(gateway_url: str, question: str, filters: dict) -> dict | None:
    """Send query through the gateway to the chat service (full 9-layer pipeline).

    Returns the parsed JSON response dict, or None if unreachable.
    """
    try:
        import httpx
    except ImportError:
        # httpx not available, try urllib
        return _query_via_urllib(gateway_url, question, filters)

    try:
        with httpx.Client(timeout=httpx.Timeout(connect=3.0, read=180.0, write=5.0, pool=5.0)) as client:
            resp = client.post(
                f"{gateway_url}/v1/chat",
                json={"message": question, "filters": filters, "stream": False},
                headers={"X-Bitmod-Debug": "true", **_gateway_auth_headers()},
            )
            if resp.status_code in (401, 403):
                raise RuntimeError(
                    "Gateway rejected the request (HTTP "
                    f"{resp.status_code}). Auth is enabled, so set BITMOD_API_KEY to one of the "
                    "keys in the gateway's BITMOD_API_KEYS list."
                )
            if resp.status_code == 200:
                return resp.json()  # type: ignore[no-any-return]
            # Non-200: include status and detail in the error
            detail = ""
            try:
                detail = resp.json().get("detail", resp.text[:200])
            except Exception:
                detail = resp.text[:200]
            raise httpx.HTTPStatusError(
                f"HTTP {resp.status_code}: {detail}",
                request=resp.request,
                response=resp,
            )
    except httpx.ConnectError:
        return None
    except httpx.HTTPStatusError:
        raise
    except httpx.TimeoutException:
        raise
    except Exception:
        return None


def _query_via_urllib(gateway_url: str, question: str, filters: dict) -> dict | None:
    """Fallback using stdlib urllib (no httpx dependency)."""
    import json
    import urllib.error
    import urllib.request

    payload = json.dumps({"message": question, "filters": filters, "stream": False}).encode()
    req = urllib.request.Request(  # noqa: S310 — intentional HTTP request to local gateway
        f"{gateway_url}/v1/chat",
        data=payload,
        headers={"Content-Type": "application/json", "X-Bitmod-Debug": "true", **_gateway_auth_headers()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310 — intentional HTTP request to local gateway
            if resp.status == 200:
                return json.loads(resp.read())  # type: ignore[no-any-return]
            raise urllib.error.HTTPError(req.full_url, resp.status, f"HTTP {resp.status}", resp.headers, None)
    except (ConnectionError, OSError):
        return None
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError as e:
        if isinstance(e.reason, ConnectionRefusedError):
            return None
        raise


def _cmd_query_offline(args, question: str, filters: dict) -> int:
    """Offline fallback: direct bm.query() with limited pipeline."""
    from bitmod.api import Bitmod

    try:
        bm = Bitmod(config_path=args.config)
    except Exception as e:
        if _is_json():
            _json_output({"error": str(e)})
            return 1
        print(f"  {_red('x')} Failed to initialize BitMod: {e}")
        return 1

    start = time.monotonic()
    try:
        result = bm.query(question, filters=filters)
    except Exception as e:
        elapsed = time.monotonic() - start
        if _is_json():
            _json_output({"error": str(e), "elapsed_s": round(elapsed, 2)})
            return 1
        print(f"  {_red('x')} Query failed after {elapsed:.2f}s: {e}")
        return 1
    elapsed = time.monotonic() - start

    if _is_json():
        _json_output(
            {
                "answer": result.answer,
                "cached": result.cached,
                "cache_key": result.cache_key,
                "cache_layer": result.cache_layer or ("cache" if result.cached else "llm_generation"),
                "model_used": result.model_used,
                "generation_ms": result.generation_ms,
                "elapsed_s": round(elapsed, 2),
                "sources": result.sources,
                "pipeline_trace": result.pipeline_trace,
                "token_usage": result.token_usage,
                "offline": True,
            }
        )
        bm.close()
        return 0

    if result.cached:
        cache_tag = _green("HIT")
    else:
        cache_tag = _yellow("MISS")

    layer = result.cache_layer or ("cache" if result.cached else "llm_generation")
    _print(f"  {_dim('cache:')} {cache_tag} {_dim('(' + layer + ')')}")
    model_name = result.model_used or "n/a"
    gen_ms = result.generation_ms
    _print(f"  {_dim('model:')} {model_name}  {_dim('gen:')} {gen_ms}ms  {_dim('wall:')} {elapsed:.2f}s")

    if result.pipeline_trace:
        _print()
        _print(f"  {_bold('Pipeline')} {_dim('(' + str(len(result.pipeline_trace)) + ' steps):')}")
        for step in result.pipeline_trace:
            _print_pipeline_step(step)

    if result.token_usage:
        _print_token_usage(result.token_usage, result.cached)

    _print()
    print(result.answer)

    if result.sources:
        _print()
        _print(f"  {_dim('Sources:')}")
        for src in result.sources[:5]:
            if isinstance(src, dict):
                _print_source(src)

    bm.close()
    return 0


def _print_pipeline_step(step: dict) -> None:
    """Print a single pipeline step with color-coded action."""
    mechanism = step.get("mechanism", "")
    action = step.get("action", "")
    step_ms = step.get("elapsed_ms", 0)
    detail = step.get("detail", {})

    action_colors = {
        "HIT": _green,
        "STORED": _green,
        "FULL_HIT": _green,
        "MISS": _yellow,
        "PARTIAL": _yellow,
        "FALLTHROUGH": _yellow,
        "DONE": _cyan,
        "HANDLED": _cyan,
        "SKIP": _dim,
        "ERROR": _red,
        "REJECTED": _red,
    }
    color_fn = action_colors.get(action, _dim)
    action_str = color_fn(action)

    mechanism_display = mechanism.replace("_", " ").title()
    time_str = f"  {_dim(str(int(step_ms)) + 'ms')}" if step_ms > 0 else ""

    # Extra detail context
    detail_parts = []
    if detail.get("results"):
        detail_parts.append(str(detail["results"]) + " results")
    if detail.get("model"):
        detail_parts.append(detail["model"])
    if detail.get("key"):
        detail_parts.append(detail["key"])
    if detail.get("confidence"):
        detail_parts.append(str(round(detail["confidence"], 2)))
    if detail.get("intent"):
        detail_parts.append(detail["intent"])
    if detail.get("role"):
        detail_parts.append(detail["role"])
    if detail.get("tool"):
        detail_parts.append(detail["tool"])
    if detail.get("preview"):
        preview = str(detail["preview"])[:60]
        detail_parts.append('"' + preview + '"')
    detail_str = f"  {_dim(', '.join(detail_parts))}" if detail_parts else ""

    print(f"    {mechanism_display} -> {action_str}{time_str}{detail_str}")

    # Nested agent details
    if mechanism == "agent_tool_call" and detail.get("args"):
        query_arg = detail["args"].get("query", "") if isinstance(detail["args"], dict) else ""
        if query_arg:
            q_display = 'query: "' + str(query_arg)[:80] + '"'
            print(f"      {_dim(q_display)}")
    if mechanism == "agent_role_shift" and detail.get("old_role"):
        role_display = str(detail["old_role"]) + " -> " + str(detail.get("new_role", "?"))
        print(f"      {_dim(role_display)}")


def _print_token_usage(tu: dict, cached: bool) -> None:
    """Print token usage and cost information."""
    print()
    if cached:
        cached_tok = tu.get("cached_tokens", 0)
        saved_tok = tu.get("tokens_saved", 0)
        savings = tu.get("estimated_savings", 0)
        parts = []
        if cached_tok:
            parts.append(f"{cached_tok:,} cached")
        if saved_tok:
            parts.append(f"{saved_tok:,} saved")
        if savings:
            parts.append("$" + f"{savings:.4f}" + " saved")
        if parts:
            print(f"  {_bold('Tokens:')} {_green('  '.join(parts))}")
    else:
        in_tok = tu.get("input_tokens", 0)
        out_tok = tu.get("output_tokens", 0)
        total_tok = tu.get("total_tokens", 0)
        cost = tu.get("estimated_cost", 0)
        saved_tok = tu.get("tokens_saved", 0)
        parts = [f"{in_tok:,} in", f"{out_tok:,} out", f"{total_tok:,} total"]
        if cost:
            parts.append("$" + f"{cost:.4f}")
        print(f"  {_bold('Tokens:')} {'  '.join(parts)}")
        if saved_tok:
            print(f"  {_green('  ' + str(saved_tok) + ' tokens saved from context')}")

    if tu.get("pricing_stale"):
        p_date = tu.get("pricing_updated", "unknown")
        print(f"  {_yellow('  pricing from ' + p_date)}")


def _print_source(src: dict) -> None:
    """Print a single source with citation and score."""
    src_type = src.get("type", "document")
    if src_type == "code":
        file_path = src.get("file", "")
        lines = src.get("lines", "")
        symbol = src.get("symbol_name", "")
        label = f"{file_path}:{lines}" if lines else file_path
        if symbol:
            label += f" ({symbol})"
        print(f"    - {_cyan(label)}")
    elif src_type == "conversation":
        q = src.get("question", "")
        print(f"    - {_dim('Past:')} {q[:80]}")
    else:
        citation = src.get("citation") or src.get("title") or src.get("section_id", "")[:12]
        score = src.get("score")
        score_str = ""
        if score is not None:
            try:
                score_str = f" {_dim('(' + f'{float(score):.0%}' + ')')}"
            except (ValueError, TypeError):
                pass
        print(f"    - {citation}{score_str}")


# ---------------------------------------------------------------------------
# bitmod serve
# ---------------------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    """Start local FastAPI server."""
    # Auto-setup if this is a fresh install
    from bitmod.setup import auto_setup_if_needed

    if auto_setup_if_needed():
        print(f"{_green('+')} First-time setup completed automatically.")
        print(f"  {_dim('Run `bitmod doctor` to check system health.')}")
        print()

    try:
        import uvicorn  # noqa: F401
    except ImportError:
        print(f"{_red('x')} Server dependencies not installed.")
        print(f"  Install with: {_cyan('pip install bitmod[server]')}")
        return 1

    try:
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        print(f"{_red('x')} FastAPI not installed.")
        print(f"  Install with: {_cyan('pip install bitmod[server]')}")
        return 1

    port = args.port
    host = args.host

    if not _check_port_available(host, port):
        return 1

    display_host = "localhost" if host == "0.0.0.0" else host  # noqa: S104
    print(f"{_cyan('>')} Starting Bitmod server on {host}:{port}")
    print(f"  Config: {args.config}")
    print(f"  Docs:   http://{display_host}:{port}/docs")
    print()

    app = _create_app(args.config)

    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def _create_app(config_path: str) -> FastAPI:  # noqa: F821
    """Create the FastAPI application for `bitmod serve`."""
    import logging as _logging
    import os

    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field

    from bitmod import __version__
    from bitmod.api import Bitmod

    _log = _logging.getLogger("bitmod.serve")

    app = FastAPI(
        title="Bitmod",
        description="Modular AI Data Infrastructure -- Compute once, serve forever.",
        version=__version__,
    )

    # --- CORS: restrict to localhost by default, configurable via env ---
    cors_origins = os.getenv("BITMOD_CORS_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cors_origins],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # --- Security headers middleware ---
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    # --- Rate limiting (in-memory, no Redis needed) ---
    _rate_limits: dict[str, list[float]] = {}
    rate_limit_max = int(os.getenv("BITMOD_RATE_LIMIT", "60"))  # requests per minute
    rate_window = 60  # seconds

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        import time as _time

        if request.url.path in ("/health", "/docs", "/openapi.json"):
            return await call_next(request)
        client_ip = request.client.host if request.client else "unknown"
        now = _time.time()
        window_start = now - rate_window
        hits = _rate_limits.get(client_ip, [])
        hits = [t for t in hits if t > window_start]
        if len(hits) >= rate_limit_max:
            return JSONResponse(status_code=429, content={"error": "Rate limit exceeded"})
        hits.append(now)
        _rate_limits[client_ip] = hits
        # Cleanup stale entries periodically
        if len(_rate_limits) > 1000:
            stale = [k for k, v in _rate_limits.items() if not v or v[-1] < window_start]
            for k in stale:
                del _rate_limits[k]
        return await call_next(request)

    # --- Auth: optional, enabled via BITMOD_API_KEY or BITMOD_AUTH_ENABLED ---
    _api_key = os.getenv("BITMOD_API_KEY", "")
    _auth_enabled = bool(_api_key) or os.getenv("BITMOD_AUTH_ENABLED", "").lower() in ("1", "true", "yes")

    def _check_auth(request: Request) -> None:
        """Validate API key if auth is enabled."""
        if not _auth_enabled:
            return
        key = request.headers.get("x-api-key", "") or (
            request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        )
        if not key or (_api_key and key != _api_key):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

    bm = Bitmod(config_path=config_path)

    # -- Request/Response models --

    class IngestRequest(BaseModel):
        text: str = Field(..., description="Text content to ingest", min_length=1, max_length=10_000_000)
        title: str | None = None
        document_type: str | None = None
        source: str | None = None

    class IngestResponse(BaseModel):
        document_id: str
        title: str
        source_format: str
        sections: int
        chunks: int
        embedded: bool
        errors: list[str] = Field(default_factory=list)

    class QueryRequest(BaseModel):
        question: str = Field(..., min_length=1, max_length=10000)
        filters: dict = Field(default_factory=dict)

    class QueryResponse(BaseModel):
        answer: str
        cached: bool
        cache_key: str | None
        sources: list[dict]
        model_used: str | None
        generation_ms: int

    class StatusResponse(BaseModel):
        documents: int
        sections: int
        chunks: int
        cache_stats: dict
        db_backend: str
        llm_provider: str
        embedding_provider: str
        vector_store: str

    # -- Routes --

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "bitmod", "version": __version__}

    @app.post("/v1/ingest", response_model=IngestResponse)
    async def ingest(req: IngestRequest, request: Request) -> IngestResponse:
        _check_auth(request)
        kwargs = {}
        if req.title:
            kwargs["title"] = req.title
        if req.document_type:
            kwargs["document_type"] = req.document_type
        if req.source:
            kwargs["source"] = req.source

        try:
            result = bm.ingest(req.text, **kwargs)
        except Exception:
            _log.exception("Ingest failed")
            raise HTTPException(status_code=400, detail="Ingestion failed. Check server logs.")

        return IngestResponse(
            document_id=result.document_id,
            title=result.title,
            source_format=result.source_format,
            sections=result.sections,
            chunks=result.chunks,
            embedded=result.embedded,
            errors=result.errors,
        )

    @app.post("/v1/query", response_model=QueryResponse)
    async def query(req: QueryRequest, request: Request) -> QueryResponse:
        _check_auth(request)
        try:
            result = bm.query(req.question, filters=req.filters)
        except Exception:
            _log.exception("Query failed")
            raise HTTPException(status_code=500, detail="Query failed. Check server logs.")

        return QueryResponse(
            answer=result.answer,
            cached=result.cached,
            cache_key=result.cache_key,
            sources=result.sources,
            model_used=result.model_used,
            generation_ms=result.generation_ms,
        )

    @app.get("/v1/status", response_model=StatusResponse)
    async def status(request: Request) -> StatusResponse:
        _check_auth(request)
        s = bm.status()
        return StatusResponse(
            documents=s.documents,
            sections=s.sections,
            chunks=s.chunks,
            cache_stats=s.cache_stats,
            db_backend=s.db_backend,
            llm_provider=s.llm_provider,
            embedding_provider=s.embedding_provider,
            vector_store=s.vector_store,
        )

    @app.get("/v1/cache/stats")
    async def cache_stats(request: Request) -> dict:
        _check_auth(request)
        return bm.get_cache_stats()

    @app.get("/v1/admin/metrics")
    async def admin_metrics(request: Request) -> dict:
        _check_auth(request)
        return bm.admin_metrics()

    return app


# ---------------------------------------------------------------------------
# bitmod status
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    """Show system status: cache stats, document counts, provider config."""
    from bitmod.api import Bitmod

    bm = Bitmod(config_path=args.config)
    s = bm.status()

    if _is_json():
        _json_output(
            {
                "config": getattr(bm._config, "_loaded_from", ""),
                "db_backend": s.db_backend,
                "llm_provider": s.llm_provider,
                "embedding_provider": s.embedding_provider,
                "vector_store": s.vector_store,
                "documents": s.documents,
                "sections": s.sections,
                "chunks": s.chunks,
                "cache_stats": s.cache_stats,
            }
        )
        bm.close()
        return 0

    _print(f"{_bold('Bitmod Status')}")
    _print()

    # Show active config file
    config_source = getattr(bm._config, "_loaded_from", "")
    if config_source:
        _print(f"  {_dim('Config:')}     {config_source}")
    else:
        _print(f"  {_dim('Config:')}     {_dim('(environment variables only)')}")

    # Provider config
    _print(f"  {_dim('Database:')}   {s.db_backend}")
    _print(f"  {_dim('LLM:')}        {s.llm_provider}")
    _print(f"  {_dim('Embedding:')}  {s.embedding_provider}")
    _print(f"  {_dim('Vectors:')}    {s.vector_store}")
    _print()

    # Document counts
    _print(f"  {_bold('Data:')}")
    _print(f"    Documents:  {s.documents}")
    _print(f"    Sections:   {s.sections}")
    _print(f"    Chunks:     {s.chunks}")
    _print()

    # Cache stats
    cs = s.cache_stats
    _print(f"  {_bold('Cache:')}")
    _print(f"    Entries:         {cs.get('valid_entries', 0)} valid / {cs.get('total_entries', 0)} total")
    _print(f"    Hit rate:        {cs.get('hit_rate', 0)}%")
    _print(f"    Total serves:    {cs.get('total_serves', 0)}")
    _print(f"    Compute saved:   {cs.get('total_compute_saved_s', 0)}s")
    _print(f"    Avg generation:  {cs.get('avg_generation_ms', 0)}ms")

    bm.close()
    return 0


# ---------------------------------------------------------------------------
# bitmod migrate
# ---------------------------------------------------------------------------


def cmd_migrate(args: argparse.Namespace) -> int:
    """Run database migrations or show migration status."""
    from bitmod.api import Bitmod
    from bitmod.migrations import MigrationRunner

    bm = Bitmod(config_path=args.config)
    backend = bm._get_backend()
    runner = MigrationRunner(backend)

    _result_code = 0
    _result_data: Any = None

    with backend.session() as session:
        if args.status:
            status = runner.status(session)
            mismatches = runner.verify_checksums(session)
            _result_data = ("status", status, mismatches)
        else:
            target = args.target
            pending = runner.get_pending(session)
            if target is not None:
                pending = [m for m in pending if m.version <= target]

            if not pending:
                current = runner.get_current_version(session)
                _result_data = ("no_pending", current, None)
            else:
                if not _is_json():
                    target_label = f" to version {target}" if target is not None else ""
                    print(f"{_cyan('>')} Applying {len(pending)} migration(s){target_label}...")
                    print()

                applied = runner.migrate(session, target_version=target)
                current = runner.get_current_version(session)
                _result_data = ("applied", applied, current)

    # Output after session is closed
    if _result_data is not None:
        kind = _result_data[0]

        if kind == "status":
            status, mismatches = _result_data[1], _result_data[2]
            if _is_json():
                _json_output(
                    {
                        "backend": status["backend"],
                        "current_version": status["current_version"],
                        "applied_count": status["applied_count"],
                        "pending_count": status["pending_count"],
                        "history": status.get("history", []),
                        "pending": status.get("pending", []),
                        "checksum_warnings": mismatches,
                    }
                )
            else:
                print(f"{_bold('Migration Status')}")
                print()
                print(f"  {_dim('Backend:')}          {status['backend']}")
                print(f"  {_dim('Current version:')}  {status['current_version']}")
                print(f"  {_dim('Applied:')}          {status['applied_count']}")
                print(f"  {_dim('Pending:')}          {status['pending_count']}")

                if status["history"]:
                    print()
                    print(f"  {_bold('Applied Migrations:')}")
                    for entry in status["history"]:
                        v = _cyan(f"{entry['version']:03d}")
                        applied_at = _dim(entry["applied_at"])
                        checksum = _dim(entry["checksum"])
                        print(f"    {_green('+')} {v}  {entry['name']}  {applied_at}  {checksum}")

                if status["pending"]:
                    print()
                    print(f"  {_bold('Pending Migrations:')}")
                    for entry in status["pending"]:
                        v = _cyan(f"{entry['version']:03d}")
                        print(f"    {_yellow('~')} {v}  {entry['name']}")

                if mismatches:
                    print()
                    print(f"  {_red('Checksum Warnings:')}")
                    for m in mismatches:
                        print(f"    {_red('!')} {m['version']:03d} {m['name']}: {m['issue']}")

                if status["pending_count"] == 0:
                    print()
                    print(f"  {_green('Database is up to date.')}")

        elif kind == "no_pending":
            current = _result_data[1]
            if _is_json():
                _json_output({"applied": [], "current_version": current})
            else:
                print(f"{_green('+')} No pending migrations. Database is up to date.")

        elif kind == "applied":
            applied, current = _result_data[1], _result_data[2]
            if _is_json():
                _json_output(
                    {
                        "applied": [{"version": m.version, "name": m.name} for m in applied],
                        "current_version": current,
                    }
                )
            else:
                for migration in applied:
                    print(f"  {_green('+')} {_cyan(f'{migration.version:03d}')}  {migration.name}")
                print()
                print(f"{_green('+')} Database at version {_bold(str(current))}.")

    bm.close()
    return _result_code


# ---------------------------------------------------------------------------
# bitmod backup
# ---------------------------------------------------------------------------


def cmd_backup(args: argparse.Namespace) -> int:
    """Manage backup sessions (persistent context window)."""
    import datetime

    from bitmod.api import Bitmod

    bm = Bitmod(config_path=args.config)

    from bitmod.backup import BackupManager

    mgr = BackupManager(
        path=bm.config.backup.path,
        compress=bm.config.backup.compress,
        max_sessions=bm.config.backup.max_sessions,
    )

    action = args.action

    if action == "list":
        sessions = mgr.list_sessions()

        if _is_json():
            _json_output(
                {
                    "sessions": [
                        {
                            "id": s.id,
                            "name": s.name,
                            "created_at": s.created_at,
                            "tags": s.tags,
                            "total_queries": s.total_queries,
                            "total_cache_hits": s.total_cache_hits,
                            "total_ingestions": s.total_ingestions,
                            "entry_count": s.entry_count,
                        }
                        for s in sessions
                    ]
                }
            )
            bm.close()
            return 0

        if not sessions:
            print(f"{_dim('No backup sessions found.')}")
            bm.close()
            return 0

        print(f"{_bold('Backup Sessions')}")
        print()
        for s in sessions:
            created = datetime.datetime.fromtimestamp(s.created_at).strftime("%Y-%m-%d %H:%M")
            tags_str = f"  {_dim(', '.join(s.tags))}" if s.tags else ""
            print(f"  {_cyan(s.id)}  {s.name}{tags_str}")
            stats = (
                f"{created}  |  {s.total_queries} queries  |  "
                f"{s.total_cache_hits} cache hits  |  "
                f"{s.total_ingestions} ingests  |  {s.entry_count} total entries"
            )
            print(f"    {_dim(stats)}")

    elif action == "show":
        if not args.session_id:
            print(f"{_red('x')} Session ID required: bitmod backup show <session_id>")
            bm.close()
            return 1

        entries = mgr.get_entries(args.session_id, limit=args.limit or 20)

        if _is_json():
            _json_output(
                {
                    "session_id": args.session_id,
                    "entries": [
                        {
                            "event_type": e.event_type,
                            "timestamp": e.timestamp,
                            "question": getattr(e, "question", ""),
                            "answer": getattr(e, "answer", ""),
                            "metadata": getattr(e, "metadata", {}),
                        }
                        for e in entries
                    ],
                }
            )
            bm.close()
            return 0

        if not entries:
            print(f"{_dim('No entries found for session')} {args.session_id}")
            bm.close()
            return 0

        session = mgr.get_session(args.session_id)
        if session:
            print(f"{_bold(session.name)} {_dim(f'({session.id})')}")
            print()

        for entry in entries:
            ts = datetime.datetime.fromtimestamp(entry.timestamp).strftime("%H:%M:%S")
            tag = {
                "query": _yellow("MISS"),
                "cache_hit": _green("HIT"),
                "ingest": _cyan("INGEST"),
                "error": _red("ERROR"),
            }.get(entry.event_type, _dim(entry.event_type))

            if entry.event_type in ("query", "cache_hit"):
                print(f"  {_dim(ts)} {tag}  {entry.question}")
                preview = entry.answer[:120].replace("\n", " ")
                print(f"    {_dim(preview)}{'...' if len(entry.answer) > 120 else ''}")
            elif entry.event_type == "ingest":
                title = entry.metadata.get("title", "")
                secs = entry.metadata.get("sections", 0)
                print(f"  {_dim(ts)} {tag}  {title} ({secs} sections)")
            elif entry.event_type == "error":
                print(f"  {_dim(ts)} {tag}  {entry.question}")
                print(f"    {_dim(entry.metadata.get('error', ''))}")
            print()

    elif action == "context":
        if not args.session_id:
            print(f"{_red('x')} Session ID required: bitmod backup context <session_id>")
            bm.close()
            return 1

        context = mgr.build_context(
            args.session_id,
            limit=args.limit or 50,
            include_sources=True,
        )
        if _is_json():
            _json_output({"session_id": args.session_id, "context": context or ""})
            bm.close()
            return 0
        if context:
            print(context)
        else:
            print(f"{_dim('No query history in this session.')}")

    elif action == "export":
        if not args.session_id:
            print(f"{_red('x')} Session ID required: bitmod backup export <session_id>")
            bm.close()
            return 1
        output = args.output or f"{args.session_id}.jsonl.gz"
        count = mgr.export_session(args.session_id, output)
        if _is_json():
            _json_output({"exported": count, "file": output})
        else:
            print(f"{_green('+')} Exported {count} entries to {output}")

    elif action == "import":
        if not args.file:
            print(f"{_red('x')} File required: bitmod backup import <file>")
            bm.close()
            return 1
        session_id = mgr.import_session(args.file)
        if session_id:
            session = mgr.get_session(session_id)
            name = session.name if session else session_id
            if _is_json():
                _json_output({"session_id": session_id, "name": name})
            else:
                print(f"{_green('+')} Imported as session {_cyan(session_id)} ({name})")
        else:
            if _is_json():
                _json_output({"error": f"No entries found in {args.file}"})
            else:
                print(f"{_red('x')} No entries found in {args.file}")
            bm.close()
            return 1

    elif action == "delete":
        if not args.session_id:
            print(f"{_red('x')} Session ID required: bitmod backup delete <session_id>")
            bm.close()
            return 1
        if mgr.delete_session(args.session_id):
            if _is_json():
                _json_output({"deleted": args.session_id})
            else:
                print(f"{_green('+')} Deleted session {args.session_id}")
        else:
            if _is_json():
                _json_output({"error": f"Session not found: {args.session_id}"})
            else:
                print(f"{_red('x')} Session not found: {args.session_id}")
            bm.close()
            return 1

    else:
        print(f"{_red('x')} Unknown action: {action}")
        print("  Available: list, show, context, export, import, delete")
        bm.close()
        return 1

    bm.close()
    return 0


# ---------------------------------------------------------------------------
# bitmod update
# ---------------------------------------------------------------------------


def _fetch_latest_version() -> str | None:
    """Fetch the latest bitmod version from PyPI. Returns version string or None."""
    import json
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(  # noqa: S310 — intentional PyPI version check
            "https://pypi.org/pypi/bitmod/json",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 — intentional PyPI version check
            data = json.loads(resp.read())
            return data.get("info", {}).get("version")  # type: ignore[no-any-return]
    except Exception:
        return None


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a version string like '0.2.1' into a tuple (0, 2, 1)."""
    parts = []
    for p in v.strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            break
    return tuple(parts)


def cmd_update(args: argparse.Namespace) -> int:
    """Check for updates and optionally install them."""
    current = _get_version()
    print(f"{_bold('Bitmod Update Check')}")
    print(f"  {_dim('Current version:')} {current}")
    print()

    print(f"  {_dim('Checking PyPI...')}")
    latest = _fetch_latest_version()

    if latest is None:
        print(f"  {_yellow('!')} Could not reach PyPI. Check your internet connection.")
        return 1

    if _parse_version(latest) > _parse_version(current):
        print(f"  {_green('+')} New version available: {_bold(latest)}")
        print()
        print(f"  {_bold('To update:')}")
        print(f"    {_cyan('pip install --upgrade bitmod')}")
        print()

    elif _parse_version(latest) == _parse_version(current):
        print(f"  {_green('+')} You are on the latest version ({current}).")
    else:
        print(f"  {_dim('You are running a newer version than PyPI (' + current + ' > ' + latest + ')')}")

    return 0


# ---------------------------------------------------------------------------
# bitmod proxy
# ---------------------------------------------------------------------------


def _detect_llm_provider() -> tuple[str, str]:
    """Auto-detect LLM provider from environment variables.

    Returns (provider_name, detail_string).
    """
    import os

    if os.getenv("OPENAI_API_KEY"):
        return "openai", "OpenAI (OPENAI_API_KEY)"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic", "Anthropic (ANTHROPIC_API_KEY)"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini", "Google Gemini (GEMINI_API_KEY)"
    if os.getenv("XAI_API_KEY"):
        return "xai", "xAI Grok (XAI_API_KEY)"
    if os.getenv("MISTRAL_API_KEY"):
        return "mistral", "Mistral (MISTRAL_API_KEY)"
    return "ollama", "Ollama (localhost:11434)"


def cmd_proxy(args: argparse.Namespace) -> int:
    """Start the BitMod gateway proxy."""
    import os

    try:
        import uvicorn  # noqa: F401
    except ImportError:
        print(f"{_red('x')} uvicorn not installed.")
        print(f"  Install with: {_cyan('pip install bitmod[server]')}")
        return 1

    host = args.host
    port = args.port

    if not _check_port_available(host, port):
        return 1

    if args.verbose:
        os.environ["BITMOD_LOG_LEVEL"] = "DEBUG"

    provider, provider_detail = _detect_llm_provider()
    version = _get_version()

    # Startup banner
    display_host = "localhost" if host == "0.0.0.0" else host  # noqa: S104
    print()
    print(f"  {_bold(_blue('BitMod Gateway Proxy'))}")
    print(f"  {_dim('Version:')}    {version}")
    print(f"  {_dim('Listening:')}  http://{display_host}:{port}")
    print(f"  {_dim('Provider:')}   {provider_detail}")
    print()
    print(f"  {_dim('Endpoints:')}")
    print(f"    {_cyan('POST')}  /v1/chat/completions")
    print(f"    {_cyan('POST')}  /v1/completions")
    print(f"    {_cyan('GET ')}  /v1/models")
    print(f"    {_cyan('GET ')}  /health")
    print(f"    {_cyan('GET ')}  /metrics")
    print(f"    {_cyan('GET ')}  /docs")
    if args.dashboard:
        print(f"    {_cyan('GET ')}  /admin  {_dim('(opening in browser)')}")
    print()

    if args.dashboard:
        # Open after a short delay so the server has time to bind
        import threading
        import webbrowser

        def _open_browser() -> None:
            import time as _time

            _time.sleep(1.5)
            webbrowser.open(f"http://localhost:{port}/admin")

        threading.Thread(target=_open_browser, daemon=True).start()

    # Determine which app module to run.
    # Priority: gateway service (project dir) > core proxy module > error
    _app_path = None
    try:
        import services.gateway.app.main  # noqa: F401

        _app_path = "services.gateway.app.main:app"
    except (ModuleNotFoundError, ImportError):
        try:
            from bitmod.proxy.app import app as _proxy_app  # noqa: F401

            _app_path = "bitmod.proxy.app:app"
        except (ModuleNotFoundError, ImportError):
            pass

    if _app_path is None:
        print(f"{_red('x')} Could not start proxy.")
        print("  Run from the BitMod project directory, or install with:")
        print(f"    {_cyan('pip install bitmod[server]')}")
        return 1

    log_level = "debug" if args.verbose else "info"
    uvicorn.run(
        _app_path,
        host=host,
        port=port,
        reload=False,
        log_level=log_level,
    )
    return 0


# ---------------------------------------------------------------------------
# bitmod cache
# ---------------------------------------------------------------------------


def cmd_cache(args: argparse.Namespace) -> int:
    """Manage cache: stats, recent queries, search, clear."""
    from bitmod.api import Bitmod

    action = args.action
    bm = Bitmod(config_path=args.config)

    if action == "stats":
        stats = bm.get_cache_stats()

        if _is_json():
            _json_output(stats)
            bm.close()
            return 0

        _print(f"{_bold('Cache Statistics')}")
        _print()
        valid = stats.get("valid_entries", 0)
        total = stats.get("total_entries", 0)
        _print(f"  {_dim('Entries:')}        {valid} valid / {total} total")
        _print(f"  {_dim('Hit rate:')}       {stats.get('hit_rate', 0)}%")
        _print(f"  {_dim('Total serves:')}   {stats.get('total_serves', 0)}")
        _print(f"  {_dim('Compute saved:')}  {stats.get('total_compute_saved_s', 0)}s")
        _print(f"  {_dim('Avg generation:')} {stats.get('avg_generation_ms', 0)}ms")

        bm.close()
        return 0

    if action == "clear":
        backend = bm._get_backend()
        with backend.session() as session:
            count = backend.cache_clear_all(session)

        if _is_json():
            _json_output({"cleared": count})
            bm.close()
            return 0

        if count:
            _print(f"{_green('+')} Cleared {count} cached {'entry' if count == 1 else 'entries'}")
        else:
            _print(f"{_dim('Cache was already empty.')}")

        bm.close()
        return 0

    if action == "recent":
        limit = getattr(args, "limit", None) or 20
        backend = bm._get_backend()
        with backend.session() as session:
            if hasattr(backend, "recent_cached_queries"):
                rows = backend.recent_cached_queries(session, limit=limit)
            else:
                rows = []

        if _is_json():
            _json_output({"entries": rows})
            bm.close()
            return 0

        if not rows:
            _print(f"{_dim('No cached queries yet.')}")
            bm.close()
            return 0

        _print(f"{_bold('Recent Cached Queries')}")
        _print()
        for row in rows:
            q = row.get("question", "")[:80]
            serves = row.get("serve_count", 0)
            model = row.get("model_used", "")
            gen = row.get("generation_ms", 0)
            valid = _green("valid") if row.get("is_valid") else _red("invalid")
            _print(f"  {valid}  {_cyan(q)}")
            _print(f"    {_dim(f'{model} | {gen}ms | {serves} serves')}")

        bm.close()
        return 0

    if action == "search":
        query = getattr(args, "query", None)
        if not query:
            print(f"{_red('x')} Query required: bitmod cache search <query>")
            bm.close()
            return 1

        backend = bm._get_backend()
        results = []
        with backend.session() as session:
            if hasattr(backend, "cache_fuzzy_match"):
                from bitmod.cache_engine import normalize_for_key

                normalized = normalize_for_key(query)
                records = backend.cache_fuzzy_match(session, normalized, filters={}, threshold=0.5, max_results=10)
                for r in records:
                    results.append(
                        {
                            "id": r.id,
                            "question": r.question_raw,
                            "model_used": r.model_used,
                            "serve_count": r.serve_count,
                            "generation_ms": r.generation_ms,
                            "is_valid": r.is_valid,
                            "answer_preview": r.answer_text[:120],
                        }
                    )

        if _is_json():
            _json_output({"query": query, "results": results})
            bm.close()
            return 0

        if not results:
            _print(f"{_dim('No matching cache entries for:')} {query}")
            bm.close()
            return 0

        _print(f"{_bold('Cache Search:')} {query}")
        _print()
        for r in results:
            valid = _green("valid") if r["is_valid"] else _red("invalid")
            _print(f"  {valid}  {_cyan(r['question'][:80])}")
            preview = r["answer_preview"].replace("\n", " ")
            _print(f"    {_dim(preview)}{'...' if len(r['answer_preview']) >= 120 else ''}")
            model = r["model_used"]
            gen = r["generation_ms"]
            serves = r["serve_count"]
            _print(f"    {_dim(f'{model} | {gen}ms | {serves} serves')}")

        bm.close()
        return 0

    print(f"{_red('x')} Unknown action: {action}")
    print("  Available: stats, recent, search, clear")
    bm.close()
    return 1


# ---------------------------------------------------------------------------
# bitmod completions
# ---------------------------------------------------------------------------

_BASH_COMPLETION = """# Bitmod bash completion
# Add to ~/.bashrc: eval "$(bitmod completions bash)"
_bitmod_completions() {
    local cur prev commands
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    commands="init doctor ingest query serve proxy status cache migrate backup update config completions"

    case "$prev" in
        bitmod)
            COMPREPLY=($(compgen -W "$commands --help --version --format --quiet --verbose --debug" -- "$cur"))
            ;;
        backup)
            COMPREPLY=($(compgen -W "list show context export import delete" -- "$cur"))
            ;;
        cache)
            COMPREPLY=($(compgen -W "stats recent search clear" -- "$cur"))
            ;;
        config)
            COMPREPLY=($(compgen -W "show" -- "$cur"))
            ;;
        ingest)
            COMPREPLY=($(compgen -f -- "$cur"))
            ;;
        --format)
            COMPREPLY=($(compgen -W "text json" -- "$cur"))
            ;;
        completions)
            COMPREPLY=($(compgen -W "bash zsh fish --install" -- "$cur"))
            ;;
        *)
            COMPREPLY=($(compgen -f -- "$cur"))
            ;;
    esac
}
complete -F _bitmod_completions bitmod
"""

_ZSH_COMPLETION = """#compdef bitmod
# Bitmod zsh completion
# Add to ~/.zshrc: eval "$(bitmod completions zsh)"
_bitmod() {
    local -a commands
    commands=(
        'init:Initialize bitmod.yaml and database'
        'doctor:Check system health and dependencies'
        'ingest:Ingest files or directories'
        'query:Query with cache stats'
        'serve:Start local API server'
        'proxy:Start the gateway proxy'
        'status:Show system status'
        'cache:Manage cache (stats, recent, search, clear)'
        'migrate:Run database migrations'
        'backup:Manage backup sessions'
        'update:Check for new versions'
        'config:Show resolved configuration'
        'completions:Generate shell completion script'
    )

    _arguments -C \\
        '--help[Show help]' \\
        '--version[Show version]' \\
        '--format[Output format]:format:(text json)' \\
        '--quiet[Suppress non-essential output]' \\
        '--verbose[Set log level to INFO]' \\
        '--debug[Set log level to DEBUG]' \\
        '1:command:->command' \\
        '*::arg:->args'

    case $state in
        command)
            _describe 'commands' commands
            ;;
        args)
            case $words[1] in
                backup)
                    _values 'action' list show context export import delete
                    ;;
                cache)
                    _values 'action' stats recent search clear
                    ;;
                config)
                    _values 'action' show
                    ;;
                ingest)
                    _files
                    ;;
                completions)
                    _values 'shell' bash zsh fish
                    ;;
            esac
            ;;
    esac
}
_bitmod "$@"
"""

_FISH_COMPLETION = """# Bitmod fish completion
# Add to fish: bitmod completions fish | source
complete -c bitmod -n '__fish_use_subcommand' -a init -d 'Initialize bitmod.yaml and database'
complete -c bitmod -n '__fish_use_subcommand' -a doctor -d 'Check system health'
complete -c bitmod -n '__fish_use_subcommand' -a ingest -d 'Ingest files or directories'
complete -c bitmod -n '__fish_use_subcommand' -a query -d 'Query with cache stats'
complete -c bitmod -n '__fish_use_subcommand' -a serve -d 'Start local API server'
complete -c bitmod -n '__fish_use_subcommand' -a proxy -d 'Start the gateway proxy'
complete -c bitmod -n '__fish_use_subcommand' -a status -d 'Show system status'
complete -c bitmod -n '__fish_use_subcommand' -a cache -d 'Manage cache'
complete -c bitmod -n '__fish_use_subcommand' -a migrate -d 'Run database migrations'
complete -c bitmod -n '__fish_use_subcommand' -a backup -d 'Manage backup sessions'
complete -c bitmod -n '__fish_use_subcommand' -a update -d 'Check for new versions'
complete -c bitmod -n '__fish_use_subcommand' -a config -d 'Show resolved configuration'
complete -c bitmod -n '__fish_use_subcommand' -a completions -d 'Generate shell completion'
complete -c bitmod -n '__fish_use_subcommand' -l format -a 'text json' -d 'Output format'
complete -c bitmod -n '__fish_use_subcommand' -l quiet -d 'Suppress non-essential output'
complete -c bitmod -n '__fish_seen_subcommand_from backup' -a 'list show context export import delete'
complete -c bitmod -n '__fish_seen_subcommand_from cache' -a 'stats recent search clear'
complete -c bitmod -n '__fish_seen_subcommand_from config' -a 'show'
complete -c bitmod -n '__fish_seen_subcommand_from completions' -a 'bash zsh fish'
"""


def cmd_completions(args: argparse.Namespace) -> int:
    """Generate or install shell completion scripts."""
    shell = args.shell

    scripts = {
        "bash": _BASH_COMPLETION,
        "zsh": _ZSH_COMPLETION,
        "fish": _FISH_COMPLETION,
    }

    if shell not in scripts:
        print(f"{_red('x')} Unsupported shell: {shell}")
        print("  Supported: bash, zsh, fish")
        return 1

    # --install: auto-append to shell rc file
    if getattr(args, "install", False):
        return _install_completions(shell)

    print(scripts[shell].strip())
    return 0


def _install_completions(shell: str) -> int:
    """Auto-install completions into the user's shell rc file."""
    import os

    home = os.path.expanduser("~")

    # Determine the rc file and the eval line
    rc_map = {
        "bash": (
            os.path.join(home, ".bashrc"),
            'eval "$(bitmod completions bash)"',
        ),
        "zsh": (
            os.path.join(home, ".zshrc"),
            'eval "$(bitmod completions zsh)"',
        ),
        "fish": (
            os.path.join(home, ".config", "fish", "config.fish"),
            "bitmod completions fish | source",
        ),
    }

    rc_path, eval_line = rc_map[shell]

    # Check if already installed
    if os.path.isfile(rc_path):
        content = Path(rc_path).read_text()
        if "bitmod completions" in content:
            print(f"{_green(_CHECK)} Completions already installed in {rc_path}")
            return 0

    # For fish, ensure the config directory exists
    if shell == "fish":
        os.makedirs(os.path.dirname(rc_path), exist_ok=True)

    # Append the eval line
    with open(rc_path, "a") as f:
        f.write(f"\n# Bitmod shell completions\n{eval_line}\n")

    print(f"{_green(_CHECK)} Completions installed in {rc_path}")
    print(f"  {_dim('Restart your shell or run:')} source {rc_path}")
    return 0


# ---------------------------------------------------------------------------
# bitmod config
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS = {"api_key", "secret", "password", "token", "dsn", "encryption_key"}


def _mask_sensitive(data: dict, depth: int = 0) -> dict:
    """Recursively mask values whose keys look like secrets."""
    masked: dict = {}
    for k, v in data.items():
        if isinstance(v, dict):
            masked[k] = _mask_sensitive(v, depth + 1)
        elif any(s in k.lower() for s in _SENSITIVE_KEYS) and v:
            masked[k] = "***"
        else:
            masked[k] = v
    return masked


def cmd_config(args: argparse.Namespace) -> int:
    """Show resolved configuration."""
    from bitmod.config import load_config

    cfg = load_config(getattr(args, "config", None))
    raw = cfg.to_dict() if hasattr(cfg, "to_dict") else vars(cfg)
    masked = _mask_sensitive(raw)

    if _is_json():
        _json_output(masked)
        return 0

    try:
        import yaml  # type: ignore[import-untyped]

        print(yaml.dump(masked, default_flow_style=False, sort_keys=False))
    except ImportError:
        print(_json_mod.dumps(masked, indent=2, default=str))
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bitmod",
        description="Bitmod -- Modular AI Data Infrastructure. Compute once, serve forever.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    parser.add_argument(
        "-c",
        "--config",
        default="bitmod.yaml",
        help="Path to config file (default: bitmod.yaml)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text). Use json for machine-readable output.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress non-essential output (only show results/errors)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Set log level to INFO",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Set log level to DEBUG (overrides --verbose)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- config ---
    p_config = subparsers.add_parser("config", help="Show resolved configuration")
    p_config.add_argument("action", choices=["show"], help="Action to perform")

    # --- init ---
    p_init = subparsers.add_parser("init", help="Initialize bitmod.yaml and database")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing config")
    p_init.add_argument("--auto", action="store_true", help="Non-interactive setup with defaults")

    # --- doctor ---
    subparsers.add_parser("doctor", help="Check system health and dependencies")

    # --- ingest ---
    p_ingest = subparsers.add_parser("ingest", help="Ingest files or directories (use - for stdin)")
    p_ingest.add_argument("path", help="File or directory to ingest (use - for stdin)")
    p_ingest.add_argument("-t", "--title", help="Document title")
    p_ingest.add_argument("--document-type", help="Document type (e.g., 'legal', 'api', 'report')")
    p_ingest.add_argument("--source", help="Source label (e.g., 'uploads', 'sync')")
    p_ingest.add_argument(
        "-m",
        "--metadata",
        nargs="*",
        metavar="KEY=VALUE",
        help="Custom metadata key=value pairs (e.g., -m author=Ryan version=2.0)",
    )

    # --- query ---
    p_query = subparsers.add_parser("query", help="Query with cache stats")
    p_query.add_argument("question", help="Natural language question")
    p_query.add_argument("-j", "--jurisdiction", help="Filter by jurisdiction")
    p_query.add_argument("--document-type", help="Filter by document type")

    # --- serve ---
    p_serve = subparsers.add_parser("serve", help="Start local API server")
    p_serve.add_argument("-p", "--port", type=int, default=8000, help="Port (default: 8000)")
    p_serve.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")

    # --- status ---
    subparsers.add_parser("status", help="Show system status")

    # --- cache ---
    p_cache = subparsers.add_parser("cache", help="Manage cache (stats, recent, search, clear)")
    p_cache.add_argument("action", choices=["stats", "recent", "search", "clear"], help="Action to perform")
    p_cache.add_argument("query", nargs="?", default=None, help="Search query (for search action)")
    p_cache.add_argument("-n", "--limit", type=int, default=None, help="Max entries (for recent)")

    # --- migrate ---
    p_migrate = subparsers.add_parser("migrate", help="Run database migrations")
    p_migrate.add_argument("--status", action="store_true", help="Show migration status")
    p_migrate.add_argument("--target", type=int, default=None, help="Migrate to specific version")

    # --- backup ---
    p_backup = subparsers.add_parser("backup", help="Manage backup sessions (persistent context)")
    p_backup.add_argument(
        "action", choices=["list", "show", "context", "export", "import", "delete"], help="Action to perform"
    )
    p_backup.add_argument("session_id", nargs="?", default=None, help="Session ID (for show/context/export/delete)")
    p_backup.add_argument("--file", help="File path (for import)")
    p_backup.add_argument("--output", "-o", help="Output file path (for export)")
    p_backup.add_argument("--limit", "-n", type=int, default=None, help="Max entries to show")

    # --- proxy ---
    p_proxy = subparsers.add_parser("proxy", help="Start the gateway proxy (reverse proxy to LLM providers)")
    p_proxy.add_argument("-p", "--port", type=int, default=8001, help="Port (default: 8001)")
    p_proxy.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")  # noqa: S104 — intentional bind to all interfaces for proxy
    p_proxy.add_argument("--verbose", action="store_true", help="Enable debug logging and pipeline traces")
    p_proxy.add_argument("--dashboard", action="store_true", help="Open admin dashboard in browser after startup")

    # --- update ---
    subparsers.add_parser("update", help="Check for new versions of Bitmod")

    # --- completions ---
    p_completions = subparsers.add_parser("completions", help="Generate or install shell completions")
    p_completions.add_argument("shell", choices=["bash", "zsh", "fish"], help="Shell type")
    p_completions.add_argument("--install", action="store_true", help="Auto-install into your shell rc file")

    return parser


def _get_version() -> str:
    try:
        from bitmod import __version__

        return __version__
    except ImportError:
        return "0.2.1"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    global _OUTPUT_FORMAT, _QUIET

    parser = build_parser()
    args = parser.parse_args()

    # Apply global output flags
    _OUTPUT_FORMAT = getattr(args, "format", "text")
    _QUIET = getattr(args, "quiet", False)

    # In JSON mode, suppress color and non-essential output automatically
    if _is_json():
        _QUIET = True

    # Apply global log level flags before any subcommand runs
    if args.debug:
        import logging

        logging.basicConfig(level=logging.DEBUG)
    elif args.verbose:
        import logging

        logging.basicConfig(level=logging.INFO)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "init": cmd_init,
        "config": cmd_config,
        "doctor": cmd_doctor,
        "ingest": cmd_ingest,
        "query": cmd_query,
        "serve": cmd_serve,
        "proxy": cmd_proxy,
        "status": cmd_status,
        "cache": cmd_cache,
        "migrate": cmd_migrate,
        "backup": cmd_backup,
        "update": cmd_update,
        "completions": cmd_completions,
    }

    handler = commands.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        exit_code = handler(args)
    except KeyboardInterrupt:
        print()
        sys.exit(130)
    except Exception as e:
        if _is_json():
            _json_output({"error": str(e)})
            sys.exit(1)
        print(f"{_red('Error:')} {e}", file=sys.stderr)
        sys.exit(1)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
