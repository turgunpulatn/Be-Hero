import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { usePay, usePlan } from "../api/hooks";
import type { Payment } from "../api/types";
import { BackLink, Button, cx, ErrorText, Footnote, PageTitle, Spinner, StickyAction } from "../components/ui";
import { formatSum } from "../lib/format";

const PROVIDERS = [
  { id: "payme", name: "Payme" },
  { id: "click", name: "Click" },
];

function Checkout({ payment, onClose, onPaid }: { payment: Payment; onClose: () => void; onPaid: () => void }) {
  const { confirm } = usePay();
  const name = PROVIDERS.find((p) => p.id === payment.provider)?.name;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-4">
      <div className="card w-full max-w-sm p-6 text-center">
        <p className="eyebrow">{name} · demo to‘lov</p>
        <p className="mt-4 text-3xl font-semibold">{formatSum(payment.amount_uzs)}</p>
        <p className="mt-1 text-sm text-muted">Anti-Firibgar · {payment.reviews_granted} ta tahlil</p>
        <p className="mt-4 rounded-lg bg-panel px-3 py-2 text-xs text-muted">Bu sinov sahifasi. Haqiqiy pul yechilmaydi.</p>
        <ErrorText error={confirm.error} />
        <Button full className="mt-6" loading={confirm.isPending} onClick={() => confirm.mutate(payment.id, { onSuccess: onPaid })}>
          To‘lash
        </Button>
        <Button variant="ghost" full className="mt-2" onClick={onClose}>
          Bekor qilish
        </Button>
      </div>
    </div>
  );
}

export default function Payments() {
  const navigate = useNavigate();
  const plan = usePlan();
  const { create } = usePay();
  const [provider, setProvider] = useState("payme");
  const [checkout, setCheckout] = useState<Payment | null>(null);
  const [done, setDone] = useState(false);

  if (plan.isLoading) return <Spinner />;
  if (!plan.data) return <ErrorText error={plan.error} />;
  const p = plan.data;
  const freeLeft = p.free_reviews_total - p.free_reviews_used;
  const outOfReviews = freeLeft <= 0 && p.paid_reviews_left <= 0;
  const providerName = PROVIDERS.find((x) => x.id === provider)!.name;

  if (done)
    return (
      <div className="card mx-auto mt-10 max-w-md p-8 text-center">
        <p className="text-4xl">✓</p>
        <h1 className="mt-3 text-2xl font-semibold">To‘lov qabul qilindi</h1>
        <p className="mt-2 text-muted">Sizda {freeLeft + p.paid_reviews_left} ta tahlil bor.</p>
        <Button full className="mt-6" onClick={() => navigate("/hujjatlar")}>
          Hujjatlarimga qaytish
        </Button>
      </div>
    );

  const action = (
    <>
      <div className="mb-4 flex justify-between text-[15px]">
        <span>Jami</span>
        <span className="font-semibold">{formatSum(p.package_price_uzs)}</span>
      </div>
      <ErrorText error={create.error} />
      <Button full loading={create.isPending} onClick={() => create.mutate(provider, { onSuccess: setCheckout })}>
        {formatSum(p.package_price_uzs)} to‘lash
      </Button>
      <Footnote>To‘lovni {providerName} ilovasida yakunlaysiz. Demo: haqiqiy to‘lov amalga oshirilmaydi.</Footnote>
    </>
  );

  return (
    <>
      <BackLink />
      <div className="mt-4">
        <PageTitle
          title="Tahlilni davom ettirish"
          sub={outOfReviews ? "Bepul tahlillaringiz tugadi." : `Sizda ${freeLeft + p.paid_reviews_left} ta tahlil qoldi.`}
        />
      </div>

      <div className="md:grid md:grid-cols-[1.3fr_1fr] md:items-start md:gap-8">
        <div>
          <div className="mb-2 flex justify-between text-sm">
            <span>Bepul tahlillar</span>
            <span className="text-muted">
              {p.free_reviews_total} tadan {p.free_reviews_used} tasi ishlatildi
            </span>
          </div>
          <div className="mb-6 h-1.5 overflow-hidden rounded-full bg-panel-strong">
            <div className="h-full bg-primary/70" style={{ width: `${(p.free_reviews_used / p.free_reviews_total) * 100}%` }} />
          </div>

          <div className="rounded-2xl bg-panel p-6">
            <p className="font-medium">Yana {p.package_reviews} ta tahlil</p>
            <p className="mt-2 text-[32px] font-semibold tracking-tight">{formatSum(p.package_price_uzs)}</p>
            <p className="mt-1 text-sm text-muted">Bir martalik to‘lov · Obuna yo‘q</p>
          </div>
          {p.paid_reviews_left > 0 && (
            <p className="mt-3 text-sm text-muted">Sotib olingan tahlillardan qolgani: {p.paid_reviews_left}</p>
          )}
        </div>

        <div className="mt-8 md:card md:mt-0 md:p-6">
          <p className="mb-3 text-sm font-medium">To‘lov usuli</p>
          <div className="space-y-3">
            {PROVIDERS.map((x) => (
              <label
                key={x.id}
                className={cx(
                  "flex cursor-pointer items-center justify-between rounded-xl border bg-white px-4 py-3.5 text-[15px]",
                  provider === x.id ? "border-primary ring-1 ring-primary" : "border-line",
                )}
              >
                {x.name}
                <input type="radio" name="provider" className="h-4 w-4 accent-primary" checked={provider === x.id} onChange={() => setProvider(x.id)} />
              </label>
            ))}
          </div>
          <div className="mt-8 hidden md:block">{action}</div>
        </div>
      </div>

      <div className="md:hidden">
        <StickyAction>{action}</StickyAction>
      </div>

      {checkout && (
        <Checkout
          payment={checkout}
          onClose={() => setCheckout(null)}
          onPaid={() => {
            setCheckout(null);
            setDone(true);
          }}
        />
      )}
    </>
  );
}
