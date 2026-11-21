# ingest.py
import os
import re
import shutil
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document
from langchain_chroma import Chroma  # same package as analyze.py
from common import DB_DIR, COLLECTION_NAME, EMBED_MODEL, normalize_uzbek, make_embeddings, split_law_articles

LAWS_DIR = Path("laws")


def clean_law_text(text: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"=====\s*Page\s+\d+\s*\[text layer\]\s*=====", "\n\n", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def load_all_laws():
    all_docs = []
    for file in LAWS_DIR.glob("*.txt"):
        if file.stat().st_size == 0:
            continue
        loader = TextLoader(str(file), encoding="utf-8")
        docs = loader.load()
        for doc in docs:
            doc.page_content = clean_law_text(normalize_uzbek(doc.page_content))
            doc.metadata["source_file"] = file.name
        all_docs.extend(docs)
    return all_docs


def main():
    docs = load_all_laws()
    if not docs:
        print(f"❌ В папке {LAWS_DIR}/ нет непустых .txt файлов.")
        return
    print(f"📚 Загружено файлов: {len(docs)}")

    chunks = []
    for doc in docs:
        pieces = split_law_articles(doc.page_content, max_chars=1200)
        print(f"   {doc.metadata['source_file']}: {len(pieces)} кусков")
        for piece in pieces:
            chunks.append(Document(page_content=piece, metadata=dict(doc.metadata)))
    print(f"✅ Нарезано кусков: {len(chunks)}")

    # Build into a NEW folder first: if embedding fails halfway, the old working DB is untouched.
    # The old DB is replaced only at the very end.
    # IMPORTANT: stop server.py / app.py before running this (they keep the DB open), and start them again after.
    tmp_dir = DB_DIR.rstrip("/\\") + "_new"
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)

    print("🧠 Создаю эмбеддинги батчами (Ollama)...")
    embeddings = make_embeddings()
    print(f"   модель эмбеддингов: {EMBED_MODEL} -> {DB_DIR}")
    vectorstore = Chroma(persist_directory=tmp_dir, collection_name=COLLECTION_NAME, embedding_function=embeddings)

    batch_size = 20
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        print(f"   Обработано {i + len(batch)} из {len(chunks)}...")
        vectorstore.add_documents(batch)

    count = vectorstore._collection.count()
    del vectorstore   # release the sqlite file before moving the folder (needed on Windows)
    import gc
    gc.collect()

    try:
        if os.path.exists(DB_DIR):
            shutil.rmtree(DB_DIR)
        os.replace(tmp_dir, DB_DIR)
    except OSError as e:
        print(f"❌ Не удалось заменить {DB_DIR}: {e}\n"
              f"   Скорее всего, база открыта сервером. Остановите server.py/app.py и запустите ingest.py снова.\n"
              f"   Новая база сохранена в {tmp_dir}.")
        return

    print(f"✅ База создана: всего чанков: {count}. Перезапустите сервер, чтобы он увидел новую базу.")


if __name__ == "__main__":
    main()