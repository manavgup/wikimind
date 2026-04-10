"""Semantic search via ChromaDB vector store and sentence-transformers embeddings.

Provides article-level embedding and hybrid search that combines keyword
matching with vector similarity. All search-extra dependencies (chromadb,
sentence-transformers) are optional -- the service degrades gracefully when
they are not installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from wikimind.config import get_settings

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Optional dependency availability check (mirrors _DOCLING_AVAILABLE pattern)
# ---------------------------------------------------------------------------

try:
    import chromadb as _chromadb
    from sentence_transformers import SentenceTransformer as _SentenceTransformer

    _SEARCH_AVAILABLE = True
except ImportError:
    _chromadb = None  # type: ignore[assignment]
    _SentenceTransformer = None  # type: ignore[assignment,misc]
    _SEARCH_AVAILABLE = False


@dataclass
class SemanticSearchResult:
    """A single result from a ChromaDB vector similarity query."""

    article_id: str
    score: float
    chunk_text: str
    chunk_index: int


def _estimate_tokens(text: str) -> int:
    """Rough token count: ~4 characters per token for English text."""
    return len(text) // 4


def chunk_article_text(
    text: str,
    chunk_size_tokens: int = 500,
    chunk_overlap_tokens: int = 50,
) -> list[str]:
    """Split article markdown into overlapping chunks.

    Splits on double newlines (paragraph boundaries). Short paragraphs are
    merged into the current chunk until ``chunk_size_tokens`` is reached;
    paragraphs exceeding the limit are hard-split by character count.

    Args:
        text: Full article text.
        chunk_size_tokens: Target chunk size in approximate tokens.
        chunk_overlap_tokens: Overlap between consecutive chunks in tokens.

    Returns:
        List of chunk strings.
    """
    if not text.strip():
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0
    char_limit = chunk_size_tokens * 4  # rough chars-per-token factor
    overlap_chars = chunk_overlap_tokens * 4

    for para in paragraphs:
        para_tokens = _estimate_tokens(para)

        # If a single paragraph exceeds the limit, hard-split it
        if para_tokens > chunk_size_tokens:
            # Flush current buffer first
            if current_parts:
                chunks.append("\n\n".join(current_parts))
                current_parts = []
                current_tokens = 0

            # Hard-split the oversized paragraph
            start = 0
            while start < len(para):
                end = start + char_limit
                chunk_text = para[start:end]
                chunks.append(chunk_text)
                start = end - overlap_chars if end < len(para) else end
            continue

        # Would adding this paragraph exceed the limit?
        if current_tokens + para_tokens > chunk_size_tokens and current_parts:
            chunks.append("\n\n".join(current_parts))
            # Keep overlap: carry over trailing text from last chunk
            overlap_text = current_parts[-1] if current_parts else ""
            if _estimate_tokens(overlap_text) <= chunk_overlap_tokens:
                current_parts = [overlap_text]
                current_tokens = _estimate_tokens(overlap_text)
            else:
                current_parts = []
                current_tokens = 0

        current_parts.append(para)
        current_tokens += para_tokens

    # Flush remaining
    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks


class EmbeddingService:
    """Manage article embeddings in ChromaDB and perform semantic search.

    Requires the ``[search]`` optional extras (chromadb, sentence-transformers).
    All public methods raise ``RuntimeError`` if the extras are not installed.
    """

    def __init__(self) -> None:
        if not _SEARCH_AVAILABLE:
            raise RuntimeError("Search extras not installed. Install with: pip install 'wikimind[search]'")

        settings = get_settings()
        chroma_path = Path(settings.data_dir) / "db" / "chroma"
        chroma_path.mkdir(parents=True, exist_ok=True)

        self._client: Any = _chromadb.PersistentClient(path=str(chroma_path))  # type: ignore[union-attr]
        self._collection: Any = self._client.get_or_create_collection(
            name="wikimind_chunks",
            metadata={"hnsw:space": "cosine"},
        )
        self._model_name = settings.embedding.model_name
        self._chunk_size = settings.embedding.chunk_size_tokens
        self._chunk_overlap = settings.embedding.chunk_overlap_tokens
        self._min_score = settings.embedding.min_similarity_score
        self._model: Any = None

        log.info(
            "ChromaDB initialized",
            path=str(chroma_path),
            chunks=self._collection.count(),
            model=self._model_name,
        )

    def _get_model(self) -> Any:
        """Lazily load the sentence-transformers model on first use."""
        if self._model is None:
            self._model = _SentenceTransformer(self._model_name)  # type: ignore[misc]
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        """Encode texts into embedding vectors."""
        model = self._get_model()
        embeddings = model.encode(texts, show_progress_bar=False)  # type: ignore[union-attr]
        return [e.tolist() for e in embeddings]  # type: ignore[union-attr]

    def embed_article(self, article_id: str, title: str, content: str) -> int:
        """Chunk and embed an article's content into ChromaDB.

        Any existing embeddings for the article are deleted first so
        re-embedding is idempotent.

        Args:
            article_id: UUID of the article.
            title: Article title (stored as metadata).
            content: Full markdown content of the article.

        Returns:
            Number of chunks embedded.
        """
        # Remove stale embeddings for this article
        self.delete_article(article_id)

        chunks = chunk_article_text(content, self._chunk_size, self._chunk_overlap)
        if not chunks:
            return 0

        embeddings = self._encode(chunks)

        ids = [f"{article_id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "article_id": article_id,
                "article_title": title,
                "chunk_index": i,
            }
            for i in range(len(chunks))
        ]

        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )

        log.info(
            "Article embedded",
            article_id=article_id,
            title=title,
            chunks=len(chunks),
        )
        return len(chunks)

    def search(self, query: str, limit: int = 20) -> list[SemanticSearchResult]:
        """Query ChromaDB for semantically similar chunks.

        Args:
            query: Natural language search query.
            limit: Maximum number of results.

        Returns:
            Ranked list of :class:`SemanticSearchResult`.
        """
        if self._collection.count() == 0:
            return []

        query_embedding = self._encode([query])
        results = self._collection.query(
            query_embeddings=query_embedding,
            n_results=min(limit, self._collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        search_results: list[SemanticSearchResult] = []
        if not results["ids"] or not results["ids"][0]:
            return search_results

        for i, _id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i] if results["distances"] else 0.0  # type: ignore[index]
            # ChromaDB cosine distance is in [0, 2]; convert to similarity score [0, 1]
            score = 1.0 - (distance / 2.0)  # type: ignore[operator]

            # Filter out low-relevance results — ChromaDB always returns top N
            # regardless of actual similarity.
            if score < self._min_score:
                continue

            metadata = results["metadatas"][0][i] if results["metadatas"] else {}  # type: ignore[index]
            document = results["documents"][0][i] if results["documents"] else ""  # type: ignore[index]

            search_results.append(
                SemanticSearchResult(
                    article_id=metadata.get("article_id", ""),  # type: ignore[union-attr]
                    score=score,
                    chunk_text=document,  # type: ignore[arg-type]
                    chunk_index=metadata.get("chunk_index", 0),  # type: ignore[union-attr]
                )
            )

        return search_results

    def delete_article(self, article_id: str) -> None:
        """Remove all embeddings for an article from ChromaDB.

        Args:
            article_id: UUID of the article whose chunks should be removed.
        """
        try:
            self._collection.delete(where={"article_id": article_id})
        except Exception:
            # Collection may be empty or article may not exist -- both are fine
            log.debug("delete_article no-op", article_id=article_id)

    def get_stats(self) -> dict:
        """Return basic statistics about the vector store.

        Returns:
            Dict with ``total_chunks`` count.
        """
        return {
            "total_chunks": self._collection.count(),
        }


# ---------------------------------------------------------------------------
# Module-level singleton (only created when search extras are available)
# ---------------------------------------------------------------------------

_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService | None:
    """Return a singleton EmbeddingService, or None if search extras are missing."""
    global _embedding_service
    if not _SEARCH_AVAILABLE:
        return None
    if _embedding_service is None:
        try:
            _embedding_service = EmbeddingService()
        except Exception:
            log.warning("Failed to initialize EmbeddingService")
            return None
    return _embedding_service
