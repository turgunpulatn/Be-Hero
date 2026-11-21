import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { API } from "../api/client";
import { useDocument, useReview } from "../api/hooks";
import DocumentView from "../components/DocumentView";
import { BackLink, Button, ErrorText, Footnote, Spinner, StickyAction } from "../components/ui";
import { categoryLabel } from "../lib/format";

export default function DocumentPage() {
  const id = Number(useParams().reviewId);
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const review = useReview(id);
  const doc = useDocument(review.data?.document_id);

  if (review.isLoading || doc.isLoading) return <Spinner />;
  if (!review.data || !doc.data) return <ErrorText error={review.error ?? doc.error ?? "Topilmadi"} />;

  const r = review.data;
  const d = doc.data;
  const findings = r.findings.slice().sort((a, b) => a.clause_idx - b.clause_idx);
  const active = Number(params.get("b")) || findings[0]?.clause_idx;
  const pos = findings.findIndex((f) => f.clause_idx === active);
  const current = pos >= 0 ? findings[pos] : undefined;
  const go = (clause: number) => setParams({ b: String(clause) }, { replace: true });

  const panel = current ? (
    <>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-danger">
        {pos + 1} / {findings.length} belgi · {categoryLabel(current.category)}
      </p>
      <p className="mt-1.5 text-[15px]">{current.title}.</p>
      {findings.length > 1 && (
        <div className="mt-2 flex gap-4 text-sm">
          <button className="link disabled:opacity-40" disabled={pos === 0} onClick={() => go(findings[pos - 1].clause_idx)}>
            Oldingi
          </button>
          <button
            className="link disabled:opacity-40"
            disabled={pos === findings.length - 1}
            onClick={() => go(findings[pos + 1].clause_idx)}
          >
            Keyingi
          </button>
        </div>
      )}
    </>
  ) : (
    <p className="text-[15px] text-ok">Bu hujjatda belgilangan band yo‘q.</p>
  );

  const action = (
    <Button full onClick={() => navigate(`/tahlil/${id}/chat`)}>
      Savollar tayyorlash
    </Button>
  );

  return (
    <>
      <BackLink to={`/tahlil/${id}`}>Natijalarga qaytish</BackLink>
      <h1 className="mb-4 mt-4 text-[28px] font-semibold tracking-tight md:text-[32px]">{d.title}</h1>
      <div className="mb-2 flex justify-between text-xs text-muted">
        <span>{d.clauses.length} ta band</span>
        {d.has_file && (
          <a className="link" href={`${API}/documents/${d.id}/file`} target="_blank" rel="noreferrer">
            Asl faylni ochish
          </a>
        )}
      </div>

      <div className="md:grid md:grid-cols-[1fr_300px] md:items-start md:gap-6">
        <DocumentView
          title={d.title}
          isSample={d.is_sample}
          clauses={d.clauses}
          findings={r.findings}
          activeClause={active}
          onSelect={(f) => go(f.clause_idx)}
        />
        <aside className="card sticky top-8 hidden p-5 md:block">
          {panel}
          <div className="mt-5">{action}</div>
          <Footnote>AI xato qilishi mumkin. Mahalliy advokat bilan tekshiring.</Footnote>
        </aside>
      </div>

      <div className="md:hidden">
        <StickyAction>
          <div className="mb-3">{panel}</div>
          {action}
        </StickyAction>
      </div>
    </>
  );
}
