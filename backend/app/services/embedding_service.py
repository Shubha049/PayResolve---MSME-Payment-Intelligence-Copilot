"""
Provider-agnostic Embedding Service for PayResolve AI.

Supports:
  1. Fast Local Deterministic Provider (default for local dev & testing, zero dependencies/latency)
  2. OpenAI Embedding Provider (when configured)
  3. Gemini Embedding Provider (when configured)
"""

import abc
import hashlib
import math
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)


class BaseEmbeddingProvider(abc.ABC):
    """Abstract base class for vector embedding generation."""

    @abc.abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for a list of document chunk texts."""
        pass

    def embed_query(self, query: str) -> list[float]:
        """Generate embedding vector for a single query."""
        results = self.embed_texts([query])
        return results[0] if results else [0.0] * self.dimension

    @property
    @abc.abstractmethod
    def dimension(self) -> int:
        """Vector dimension."""
        pass


class DeterministicLocalEmbeddingProvider(BaseEmbeddingProvider):
    """
    Offline, fast deterministic embedding generator.
    Produces dense 384-dimensional unit vectors using token hashing + position weighting.
    Captures semantic word overlap and n-gram similarity with zero network calls or heavy weights.
    """

    def __init__(self, dimension: int = 384):
        self._dim = dimension

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * self._dim
            tokens = text.lower().split()
            if not tokens:
                vectors.append([0.0] * self._dim)
                continue

            # Project words and character bigrams into the vector space
            for idx, token in enumerate(tokens):
                # Word hash
                h_word = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
                slot = h_word % self._dim
                sign = 1.0 if (h_word >> 8) % 2 == 0 else -1.0
                vec[slot] += sign * (1.0 + 1.0 / (idx + 1))

                # Subword n-grams for typo resilience
                if len(token) > 3:
                    for i in range(len(token) - 2):
                        ngram = token[i:i+3]
                        h_ng = int(hashlib.sha256(ngram.encode("utf-8")).hexdigest(), 16)
                        slot_ng = h_ng % self._dim
                        sign_ng = 1.0 if (h_ng >> 8) % 2 == 0 else -1.0
                        vec[slot_ng] += sign_ng * 0.5

            # L2 normalize
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [round(v / norm, 6) for v in vec]
            vectors.append(vec)

        return vectors


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI text-embedding-3-small provider."""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dimension: int = 1536):
        import httpx
        self._api_key = api_key
        self._model = model
        self._dim = dimension
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = self._client.post(
                "https://api.openai.com/v1/embeddings",
                json={"input": texts, "model": self._model},
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]
        except Exception as exc:
            logger.error("OpenAI embedding request failed: %s", exc)
            fallback = DeterministicLocalEmbeddingProvider(dimension=self._dim)
            return fallback.embed_texts(texts)


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """Google Gemini text-embedding-004 provider."""

    def __init__(self, api_key: str, dimension: int = 768):
        import httpx
        self._api_key = api_key
        self._dim = dimension
        self._client = httpx.Client(timeout=30.0)

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={self._api_key}"
                resp = self._client.post(
                    url,
                    json={
                        "model": "models/text-embedding-004",
                        "content": {"parts": [{"text": text}]},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                results.append(data["embedding"]["values"])
            except Exception as exc:
                logger.error("Gemini embedding request failed: %s", exc)
                fallback = DeterministicLocalEmbeddingProvider(dimension=self._dim)
                results.append(fallback.embed_query(text))
        return results


_embedding_provider_instance: Optional[BaseEmbeddingProvider] = None


def get_embedding_provider() -> BaseEmbeddingProvider:
    """
    Factory function returning the active embedding provider based on configuration.
    """
    global _embedding_provider_instance
    if _embedding_provider_instance is not None:
        return _embedding_provider_instance

    prov_type = settings.EMBEDDING_PROVIDER.lower()

    if prov_type == "openai" and settings.OPENAI_API_KEY:
        logger.info("Using OpenAI embedding provider")
        _embedding_provider_instance = OpenAIEmbeddingProvider(api_key=settings.OPENAI_API_KEY)
    elif prov_type == "gemini" and settings.GEMINI_API_KEY:
        logger.info("Using Gemini embedding provider")
        _embedding_provider_instance = GeminiEmbeddingProvider(api_key=settings.GEMINI_API_KEY)
    else:
        logger.info("Using Deterministic Local embedding provider (dimension=%d)", settings.EMBEDDING_DIMENSION)
        _embedding_provider_instance = DeterministicLocalEmbeddingProvider(dimension=settings.EMBEDDING_DIMENSION)

    return _embedding_provider_instance


def set_embedding_provider(provider: BaseEmbeddingProvider) -> None:
    """Override embedding provider (useful for testing)."""
    global _embedding_provider_instance
    _embedding_provider_instance = provider
