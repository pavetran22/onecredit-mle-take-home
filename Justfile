set shell := ["bash", "-euo", "pipefail", "-c"]

default: setup

# Install the producer's dependencies.
setup:
    uv sync --locked

# Start Postgres (with pgvector) and RabbitMQ, and wait until both are healthy.
up:
    docker compose up -d --wait

# Stop everything and delete the volumes.
down:
    docker compose down -v

# Replay the registry feed onto the company-events queue.
publish:
    uv run python -m producer.publish

# Run the consumer (reads company-events into Postgres).
consume:
    uv run python -m app.consumer

# Run the similar-companies API on :8000.
api:
    uv run uvicorn app.api:app --port 8000

# Run unit + integration tests (needs `just up`).
test:
    uv run pytest -q

# Compare embedding models on English/Malay translation pairs.
eval:
    uv run python -m evals.cross_lingual
