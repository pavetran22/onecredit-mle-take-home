import json, collections
from datetime import datetime, timezone, timedelta
MYT = timezone(timedelta(hours=8))

rows = []
for i, line in enumerate(open("data/feed.jsonl", encoding="utf-8"), 1):
    try: o = json.loads(line)
    except Exception: continue
    if isinstance(o, dict): rows.append((i, o))

print("== data that is NOT an object ==")
n = 0
for i, o in rows:
    if "data" in o and not isinstance(o["data"], dict):
        n += 1
        if n <= 4: print(" line", i, repr(o)[:220])
print(" total:", n)

print("\n== struck-off events ==")
for i, o in rows:
    if o.get("type") == "company-struck-off": print(" line", i, o)

print("\n== timestamps ==")
naive, unparse, ex = 0, 0, []
for i, o in rows:
    t = o.get("updatedAt")
    if not t: continue
    try: d = datetime.fromisoformat(t)
    except Exception: unparse += 1; ex.append((i, t)); continue
    if d.tzinfo is None: naive += 1; ex.append((i, t))
print(" no timezone:", naive, "| unparseable:", unparse)
for e in ex[:5]: print("  e.g.", e)

print("\n== ordering (naive treated as +08:00) ==")
last, ooo, same = {}, 0, 0
for i, o in rows:
    k, t = o.get("registrationNumber"), o.get("updatedAt")
    if not k or not t: continue
    try: d = datetime.fromisoformat(t)
    except Exception: continue
    if d.tzinfo is None: d = d.replace(tzinfo=MYT)
    if k in last:
        if d < last[k]: ooo += 1
        elif d == last[k]: same += 1
    last[k] = max(last.get(k, d), d)
print(" out-of-order:", ooo, "| same timestamp as previous:", same)

print("\n== a company with several events ==")
c = collections.Counter(o.get("registrationNumber") for _, o in rows)
k = next(k for k, v in c.most_common() if k)
for i, o in rows:
    if o.get("registrationNumber") == k: print(" line", i, o)
