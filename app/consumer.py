"""Consume company-events into Postgres without losing messages.
Ack only after the effect is committed (or stored in rejected_events)."""
from __future__ import annotations
import asyncio, collections, logging, os
import aio_pika
from app.db import apply_event, connect
from app.embed import load_embedder
from app.events import parse_event

QUEUE = "company-events"
RABBITMQ_URL = os.environ.get("RABBITMQ_URL", f"amqp://guest:guest@localhost:{os.environ.get('RABBITMQ_PORT', '5672')}/")
log = logging.getLogger("consumer")

async def run() -> None:
    embedder = load_embedder()  # load once, not per message
    conn = await connect()
    stats = collections.Counter()
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=50)
        # Must match the owner's declaration: durable, no extra arguments.
        queue = await channel.declare_queue(QUEUE, durable=True)
        log.info("consuming from %s", QUEUE)
        async with queue.iterator() as messages:
            async for message in messages:
                try:
                    outcome = await apply_event(conn, parse_event(message.body), message.body, message.message_id, embedder)
                except Exception:
                    log.exception("processing failed, requeueing %s", message.message_id)
                    await message.nack(requeue=True)
                    await asyncio.sleep(1)  # back off during outages
                    continue
                await message.ack()
                stats[outcome] += 1
                if sum(stats.values()) % 250 == 0:
                    log.info("progress %s", dict(stats))

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run())

if __name__ == "__main__":
    main()
