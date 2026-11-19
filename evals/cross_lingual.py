"""Cross-lingual retrieval eval: does each description find its English/Malay twin?

Embeds every distinct description in the feed, then for each labelled pair checks the rank
of the twin among all other descriptions (both directions). Reports recall@1, recall@5, MRR.
Usage: uv run python -m evals.cross_lingual [model ...]
Pairs were labelled by hand (with AI assistance) from the distinct descriptions in the feed.
"""
from __future__ import annotations
import sys
import numpy as np
from sentence_transformers import SentenceTransformer
from app.events import Upsert, parse_event

CITIES = ["Ipoh", "Johor Bahru", "Kota Kinabalu", "Kuantan", "Kuching", "Melaka", "Penang", "Seremban", "the Klang Valley"]
CITY_TEMPLATES = [
    ("Private kindergarten and childcare in {}", "Tadika swasta dan taska di {}"),
    ("Operating cafes and coffee shops in {}", "Mengusahakan kedai kopi dan kafe di {}"),
    ("General practice clinic in {}", "Klinik perubatan am di {}"),
    ("Boutique hotel in {}", "Hotel butik di {}"),
    ("Last-mile parcel delivery across {}", "Penghantaran bungkusan ke seluruh {}"),
    ("Retail of mobile phones and accessories in {}", "Penjualan telefon bimbit dan aksesori di {}"),
]
PAIRS = [
    ("Durian orchard and fruit export", "Kebun durian dan eksport buah-buahan"),
    ("Oil palm plantation and fresh fruit bunch supply", "Ladang kelapa sawit dan pembekalan buah tandan segar"),
    ("Poultry farming and egg production", "Penternakan ayam dan pengeluaran telur"),
    ("Civil engineering works for roads and drainage", "Kerja-kerja kejuruteraan awam jalan dan saliran"),
    ("General contractor for residential and commercial buildings", "Kontraktor am bangunan kediaman dan komersial"),
    ("Renovation and interior fit-out for offices", "Pengubahsuaian dan kerja dalaman pejabat"),
    ("Tuition centre for primary and secondary students", "Pusat tuisyen untuk pelajar sekolah rendah dan menengah"),
    ("Bakery producing bread, cakes and pastries for retail outlets", "Pengeluaran roti dan kek untuk kedai runcit"),
    ("Halal catering for corporate events and weddings", "Perkhidmatan katering makanan halal untuk majlis"),
    ("Restaurant serving Malaysian and Chinese cuisine", "Restoran masakan Melayu dan Cina"),
    ("Community pharmacy and health supplements", "Farmasi komuniti dan makanan tambahan"),
    ("Home nursing care for the elderly", "Perkhidmatan jagaan warga emas di rumah"),
    ("Homestay and chalet operations by the beach", "Pengusaha homestay dan chalet tepi pantai"),
    ("Travel agency for umrah and inbound tourism", "Agensi pelancongan umrah dan pelancongan masuk"),
    ("Freight forwarding and customs brokerage at Port Klang", "Agensi penghantaran fret dan kastam"),
    ("Cold chain transport and storage of frozen goods", "Perkhidmatan pengangkutan dan penyimpanan barangan sejuk beku"),
    ("Manufacture of furniture from rubberwood", "Pembuatan perabot daripada kayu getah"),
    ("Manufacture of plastic packaging for food products", "Pengilangan bungkusan plastik untuk produk makanan"),
    ("Production of rubber gloves for export", "Pengeluaran sarung tangan getah untuk eksport"),
    ("Accounting, tax and company secretarial services", "Perkhidmatan perakaunan, cukai dan kesetiausahaan syarikat"),
    ("Management consulting for SMEs", "Perunding pengurusan untuk PKS"),
    ("Mini market selling groceries and household goods", "Kedai runcit barangan keperluan harian"),
    ("Online retail of baby products and toys", "Perniagaan dalam talian produk bayi"),
    ("Software development for small business accounting", "Pembangunan perisian perakaunan untuk perniagaan kecil"),
] + [(en.format(c), ms.format(c)) for en, ms in CITY_TEMPLATES for c in CITIES]

MODELS = ["intfloat/multilingual-e5-small", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"]
PREFIX = {"intfloat/multilingual-e5-small": "query: "}


def corpus() -> list[str]:
    texts = set()
    for line in open("data/feed.jsonl", encoding="utf-8"):
        e = parse_event(line)
        if isinstance(e, Upsert) and e.nature_of_business:
            texts.add(e.nature_of_business)
    return sorted(texts)


def evaluate(model_name: str, texts: list[str]) -> tuple[int, float, float, float]:
    model = SentenceTransformer(model_name, device="cpu")
    emb = model.encode([PREFIX.get(model_name, "") + t for t in texts], normalize_embeddings=True, batch_size=64)
    idx = {t: i for i, t in enumerate(texts)}
    sims = emb @ emb.T
    np.fill_diagonal(sims, -np.inf)  # a text cannot match itself
    ranks = []
    for en, ms in PAIRS:
        for query, twin in ((en, ms), (ms, en)):
            if query in idx and twin in idx:
                order = np.argsort(-sims[idx[query]])
                ranks.append(int(np.where(order == idx[twin])[0][0]) + 1)
    r = np.array(ranks)
    return len(r), float((r <= 1).mean()), float((r <= 5).mean()), float((1 / r).mean())


if __name__ == "__main__":
    texts = corpus()
    print(f"{len(texts)} distinct descriptions in feed")
    print(f"{'model':62s} {'queries':>7s} {'R@1':>6s} {'R@5':>6s} {'MRR':>6s}")
    for name in sys.argv[1:] or MODELS:
        n, r1, r5, mrr = evaluate(name, texts)
        print(f"{name:62s} {n:7d} {r1:6.2f} {r5:6.2f} {mrr:6.2f}")
