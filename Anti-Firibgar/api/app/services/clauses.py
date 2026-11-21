"""Split contract text into numbered clauses."""

import re
from dataclasses import dataclass

# "1.", "2)", "3.1.", "4-modda", "5-band", "Статья 6" at the start of a line.
HEADING = re.compile(
    r"^\s*(?:(\d+(?:\.\d+)*)[.)]\s+|(\d+)\s*-\s*(?:modda|band)\b[.:]?\s*|(?:Статья|Пункт)\s+(\d+)[.:]?\s*)",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class ClauseData:
    idx: int
    title: str
    text: str


def _title_and_body(chunk: str) -> tuple[str, str]:
    """Use a short first sentence ending in '.' as the clause title, e.g. 'Narx. Kvartiraning narxi ...'."""
    chunk = re.sub(r"[ \t]+", " ", chunk).strip()
    m = re.match(r"^([^.\n]{2,60})\.\s+(.+)$", chunk, re.DOTALL)
    if m and len(m.group(1).split()) <= 6:
        return m.group(1).strip(), m.group(2).strip()
    first_line, _, rest = chunk.partition("\n")
    if rest and len(first_line) <= 80:
        return first_line.strip(), rest.strip()
    return "", chunk


def split_clauses(text: str) -> list[ClauseData]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []

    matches = list(HEADING.finditer(text))
    clauses: list[ClauseData] = []

    if len(matches) >= 2:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            clauses.append(ClauseData(0, "Kirish", preamble))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            title, body = _title_and_body(text[m.end() : end])
            if body:
                clauses.append(ClauseData(len(clauses) + 1, title, body))
    else:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        for p in paragraphs:
            clauses.append(ClauseData(len(clauses) + 1, "", re.sub(r"[ \t]+", " ", p)))

    # Re-number from 1 so the UI can show "1.", "2.", ...
    for i, c in enumerate(clauses, start=1):
        c.idx = i
    return clauses
