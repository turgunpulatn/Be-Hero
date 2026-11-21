import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useDocument, useMe, useStartReview } from "../api/hooks";
import DocumentView from "../components/DocumentView";
import { BackLink, Button, ErrorText, Footnote, Label, PageTitle, Spinner, StickyAction } from "../components/ui";
import { SOURCE_LABEL } from "../lib/format";

const EXAMPLES = [
  ["Uy sotib olish", "Uy sotib olmoqchiman. Mulk huquqi va pulni qaytarish shartlarini tekshiring."],
  ["Ijaraga olish", "Kvartirani ijaraga olmoqchiman. Garov puli va narx oshishi xavflarini tekshiring."],
  ["Ishga kirish", "Ishga kiryapman. Ish haqi, sinov muddati va jarimalarni tekshiring."],
  ["Avtomobil", "Avtomobil sotib olmoqchiman. To‘lov va hujjatlarni topshirish shartlarini tekshiring."],
];

export default function Goal() {
  const docId = Number(useParams().docId);
  const navigate = useNavigate();
  const doc = useDocument(docId);
  const me = useMe();
  const start = useStartReview(docId);
  const [goal, setGoal] = useState("");

  useEffect(() => {
    if (doc.data?.latest_review && !goal) setGoal(doc.data.latest_review.goal);
    // only prefill once, when the document loads
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.data?.id]);

  if (doc.isLoading) return <Spinner />;
  if (doc.error || !doc.data) return <ErrorText error={doc.error ?? "Hujjat topilmadi"} />;
  const d = doc.data;
  const left = me.data?.reviews_left ?? 0;

  const submit = () =>
    start.mutate(goal.trim(), {
      onSuccess: (r) => navigate(`/tahlil/${r.id}`),
      onError: (e) => {
        if (e instanceof ApiError && e.status === 402) navigate("/tolov");
      },
    });

  const action = (
    <>
      <ErrorText error={start.error} />
      <Button full onClick={left > 0 ? submit : () => navigate("/tolov")} disabled={goal.trim().length < 3} loading={start.isPending}>
        {left > 0 ? "Xavflarni topish" : "Tahlillar tugadi — to‘lov qilish"}
      </Button>
      <Footnote>AI tahlili, yuridik maslahat emas.</Footnote>
    </>
  );

  return (
    <>
      <BackLink to="/hujjatlar" />
      <div className="mt-4">
        <PageTitle eyebrow="2-qadam / 3" title="Maqsadingiz nima?" />
      </div>

      <div className="md:grid md:grid-cols-[1.4fr_1fr] md:items-start md:gap-8">
        <div className="hidden max-h-[70vh] overflow-auto md:block">
          <DocumentView title={d.title} isSample={d.is_sample} clauses={d.clauses} findings={[]} compact />
        </div>

        <div className="md:card md:p-6">
          <div className="mb-6 rounded-2xl bg-panel px-4 py-3.5">
            <p className="font-medium">{d.filename || d.title}</p>
            <p className="text-xs text-muted">
              {d.is_sample ? "Namuna hujjat" : `${SOURCE_LABEL[d.source]} · ${d.clauses.length} ta band`}
            </p>
          </div>

          <Label htmlFor="goal">Maqsadingiz</Label>
          <textarea
            id="goal"
            rows={4}
            className="field resize-none"
            placeholder="Masalan: 10 000 dollarga uy sotib olmoqchiman. Mulk huquqi va pulni qaytarish shartlarini tekshiring."
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
          <div className="mt-3 flex flex-wrap gap-2">
            {EXAMPLES.map(([label, text]) => (
              <button
                key={label}
                type="button"
                onClick={() => setGoal(text)}
                className="rounded-full border border-line bg-white px-3 py-1.5 text-xs text-ink/80 hover:border-primary/50"
              >
                {label}
              </button>
            ))}
          </div>
          <p className="mt-4 text-xs text-muted">
            Huquqiy tekshiruv O‘zbekiston qonunchiligi asosida. Qolgan tahlillar: {left}.
          </p>

          <div className="mt-8 hidden md:block">{action}</div>
        </div>
      </div>

      <div className="md:hidden">
        <StickyAction>{action}</StickyAction>
      </div>
    </>
  );
}
