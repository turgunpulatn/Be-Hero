from dataclasses import dataclass, field
from typing import Protocol

RISKS = ("high", "medium", "low")

# Map every apostrophe variant used in Uzbek Latin to "'" (1 char -> 1 char, so string offsets stay valid).
_APOS = str.maketrans({c: "'" for c in "‘’ʻʼ`´"})


def norm(text: str) -> str:
    return text.translate(_APOS)


@dataclass
class ClauseIn:
    idx: int
    title: str
    text: str


@dataclass
class FindingData:
    clause_idx: int
    risk: str
    category: str
    title: str
    explanation: str
    quote: str
    suggested_question: str
    law_refs: list = field(default_factory=list)


@dataclass
class AnalysisData:
    summary: str
    findings: list[FindingData]


@dataclass
class ChatContext:
    goal: str
    clauses: list[ClauseIn]
    findings: list[FindingData]
    history: list[tuple[str, str]]  # (role, content)


class AIProvider(Protocol):
    name: str

    def analyze(self, goal: str, clauses: list[ClauseIn]) -> AnalysisData: ...

    def chat(self, ctx: ChatContext, question: str) -> str: ...
