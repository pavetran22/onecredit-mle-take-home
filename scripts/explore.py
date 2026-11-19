import json, collections
from datetime import datetime

rows, bad = [], []
for i, line in enumerate(open("data/feed.jsonl", encoding="utf-8"), 1):
    try:
        obj = json.loads(line)
    except Exception as e:
        bad.append((i, "unparseable", repr(line[:200]), str(e)[:80])); continue
    if not isinstance(obj, dict):
        bad.append((i, f"not an object ({type(obj).__name__})", repr(line[:200]), "")); continue
    rows.append((i, obj))

print("good events:", len(rows), "| bad lines:", len(bad))
for b in bad: print("  BAD", b)

print("\ntypes:", collections.Counter(o.get("type") for _, o in rows))
print("data keys:", collections.Counter(k for _, o in rows for k in (o.get("data") or {})))
missing = [(i, o) for i, o in rows if not o.get("registrationNumber") or not o.get("updatedAt") or not isinstance(o.get("data"), dict)]
print("events missing id/updatedAt/data:", len(missing))
for i, o in missing[:3]: print("  e.g. line", i, o)

ids = collections.Counter(o.get("registrationNumber") for _, o in rows)
print("\nunique companies:", len(ids), "| with >1 event:", sum(c > 1 for c in ids.values()))

last, ooo, tz, badts = {}, 0, collections.Counter(), 0
for i, o in rows:
    k, t = o.get("registrationNumber"), o.get("updatedAt")
    if not k or not t: continue
    try: d = datetime.fromisoformat(t)
    except Exception: badts += 1; continue
    tz[str(d.utcoffset())] += 1
    if k in last and d < last[k]: ooo += 1
    last[k] = max(last.get(k, d), d)
print("out-of-order events:", ooo, "| bad timestamps:", badts)
print("timezones:", tz)

empty = sum(1 for _, o in rows if isinstance(o.get("data"), dict) and not (o["data"].get("natureOfBusiness") or "").strip())
print("events with empty natureOfBusiness:", empty)
