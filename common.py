# common.py - code shared by analyze.py and ingest.py (so they can never drift apart again)
import os
import re

from dotenv import load_dotenv

load_dotenv()

from langchain_ollama import OllamaEmbeddings

# ---------------------------------------------------------------- embedding model / vector DB location
# Default = your current setup, so nothing changes until you set EMBED_MODEL in .env.
# Every embedding model gets its OWN folder, so switching models never breaks the old DB
# (and you can compare two models with test_rag.py). Re-run `python ingest.py` after switching.
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
_slug = re.sub(r"[^a-z0-9]+", "_", EMBED_MODEL.lower()).strip("_")
DB_DIR = "./chroma_db" if EMBED_MODEL == "nomic-embed-text" else f"./chroma_db_{_slug}"
COLLECTION_NAME = "laws_uz_realestate"


def normalize_uzbek(text: str) -> str:
    """Unify o' / g' apostrophes into 'ʻ' (U+02BB) and the tutuq into 'ʼ' (U+02BC), PRESERVING letter case."""
    text = re.sub(r"([Oo])[\u2018\u2019\u02BB\u02BC\u0060']", lambda m: m.group(1) + "\u02BB", text)
    text = re.sub(r"([Gg])[\u2018\u2019\u02BB\u02BC\u0060']", lambda m: m.group(1) + "\u02BB", text)
    # tutuq belgisi between two letters: ma'lumot / ma`lumot / ma’lumot -> maʼlumot
    text = re.sub(r"(?<=[^\W\d_])[\u2018\u2019\u0060'](?=[^\W\d_])", "\u02BC", text)
    return text


class PrefixedOllamaEmbeddings(OllamaEmbeddings):
    """nomic-embed-text needs task prefixes; bge-m3 and most other models do NOT."""

    def _needs_prefix(self) -> bool:
        return str(self.model).startswith("nomic")

    def embed_documents(self, texts):
        if self._needs_prefix():
            texts = [f"search_document: {t}" for t in texts]
        return super().embed_documents(texts)

    def embed_query(self, text):
        if self._needs_prefix():
            text = f"search_query: {text}"
        return super().embed_query(text)


def make_embeddings():
    return PrefixedOllamaEmbeddings(model=EMBED_MODEL)


# ---------------------------------------------------------------- splitting
_CLAUSE_START = re.compile(r"\n(?=\s*\d{1,2}(?:\.\d{1,2})*[.)]\s+\S)")


def split_contract(text: str, max_chars: int) -> list[str]:
    """Cut a contract into pieces of <= max_chars, preferring paragraph / sentence ends
    instead of cutting in the middle of a clause (a cut clause = a risk the AI cannot quote)."""
    chunks, start, n = [], 0, len(text)
    floor = int(max_chars * 0.6)           # never make a piece shorter than 60% just to find a nicer cut
    markers = ("\n\n", ".\n", ". ", "\n")  # in order of preference
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            window = text[start:end]
            cut = -1
            for mm in _CLAUSE_START.finditer(window):   # best cut: right before a numbered clause "\n3. ..."
                if mm.start() >= floor:
                    cut = mm.start()
            for m in (markers if cut == -1 else ()):
                idx = window.rfind(m)
                if idx >= floor:
                    cut = idx + (1 if m.startswith(".") else 0)
                    break
            end = start + (cut if cut != -1 else len(window))
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end
    return chunks


# "12-modda." at a word boundary (all laws are in Uzbek)
ARTICLE_RE = re.compile(r"(?:(?<=\s)|^)(\d{1,3}(?:-\d{1,2})?-modda\.)")


def split_law_articles(text: str, max_chars: int = 1200) -> list[str]:
    """One chunk per law article, each starting with its header ("123-modda. ..."), so retrieval
    returns whole legal norms and the AI can cite the article number. Long articles are split
    further, and EVERY piece keeps the article header. Falls back to plain splitting if the
    text has no article markers."""
    parts = ARTICLE_RE.split(text)
    if len(parts) == 1:
        return split_contract(text, max_chars)
    out = []
    pre = parts[0].strip()
    if pre:
        out.extend(split_contract(pre, max_chars))
    for i in range(1, len(parts), 2):
        header, body = parts[i], parts[i + 1].strip() if i + 1 < len(parts) else ""
        full = f"{header} {body}".strip()
        if len(full) <= max_chars:
            out.append(full)
            continue
        for piece in split_contract(body, max_chars - len(header) - 1):
            out.append(f"{header} {piece}")
    return out