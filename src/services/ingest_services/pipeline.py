"""
Qdrant ingestion pipeline — load, chunk, embed, upsert.

This module contains the core service logic for ingesting documents
into Qdrant Cloud.  Scripts (``scripts/ingest_to_qdrant.py``) and CLI
commands should call :func:`run_ingest` rather than duplicating the
pipeline steps.
"""

import json
from loguru import logger
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from infrastructure.config import (
    MARKDOWN_DIR,
    JSONL_DIR,
    KB_DIR,
    QDRANT_COLLECTION_NAME,
    EMBEDDING_BATCH_SIZE,
)
from infrastructure.llm import get_default_embeddings
from infrastructure.db.qdrant_client import (
    ensure_collection,
    delete_collection,
    upsert_chunks,
    collection_info,
)
from .chunkers import (
    semantic_chunk,
    fixed_chunk,
    sliding_chunk,
    parent_child_chunk,
)
# =====================================================================
# Strategy registry
# =====================================================================

STRATEGY_MAP = {
    "semantic": semantic_chunk,
    "fixed": fixed_chunk,
    "sliding": sliding_chunk,
    "parent_child": parent_child_chunk,
}


# =====================================================================
# Document loaders
# =====================================================================


def load_kb_docs(kb_dir: Path | None = None) -> List[Dict[str, Any]]:
    """Load internal knowledge-base markdown documents."""
    kb_dir = Path(kb_dir or KB_DIR)
    if not kb_dir.exists():
        raise FileNotFoundError(f"Knowledge-base directory not found: {kb_dir}")

    docs: List[Dict[str, Any]] = []
    for md_file in sorted(kb_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8").strip()
        if not content:
            continue

        title = content.split("\n", 1)[0].lstrip("# ").strip() or md_file.stem
        doc_slug = md_file.stem.lstrip("0123456789_")
        url = f"internal://nawaloka/{doc_slug}"
        docs.append({"url": url, "title": title, "content": content})

    logger.info("Loaded {} knowledge-base documents from {}", len(docs), kb_dir)
    return docs


def load_markdown_docs(md_dir: Path | None = None) -> List[Dict[str, Any]]:
    """Load crawled markdown files from disk."""
    md_dir = Path(md_dir or MARKDOWN_DIR)
    if not md_dir.exists():
        raise FileNotFoundError(f"Markdown directory not found: {md_dir}")

    docs: List[Dict[str, Any]] = []
    for md_file in sorted(md_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8").strip()
        if not content:
            continue

        lines = content.splitlines()
        title_lines: List[str] = []
        if lines:
            title_lines.append(lines[0].lstrip("# ").strip())
            for line in lines[1:]:
                stripped = line.strip()
                if not stripped or stripped.startswith("**"):
                    break
                title_lines.append(stripped)

        title = " ".join(part for part in title_lines if part).strip() or md_file.stem

        metadata: Dict[str, str] = {}
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("**URL**:"):
                metadata["url"] = stripped.split(":", 1)[1].strip()
                continue

            if ":" not in stripped or stripped.startswith("**"):
                continue

            key, value = stripped.split(":", 1)
            key = key.strip().lower().replace(" ", "_")
            if key in {"product_name", "partner", "price", "description"}:
                metadata[key] = value.strip()

        docs.append(
            {
                "url": metadata.get("url", ""),
                "title": title,
                "content": content,
                "product_name": metadata.get("product_name", title),
                "partner": metadata.get("partner"),
                "price": metadata.get("price"),
                "description": metadata.get("description", ""),
            }
        )

    logger.info("Loaded {} markdown documents from {}", len(docs), md_dir)
    return docs


def load_jsonl_docs(jsonl_dir: Path | None = None) -> List[Dict[str, Any]]:
    """Load documents from JSONL crawl output."""
    jsonl_path = Path(jsonl_dir or JSONL_DIR)
    if not jsonl_path.exists():
        raise FileNotFoundError(f"JSONL file or directory not found: {jsonl_path}")

    if jsonl_path.is_file():
        jsonl_files = [jsonl_path]
    else:
        jsonl_files = sorted(jsonl_path.glob("*.jsonl"))
        if not jsonl_files:
            raise FileNotFoundError(f"No JSONL files found in directory: {jsonl_path}")

    docs: List[Dict[str, Any]] = []
    for jsonl_file in jsonl_files:
        with open(jsonl_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("content"):
                    doc = {
                        "url": obj.get("url", ""),
                        "title": obj.get("title") or obj.get("product_name", ""),
                        "content": obj["content"],
                        "product_name": obj.get("product_name", ""),
                        "partner": obj.get("partner"),
                        "price": obj.get("price"),
                        "availability": obj.get("availability"),
                        "delivery_info": obj.get("delivery_info", []),
                        "tags": obj.get("tags", []),
                        "description": obj.get("description", ""),
                        "product_id": obj.get("product_id"),
                        "product_type": obj.get("product_type"),
                        "quantity": obj.get("quantity"),
                        "color_options": obj.get("color_options", []),
                        "size_options": obj.get("size_options", []),
                        "option_values": obj.get("option_values", []),
                        "supports_custom_text": obj.get("supports_custom_text", False),
                        "custom_text_max_length": obj.get("custom_text_max_length"),
                        "custom_text_placeholder": obj.get("custom_text_placeholder"),
                    }
                    docs.append(doc)

    logger.info("Loaded {} documents from JSONL in {}", len(docs), jsonl_path)
    return docs


LOADER_MAP = {
    "kb": load_kb_docs,
    "markdown": load_markdown_docs,
    "jsonl": load_jsonl_docs,
}


# =====================================================================
# Embedding helper
# =====================================================================


def embed_texts(
    texts: List[str],
    batch_size: int = EMBEDDING_BATCH_SIZE,
) -> List[List[float]]:
    """Embed a list of texts using the configured embedding model."""
    embedder = get_default_embeddings(batch_size=batch_size)
    all_embeddings: List[List[float]] = []

    total_batches = (len(texts) + batch_size - 1) // batch_size
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        batch_num = i // batch_size + 1
        logger.info(
            "Embedding batch {}/{} ({} texts)...",
            batch_num,
            total_batches,
            len(batch),
        )
        batch_embeddings = embedder.embed_documents(batch)
        all_embeddings.extend(batch_embeddings)

    return all_embeddings


# =====================================================================
# Parent-child helpers
# =====================================================================


def _build_parent_lookup(parents: List[Dict[str, Any]]) -> Dict[str, str]:
    """Build a mapping from parent_id → parent text."""
    return {p["parent_id"]: p["text"] for p in parents}


def _enrich_children_with_parent_text(
    children: List[Dict[str, Any]],
    parent_lookup: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Attach ``parent_text`` to each child chunk for richer LLM context."""
    for child in children:
        pid = child.get("parent_id", "")
        child["parent_text"] = parent_lookup.get(pid, child["text"])
    return children


# =====================================================================
# Core pipeline
# =====================================================================


def run_ingest(
    source: str = "kb",
    strategy: str = "parent_child",
    recreate: bool = False,
) -> int:
    """
    End-to-end ingestion pipeline.

    Args:
        source: One of ``kb``, ``markdown``, ``jsonl``.
        strategy: One of ``semantic``, ``fixed``, ``sliding``, ``parent_child``.
        recreate: If ``True``, drop and recreate the Qdrant collection first.

    Returns:
        Number of points upserted.

    Raises:
        ValueError: If *source* or *strategy* is unknown.
        FileNotFoundError: If the source directory does not exist.
    """
    logger.info("=" * 70)
    logger.info("🚀 QDRANT INGESTION PIPELINE")
    logger.info("=" * 70)

    # ── 1. Load documents ────────────────────────────────────
    loader = LOADER_MAP.get(source)
    if loader is None:
        raise ValueError(
            f"Unknown source: {source}. Choose from {list(LOADER_MAP.keys())}"
        )

    logger.info(f"\n📂 Loading documents (source={source})...")
    docs = loader()
    if not docs:
        logger.error("❌ No documents loaded. Nothing to ingest.")
        sys.exit(1)

    # ── 2. Chunk ─────────────────────────────────────────────
    logger.info(f"\n✂️  Chunking (strategy={strategy})...")
    chunk_fn = STRATEGY_MAP.get(strategy)
    if chunk_fn is None:
        raise ValueError(
            f"Unknown strategy: {strategy}. Choose from {list(STRATEGY_MAP.keys())}"
        )

    if strategy == "parent_child":
        children, parents = chunk_fn(docs)
        logger.info(f"   → {len(children)} child chunks, {len(parents)} parent chunks")
        parent_lookup = _build_parent_lookup(parents)
        chunks = _enrich_children_with_parent_text(children, parent_lookup)
        logger.info("   → Each child enriched with parent_text for richer LLM context")
    else:
        chunks = chunk_fn(docs)
        logger.info(f"   → {len(chunks)} chunks created")

    if not chunks:
        logger.error("❌ No chunks produced. Check your documents.")
        sys.exit(1)

    # ── 3. Embed ─────────────────────────────────────────────
    logger.info(f"\n🔢 Embedding {len(chunks)} chunks...")
    texts = [c["text"] for c in chunks]
    t0 = time.time()
    embeddings = embed_texts(texts)
    embed_secs = time.time() - t0
    logger.success(f"   → Embedding done in {embed_secs:.1f}s")

    # ── 4. Create / recreate collection ──────────────────────
    if recreate:
        logger.info(f"\n🗑️  Recreating collection '{QDRANT_COLLECTION_NAME}'...")
        try:
            delete_collection()
        except Exception:
            pass  # collection may not exist yet

    ensure_collection()

    # ── 5. Upsert ────────────────────────────────────────────
    logger.info(f"\n⬆️  Upserting {len(chunks)} points into Qdrant...")
    t0 = time.time()
    n = upsert_chunks(chunks, embeddings)
    upsert_secs = time.time() - t0
    logger.info(f"   → Upserted {n} points in {upsert_secs:.1f}s")

    # ── 6. Verify ────────────────────────────────────────────
    logger.info("\n📊 Collection info:")
    info = collection_info()
    for k, v in info.items():
        logger.info(f"   {k}: {v}")

    logger.info("\n" + "=" * 70)
    logger.success("✅ INGESTION COMPLETE")
    logger.info(f"   Source: {source}")
    logger.info(f"   Strategy: {strategy}")
    logger.info(f"   Chunks indexed: {n}")
    if strategy == "parent_child":
        logger.info("   Parent context: Stored in payload for richer LLM generation")
    logger.info("=" * 70)

    return n
