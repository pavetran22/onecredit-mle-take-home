import collections, sys
sys.path.insert(0, ".")
from app.events import parse_event, Rejected

results = collections.Counter()
for line in open("data/feed.jsonl", encoding="utf-8"):
    e = parse_event(line)
    results[f"rejected:{e.reason}" if isinstance(e, Rejected) else type(e).__name__] += 1
for k, v in sorted(results.items()): print(f"{v:5d}  {k}")
