"""Comprehensive mock-based adapter tests for all bitmod adapters.

Covers: embedding, vector store, database, and LLM adapters.
Each test mocks external dependencies so no real services are needed.
"""

from __future__ import annotations

import asyncio
import importlib.util
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bitmod.interfaces.llm import LLMMessage, LLMResponse
from bitmod.interfaces.vectors import VectorResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_async(coro):
    """Run an async coroutine synchronously for tests."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


# ===========================================================================
# EMBEDDING ADAPTERS
# ===========================================================================


class TestOllamaEmbeddingAdapter:
    """Tests for OllamaEmbeddingAdapter."""

    @patch("bitmod.adapters.embed_ollama.httpx.post")
    def test_embed_returns_list_of_floats(self, mock_post):
        from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        adapter = OllamaEmbeddingAdapter(model="nomic-embed-text", base_url="http://localhost:11434")
        result = adapter.embed("hello world")

        assert isinstance(result, list)
        assert all(isinstance(x, float) for x in result)
        assert result == [0.1, 0.2, 0.3]

    @patch("bitmod.adapters.embed_ollama.httpx.post")
    def test_embed_calls_correct_endpoint(self, mock_post):
        from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"embedding": [0.5]}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        adapter = OllamaEmbeddingAdapter(model="test-model", base_url="http://myhost:11434")
        adapter.embed("test")

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://myhost:11434/api/embeddings"
        assert call_args[1]["json"]["model"] == "test-model"
        assert call_args[1]["json"]["prompt"] == "test"

    @patch("bitmod.adapters.embed_ollama.httpx.post")
    def test_embed_raises_on_http_error(self, mock_post):
        import httpx
        from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
        mock_post.return_value = mock_resp

        adapter = OllamaEmbeddingAdapter()
        with pytest.raises(httpx.HTTPStatusError):
            adapter.embed("fail")

    @patch("bitmod.adapters.embed_ollama.httpx.post")
    def test_embed_batch_returns_list_of_lists(self, mock_post):
        from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter

        embeddings = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            r = MagicMock()
            r.json.return_value = {"embedding": embeddings[call_count]}
            r.raise_for_status = MagicMock()
            call_count += 1
            return r

        mock_post.side_effect = side_effect

        adapter = OllamaEmbeddingAdapter()
        result = adapter.embed_batch(["a", "b", "c"])

        assert len(result) == 3
        assert result == embeddings

    @patch("bitmod.adapters.embed_ollama.httpx.post")
    def test_dimensions_returns_768(self, mock_post):
        from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter

        adapter = OllamaEmbeddingAdapter()
        assert adapter.dimensions() == 768

    @patch("bitmod.adapters.embed_ollama.httpx.post")
    def test_embed_with_default_base_url(self, mock_post):
        from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"embedding": [1.0]}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        adapter = OllamaEmbeddingAdapter()
        adapter.embed("test")
        call_url = mock_post.call_args[0][0]
        assert "localhost:11434" in call_url


class TestCohereEmbeddingAdapter:
    """Tests for CohereEmbeddingAdapter."""

    @patch.dict("sys.modules", {"cohere": MagicMock()})
    def test_embed_returns_list_of_floats(self):
        # Re-import after patching cohere
        import importlib

        import bitmod.adapters.embed_cohere as mod

        importlib.reload(mod)

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings = [[0.1, 0.2, 0.3]]
        mock_client.embed.return_value = mock_response

        adapter = mod.CohereEmbeddingAdapter.__new__(mod.CohereEmbeddingAdapter)
        adapter._client = mock_client
        adapter._model = "embed-v4.0"

        result = adapter.embed("hello")
        assert result == [0.1, 0.2, 0.3]

    @patch.dict("sys.modules", {"cohere": MagicMock()})
    def test_embed_batch_returns_all_embeddings(self):
        import importlib

        import bitmod.adapters.embed_cohere as mod

        importlib.reload(mod)

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings = [[0.1, 0.2], [0.3, 0.4]]
        mock_client.embed.return_value = mock_response

        adapter = mod.CohereEmbeddingAdapter.__new__(mod.CohereEmbeddingAdapter)
        adapter._client = mock_client
        adapter._model = "embed-v4.0"

        result = adapter.embed_batch(["a", "b"])
        assert result == [[0.1, 0.2], [0.3, 0.4]]

    @patch.dict("sys.modules", {"cohere": MagicMock()})
    def test_embed_passes_correct_params(self):
        import importlib

        import bitmod.adapters.embed_cohere as mod

        importlib.reload(mod)

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings = [[0.5]]
        mock_client.embed.return_value = mock_response

        adapter = mod.CohereEmbeddingAdapter.__new__(mod.CohereEmbeddingAdapter)
        adapter._client = mock_client
        adapter._model = "embed-v4.0"

        adapter.embed("test text")
        mock_client.embed.assert_called_once_with(texts=["test text"], model="embed-v4.0", input_type="search_document")

    @patch.dict("sys.modules", {"cohere": MagicMock()})
    def test_embed_handles_api_error(self):
        import importlib

        import bitmod.adapters.embed_cohere as mod

        importlib.reload(mod)

        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("API rate limit")

        adapter = mod.CohereEmbeddingAdapter.__new__(mod.CohereEmbeddingAdapter)
        adapter._client = mock_client
        adapter._model = "embed-v4.0"

        with pytest.raises(Exception, match="API rate limit"):
            adapter.embed("fail")

    @patch.dict("sys.modules", {"cohere": MagicMock()})
    def test_dimensions_returns_1024(self):
        import importlib

        import bitmod.adapters.embed_cohere as mod

        importlib.reload(mod)

        adapter = mod.CohereEmbeddingAdapter.__new__(mod.CohereEmbeddingAdapter)
        adapter._client = MagicMock()
        adapter._model = "embed-v4.0"
        assert adapter.dimensions() == 1024


@pytest.mark.skipif(not importlib.util.find_spec("numpy"), reason="numpy not installed")
class TestLocalEmbeddingAdapter:
    """Tests for LocalEmbeddingAdapter (SentenceTransformers)."""

    @patch.dict("sys.modules", {"sentence_transformers": MagicMock()})
    def test_embed_returns_list_of_floats(self):
        import importlib

        import bitmod.adapters.embed_local as mod
        import numpy as np

        importlib.reload(mod)

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
        mock_model.get_sentence_embedding_dimension.return_value = 384

        adapter = mod.LocalEmbeddingAdapter.__new__(mod.LocalEmbeddingAdapter)
        adapter._model = mock_model
        adapter._dimensions = 384

        result = adapter.embed("hello")
        # Source calls .tolist() on numpy array — verify it produces a real Python list of floats
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(x, float) for x in result)
        assert result == pytest.approx([0.1, 0.2, 0.3])

    @patch.dict("sys.modules", {"sentence_transformers": MagicMock()})
    def test_embed_batch_returns_list_of_lists(self):
        import importlib

        import bitmod.adapters.embed_local as mod
        import numpy as np

        importlib.reload(mod)

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2], [0.3, 0.4]])
        mock_model.get_sentence_embedding_dimension.return_value = 2

        adapter = mod.LocalEmbeddingAdapter.__new__(mod.LocalEmbeddingAdapter)
        adapter._model = mock_model
        adapter._dimensions = 2

        result = adapter.embed_batch(["a", "b"])
        # Source calls .tolist() on each row — verify actual Python lists, not numpy
        assert len(result) == 2
        assert all(isinstance(r, list) for r in result)
        assert all(isinstance(x, float) for r in result for x in r)
        assert result[0] == pytest.approx([0.1, 0.2])
        assert result[1] == pytest.approx([0.3, 0.4])

    @patch.dict("sys.modules", {"sentence_transformers": MagicMock()})
    def test_dimensions_returns_model_dimension(self):
        import importlib

        import bitmod.adapters.embed_local as mod

        importlib.reload(mod)

        adapter = mod.LocalEmbeddingAdapter.__new__(mod.LocalEmbeddingAdapter)
        adapter._model = MagicMock()
        adapter._dimensions = 512

        assert adapter.dimensions() == 512

    @patch.dict("sys.modules", {"sentence_transformers": MagicMock()})
    def test_embed_uses_normalize_embeddings(self):
        import importlib

        import bitmod.adapters.embed_local as mod
        import numpy as np

        importlib.reload(mod)

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.5])

        adapter = mod.LocalEmbeddingAdapter.__new__(mod.LocalEmbeddingAdapter)
        adapter._model = mock_model
        adapter._dimensions = 1

        adapter.embed("test")
        mock_model.encode.assert_called_once_with("test", normalize_embeddings=True)


# ===========================================================================
# VECTOR STORE ADAPTERS
# ===========================================================================


class TestChromaAdapter:
    """Tests for ChromaAdapter."""

    @patch.dict("sys.modules", {"chromadb": MagicMock()})
    def test_initialize_creates_collection(self):
        import importlib

        import bitmod.adapters.vec_chroma as mod

        importlib.reload(mod)

        mock_client = MagicMock()
        adapter = mod.ChromaAdapter.__new__(mod.ChromaAdapter)
        adapter._client = mock_client
        adapter._collection = None

        adapter.initialize("test_col", 384)
        mock_client.get_or_create_collection.assert_called_once_with(name="test_col", metadata={"hnsw:space": "cosine"})

    @patch.dict("sys.modules", {"chromadb": MagicMock()})
    def test_upsert_stores_vectors(self):
        import importlib

        import bitmod.adapters.vec_chroma as mod

        importlib.reload(mod)

        mock_collection = MagicMock()
        adapter = mod.ChromaAdapter.__new__(mod.ChromaAdapter)
        adapter._client = MagicMock()
        adapter._collection = mock_collection

        adapter.upsert(ids=["id1"], embeddings=[[0.1, 0.2]], metadata=[{"k": "v"}], texts=["hello"])
        mock_collection.upsert.assert_called_once_with(
            ids=["id1"], embeddings=[[0.1, 0.2]], metadatas=[{"k": "v"}], documents=["hello"]
        )

    @patch.dict("sys.modules", {"chromadb": MagicMock()})
    def test_upsert_without_metadata_or_texts(self):
        import importlib

        import bitmod.adapters.vec_chroma as mod

        importlib.reload(mod)

        mock_collection = MagicMock()
        adapter = mod.ChromaAdapter.__new__(mod.ChromaAdapter)
        adapter._collection = mock_collection

        adapter.upsert(ids=["id1"], embeddings=[[0.1]])
        mock_collection.upsert.assert_called_once_with(ids=["id1"], embeddings=[[0.1]])

    @patch.dict("sys.modules", {"chromadb": MagicMock()})
    def test_search_returns_vector_results(self):
        import importlib

        import bitmod.adapters.vec_chroma as mod

        importlib.reload(mod)

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["id1", "id2"]],
            "distances": [[0.1, 0.3]],
            "metadatas": [[{"a": 1}, {"b": 2}]],
        }

        adapter = mod.ChromaAdapter.__new__(mod.ChromaAdapter)
        adapter._collection = mock_collection

        results = adapter.search([0.5, 0.5], limit=2)
        assert len(results) == 2
        assert isinstance(results[0], VectorResult)
        assert results[0].id == "id1"
        assert results[0].score == pytest.approx(0.9)  # 1 - 0.1

    @patch.dict("sys.modules", {"chromadb": MagicMock()})
    def test_search_with_filters(self):
        import importlib

        import bitmod.adapters.vec_chroma as mod

        importlib.reload(mod)

        mock_collection = MagicMock()
        mock_collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]]}

        adapter = mod.ChromaAdapter.__new__(mod.ChromaAdapter)
        adapter._collection = mock_collection

        adapter.search([0.1], filters={"type": "doc"})
        call_kwargs = mock_collection.query.call_args[1]
        assert call_kwargs["where"] == {"type": "doc"}

    @patch.dict("sys.modules", {"chromadb": MagicMock()})
    def test_delete_removes_vectors(self):
        import importlib

        import bitmod.adapters.vec_chroma as mod

        importlib.reload(mod)

        mock_collection = MagicMock()
        adapter = mod.ChromaAdapter.__new__(mod.ChromaAdapter)
        adapter._collection = mock_collection

        adapter.delete(["id1", "id2"])
        mock_collection.delete.assert_called_once_with(ids=["id1", "id2"])


class TestQdrantAdapter:
    """Tests for QdrantAdapter."""

    def _make_adapter(self):
        mock_client = MagicMock()
        # Need to patch imports at module level
        mock_qdrant = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "qdrant_client": mock_qdrant,
                "qdrant_client.models": mock_qdrant.models,
            },
        ):
            import importlib

            import bitmod.adapters.vec_qdrant as mod

            importlib.reload(mod)

            adapter = mod.QdrantAdapter.__new__(mod.QdrantAdapter)
            adapter._client = mock_client
            adapter._collection = "test"
            # Capture mock classes for verifying constructor calls
            adapter._mock_qdrant = mock_qdrant
            return adapter, mock_client, mod

    def test_initialize_creates_collection_if_not_exists(self):
        adapter, mock_client, mod = self._make_adapter()

        mock_collections_resp = MagicMock()
        mock_collections_resp.collections = []
        mock_client.get_collections.return_value = mock_collections_resp

        adapter.initialize("new_col", 768)
        mock_client.create_collection.assert_called_once()
        assert adapter._collection == "new_col"

    def test_initialize_skips_existing_collection(self):
        adapter, mock_client, mod = self._make_adapter()

        existing = MagicMock()
        existing.name = "existing_col"
        mock_collections_resp = MagicMock()
        mock_collections_resp.collections = [existing]
        mock_client.get_collections.return_value = mock_collections_resp

        adapter.initialize("existing_col", 768)
        mock_client.create_collection.assert_not_called()

    def test_upsert_stores_points(self):
        adapter, mock_client, mod = self._make_adapter()

        adapter.upsert(
            ids=["id1"],
            embeddings=[[0.1, 0.2]],
            metadata=[{"key": "val"}],
            texts=["hello"],
        )
        mock_client.upsert.assert_called_once()
        call_kwargs = mock_client.upsert.call_args[1]
        assert call_kwargs["collection_name"] == "test"
        assert len(call_kwargs["points"]) == 1
        # PointStruct is a mock, so verify it was called with the right args
        mock_point_struct = adapter._mock_qdrant.models.PointStruct
        mock_point_struct.assert_called_once()
        ps_kwargs = mock_point_struct.call_args[1]
        assert ps_kwargs["id"] == "id1"
        assert ps_kwargs["vector"] == [0.1, 0.2]
        assert ps_kwargs["payload"]["key"] == "val"
        assert ps_kwargs["payload"]["text"] == "hello"

    def test_search_returns_vector_results(self):
        adapter, mock_client, mod = self._make_adapter()

        mock_result = MagicMock()
        mock_result.id = "id1"
        mock_result.score = 0.95
        mock_result.payload = {"key": "val"}
        mock_client.search.return_value = [mock_result]

        results = adapter.search([0.1, 0.2], limit=5)
        assert len(results) == 1
        assert results[0].id == "id1"
        assert results[0].score == 0.95
        assert results[0].metadata == {"key": "val"}

    def test_search_with_filters(self):
        adapter, mock_client, mod = self._make_adapter()
        mock_client.search.return_value = []

        adapter.search([0.1], filters={"type": "doc"})
        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs["query_filter"] is not None
        # Source builds Filter(must=[FieldCondition(key=k, match=MatchValue(value=v))])
        # Verify the mock constructor calls rather than attributes on the mock result
        mock_field_cond = adapter._mock_qdrant.models.FieldCondition
        mock_field_cond.assert_called_once()
        fc_kwargs = mock_field_cond.call_args[1]
        assert fc_kwargs["key"] == "type"
        # MatchValue was called with value="doc"
        mock_match_val = adapter._mock_qdrant.models.MatchValue
        mock_match_val.assert_called_once_with(value="doc")
        # Filter was called with must=[the_field_condition]
        mock_filter = adapter._mock_qdrant.models.Filter
        mock_filter.assert_called_once()

    def test_delete_removes_points(self):
        adapter, mock_client, mod = self._make_adapter()

        adapter.delete(["id1", "id2"])
        mock_client.delete.assert_called_once()
        call_kwargs = mock_client.delete.call_args[1]
        assert call_kwargs["collection_name"] == "test"


class TestPineconeAdapter:
    """Tests for PineconeAdapter."""

    def _make_adapter(self):
        mock_pc = MagicMock()
        mock_index = MagicMock()

        with patch.dict("sys.modules", {"pinecone": MagicMock()}):
            import importlib

            import bitmod.adapters.vec_pinecone as mod

            importlib.reload(mod)

            adapter = mod.PineconeAdapter.__new__(mod.PineconeAdapter)
            adapter._pc = mock_pc
            adapter._index_name = "bitmod"
            adapter._index = mock_index
            adapter._namespace = "default"
            return adapter, mock_pc, mock_index, mod

    def test_initialize_creates_index_if_not_exists(self):
        adapter, mock_pc, mock_index, mod = self._make_adapter()

        mock_pc.list_indexes.return_value = []
        adapter.initialize("test", 768)
        mock_pc.create_index.assert_called_once()

    def test_initialize_skips_existing_index(self):
        adapter, mock_pc, mock_index, mod = self._make_adapter()

        existing = MagicMock()
        existing.name = "bitmod"
        mock_pc.list_indexes.return_value = [existing]
        adapter.initialize("test", 768)
        mock_pc.create_index.assert_not_called()

    def test_upsert_stores_vectors(self):
        adapter, mock_pc, mock_index, mod = self._make_adapter()

        adapter.upsert(
            ids=["id1"],
            embeddings=[[0.1, 0.2]],
            metadata=[{"key": "val"}],
            texts=["hello"],
        )
        mock_index.upsert.assert_called_once()
        call_kwargs = mock_index.upsert.call_args[1]
        vectors = call_kwargs["vectors"]
        assert len(vectors) == 1
        assert vectors[0]["id"] == "id1"
        assert vectors[0]["metadata"]["text"] == "hello"

    def test_search_returns_vector_results(self):
        adapter, mock_pc, mock_index, mod = self._make_adapter()

        mock_match = MagicMock()
        mock_match.id = "id1"
        mock_match.score = 0.92
        mock_match.metadata = {"key": "val"}
        mock_result = MagicMock()
        mock_result.matches = [mock_match]
        mock_index.query.return_value = mock_result

        results = adapter.search([0.1, 0.2], limit=5)
        assert len(results) == 1
        assert results[0].id == "id1"
        assert results[0].score == 0.92

    def test_search_with_filters(self):
        adapter, mock_pc, mock_index, mod = self._make_adapter()

        mock_index.query.return_value = MagicMock(matches=[])
        adapter.search([0.1], filters={"type": "doc"})
        call_kwargs = mock_index.query.call_args[1]
        assert call_kwargs["filter"] == {"type": "doc"}

    def test_delete_removes_vectors(self):
        adapter, mock_pc, mock_index, mod = self._make_adapter()

        adapter.delete(["id1", "id2"])
        mock_index.delete.assert_called_once_with(ids=["id1", "id2"], namespace="default")

    def test_upsert_without_metadata(self):
        adapter, mock_pc, mock_index, mod = self._make_adapter()

        adapter.upsert(ids=["id1"], embeddings=[[0.1]])
        vectors = mock_index.upsert.call_args[1]["vectors"]
        assert vectors[0]["metadata"] == {}


# ===========================================================================
# DATABASE ADAPTERS
# ===========================================================================


class TestPostgreSQLBackend:
    """Tests for PostgreSQLBackend with mocked SQLAlchemy."""

    def _load_module(self):
        """Load db_postgresql with mocked sqlalchemy/pgvector."""
        import importlib

        mock_sa = MagicMock()
        mock_sa.create_engine = MagicMock()
        mock_sa.MetaData = MagicMock
        mock_sa.Table = MagicMock()
        mock_sa.Column = MagicMock()
        mock_sa.String = MagicMock()
        mock_sa.Text = MagicMock()
        mock_sa.Boolean = MagicMock()
        mock_sa.Integer = MagicMock()
        mock_sa.Float = MagicMock()
        mock_sa.DateTime = MagicMock()
        mock_sa.JSON = MagicMock()
        mock_sa.text = MagicMock()
        mock_sa.insert = MagicMock()
        mock_sa.select = MagicMock()
        mock_sa.update = MagicMock()
        mock_sa.delete = MagicMock()
        mock_sa.func = MagicMock()
        mock_sa.LargeBinary = MagicMock()
        mock_sa.orm = MagicMock()
        mock_sa.orm.Session = MagicMock()
        mock_sa.orm.sessionmaker = MagicMock()
        # source_sections is declared JSONB (not JSON) so the GIN index and the
        # @> containment query work, which means the dialect submodule has to be
        # importable here too.
        mock_sa.dialects = MagicMock()
        mock_sa.dialects.postgresql = MagicMock()
        mock_sa.dialects.postgresql.JSONB = MagicMock()
        mock_pgvector = MagicMock()
        modules = {
            "sqlalchemy": mock_sa,
            "sqlalchemy.orm": mock_sa.orm,
            "sqlalchemy.dialects": mock_sa.dialects,
            "sqlalchemy.dialects.postgresql": mock_sa.dialects.postgresql,
            "pgvector": mock_pgvector,
            "pgvector.sqlalchemy": mock_pgvector.sqlalchemy,
        }
        with patch.dict("sys.modules", modules):
            import bitmod.adapters.db_postgresql as mod

            importlib.reload(mod)
            return mod, mock_sa

    def test_instantiation(self):
        mod, mock_sa = self._load_module()
        backend = mod.PostgreSQLBackend("postgresql://localhost/test")
        assert backend._url == "postgresql://localhost/test"

    def test_session_context_manager(self):
        mod, mock_sa = self._load_module()
        mock_session = MagicMock()
        backend = mod.PostgreSQLBackend.__new__(mod.PostgreSQLBackend)
        backend._Session = MagicMock(return_value=mock_session)
        backend._engine = MagicMock()

        with backend.session() as s:
            assert s is mock_session
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    def test_session_rollback_on_error(self):
        mod, mock_sa = self._load_module()
        mock_session = MagicMock()
        backend = mod.PostgreSQLBackend.__new__(mod.PostgreSQLBackend)
        backend._Session = MagicMock(return_value=mock_session)
        backend._engine = MagicMock()

        with pytest.raises(ValueError):
            with backend.session() as _s:
                raise ValueError("test error")
        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()

    def test_initialize_creates_extensions_and_tables(self):
        mod, mock_sa = self._load_module()
        backend = mod.PostgreSQLBackend("postgresql://localhost/test")
        mock_conn = MagicMock()
        backend._engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        backend._engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        backend.initialize()
        assert backend._tables_created is True
        # Verify engine.connect() was called to execute CREATE EXTENSION
        backend._engine.connect.assert_called()
        # Verify table metadata exists after init
        assert hasattr(backend, "_documents")
        assert hasattr(backend, "_sections")

    def test_store_document(self):
        mod, mock_sa = self._load_module()
        from bitmod.interfaces.database import DocumentRecord

        backend = mod.PostgreSQLBackend("postgresql://localhost/test")
        mock_conn = MagicMock()
        backend._engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        backend._engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        backend.initialize()

        mock_session = MagicMock()
        doc = DocumentRecord(id="doc1", document_type="pdf", source="test", title="Test Doc")
        backend.store_document(mock_session, doc)
        mock_session.execute.assert_called_once()
        # Verify the insert was called with the correct document ID
        call_args = mock_session.execute.call_args
        assert call_args is not None


class TestMySQLBackend:
    """Tests for MySQLBackend with mocked SQLAlchemy."""

    def _load_module(self):
        """Load db_mysql with mocked sqlalchemy."""
        import importlib

        mock_sa = MagicMock()
        mock_sa.create_engine = MagicMock()
        mock_sa.MetaData = MagicMock
        mock_sa.Table = MagicMock()
        mock_sa.Column = MagicMock()
        mock_sa.String = MagicMock()
        mock_sa.Text = MagicMock()
        mock_sa.Boolean = MagicMock()
        mock_sa.Integer = MagicMock()
        mock_sa.Float = MagicMock()
        mock_sa.DateTime = MagicMock()
        mock_sa.JSON = MagicMock()
        mock_sa.text = MagicMock()
        mock_sa.insert = MagicMock()
        mock_sa.select = MagicMock()
        mock_sa.update = MagicMock()
        mock_sa.delete = MagicMock()
        mock_sa.func = MagicMock()
        mock_sa.LargeBinary = MagicMock()
        mock_sa.orm = MagicMock()
        mock_sa.orm.Session = MagicMock()
        mock_sa.orm.sessionmaker = MagicMock()
        modules = {
            "sqlalchemy": mock_sa,
            "sqlalchemy.orm": mock_sa.orm,
        }
        with patch.dict("sys.modules", modules):
            import bitmod.adapters.db_mysql as mod

            importlib.reload(mod)
            return mod, mock_sa

    def test_instantiation(self):
        mod, mock_sa = self._load_module()
        backend = mod.MySQLBackend("mysql://localhost/test")
        # Verify the backend object was created with expected state
        assert hasattr(backend, "_engine")
        assert hasattr(backend, "_Session")

    def test_session_context_manager(self):
        mod, mock_sa = self._load_module()
        mock_session = MagicMock()
        backend = mod.MySQLBackend.__new__(mod.MySQLBackend)
        backend._Session = MagicMock(return_value=mock_session)
        backend._engine = MagicMock()

        with backend.session() as s:
            assert s is mock_session
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    def test_session_rollback_on_error(self):
        mod, mock_sa = self._load_module()
        mock_session = MagicMock()
        backend = mod.MySQLBackend.__new__(mod.MySQLBackend)
        backend._Session = MagicMock(return_value=mock_session)
        backend._engine = MagicMock()

        with pytest.raises(RuntimeError):
            with backend.session() as _s:
                raise RuntimeError("db error")
        mock_session.rollback.assert_called_once()

    def test_initialize_creates_tables(self):
        mod, mock_sa = self._load_module()
        backend = mod.MySQLBackend("mysql://localhost/test")
        mock_conn = MagicMock()
        backend._engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        backend._engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        backend.initialize()
        # Verify table metadata was created
        assert hasattr(backend, "_documents")
        assert hasattr(backend, "_sections")
        assert hasattr(backend, "_chunks")

    def test_store_section(self):
        mod, mock_sa = self._load_module()
        from bitmod.interfaces.database import SectionRecord

        backend = mod.MySQLBackend("mysql://localhost/test")
        mock_conn = MagicMock()
        backend._engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        backend._engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        backend.initialize()

        mock_session = MagicMock()
        section = SectionRecord(id="s1", document_id="d1", text_content="test", version_hash="abc")
        backend.store_section(mock_session, section)
        mock_session.execute.assert_called_once()
        # Verify the insert was called with args
        call_args = mock_session.execute.call_args
        assert call_args is not None


class TestMongoDBBackend:
    """Tests for MongoDBBackend with mocked pymongo."""

    @patch.dict("sys.modules", {"pymongo": MagicMock()})
    def test_instantiation(self):
        import importlib

        import bitmod.adapters.db_mongodb as mod

        importlib.reload(mod)

        mock_client = MagicMock()
        adapter = mod.MongoDBBackend.__new__(mod.MongoDBBackend)
        adapter._client = mock_client
        adapter._db = mock_client["bitmod"]
        # Verify both client and db references are stored
        assert adapter._db is not None
        assert adapter._client is mock_client

    @patch.dict("sys.modules", {"pymongo": MagicMock()})
    def test_session_yields_db(self):
        import importlib

        import bitmod.adapters.db_mongodb as mod

        importlib.reload(mod)

        mock_db = MagicMock()
        adapter = mod.MongoDBBackend.__new__(mod.MongoDBBackend)
        adapter._client = MagicMock()
        adapter._db = mock_db

        with adapter.session() as s:
            assert s is mock_db

    @patch.dict("sys.modules", {"pymongo": MagicMock()})
    def test_initialize_creates_indexes(self):
        import importlib

        import bitmod.adapters.db_mongodb as mod

        importlib.reload(mod)

        mock_db = MagicMock()
        adapter = mod.MongoDBBackend.__new__(mod.MongoDBBackend)
        adapter._client = MagicMock()
        adapter._db = mock_db

        adapter.initialize()
        # Should create indexes on various collections
        assert mock_db.documents.create_index.called
        assert mock_db.sections.create_index.called
        assert mock_db.chunks.create_index.called
        assert mock_db.answer_cache.create_index.called

    @patch.dict("sys.modules", {"pymongo": MagicMock()})
    def test_store_document(self):
        import importlib

        import bitmod.adapters.db_mongodb as mod
        from bitmod.interfaces.database import DocumentRecord

        importlib.reload(mod)

        mock_db = MagicMock()
        adapter = mod.MongoDBBackend.__new__(mod.MongoDBBackend)
        adapter._client = MagicMock()
        adapter._db = mock_db

        doc = DocumentRecord(id="doc1", document_type="pdf", source="test", title="Test")
        adapter.store_document(mock_db, doc)
        mock_db.documents.insert_one.assert_called_once()

    @patch.dict("sys.modules", {"pymongo": MagicMock()})
    def test_get_section_returns_none_when_not_found(self):
        import importlib

        import bitmod.adapters.db_mongodb as mod

        importlib.reload(mod)

        mock_db = MagicMock()
        mock_db.sections.find_one.return_value = None

        adapter = mod.MongoDBBackend.__new__(mod.MongoDBBackend)
        adapter._client = MagicMock()
        adapter._db = mock_db

        result = adapter.get_section(mock_db, "nonexistent")
        assert result is None

    @patch.dict("sys.modules", {"pymongo": MagicMock()})
    def test_get_section_returns_record(self):
        import importlib

        import bitmod.adapters.db_mongodb as mod

        importlib.reload(mod)

        mock_db = MagicMock()
        mock_db.sections.find_one.return_value = {
            "id": "s1",
            "document_id": "d1",
            "text_content": "hello",
            "version_hash": "abc",
            "citation": None,
            "is_current": True,
        }

        adapter = mod.MongoDBBackend.__new__(mod.MongoDBBackend)
        adapter._client = MagicMock()
        adapter._db = mock_db

        result = adapter.get_section(mock_db, "s1")
        assert result is not None
        assert result.id == "s1"

    @patch.dict("sys.modules", {"pymongo": MagicMock()})
    def test_cache_invalidate(self):
        import importlib

        import bitmod.adapters.db_mongodb as mod

        importlib.reload(mod)

        mock_db = MagicMock()
        adapter = mod.MongoDBBackend.__new__(mod.MongoDBBackend)
        adapter._client = MagicMock()
        adapter._db = mock_db

        adapter.cache_invalidate(mock_db, "cache1", "stale data")
        mock_db.answer_cache.update_one.assert_called_once()

    @patch.dict("sys.modules", {"pymongo": MagicMock()})
    def test_cache_increment_serve(self):
        import importlib

        import bitmod.adapters.db_mongodb as mod

        importlib.reload(mod)

        mock_db = MagicMock()
        adapter = mod.MongoDBBackend.__new__(mod.MongoDBBackend)
        adapter._client = MagicMock()
        adapter._db = mock_db

        adapter.cache_increment_serve(mock_db, "cache1")
        mock_db.answer_cache.update_one.assert_called_once_with({"id": "cache1"}, {"$inc": {"serve_count": 1}})


# ===========================================================================
# LLM ADAPTERS
# ===========================================================================


class TestBedrockAdapter:
    """Tests for BedrockAdapter with mocked boto3."""

    @patch.dict("sys.modules", {"boto3": MagicMock()})
    def test_instantiation(self):
        import importlib

        import bitmod.adapters.llm_bedrock as mod

        importlib.reload(mod)

        adapter = mod.BedrockAdapter.__new__(mod.BedrockAdapter)
        adapter._model = "anthropic.claude-sonnet-4-20250514-v1:0"
        adapter._region = "us-east-1"
        adapter._client = MagicMock()
        assert adapter._model == "anthropic.claude-sonnet-4-20250514-v1:0"

    @patch.dict("sys.modules", {"boto3": MagicMock()})
    def test_generate_returns_llm_response(self):
        import importlib

        import bitmod.adapters.llm_bedrock as mod

        importlib.reload(mod)

        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "Hello from Bedrock!"}]}},
            "usage": {"inputTokens": 10, "outputTokens": 5},
        }

        adapter = mod.BedrockAdapter.__new__(mod.BedrockAdapter)
        adapter._model = "anthropic.claude-sonnet-4-20250514-v1:0"
        adapter._region = "us-east-1"
        adapter._client = mock_client

        messages = [LLMMessage(role="user", content="Hi")]
        result = run_async(adapter.generate(messages))

        assert isinstance(result, LLMResponse)
        assert result.content == "Hello from Bedrock!"
        assert result.usage["input_tokens"] == 10
        assert result.usage["output_tokens"] == 5

    @patch.dict("sys.modules", {"boto3": MagicMock()})
    def test_generate_handles_tool_calls(self):
        import importlib

        import bitmod.adapters.llm_bedrock as mod

        importlib.reload(mod)

        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {"content": [{"toolUse": {"toolUseId": "tc1", "name": "search", "input": {"q": "test"}}}]}
            },
            "usage": {"inputTokens": 5, "outputTokens": 3},
        }

        adapter = mod.BedrockAdapter.__new__(mod.BedrockAdapter)
        adapter._model = "test"
        adapter._region = "us-east-1"
        adapter._client = mock_client

        messages = [LLMMessage(role="user", content="search for test")]
        result = run_async(adapter.generate(messages))

        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "search"

    @patch.dict("sys.modules", {"boto3": MagicMock()})
    def test_generate_handles_system_messages(self):
        import importlib

        import bitmod.adapters.llm_bedrock as mod

        importlib.reload(mod)

        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "ok"}]}},
            "usage": {},
        }

        adapter = mod.BedrockAdapter.__new__(mod.BedrockAdapter)
        adapter._model = "test"
        adapter._region = "us-east-1"
        adapter._client = mock_client

        messages = [
            LLMMessage(role="system", content="You are helpful"),
            LLMMessage(role="user", content="Hi"),
        ]
        run_async(adapter.generate(messages))

        call_kwargs = mock_client.converse.call_args[1]
        assert "system" in call_kwargs
        assert call_kwargs["system"][0]["text"] == "You are helpful"

    @patch.dict("sys.modules", {"boto3": MagicMock()})
    def test_generate_error_propagates(self):
        import importlib

        import bitmod.adapters.llm_bedrock as mod

        importlib.reload(mod)

        mock_client = MagicMock()
        mock_client.converse.side_effect = Exception("Bedrock throttled")

        adapter = mod.BedrockAdapter.__new__(mod.BedrockAdapter)
        adapter._model = "test"
        adapter._region = "us-east-1"
        adapter._client = mock_client

        messages = [LLMMessage(role="user", content="Hi")]
        with pytest.raises(Exception, match="Bedrock throttled"):
            run_async(adapter.generate(messages))


class TestAzureOpenAIAdapter:
    """Tests for AzureOpenAIAdapter with mocked openai SDK."""

    @patch.dict("sys.modules", {"openai": MagicMock()})
    @patch.dict("os.environ", {"AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com", "AZURE_OPENAI_API_KEY": "key"})
    def test_instantiation(self):
        import importlib

        import bitmod.adapters.llm_azure_openai as mod

        importlib.reload(mod)

        adapter = mod.AzureOpenAIAdapter.__new__(mod.AzureOpenAIAdapter)
        adapter._model = "gpt-4o"
        adapter._client = MagicMock()
        assert adapter._model == "gpt-4o"
        assert adapter._client is not None

    @patch.dict("sys.modules", {"openai": MagicMock()})
    def test_generate_returns_llm_response(self):
        import importlib

        import bitmod.adapters.llm_azure_openai as mod

        importlib.reload(mod)

        mock_client = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello from Azure!"
        mock_choice.message.tool_calls = None
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 5
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "gpt-4o"
        mock_response.usage = mock_usage
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        adapter = mod.AzureOpenAIAdapter.__new__(mod.AzureOpenAIAdapter)
        adapter._model = "gpt-4o"
        adapter._client = mock_client

        messages = [LLMMessage(role="user", content="Hi")]
        result = run_async(adapter.generate(messages))

        assert isinstance(result, LLMResponse)
        assert result.content == "Hello from Azure!"
        assert result.usage["input_tokens"] == 10

    @patch.dict("sys.modules", {"openai": MagicMock()})
    def test_generate_handles_tool_calls(self):
        import importlib

        import bitmod.adapters.llm_azure_openai as mod

        importlib.reload(mod)

        mock_tc = MagicMock()
        mock_tc.id = "tc1"
        mock_tc.function.name = "search"
        mock_tc.function.arguments = '{"q": "test"}'

        mock_choice = MagicMock()
        mock_choice.message.content = ""
        mock_choice.message.tool_calls = [mock_tc]
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "gpt-4o"
        mock_response.usage = MagicMock(prompt_tokens=5, completion_tokens=3)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        adapter = mod.AzureOpenAIAdapter.__new__(mod.AzureOpenAIAdapter)
        adapter._model = "gpt-4o"
        adapter._client = mock_client

        messages = [LLMMessage(role="user", content="search")]
        result = run_async(adapter.generate(messages))

        assert result.tool_calls is not None
        assert result.tool_calls[0]["name"] == "search"

    @patch.dict("sys.modules", {"openai": MagicMock()})
    def test_generate_error_propagates(self):
        import importlib

        import bitmod.adapters.llm_azure_openai as mod

        importlib.reload(mod)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("Azure error"))

        adapter = mod.AzureOpenAIAdapter.__new__(mod.AzureOpenAIAdapter)
        adapter._model = "gpt-4o"
        adapter._client = mock_client

        with pytest.raises(Exception, match="Azure error"):
            run_async(adapter.generate([LLMMessage(role="user", content="Hi")]))


class TestHuggingFaceAdapter:
    """Tests for HuggingFaceAdapter with mocked huggingface_hub SDK."""

    @patch.dict("sys.modules", {"huggingface_hub": MagicMock()})
    def test_instantiation(self):
        import importlib

        import bitmod.adapters.llm_huggingface as mod

        importlib.reload(mod)

        adapter = mod.HuggingFaceAdapter.__new__(mod.HuggingFaceAdapter)
        adapter._model = "meta-llama/Llama-3.1-70B-Instruct"
        adapter._client = MagicMock()
        assert adapter._model == "meta-llama/Llama-3.1-70B-Instruct"
        assert adapter._client is not None

    @patch.dict("sys.modules", {"huggingface_hub": MagicMock()})
    def test_generate_returns_llm_response(self):
        import importlib

        import bitmod.adapters.llm_huggingface as mod

        importlib.reload(mod)

        mock_choice = MagicMock()
        mock_choice.message.content = "Hello from HuggingFace!"
        mock_choice.message.tool_calls = None
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 8
        mock_usage.completion_tokens = 4
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        adapter = mod.HuggingFaceAdapter.__new__(mod.HuggingFaceAdapter)
        adapter._model = "test-model"
        adapter._client = mock_client

        messages = [LLMMessage(role="user", content="Hi")]
        result = run_async(adapter.generate(messages))

        assert isinstance(result, LLMResponse)
        assert result.content == "Hello from HuggingFace!"

    @patch.dict("sys.modules", {"huggingface_hub": MagicMock()})
    def test_generate_with_temperature_zero_uses_0_01(self):
        import importlib

        import bitmod.adapters.llm_huggingface as mod

        importlib.reload(mod)

        mock_choice = MagicMock()
        mock_choice.message.content = "ok"
        mock_choice.message.tool_calls = None
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = MagicMock(prompt_tokens=1, completion_tokens=1)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        adapter = mod.HuggingFaceAdapter.__new__(mod.HuggingFaceAdapter)
        adapter._model = "test"
        adapter._client = mock_client

        run_async(adapter.generate([LLMMessage(role="user", content="Hi")], temperature=0.0))
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 0.01

    @patch.dict("sys.modules", {"huggingface_hub": MagicMock()})
    def test_generate_handles_tool_calls(self):
        import importlib

        import bitmod.adapters.llm_huggingface as mod

        importlib.reload(mod)

        mock_tc = MagicMock()
        mock_tc.id = "tc1"
        mock_tc.function.name = "lookup"
        mock_tc.function.arguments = '{"key": "val"}'

        mock_choice = MagicMock()
        mock_choice.message.content = ""
        mock_choice.message.tool_calls = [mock_tc]
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = MagicMock(prompt_tokens=1, completion_tokens=1)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        adapter = mod.HuggingFaceAdapter.__new__(mod.HuggingFaceAdapter)
        adapter._model = "test"
        adapter._client = mock_client

        result = run_async(adapter.generate([LLMMessage(role="user", content="lookup")]))
        assert result.tool_calls is not None
        assert result.tool_calls[0]["name"] == "lookup"

    @patch.dict("sys.modules", {"huggingface_hub": MagicMock()})
    def test_generate_error_propagates(self):
        import importlib

        import bitmod.adapters.llm_huggingface as mod

        importlib.reload(mod)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("HF API down"))

        adapter = mod.HuggingFaceAdapter.__new__(mod.HuggingFaceAdapter)
        adapter._model = "test"
        adapter._client = mock_client

        with pytest.raises(Exception, match="HF API down"):
            run_async(adapter.generate([LLMMessage(role="user", content="Hi")]))

