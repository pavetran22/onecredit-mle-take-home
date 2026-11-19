import json, collections, sys
sys.path.insert(0, ".")
from app.events import parse_event, Rejected, Upsert

FIELDS = ["companyName", "natureOfBusiness", "state", "industry"]
pattern, examples, regs = collections.Counter(), {}, set()
for i, line in enumerate(open("data/feed.jsonl", encoding="utf-8"), 1):
    if parse_event(line) != Rejected("missing_fields"): continue
    o = json.loads(line); d = o["data"]
    key = " | ".join(f"{f}={'MISSING' if f not in d else ('NULL' if d[f] is None else ('EMPTY' if not str(d[f]).strip() else 'ok'))}" for f in FIELDS)
    pattern[key] += 1; examples.setdefault(key, (i, d)); regs.add(o["registrationNumber"])
for k, v in pattern.most_common():
    print(f"{v:4d}  {k}\n      e.g. line {examples[k][0]}: {examples[k][1]}")

good = set()
for line in open("data/feed.jsonl", encoding="utf-8"):
    e = parse_event(line)
    if isinstance(e, Upsert): good.add(e.registration_number)
lost = regs - good
print(f"\ncompanies affected: {len(regs)} | of these, NEVER have a complete event: {len(lost)}")
print("e.g.", sorted(lost)[:5])
