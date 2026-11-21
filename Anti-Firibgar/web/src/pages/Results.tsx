import { Link, useNavigate, useParams } from "react-router-dom";

import { useDocument, useReview } from "../api/hooks";
import type { Finding, Review } from "../api/types";
import DocumentView from "../components/DocumentView";
import { BackLink, Button, ErrorText, Footnote, PageTitle, RiskTag, Spinner, StickyAction } from "../components/ui";

export function ModelNote({ model }: { model: string }) {
  if (model === "mock")
    return (
      <p className="mb-4 rounded-lg border border-dashed border-line px-3 py-2 text-xs text-muted">
        Demo tahlil: AI modeli hali ulanmagan, natijalar kalit so‘zlar asosida topildi.
      </p>
    );
  return null;
}

export function FindingCard({ f, reviewId }: { f: Finding; reviewId: number }) {
  return (
    <div className="card p-5">
      <RiskTag risk={f.risk} />
      <h3 className="mt-2 text-xl font-semibold leading-snug">{f.title}</h3>
      <p className="mt-2 text-[15px] text-ink/80">{f.explanation}</p>
      {f.quote && (
        <div className="mt-4 rounded-xl bg-panel px-4 py-3">
          <p className="eyebrow mb-1 text-[10px]">Banddan parcha · {f.clause_idx}-band</p>
          <p className="text-sm">“{f.quote}”</p>
        </div>
      )}
      {f.law_refs.length > 0 && <p className="mt-3 text-xs text-muted">Qonun: {f.law_refs.join(", ")}</p>}
      <Link to={`/tahlil/${reviewId}/hujjat?b=${f.clause_idx}`} className="link mt-4 inline-block text-sm">
        Bandni ko‘rish
      </Link>
    </div>
  );
}

function LegalCheck({ model }: { model: string }) {
  const checked = model === "legalai"; // LegalAI checks against Uzbek laws (Uy-joy kodeksi, notariat, ro‘yxatga olish...)
  return (
    <div className="mt-6 px-1">
      <p className="eyebrow mb-1 text-[10px] text-ink/60">
        Qonun tekshiruvi · {checked ? "qonun normalari asosida o‘tkazildi" : "hali o‘tkazilmagan"}
      </p>
      <p className="font-medium">O‘zbekiston qonunlari</p>
      <p className="mt-0.5 text-sm text-muted">Rasmiy manba: LexUZ (lex.uz).</p>
      <a href="https://lex.uz" target="_blank" rel="noreferrer" className="link mt-1 inline-block text-sm">
        O‘zbekiston qonunchiligini tekshirish
      </a>
    </div>
  );
}

function Pending({ review }: { review: Review }) {
  return (
    <div className="card mx-auto mt-6 max-w-lg p-10 text-center">
      <Spinner className="h-8 w-8" />
      <p className="mt-4 text-lg font-medium">Hujjat tahlil qilinmoqda…</p>
      <p className="mt-1 text-sm text-muted">{review.document_title}</p>
      <p className="mt-4 text-xs text-muted">Bu bir necha daqiqa olishi mumkin. Sahifani yopmasangiz ham bo‘ladi.</p>
    </div>
  );
}

export default function Results() {
  const id = Number(useParams().reviewId);
  const navigate = useNavigate();
  const review = useReview(id);
  const r = review.data;
  const doc = useDocument(r?.status === "done" ? r.document_id : undefined);

  if (review.isLoading) return <Spinner />;
  if (!r) return <ErrorText error={review.error ?? "Tahlil topilmadi"} />;

  const back = <BackLink to="/hujjatlar">Hujjatlarim</BackLink>;
  if (r.status === "pending" || r.status === "analyzing")
    return (
      <>
        {back}
        <Pending review={r} />
      </>
    );
  if (r.status === "failed")
    return (
      <>
        {back}
        <div className="card mx-auto mt-6 max-w-lg p-8 text-center">
          <p className="text-lg font-medium">Tahlil bajarilmadi</p>
          <p className="mt-2 text-sm text-muted">{r.error}</p>
          <Button className="mt-6" onClick={() => navigate(`/hujjat/${r.document_id}/maqsad`)}>
            Qaytadan urinish
          </Button>
        </div>
      </>
    );

  const n = r.findings.length;
  const title = n ? `${n} ta xavf topildi` : "Xavf topilmadi";
  const action = (
    <>
      <Button full onClick={() => navigate(`/tahlil/${id}/chat`)}>
        Savollar tayyorlash
      </Button>
      <Footnote>AI xato qilishi mumkin. Mahalliy advokat bilan tekshiring.</Footnote>
    </>
  );

  return (
    <>
      {back}
      <div className="mt-4">
        <PageTitle
          eyebrow="3-qadam / 3"
          title={title}
          sub={`${r.document_title} · ${r.model === "namuna" ? "Namuna tahlil" : "AI tahlili"}`}
        />
      </div>

      <div className="md:grid md:grid-cols-[1.4fr_1fr] md:items-start md:gap-8">
        <div className="hidden md:block">
          {doc.data && (
            <DocumentView
              title={doc.data.title}
              isSample={doc.data.is_sample}
              clauses={doc.data.clauses}
              findings={r.findings}
              onSelect={(f) => navigate(`/tahlil/${id}/hujjat?b=${f.clause_idx}`)}
            />
          )}
        </div>

        <div>
          <ModelNote model={r.model} />
          {r.summary && <p className="mb-4 text-[15px] text-ink/80">{r.summary}</p>}
          <div className="space-y-4">
            {r.findings.map((f) => (
              <FindingCard key={f.id} f={f} reviewId={id} />
            ))}
            {n === 0 && (
              <div className="card p-5 text-[15px] text-ok">
                Asosiy xavfli bandlar topilmadi. Baribir imzolashdan oldin to‘liq o‘qib chiqing.
              </div>
            )}
          </div>
          <LegalCheck model={r.model} />
          <div className="mt-8 hidden md:block">{action}</div>
        </div>
      </div>

      <div className="md:hidden">
        <StickyAction>{action}</StickyAction>
      </div>
    </>
  );
}
