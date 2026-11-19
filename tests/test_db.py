"""Integration tests for the event-apply rules, against the docker-compose Postgres.
Run `just up` first. Uses a separate `companies_test` database."""
import asyncio
import json

import psycopg

from app import db
from app.embed import HashEmbedder
from app.events import parse_event

TEST_URL = db.DATABASE_URL.rsplit("/", 1)[0] + "/companies_test"


class CountingEmbedder(HashEmbedder):
    def __init__(self):
        self.calls = 0

    def embed(self, text):
        self.calls += 1
        return super().embed(text)


def setup_module():
    with psycopg.connect(db.DATABASE_URL, autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname = 'companies_test'").fetchone():
            c.execute("CREATE DATABASE companies_test")


def ev(reg="SYN-1", at="2026-08-14T09:00:00+08:00", type_="company-upserted", **data):
    body = {"type": type_, "registrationNumber": reg, "updatedAt": at}
    if type_ == "company-upserted":
        body["data"] = {"companyName": "A", "natureOfBusiness": "Rubber gloves",
                        "state": "Johor", "industry": "Manufacturing", **data}
    return json.dumps(body).encode()


def scenario(steps):
    """Apply each event body in order on a clean DB; return outcomes and the SYN-1 row."""
    async def go():
        conn = await db.connect(TEST_URL)
        await conn.execute("TRUNCATE companies, rejected_events")
        embedder = CountingEmbedder()
        outcomes = [await db.apply_event(conn, parse_event(b), b, None, embedder) for b in steps]
        row = await (await conn.execute(
            """SELECT company_name, nature_of_business, state, industry, struck_off
               FROM companies WHERE registration_number = 'SYN-1'""")).fetchone()
        counts = await (await conn.execute(
            "SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM rejected_events)")).fetchone()
        await conn.close()
        return outcomes, row, counts, embedder.calls
    return asyncio.run(go())


def test_duplicate_event_is_idempotent():
    outcomes, _, counts, _ = scenario([ev(), ev()])
    assert outcomes == ["applied", "stale"] and counts == (1, 0)


def test_older_event_never_overwrites_newer():
    outcomes, row, _, _ = scenario([ev(at="2026-08-14T10:00:00+08:00", companyName="New"),
                                    ev(at="2026-08-14T09:00:00+08:00", companyName="Old")])
    assert outcomes == ["applied", "stale"] and row[0] == "New"


def test_partial_update_keeps_known_fields():
    _, row, _, _ = scenario([ev(), ev(at="2026-08-14T10:00:00+08:00", state=None, industry=None)])
    assert row[2:4] == ("Johor", "Manufacturing")


def test_struck_off_is_not_resurrected_by_late_older_upsert():
    outcomes, row, _, _ = scenario([
        ev(at="2026-08-14T09:00:00+08:00"),
        ev(at="2026-08-14T16:00:00+08:00", type_="company-struck-off"),
        ev(at="2026-08-14T12:00:00+08:00", companyName="Late")])
    assert outcomes == ["applied", "applied", "stale"] and row[4] is True and row[0] == "A"


def test_newer_upsert_after_strike_off_restores_company():
    _, row, _, _ = scenario([
        ev(at="2026-08-14T16:00:00+08:00", type_="company-struck-off"),
        ev(at="2026-08-14T18:00:00+08:00")])
    assert row[4] is False and row[0] == "A"


def test_bad_messages_are_stored_not_dropped():
    outcomes, _, counts, _ = scenario([b"null", b'{"type": "company-upserted", "data": {"com', ev(at=None)])
    assert all(o.startswith("rejected:") for o in outcomes) and counts == (0, 3)


def test_unchanged_text_is_not_re_embedded():
    *_, calls = scenario([ev(), ev(at="2026-08-14T10:00:00+08:00", companyName="Renamed")])
    assert calls == 1  # the rename does not change the embedded description
