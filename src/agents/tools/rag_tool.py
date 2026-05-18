"""
RAG Tool -- Kapruka product knowledge-base retrieval via CAG + CRAG pipeline.

Architecture:
    Query --> CAGService
              --> Qdrant cag_cache (KNN-1 semantic cache)
              --> HIT? Return instantly (0ms, $0)
              --> MISS? --> CRAGService (self-correcting retrieval)
                           --> Qdrant Kapruka product catalog KB
                           --> Confidence gate (>= configured threshold, or expand k)
                           --> LLM generates product-aware answer
              --> Cache the result for future semantic hits

In the Kapruka agent:
- Product catalog chunks are stored in Qdrant.
- User profile data is stored in the CRM users table.
- User preferences, allergies, and budget facts are stored in mem_facts.
- This tool should only retrieve product/catalog/internal FAQ knowledge.
"""

from loguru import logger
from typing import Any, Dict, List, Optional

from infrastructure.config import (
    TOP_K_RESULTS,
    SIMILARITY_THRESHOLD,
    CRAG_CONFIDENCE_THRESHOLD,
    CRAG_EXPANDED_K,
)
from infrastructure.observability import observe


class RAGTool:
    """
    Kapruka product/catalog retrieval tool backed by CAGService + CRAGService.

    Responsibilities:
    1. Search the Kapruka product knowledge base stored in Qdrant.
    2. Use CAG cache for common product/delivery/FAQ questions.
    3. Use CRAG when cached answers are unavailable.
    4. Return plain-text answers for the routing/synthesis layer.

    This tool should not update user preferences.
    Preference facts should be handled by the memory/preference update router.
    """

    def __init__(
        self,
        embedder: Any,
        llm: Optional[Any] = None,
    ) -> None:
        self.embedder = embedder
        self.llm = llm

        from services.chat_service.cag_cache import CAGCache
        from services.chat_service.rag_service import QdrantRetriever
        from services.chat_service.crag_service import CRAGService
        from services.chat_service.cag_service import CAGService

        self._cache = CAGCache(embedder=embedder)
        self._cag_service: Optional[CAGService] = None

        if llm is not None:
            retriever = QdrantRetriever(
                embedder=embedder,
                top_k=TOP_K_RESULTS,
                score_threshold=SIMILARITY_THRESHOLD,
            )

            crag_service = CRAGService(
                retriever=retriever,
                llm=llm,
                initial_k=TOP_K_RESULTS,
                expanded_k=CRAG_EXPANDED_K,
            )

            self._cag_service = CAGService(
                crag_service=crag_service,
                cache=self._cache,
            )

            logger.info(
                "Kapruka RAGTool initialised: CAG cache ({}) -> CRAG "
                "(k={}, expanded_k={}, threshold={:.2f})",
                self._cache,
                TOP_K_RESULTS,
                CRAG_EXPANDED_K,
                CRAG_CONFIDENCE_THRESHOLD,
            )
        else:
            logger.info("Kapruka RAGTool initialised in raw product-search mode (no LLM)")

    @observe(name="kapruka_rag_search")
    def search(
        self,
        query: str,
        top_k: int = TOP_K_RESULTS,
        threshold: float = SIMILARITY_THRESHOLD,
        use_cache: bool = True,
    ) -> str:
        """
        Retrieve and generate an answer from the Kapruka internal knowledge base.

        Suitable queries:
        - "Find a birthday cake under Rs. 5000"
        - "Suggest chocolate gifts"
        - "What gifts are available for anniversaries?"
        - "Can this product be delivered to Kandy?"
        - "What are common delivery rules?"

        Pipeline:
        CAG cache check -> CRAG retrieval -> LLM answer -> cache result
        """
        if not query or not query.strip():
            return "Please provide a product, gift, delivery, or catalog-related query."

        if self._cag_service is not None:
            try:
                result = self._cag_service.generate(query, use_cache=use_cache)
                answer = result.get("answer", "")
                return answer or "No relevant Kapruka product information found."
            except Exception as exc:
                logger.error("Kapruka CAG+CRAG pipeline failed: {}", exc)
                return self._raw_search(query, top_k, threshold)

        return self._raw_search(query, top_k, threshold)

    def _raw_search(
        self,
        query: str,
        top_k: int = TOP_K_RESULTS,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> str:
        """
        Fallback direct Qdrant search returning formatted product/catalog chunks.

        This mode is useful during development when the LLM is disabled.
        """
        from infrastructure.db.qdrant_client import search_chunks

        try:
            query_vec = self.embedder.embed_query(query)
        except Exception as exc:
            logger.error("Kapruka query embedding failed: {}", exc)
            return f"RAG embedding error: {exc}"

        try:
            results = search_chunks(
                query_vector=query_vec,
                top_k=top_k,
                score_threshold=threshold,
            )
        except Exception as exc:
            logger.error("Kapruka Qdrant product search failed: {}", exc)
            return f"RAG search error: {exc}"

        if not results:
            return "No matching Kapruka products or internal knowledge found."

        seen_items: set = set()
        lines: List[str] = [f"Kapruka product KB results ({len(results)} chunks):"]

        for idx, hit in enumerate(results, 1):
            product_id = hit.get("product_id") or hit.get("parent_id")
            if product_id and product_id in seen_items:
                continue
            if product_id:
                seen_items.add(product_id)

            similarity = f"{hit.get('score', 0):.2f}"
            title = (
                hit.get("product_name")
                or hit.get("title")
                or "Untitled product"
            )
            price = hit.get("price") or "Price not available"
            availability = hit.get("availability") or "Availability not available"
            url = hit.get("url") or hit.get("product_url") or "N/A"
            text = hit.get("parent_text") or hit.get("chunk_text") or ""

            lines.append(f"\n--- Result {idx} (similarity {similarity}) ---")
            lines.append(f"Product: {title}")
            lines.append(f"Price: {price}")
            lines.append(f"Availability: {availability}")
            lines.append(f"URL: {url}")
            if text:
                lines.append(text)

        return "\n".join(lines)

    def product_search(
        self,
        query: str,
        top_k: int = TOP_K_RESULTS,
        threshold: float = SIMILARITY_THRESHOLD,
        use_cache: bool = True,
    ) -> str:
        """
        Explicit product search action.

        This is a semantic product/catalog search over Qdrant.
        It does not apply user preference filtering by itself.
        The main agent or reflection layer should combine this result with mem_facts.
        """
        return self.search(
            query=query,
            top_k=top_k,
            threshold=threshold,
            use_cache=use_cache,
        )

    def delivery_knowledge_search(
        self,
        query: str,
        use_cache: bool = True,
    ) -> str:
        """
        Search internal delivery/logistics knowledge.

        This should retrieve general delivery rules or FAQ knowledge.
        Specific validation logic can still be handled by a separate logistics router.
        """
        delivery_query = f"Kapruka delivery logistics rules: {query}"
        return self.search(query=delivery_query, use_cache=use_cache)

    def warm_cache(self, queries: List[str]) -> int:
        """
        Pre-populate CAG cache with common Kapruka FAQ/product queries.

        Example queries:
        - "How long does Kapruka delivery take?"
        - "Does Kapruka offer same-day delivery?"
        - "What birthday gifts are popular?"
        """
        if self._cag_service is None:
            logger.warning("Cannot warm CAG cache because LLM-backed CAG service is not enabled")
            return 0

        return self._cag_service.warm_cache(queries)

    def cache_stats(self) -> Dict[str, Any]:
        """Return CAG cache statistics."""
        return self._cache.stats()

    def clear_cache(self) -> None:
        """Clear Kapruka CAG cache."""
        self._cache.clear()
        logger.info("Kapruka CAG cache cleared")

    def dispatch(self, action: str, params: Dict[str, Any]) -> str:
        """
        Dispatch a Kapruka RAG action by name.

        Available actions:
        - search
        - product_search
        - delivery_knowledge_search
        - cache_stats
        - clear_cache
        """
        handler_map = {
            "search": self.search,
            "product_search": self.product_search,
            "delivery_knowledge_search": self.delivery_knowledge_search,
        }

        if action in handler_map:
            return handler_map[action](**params)

        if action == "cache_stats":
            return f"Kapruka CAG cache: {self.cache_stats()}"

        if action == "clear_cache":
            self.clear_cache()
            return "Kapruka CAG cache cleared."

        return (
            f"Unknown Kapruka RAG action: {action}. "
            f"Available: {list(handler_map.keys()) + ['cache_stats', 'clear_cache']}"
        )
