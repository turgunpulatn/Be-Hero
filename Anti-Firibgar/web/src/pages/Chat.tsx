import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { useMessages, useReview, useSendMessage } from "../api/hooks";
import type { Message } from "../api/types";
import { BackLink, Button, ErrorText, Spinner } from "../components/ui";

const STARTERS = ["Imzolashdan oldin nimani so‘rashim kerak?", "Bu shartni o‘zgartirsa bo‘ladimi?", "Eng katta xavf qaysi?"];

function Bubble({ m, reviewId }: { m: Message; reviewId: number }) {
  if (m.role === "user")
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl bg-panel-strong/80 px-4 py-2.5 text-[15px]">{m.content}</p>
      </div>
    );
  const clause = m.content.match(/(\d+)-band/)?.[1];
  return (
    <div className="max-w-[95%]">
      <p className="eyebrow mb-1 text-[10px] text-ink/60">AI yordamchi</p>
      <p className="whitespace-pre-line text-[15px] leading-relaxed">{m.content}</p>
      {clause && (
        <Link to={`/tahlil/${reviewId}/hujjat?b=${clause}`} className="link mt-1 inline-block text-xs">
          Belgilangan bandni ko‘rish
        </Link>
      )}
    </div>
  );
}

export default function Chat() {
  const id = Number(useParams().reviewId);
  const review = useReview(id);
  const messages = useMessages(id);
  const send = useSendMessage(id);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.data?.length, pending]);

  if (review.isLoading) return <Spinner />;
  if (!review.data) return <ErrorText error={review.error ?? "Tahlil topilmadi"} />;
  const r = review.data;
  const top = r.findings[0];

  const ask = (q: string) => {
    q = q.trim();
    if (!q || send.isPending) return;
    setPending(q);
    setText("");
    send.mutate(q, { onSettled: () => setPending(null), onError: () => setText(q) });
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    ask(text);
  };

  const contextCard = (
    <div className="rounded-2xl bg-panel px-4 py-3">
      <p className="text-sm font-medium">{r.document_title}</p>
      <p className="text-xs text-muted">
        {r.findings.length ? `${r.findings.length} ta belgilangan band` : "Belgilangan band yo‘q"}
      </p>
    </div>
  );

  const list = messages.data ?? [];

  return (
    <>
      <BackLink to={`/tahlil/${id}`}>Natijalarga qaytish</BackLink>
      <h1 className="mb-5 mt-4 text-[28px] font-semibold tracking-tight md:text-[32px]">Savollar tayyorlash</h1>

      <div className="md:grid md:grid-cols-[1fr_300px] md:items-start md:gap-8">
        <div className="flex min-h-[60vh] flex-col">
          <div className="mb-5 md:hidden">{contextCard}</div>

          <div className="flex-1 space-y-6">
            {list.length === 0 && !pending && (
              <div>
                <p className="mb-3 text-sm text-muted">Hujjat bo‘yicha savol bering yoki tanlang:</p>
                <div className="flex flex-col items-start gap-2">
                  {STARTERS.map((s) => (
                    <button key={s} onClick={() => ask(s)} className="rounded-2xl bg-panel px-4 py-2.5 text-left text-[15px] hover:bg-panel-strong">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {list.map((m) => (
              <Bubble key={m.id} m={m} reviewId={id} />
            ))}
            {pending && (
              <>
                <Bubble m={{ id: -1, role: "user", content: pending, created_at: "" }} reviewId={id} />
                <p className="flex items-center gap-2 text-sm text-muted">
                  <Spinner className="h-4 w-4" /> Javob yozilmoqda…
                </p>
              </>
            )}
            <div ref={endRef} />
          </div>

          <form onSubmit={submit} className="sticky bottom-0 mt-6 bg-bg pb-4 pt-2">
            <ErrorText error={send.error} />
            <label htmlFor="q" className="mb-2 mt-2 block text-xs text-muted">
              Savolingiz
            </label>
            <div className="flex items-center gap-2 rounded-2xl border border-line bg-white p-1.5 focus-within:border-primary">
              <input
                id="q"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Keyin nimani so‘rashim kerak?"
                className="min-w-0 flex-1 bg-transparent px-3 py-2 text-[15px] outline-none"
              />
              <Button type="submit" className="px-4 py-2" disabled={!text.trim()} loading={send.isPending}>
                Yuborish
              </Button>
            </div>
            <p className="mt-2 text-center text-xs text-muted">AI xato qilishi mumkin. Muhim maslahatlarni tekshiring.</p>
          </form>
        </div>

        <aside className="card sticky top-8 hidden p-5 md:block">
          {contextCard}
          {top && (
            <>
              <h3 className="mt-5 text-xl font-semibold leading-snug">{top.title}</h3>
              <p className="mt-3 text-sm text-ink/80">“{top.quote}”</p>
              <Link to={`/tahlil/${id}/hujjat?b=${top.clause_idx}`} className="link mt-3 inline-block text-sm">
                Bandni ko‘rish
              </Link>
            </>
          )}
        </aside>
      </div>
    </>
  );
}
