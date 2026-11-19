# DESIGN

## What I built

```
company-events (RabbitMQ) ──> consumer ──> Postgres + pgvector <── FastAPI /companies/{id}/similar
                                 │
                                 └──> rejected_events (bad messages, with reason)
```

- **Consumer** (`app/consumer.py`): reads the queue one message at a time, parses it, applies it
  in a transaction, and acknowledges only after the effect is committed.
- **Parser** (`app/events.py`): turns every message into exactly one of `Upsert`, `StruckOff` or
  `Rejected(reason)`. It never raises, so one bad message cannot stop the consumer.
- **Storage** (`app/db.py`): one row per company (latest state), an HNSW cosine index on the
  embedding, and a `rejected_events` table.
- **API** (`app/api.py`): two-stage search: the HNSW index finds candidates, then a small re-rank
  makes results stable and slightly favours the same industry and state.

## What the feed actually contains

I profiled the feed before writing the consumer (`scripts/explore*.py`). It is deliberately messy:

| Finding | Count | Handling |
|---|---|---|
| Messages published | 2,518 | |
| Companies | 2,022 | All stored, verified against an independent count |
| Companies with more than one event | 363 | Upsert keyed on `registrationNumber` |
| Out-of-order events (older after newer) | 66 | Ignored: only strictly newer events apply |
| Exact repeats (same timestamp) | 63 | Ignored (idempotent) |
| `company-struck-off` events | 8 | Tombstone, hidden from results |
| Timestamps with no offset | 14 | Assumed Malaysia time (+08:00) |
| Timestamps as epoch milliseconds | some | Converted (UTC) |
| Partial upserts (`null`/empty fields) | 214 | **Kept**, see below |
| Descriptions repeated ~60× in one string | several | Collapsed to one copy |
| Malay descriptions | ~30% | Drove the model choice |
| Unusable messages | 37 | Stored in `rejected_events` |

The 37 rejected messages: 10 missing `registrationNumber`, 9 with `data` as a string
(`"companyName=Foo; state=Perak"`), 7 with an unparseable `updatedAt`, 6 literal `null`, 5
truncated JSON. None can be safely applied: without an id we cannot know which company, and
without a valid timestamp we cannot order it.

## Key decisions

**No message is lost.** A message is acked only after its transaction commits, or after it is
written to `rejected_events`. If processing fails unexpectedly (e.g. the database is down) the
message is nacked and requeued with a back-off. Crashing mid-message means RabbitMQ redelivers
it; that is safe because applying an event is idempotent.

**Latest information wins, by event time, not arrival time.** Each row stores the `updatedAt` of
the event that produced it. An event applies only if it is strictly newer. This is enforced
twice: in Python after reading the row under `SELECT ... FOR UPDATE`, and in SQL with
`ON CONFLICT ... DO UPDATE ... WHERE c.updated_at < EXCLUDED.updated_at`, so the database itself
refuses stale writes.

**Partial upserts are kept, not rejected.** My first version rejected events with any missing
field. Checking the data showed this would lose **186 companies entirely**, because every event
for them has a blank field. So only `companyName` is required (a card cannot be drawn without
it). A missing field means "not provided in this event", so the previous value is kept
(merge), rather than "erase it".

**Struck-off companies become tombstones, not deletes.** If we deleted the row, an older upsert
arriving late would recreate the company. Keeping the row with its timestamp makes late events
stale. A strictly newer upsert restores the company (latest event wins). Struck-off companies
are excluded from results, and requesting one returns `410 Gone`.

**I did not add a dead-letter exchange to the queue.** The producer notes the registry team owns
`company-events` and declares it durable with no extra arguments. Redeclaring it with
`x-dead-letter-exchange` would fail with a precondition error and could disrupt the owner. Bad
messages go to a `rejected_events` table instead, with the reason, message id and raw body, so
they can be inspected and replayed.

**Companies without a description are still searchable.** 39 companies never have a
`natureOfBusiness`. They are embedded from `companyName (industry)`, and `embedding_source`
records this, so the API can tell the UI the match is weaker (`matchedOn`).

**Re-embed only when the text changes.** Rows store `embedded_text`. A rename or state change
reuses the existing vector. There are only 208 distinct embedded texts across 2,022 companies.

## Choosing the embedding model (my "go deeper" area)

The brief suggests `BAAI/bge-small-en-v1.5`, an English-only model, but about 30% of
descriptions are Malay. I first used `intfloat/multilingual-e5-small` and checked real results.
They were biased by language: for *"Kerja-kerja kejuruteraan awam jalan dan saliran"* the nearest
descriptions were unrelated Malay ones (office renovation, umrah travel, kindergartens), while
its exact English translation, *"Civil engineering works for roads and drainage"* (28
companies), did not appear in the top 20.

To measure this rather than guess, I built `evals/cross_lingual.py`: 78 hand-labelled
English↔Malay translation pairs, 72 of which have both sides in the feed. For each description it checks where its
translation ranks among all 172 distinct descriptions (144 queries, both directions).

| Model (both 384-dim, CPU) | Recall@1 | Recall@5 | MRR |
|---|---|---|---|
| intfloat/multilingual-e5-small | 0.21 | 0.29 | 0.30 |
| **sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2** | **0.52** | **0.80** | **0.65** |

The paraphrase model is trained on translation pairs, so translations land close together. I
switched to it. In the API, the Malay civil-engineering company now gets the English
civil-engineering companies immediately after its exact matches. Many remaining misses are the
strict city variants (e.g. *"Hotel butik di Ipoh"* must beat *"Boutique hotel in Kuching"*).

**Ranking.** Many companies share an identical description (similarity 1.0), and Postgres
returns ties in arbitrary order, so the same page could show different cards on each load. The
API takes the top 200 candidates from the HNSW index, then sorts by similarity plus a small
same-industry boost (+0.1, since industry is language-independent), then same state, then
registration number, which makes the results deterministic. `hnsw.iterative_scan` (pgvector 0.8)
keeps scanning when the struck-off filter removes candidates.

## Assumptions

- `registrationNumber` identifies a company. `updatedAt` is the event time and defines "latest".
- Timestamps without an offset are Malaysia time (+08:00). Integer timestamps are epoch
  milliseconds (or seconds if small).
- Two events with an identical timestamp for one company are duplicates; the first one wins.
- `null`/empty fields mean "not provided", not "cleared".
- A strike-off followed by a newer upsert means the company was restored.
- State names are normalised to title case (`JOHOR` becomes `Johor`).
- "Fast enough to render while the page loads": measured 5–8 ms per request locally.

## How I tested it

- **Unit tests** (`tests/test_events.py`): parsing, timestamps (offset, naive, epoch), each
  rejection reason, partial upserts, the description clean-up and the embedding fallback.
- **Integration tests** (`tests/test_db.py`, real Postgres, fake embedder): duplicate events are
  idempotent; an older event never overwrites a newer one; partial updates keep known fields;
  a late older upsert cannot resurrect a struck-off company; a newer upsert restores it; bad
  messages are stored, not dropped; unchanged text is not re-embedded.
- **End to end**: replayed the full feed and reconciled counts: 2,022 companies stored equals
  the 2,022 distinct companies with a valid event computed independently from the file, and all
  37 rejected messages are present with reasons. Checked 404, 410, latency and result quality by
  hand.
- **Model evaluation** as above.

Not yet tested automatically: the RabbitMQ consumer loop itself (redelivery after a crash) and
the API endpoints. I verified both manually.

## 10× the volume

At this size everything is comfortably fast. For 10× (about 25k events per replay and 20k
companies), in order of impact:

1. **Batch embedding.** Embedding one text at a time is the main cost. Encode batches of
   messages together (e.g. 64), then write in one transaction.
2. **Cache embeddings by text.** Only 208 distinct texts exist for 2,022 companies. A
   `text → vector` cache (a table, or an in-process LRU) would avoid roughly 90% of model calls.
3. **Several consumers.** Correctness already holds with concurrent consumers for existing
   rows, because of the row lock and the SQL timestamp guard. For brand-new companies, I would
   add `pg_advisory_xact_lock(hashtext(registration_number))` so two consumers cannot merge the
   same new company at once. Alternatively, partition by registration number (consistent-hash
   exchange) so each company is always handled by one consumer.
4. **Database.** HNSW scales to millions of rows. Tune `m` / `ef_construction` / `ef_search`
   against recall. The API already uses a connection pool. Add read replicas for the API if
   needed.
5. **API caching.** Cache responses per company, invalidated when any of its candidates
   changes, or simply with a short TTL.

## Offline scores vs production

A model that scores well offline can still fail here because:
- **The data shifts.** New industries, new languages or new description templates may not look
  like the 172 descriptions I evaluated on.
- **My eval measures translation matching, not usefulness.** Whether a user clicks or finds a
  recommended company relevant is a different question. In production I would track
  click-through on the panel and sample results for human review.
- **Upstream quality changes.** If the registry starts sending more blank descriptions, more
  companies fall back to name-based embeddings and quality drops quietly. `embedding_source`
  makes that measurable.
- **Model and index drift.** Changing the model means re-embedding everything. Mixing vectors
  from two models silently breaks similarity, so a model version should be stored per row.

## What's left

- Monitoring: queue depth and consumer lag, rejected-event rate by reason, share of fallback
  embeddings, API latency (p95), and an alert when rejections spike.
- Store the model name/version per row, and add a re-embed job for model changes.
- Embedding cache and batch encoding (above), and the advisory lock for multi-consumer safety.
- Automated tests for the consumer loop (crash/redelivery) and the API endpoints.
- A tool to replay `rejected_events` after a fix.
- Larger evaluation: more pairs, and labelled "is this a relevant competitor" judgements, not
  only translations.
- LLM-generated explanations ("Similar because both manufacture rubber gloves for export"),
  design only: generate offline per pair of descriptions and cache them, since there are only a
  few hundred distinct texts.

## Tools and AI use

I used Claude (Anthropic) as a pair programmer throughout: to help profile the feed, draft and
review code and tests, label the translation pairs, and structure this document. I ran
everything, checked each result against the data, and can explain every part of the code and
every decision above.
