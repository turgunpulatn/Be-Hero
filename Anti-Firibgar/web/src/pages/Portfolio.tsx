import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useDocuments } from "../api/hooks";
import type { DocumentListItem } from "../api/types";
import { ArrowRight, Button, cx, ErrorText, PageTitle, Spinner, StickyAction } from "../components/ui";
import { TabBar } from "../layouts/WorkspaceLayout";
import { formatDay, pluralFlags, SOURCE_LABEL } from "../lib/format";

export const docLink = (d: DocumentListItem) =>
  d.latest_review ? `/tahlil/${d.latest_review.id}` : `/hujjat/${d.id}/maqsad`;

function Status({ d }: { d: DocumentListItem }) {
  const r = d.latest_review;
  if (!r) return <span className="text-muted">Tahlil qilinmagan</span>;
  if (r.status === "pending" || r.status === "analyzing") return <span className="text-primary">Tahlil qilinmoqda…</span>;
  if (r.status === "failed") return <span className="text-danger">Xatolik</span>;
  return <span className={r.flags ? "text-warn" : "text-ok"}>{pluralFlags(r.flags)}</span>;
}

export default function Portfolio() {
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  const docs = useDocuments(q);
  const list = docs.data ?? [];
  const samples = list.some((d) => d.is_sample);

  return (
    <>
      <div className="flex items-start justify-between gap-4">
        <PageTitle
          eyebrow="Mening hujjatlarim"
          title="Hujjatlarim"
          sub={`${list.length} ta hujjat${samples ? " · Namunalar bilan" : ""}`}
        />
        <Button className="hidden md:inline-flex" onClick={() => navigate("/yuklash")}>
          Hujjatni skanerlash
        </Button>
      </div>

      <input
        type="search"
        placeholder="Hujjatlarni qidirish"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="field mb-4 border-transparent bg-panel md:max-w-sm"
      />

      <ErrorText error={docs.error} />
      {docs.isLoading && (
        <div className="py-10 text-center">
          <Spinner />
        </div>
      )}
      {!docs.isLoading && list.length === 0 && (
        <div className="card p-8 text-center text-muted">
          {q ? "Hech narsa topilmadi." : "Hali hujjat yo‘q. Birinchi hujjatingizni skanerlang."}
        </div>
      )}

      {/* Mobile: cards */}
      <ul className="space-y-3 md:hidden">
        {list.map((d) => (
          <li key={d.id}>
            <Link to={docLink(d)} className="card block px-4 py-3.5 transition hover:border-primary/40">
              <div className="flex items-center justify-between">
                <span className="font-medium">{d.title}</span>
                <ArrowRight className="text-primary" />
              </div>
              <div className="mt-1.5 flex justify-between text-xs text-muted">
                <span>
                  {formatDay(d.created_at)} · {SOURCE_LABEL[d.source]}
                </span>
                <Status d={d} />
              </div>
            </Link>
          </li>
        ))}
      </ul>

      {/* Desktop: table */}
      {list.length > 0 && (
        <div className="card hidden overflow-hidden md:block">
          <table className="w-full text-left text-[15px]">
            <thead className="border-b border-line text-xs text-muted">
              <tr>
                <th className="px-6 py-3 font-medium">Hujjat</th>
                <th className="px-6 py-3 font-medium">Sana</th>
                <th className="px-6 py-3 font-medium">Holat</th>
                <th className="w-20 px-6 py-3 font-medium">Ochish</th>
              </tr>
            </thead>
            <tbody>
              {list.map((d) => (
                <tr
                  key={d.id}
                  onClick={() => navigate(docLink(d))}
                  className={cx("cursor-pointer border-b border-line/60 last:border-0 hover:bg-panel/50")}
                >
                  <td className="px-6 py-4 font-medium">{d.title}</td>
                  <td className="px-6 py-4 text-sm text-muted">
                    {formatDay(d.created_at)} · {SOURCE_LABEL[d.source]}
                  </td>
                  <td className="px-6 py-4 text-sm">
                    <Status d={d} />
                  </td>
                  <td className="px-6 py-4 text-primary">
                    <ArrowRight />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="md:hidden">
        <StickyAction tabs={<TabBar />}>
          <Button full onClick={() => navigate("/yuklash")}>
            Hujjatni skanerlash
          </Button>
        </StickyAction>
      </div>
    </>
  );
}
