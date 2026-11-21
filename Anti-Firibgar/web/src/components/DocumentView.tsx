import { useEffect, useRef } from "react";

import type { Clause, Finding } from "../api/types";
import { RISK_LABEL } from "../lib/format";
import { cx } from "./ui";

/** Renders text with the first occurrence of `quote` underlined (apostrophe/case-insensitive). */
export function Highlighted({ text, quote }: { text: string; quote: string }) {
  if (!quote) return <>{text}</>;
  const norm = (s: string) => s.replace(/[‘’ʻʼ`´]/g, "'").toLowerCase();
  const i = norm(text).indexOf(norm(quote));
  if (i < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, i)}
      <span className="font-semibold underline decoration-2 underline-offset-2">{text.slice(i, i + quote.length)}</span>
      {text.slice(i + quote.length)}
    </>
  );
}

interface Props {
  title: string;
  isSample?: boolean;
  clauses: Clause[];
  findings: Finding[];
  activeClause?: number;
  compact?: boolean;
  onSelect?: (f: Finding) => void;
}

export default function DocumentView({ title, isSample, clauses, findings, activeClause, compact, onSelect }: Props) {
  const refs = useRef<Record<number, HTMLDivElement | null>>({});
  // several findings can point to one clause: show the most serious one
  const rank = { high: 0, medium: 1, low: 2 } as const;
  const byClause = new Map<number, Finding>();
  for (const f of findings) {
    const cur = byClause.get(f.clause_idx);
    if (!cur || rank[f.risk] < rank[cur.risk]) byClause.set(f.clause_idx, f);
  }

  useEffect(() => {
    if (activeClause) refs.current[activeClause]?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [activeClause]);

  return (
    <article className={cx("card", compact ? "p-5" : "p-5 md:p-10")}>
      {isSample && <p className="eyebrow mb-1">Namuna hujjat</p>}
      <h2 className={cx("mb-6 font-semibold", compact ? "text-lg" : "text-xl md:text-[22px]")}>{title}</h2>
      <div className="space-y-5">
        {clauses.map((c) => {
          const f = byClause.get(c.idx);
          const heading = `${c.idx}. ${c.title}`.trim();
          if (!f) {
            return (
              <div key={c.idx} ref={(el) => (refs.current[c.idx] = el)} className={cx(activeClause === c.idx && "rounded-lg bg-panel p-3")}>
                {c.title && <p className="mb-1 text-[15px] font-medium">{heading}</p>}
                <p className="whitespace-pre-line text-[15px] leading-relaxed text-ink/90">
                  {!c.title && `${c.idx}. `}
                  {c.text}
                </p>
              </div>
            );
          }
          const tone =
            f.risk === "high"
              ? "border-danger-line bg-danger-bg text-danger"
              : f.risk === "medium"
                ? "border-amber-300 bg-amber-50 text-warn"
                : "border-line bg-panel text-ink";
          return (
            <div
              key={c.idx}
              ref={(el) => (refs.current[c.idx] = el)}
              onClick={() => onSelect?.(f)}
              className={cx(
                "rounded-lg border px-4 py-3 transition",
                tone,
                onSelect && "cursor-pointer",
                activeClause === c.idx && "ring-2 ring-primary/40",
              )}
            >
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide">
                {heading} · {RISK_LABEL[f.risk]}
              </p>
              <p className="whitespace-pre-line text-[15px] leading-relaxed">
                <Highlighted text={c.text} quote={f.quote} />
              </p>
            </div>
          );
        })}
      </div>
    </article>
  );
}
