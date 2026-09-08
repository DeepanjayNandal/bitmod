"""Tool definitions for LLM function calling.

Tools are the interface between the LLM and Bitmod's data layer.
The LLM autonomously decides which tools to call based on the user's query.

Security:
- Tool names are validated against a whitelist before execution.
- Tool arguments are validated (types, lengths, ranges).
- Results are bounded (max results, snippet length).
- No arbitrary code execution is possible through tools.
"""

import logging
import re

from bitmod.interfaces.database import DatabaseBackend
from bitmod.interfaces.llm import ToolDefinition

logger = logging.getLogger(__name__)

# Maximum result limits to prevent resource exhaustion
MAX_SEARCH_RESULTS = 50
MAX_SNIPPET_LENGTH = 500
MAX_QUERY_LENGTH = 2000


# --- Tool Definitions ---

SEARCH_DATA = ToolDefinition(
    name="search_data",
    description=(
        "Search the Bitmod data index for relevant content. "
        "Returns matching sections with citations and snippets. "
        "Use this when the user asks a question that requires looking up information."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query",
            },
            "jurisdiction": {
                "type": "string",
                "description": "Filter by jurisdiction (e.g., 'federal', 'CA', 'TX')",
            },
            "document_type": {
                "type": "string",
                "description": "Filter by document type (e.g., 'legal', 'api', 'dataset')",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default 10)",
                "default": 10,
            },
        },
        "required": ["query"],
    },
)

GET_SECTION = ToolDefinition(
    name="get_section",
    description=(
        "Retrieve the full text of a specific section by its ID or citation. "
        "Use this after search_data to get complete content for a specific result."
    ),
    parameters={
        "type": "object",
        "properties": {
            "section_id": {
                "type": "string",
                "description": "UUID of the section to retrieve",
            },
            "citation": {
                "type": "string",
                "description": "Citation string (e.g., '42 U.S.C. section 1983')",
            },
        },
    },
)

SEARCH_PROJECT = ToolDefinition(
    name="search_project",
    description=(
        "Search the user's project knowledge base for relevant code, files, and past conversations. "
        "Use this when the question relates to the user's specific project, codebase, or past interactions. "
        "Returns code chunks with file paths, line numbers, and symbol names."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query about the project",
            },
            "symbol": {
                "type": "string",
                "description": "Specific function, class, or variable name to look up",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default 10)",
                "default": 10,
            },
        },
        "required": ["query"],
    },
)

ALL_TOOLS = [SEARCH_DATA, GET_SECTION, SEARCH_PROJECT]

# Whitelist of valid tool names
_VALID_TOOL_NAMES = frozenset(t.name for t in ALL_TOOLS)

# UUID pattern for section_id validation
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


# --- Tool Execution ---


def execute_tool(
    tool_name: str,
    arguments: dict,
    backend: DatabaseBackend,
    embedder=None,
    project_id: str | None = None,
) -> dict:
    """Execute a tool call and return the result.

    Validates tool name against whitelist and sanitizes arguments.
    """
    if tool_name not in _VALID_TOOL_NAMES:
        logger.warning("Rejected unknown tool call: %s", tool_name)
        return {"error": f"Unknown tool: {tool_name}"}

    if not isinstance(arguments, dict):
        return {"error": "Tool arguments must be a dictionary."}

    try:
        if tool_name == "search_data":
            return _handle_search(arguments, backend, embedder=embedder)
        elif tool_name == "search_project":
            return _handle_search_project(arguments, backend, embedder=embedder, project_id=project_id)
        elif tool_name == "get_section":
            return _handle_get_section(arguments, backend)
        else:
            return {"error": f"No handler for tool: {tool_name}"}
    except Exception as e:
        logger.error("Tool execution error in %s: %s", tool_name, type(e).__name__)
        return {"error": "Internal tool error."}


def _handle_search(args: dict, backend: DatabaseBackend, embedder=None) -> dict:
    query = args.get("query", "")

    # Validate query
    if not isinstance(query, str) or not query.strip():
        return {"error": "Search query must be a non-empty string.", "results": [], "total": 0}
    query = query[:MAX_QUERY_LENGTH]

    # Validate and clamp limit
    limit = args.get("limit", 10)
    if not isinstance(limit, int) or limit < 1:
        limit = 10
    limit = min(limit, MAX_SEARCH_RESULTS)

    # Validate optional string filters
    jurisdiction = args.get("jurisdiction")
    if jurisdiction and (not isinstance(jurisdiction, str) or len(jurisdiction) > 100):
        jurisdiction = None

    document_type = args.get("document_type")
    if document_type and (not isinstance(document_type, str) or len(document_type) > 100):
        document_type = None

    # Generate query embedding for vector search
    query_embedding = None
    if embedder:
        try:
            query_embedding = embedder.embed(query)
        except Exception:
            logger.debug("Failed to embed query for vector search, falling back to FTS only")

    with backend.session() as session:
        results = backend.hybrid_search(
            session=session,
            query=query,
            embedding=query_embedding,
            limit=limit,
            jurisdiction=jurisdiction,
            document_type=document_type,
        )
        return {
            "results": [
                {
                    "section_id": r.section_id,
                    "citation": r.citation,
                    "title": r.title,
                    "snippet": r.snippet[:MAX_SNIPPET_LENGTH],
                    "score": r.score,
                    "version_hash": r.version_hash,
                }
                for r in results
            ],
            "total": len(results),
        }


def _handle_get_section(args: dict, backend: DatabaseBackend) -> dict:
    section_id = args.get("section_id")
    citation = args.get("citation")

    # Validate section_id format if provided (must be UUID)
    if section_id:
        if not isinstance(section_id, str):
            return {"error": "section_id must be a string."}
        if not _UUID_PATTERN.match(section_id):
            return {"error": "section_id must be a valid UUID."}

    # Validate citation if provided
    if citation:
        if not isinstance(citation, str):
            return {"error": "citation must be a string."}
        citation = citation[:500]  # Limit length

    if not section_id and not citation:
        return {"error": "Must provide section_id or citation"}

    with backend.session() as session:
        if section_id:
            section = backend.get_section(session, section_id)
        elif citation:
            section = backend.get_section_by_citation(session, citation)
        else:
            return {"error": "Must provide section_id or citation"}

        if not section:
            return {"error": "Section not found"}

        return {
            "section_id": section.id,
            "citation": section.citation,
            "title": section.section_title,
            "text": section.text_content,
            "version_hash": section.version_hash,
            "hierarchy": section.hierarchy_path,
        }


def _handle_search_project(
    args: dict,
    backend: DatabaseBackend,
    embedder=None,
    project_id: str | None = None,
) -> dict:
    """Search project knowledge: code chunks, symbols, and past conversations."""
    if not project_id:
        return {"error": "No project context. Set project_id in the request.", "results": [], "total": 0}

    query = args.get("query", "")
    if not isinstance(query, str) or not query.strip():
        return {"error": "Search query must be a non-empty string.", "results": [], "total": 0}
    query = query[:MAX_QUERY_LENGTH]

    symbol = args.get("symbol")
    limit = min(args.get("limit", 10) if isinstance(args.get("limit"), int) else 10, MAX_SEARCH_RESULTS)

    results = []

    with backend.session() as session:
        # Symbol-based lookup (exact match on function/class name)
        if symbol and isinstance(symbol, str):
            symbol = symbol[:200]
            # M4: Sanitize symbol to prevent regex/LIKE injection
            symbol = re.sub(r"[^\w.]", "", symbol)
            symbol_chunks = backend.project_chunks_by_symbol(session, project_id, symbol)
            for chunk in symbol_chunks[:limit]:
                # Resolve file path
                pf = None
                try:
                    files = backend.project_files_list(session, project_id)
                    pf_map = {f.id: f for f in files}
                    pf = pf_map.get(chunk.file_id)
                except Exception:  # noqa: S110 — file lookup failure is non-fatal
                    pass

                results.append(
                    {
                        "type": "code",
                        "file": pf.relative_path if pf else "unknown",
                        "lines": f"{chunk.start_line}-{chunk.end_line}",
                        "symbol_name": chunk.symbol_name,
                        "symbol_type": chunk.symbol_type,
                        "content": chunk.content[:MAX_SNIPPET_LENGTH],
                        "language": pf.language if pf else "",
                    }
                )

        # Semantic search over project chunks (if embedder available)
        if embedder and len(results) < limit:
            try:
                query_embedding = embedder.embed(query)
                if query_embedding:
                    remaining = limit - len(results)
                    chunks = backend.project_chunks_search(
                        session,
                        project_id,
                        query_embedding,
                        limit=remaining,
                    )
                    # Resolve file paths in batch
                    files = backend.project_files_list(session, project_id)
                    pf_map = {f.id: f for f in files}

                    seen_ids = {r.get("_chunk_id") for r in results}
                    for chunk in chunks:
                        if chunk.id in seen_ids:
                            continue
                        pf = pf_map.get(chunk.file_id)
                        results.append(
                            {
                                "type": "code",
                                "file": pf.relative_path if pf else "unknown",
                                "lines": f"{chunk.start_line}-{chunk.end_line}",
                                "symbol_name": chunk.symbol_name,
                                "symbol_type": chunk.symbol_type,
                                "content": chunk.content[:MAX_SNIPPET_LENGTH],
                                "language": pf.language if pf else "",
                            }
                        )
            except Exception:
                logger.debug("Project semantic search failed", exc_info=True)

        # Also search past conversations for this project
        if embedder:
            try:
                query_embedding = embedder.embed(query)
                if query_embedding:
                    convs = backend.conversation_search(
                        session,
                        query_embedding,
                        project_id=project_id,
                        limit=3,
                    )
                    for conv in convs:
                        results.append(
                            {
                                "type": "conversation",
                                "question": conv.user_message[:200],
                                "answer": conv.assistant_response[:MAX_SNIPPET_LENGTH],
                                "model": conv.model_used,
                                "rating": conv.rating,  # type: ignore[dict-item]
                            }
                        )
            except Exception:
                logger.debug("Conversation search failed", exc_info=True)

        # Search corrections (only approved ones to prevent poisoning)
        if embedder:
            try:
                query_embedding = embedder.embed(query)
                if query_embedding:
                    corrections = backend.correction_search(
                        session,
                        query_embedding,
                        project_id=project_id,
                        limit=2,
                    )
                    # H4: Filter to only approved corrections
                    corrections = [c for c in corrections if getattr(c, "status", "approved") == "approved"]
                    for corr in corrections:
                        results.append(
                            {
                                "type": "correction",
                                "original_question": corr.original_question[:200],
                                "corrected_answer": corr.corrected_answer[:MAX_SNIPPET_LENGTH],
                                "correction_type": corr.correction_type,
                            }
                        )
            except Exception:
                logger.debug("Correction search failed", exc_info=True)

    return {"results": results, "total": len(results)}
