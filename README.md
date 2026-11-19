# Similar companies service

Consumes company changes from the `company-events` RabbitMQ queue, stores each company in
Postgres with a pgvector embedding of its business description, and serves a fast
"Similar companies" API for the OneCredit portal.

See **[DESIGN.md](DESIGN.md)** for decisions, assumptions, scaling and what's left.

## Prerequisites

- Docker (Desktop) running
- [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just)

## Run it

```bash
just setup        # install dependencies
just up           # start Postgres (pgvector) + RabbitMQ

# Terminal 1: start the consumer (first run downloads the ~470MB embedding model)
just consume      # wait for "consuming from company-events"

# Terminal 2: replay the feed, then start the API
just publish
just api          # http://localhost:8000  (docs at /docs)
```

The consumer can be started before or after `just publish`; messages wait in the durable queue.

## Use the API

```bash
curl localhost:8000/health
curl "localhost:8000/companies/SYN-001777/similar?limit=5"
```

`GET /companies/{registrationNumber}/similar?limit=5` (limit 1–20) returns the company's own
card, which text the match was based on (`matchedOn`), and the most similar active companies,
each with the fields needed to draw a card and a `similarity` score.

| Status | Meaning |
|---|---|
| 200 | Similar companies returned |
| 404 | Unknown registration number |
| 410 | Company has been struck off |

## Test

```bash
just test         # unit tests (parser) + integration tests (needs `just up`)
just eval         # cross-lingual embedding evaluation (downloads both models)
```

Integration tests use a separate `companies_test` database and a deterministic fake
embedder, so they are fast and do not touch your data.

## Inspect what happened

```bash
docker compose exec postgres psql -U postgres -d companies -c \
  "SELECT count(*), count(*) FILTER (WHERE struck_off) AS struck_off FROM companies;"
docker compose exec postgres psql -U postgres -d companies -c \
  "SELECT reason, count(*) FROM rejected_events GROUP BY 1 ORDER BY 2 DESC;"
```

## Configuration

| Variable | Default |
|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/companies` |
| `RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` |
| `POSTGRES_PORT` / `RABBITMQ_PORT` | `5432` / `5672` (used when the URLs are not set) |
| `EMBEDDER` | unset = real model; `hash` = deterministic fake (tests, offline) |

## Layout

```
app/events.py      parse + validate raw messages (never raises)
app/db.py          schema and the rules for applying events
app/embed.py       embedding model (CPU) and a fake for tests
app/consumer.py    RabbitMQ consumer, ack-after-commit
app/api.py         FastAPI similar-companies endpoint
evals/             cross-lingual model evaluation
scripts/           data profiling used to discover the feed's edge cases
tests/             unit and integration tests
```

## Stop

```bash
just down         # stops containers and deletes volumes
```
