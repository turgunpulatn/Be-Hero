# test_rag.py
# Retrieval sanity check. Uses the SAME local vector store / embeddings as analyze.py
# (nomic-embed-text via Ollama), so nothing leaves your machine.
import logging
logging.getLogger("chromadb").setLevel(logging.ERROR)

from analyze import get_vectorstore, normalize_uzbek, ALLOWED_SOURCES

vs = get_vectorstore()
total = vs._collection.count()
print(f"Всего чанков: {total}\n")

if total == 0:
    print("❌ База пустая. Сначала запусти: python ingest.py")
    raise SystemExit(1)

# (query, files where a good answer is expected) - EDIT the expected files to match your laws/ folder.
queries = [
    ("kvartira oldi-sotdi shartnomasi notarial tasdiqlanishi", {"notariat_tartib.txt", "uy_joy_kodeksi.txt"}),
    ("uy-joy oldi-sotdi davlat roʻyxatidan oʻtkazish", {"registratsiya.txt", "uy_joy_kodeksi.txt"}),
    ("shartnoma shakliga rioya etmaslik haqiqiy emasligi", {"uy_joy_kodeksi.txt"}),
    ("notarial tasdiqlash tartibi", {"notariat_tartib.txt"}),
]

hits = 0
for q, expected in queries:
    print(f"=== {q} ===")
    q_norm = normalize_uzbek(q)
    results = vs.similarity_search_with_score(
        q_norm, k=3, filter={"source_file": {"$in": ALLOWED_SOURCES}}
    )
    found_sources = set()
    for d, score in results:  # score = distance, LOWER is better
        src = d.metadata.get("source_file", "?")
        found_sources.add(src)
        snippet = d.page_content[:160].replace("\n", " ")
        print(f"  [{src}] (dist={score:.3f}) {snippet}...")
    ok = bool(found_sources & expected)
    hits += ok
    print(f"  -> {'✅ kutilgan manba topildi' if ok else '⚠️ kutilgan manba topilmadi'} (expected: {', '.join(sorted(expected))})\n")

print(f"Итог: {hits}/{len(queries)} запросов вернули ожидаемый источник")