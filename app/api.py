"""HTTP API for the 'Similar companies' panel."""
from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool
from app.db import DATABASE_URL

async def _configure(conn):
    await register_vector_async(conn)
    # pgvector 0.8: keep scanning the index when filters (e.g. struck_off) remove rows,
    # so we still return `limit` results.
    await conn.execute("SET hnsw.iterative_scan = strict_order")
    await conn.commit()

pool = AsyncConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=False, configure=_configure)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()
    yield
    await pool.close()

app = FastAPI(title="Similar companies", lifespan=lifespan)
CARD = "registration_number, company_name, nature_of_business, state, industry"

def card(row) -> dict:
    keys = ["registrationNumber", "companyName", "natureOfBusiness", "state", "industry"]
    return dict(zip(keys, row[:5]))

@app.get("/health")
async def health():
    async with pool.connection() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}

@app.get("/companies/{registration_number}/similar")
async def similar(registration_number: str, limit: int = Query(5, ge=1, le=20)):
    async with pool.connection() as conn:
        target = await (await conn.execute(
            f"SELECT {CARD}, struck_off, embedding, embedding_source FROM companies WHERE registration_number = %s",
            (registration_number,))).fetchone()
        if target is None:
            raise HTTPException(404, "company not found")
        if target[5]:
            raise HTTPException(410, "company has been struck off")
        rows = await (await conn.execute(
            f"""SELECT {CARD}, 1 - (embedding <=> %s) AS similarity
                FROM companies
                WHERE registration_number <> %s AND NOT struck_off AND embedding IS NOT NULL
                ORDER BY embedding <=> %s
                LIMIT %s""",
            (target[6], registration_number, target[6], limit))).fetchall()
    return {
        "company": card(target),
        "matchedOn": target[7],  # 'nature_of_business' or 'fallback_name_industry'
        "similar": [{**card(r), "similarity": round(float(r[5]), 4)} for r in rows],
    }
