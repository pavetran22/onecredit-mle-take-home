"""Postgres schema and the rules for applying events."""
from __future__ import annotations

import asyncio
import os

import psycopg
from pgvector.psycopg import register_vector_async

from app.embed import Embedder
from app.events import Rejected, StruckOff, Upsert, embedding_text

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"postgresql://postgres:postgres@localhost:{os.environ.get('POSTGRES_PORT', '5432')}/companies",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    registration_number TEXT PRIMARY KEY,
    company_name        TEXT,                  -- NULL only if a strike-off arrived before any upsert
    nature_of_business  TEXT,
    state               TEXT,
    industry            TEXT,
    struck_off          BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at          TIMESTAMPTZ NOT NULL,  -- event time of the latest applied event
    embedding           vector(384),
    embedding_source    TEXT,                  -- 'nature_of_business' or 'fallback_name_industry'
    embedded_text       TEXT,                  -- lets us skip re-embedding unchanged text
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS companies_embedding_hnsw
    ON companies USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS rejected_events (
    id          BIGSERIAL PRIMARY KEY,
    reason      TEXT NOT NULL,
    message_id  TEXT,
    body        TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

UPSERT_SQL = """
INSERT INTO companies AS c (registration_number, company_name, nature_of_business, state, industry,
                            struck_off, updated_at, embedding, embedding_source, embedded_text)
VALUES (%s, %s, %s, %s, %s, FALSE, %s, %s, %s, %s)
ON CONFLICT (registration_number) DO UPDATE SET
    company_name       = EXCLUDED.company_name,
    nature_of_business = EXCLUDED.nature_of_business,
    state              = EXCLUDED.state,
    industry           = EXCLUDED.industry,
    struck_off         = FALSE,
    updated_at         = EXCLUDED.updated_at,
    embedding          = EXCLUDED.embedding,
    embedding_source   = EXCLUDED.embedding_source,
    embedded_text      = EXCLUDED.embedded_text,
    ingested_at        = now()
WHERE c.updated_at < EXCLUDED.updated_at
"""

STRUCK_OFF_SQL = """
INSERT INTO companies AS c (registration_number, struck_off, updated_at)
VALUES (%s, TRUE, %s)
ON CONFLICT (registration_number) DO UPDATE SET
    struck_off = TRUE, updated_at = EXCLUDED.updated_at, ingested_at = now()
WHERE c.updated_at < EXCLUDED.updated_at
"""


async def connect() -> psycopg.AsyncConnection:
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True)
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await register_vector_async(conn)
    await conn.execute(SCHEMA)
    return conn


async def record_rejected(conn, reason: str, body: bytes, message_id: str | None) -> None:
    await conn.execute(
        "INSERT INTO rejected_events (reason, message_id, body) VALUES (%s, %s, %s)",
        (reason, message_id, body.decode("utf-8", errors="replace")),
    )


async def apply_upsert(conn, e: Upsert, embedder: Embedder) -> str:
    async with conn.transaction():
        # Lock this company's row so the read-merge-write below is atomic.
        row = await (await conn.execute(
            """SELECT nature_of_business, state, industry, updated_at, embedded_text, embedding
               FROM companies WHERE registration_number = %s FOR UPDATE""",
            (e.registration_number,),
        )).fetchone()
        old_nature, old_state, old_industry, old_updated, old_text, old_vector = row or (None,) * 6

        if old_updated is not None and old_updated >= e.updated_at:
            return "stale"  # we already hold newer (or identical) information

        # A missing field means "not provided in this event", so keep what we knew.
        nature = e.nature_of_business or old_nature
        state = e.state or old_state
        industry = e.industry or old_industry

        text, source = embedding_text(nature, e.company_name, industry)
        if text == old_text and old_vector is not None:
            vector = old_vector  # unchanged text: no need to re-embed
        else:
            vector = await asyncio.to_thread(embedder.embed, text)  # CPU work off the event loop

        await conn.execute(UPSERT_SQL, (e.registration_number, e.company_name, nature, state,
                                        industry, e.updated_at, vector, source, text))
        return "applied"


async def apply_struck_off(conn, e: StruckOff) -> str:
    # Keep a tombstone instead of deleting, so an older upsert arriving late cannot resurrect it.
    cur = await conn.execute(STRUCK_OFF_SQL, (e.registration_number, e.updated_at))
    return "applied" if cur.rowcount else "stale"


async def apply_event(conn, event, body: bytes, message_id: str | None, embedder: Embedder) -> str:
    if isinstance(event, Rejected):
        await record_rejected(conn, event.reason, body, message_id)
        return f"rejected:{event.reason}"
    if isinstance(event, StruckOff):
        return await apply_struck_off(conn, event)
    return await apply_upsert(conn, event, embedder)
