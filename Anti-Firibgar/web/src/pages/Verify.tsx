import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { useSendOtp, useVerifyOtp } from "../api/hooks";
import OtpInput from "../components/OtpInput";
import { Button, ErrorText, Footnote, Label } from "../components/ui";
import AuthLayout from "../layouts/AuthLayout";
import { formatPhone } from "../lib/format";

interface OtpState {
  phone: string;
  dev: string | null;
  at: number;
  wait: number;
}

function readState(): OtpState | null {
  try {
    return JSON.parse(sessionStorage.getItem("otp") ?? "null");
  } catch {
    return null;
  }
}

export default function Verify() {
  const navigate = useNavigate();
  const [state, setState] = useState(readState);
  const [code, setCode] = useState("");
  const [left, setLeft] = useState(0);
  const verify = useVerifyOtp();
  const resend = useSendOtp();

  useEffect(() => {
    if (!state) return;
    const tick = () => setLeft(Math.max(0, Math.ceil(state.wait - (Date.now() - state.at) / 1000)));
    tick();
    const t = setInterval(tick, 500);
    return () => clearInterval(t);
  }, [state]);

  if (!state) return <Navigate to="/kirish" replace />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    verify.mutate(
      { phone: state.phone, code },
      {
        onSuccess: () => {
          sessionStorage.removeItem("otp");
          navigate("/hujjatlar", { replace: true });
        },
      },
    );
  };

  const doResend = () =>
    resend.mutate(state.phone, {
      onSuccess: (r) => {
        const s = { phone: r.phone, dev: r.dev_code, at: Date.now(), wait: r.resend_in };
        sessionStorage.setItem("otp", JSON.stringify(s));
        setState(s);
        setCode("");
      },
    });

  const hero = (
    <>
      <p className="eyebrow mb-4">Telefonni tasdiqlash</p>
      <h1 className="text-[32px] font-semibold leading-[1.15] tracking-tight md:text-[44px]">
        Xabarlaringizni
        <br />
        tekshiring
      </h1>
      <p className="mt-4 text-[15px] text-muted">{formatPhone(state.phone)} raqamiga yuborilgan kodni kiriting.</p>
    </>
  );

  return (
    <AuthLayout hero={hero}>
      <form onSubmit={submit}>
        <h2 className="mb-2 hidden text-2xl font-semibold md:block">Tasdiqlash kodini kiriting</h2>
        <Link to="/kirish" className="link mb-6 inline-block text-sm">
          Raqamni o‘zgartirish
        </Link>

        {state.dev && (
          <div className="mb-5 flex items-center justify-between gap-3 rounded-xl border border-dashed border-primary/40 bg-panel px-4 py-3 text-sm">
            <span>
              Demo rejim: kodingiz <b className="tracking-widest">{state.dev}</b>
            </span>
            <button type="button" className="link" onClick={() => setCode(state.dev!)}>
              Kiritish
            </button>
          </div>
        )}

        <Label>6 xonali kod</Label>
        <OtpInput value={code} onChange={setCode} />
        <p className="mt-3 text-sm text-muted">
          {left > 0 ? (
            `Kodni qayta yuborish: 00:${String(left).padStart(2, "0")}`
          ) : (
            <button type="button" className="link" onClick={doResend} disabled={resend.isPending}>
              Kodni qayta yuborish
            </button>
          )}
        </p>

        <ErrorText error={verify.error ?? resend.error} />
        <Button type="submit" full className="mt-8" disabled={code.length !== 6} loading={verify.isPending}>
          Tasdiqlash va davom etish
        </Button>
        <Footnote>Yana bir qadam qoldi.</Footnote>
      </form>
    </AuthLayout>
  );
}
