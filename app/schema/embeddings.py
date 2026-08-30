"""
Schema embedding pipeline — stores and retrieves schema metadata via ChromaDB.

Uses sentence-transformers to create dense embeddings of table descriptions,
then retrieves the most relevant tables for a given natural language query.
"""

import os
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer
from loguru import logger

from app.config import settings

# Persistent ChromaDB storage
CHROMA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "chroma_data")

_model: SentenceTransformer | None = None
_client: chromadb.ClientAPI | None = None
_collection = None


def _get_model() -> SentenceTransformer:
    """Lazy-load the embedding model."""
    global _model
    if _model is None:
        logger.info(f"🔄 Loading embedding model: {settings.embedding_model}")
        _model = SentenceTransformer(settings.embedding_model)
        logger.info("✅ Embedding model loaded")
    return _model


def _get_collection():
    """Lazy-load the ChromaDB collection."""
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=os.path.abspath(CHROMA_DIR))
        _collection = _client.get_or_create_collection(
            name="schema_metadata",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"📂 ChromaDB collection ready ({_collection.count()} entries)")
    return _collection


def embed_schema(tables_metadata: list[dict[str, Any]]) -> None:
    """
    Embed all table descriptions and store in ChromaDB.

    Called once at startup or when schema changes.
    """
    model = _get_model()
    collection = _get_collection()

    # Clear existing entries and re-embed
    existing = collection.count()
    if existing > 0:
        # Delete all existing entries
        all_ids = collection.get()["ids"]
        if all_ids:
            collection.delete(ids=all_ids)
        logger.info(f"  Cleared {existing} previous schema entries")

    documents = []
    ids = []
    metadatas = []

    for table in tables_metadata:
        doc = table["description"]
        documents.append(doc)
        ids.append(table["table_name"])
        metadatas.append({
            "table_name": table["table_name"],
            "row_count": table["row_count"],
            "column_count": len(table["columns"]),
        })

    # Generate embeddings
    embeddings = model.encode(documents, show_progress_bar=True).tolist()

    collection.add(
        documents=documents,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas,
    )

    logger.info(f"✅ Embedded {len(tables_metadata)} tables into ChromaDB")


def retrieve_relevant_tables(
    query: str,
    top_k: int = 3,
    all_tables_metadata: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Retrieve the most relevant tables for a natural language query.

    Args:
        query: Natural language question from the user
        top_k: Number of tables to return
        all_tables_metadata: Full metadata list (to return enriched results)

    Returns:
        List of table metadata dicts, ordered by relevance
    """
    model = _get_model()
    collection = _get_collection()

    query_embedding = model.encode([query]).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=min(top_k, collection.count()),
    )

    relevant_table_names = results["ids"][0] if results["ids"] else []
    distances = results["distances"][0] if results["distances"] else []

    logger.info(
        f"🔍 Query: '{query[:60]}...' → Retrieved tables: "
        f"{[f'{n} ({d:.3f})' for n, d in zip(relevant_table_names, distances)]}"
    )

    # If full metadata provided, return enriched results
    if all_tables_metadata:
        meta_lookup = {t["table_name"]: t for t in all_tables_metadata}
        return [
            meta_lookup[name]
            for name in relevant_table_names
            if name in meta_lookup
        ]

    # Return basic results
    return [
        {"table_name": name, "distance": dist}
        for name, dist in zip(relevant_table_names, distances)
    ]
