import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { useMe, useSendOtp } from "../api/hooks";
import { Button, ErrorText, Footnote, Label } from "../components/ui";
import AuthLayout from "../layouts/AuthLayout";

export const COUNTRIES = [
  { code: "998", name: "O‘zbekiston", digits: 9, placeholder: "90 123 45 67" },
  { code: "7", name: "Qozog‘iston / Rossiya", digits: 10, placeholder: "701 123 45 67" },
  { code: "996", name: "Qirg‘iziston", digits: 9, placeholder: "555 123 456" },
  { code: "992", name: "Tojikiston", digits: 9, placeholder: "93 123 4567" },
  { code: "1", name: "AQSh", digits: 10, placeholder: "201 555 0123" },
];

function formatLocal(digits: string, code: string) {
  if (code !== "998") return digits;
  const p = [digits.slice(0, 2), digits.slice(2, 5), digits.slice(5, 7), digits.slice(7, 9)];
  return p.filter(Boolean).join(" ");
}

export function LoginHero() {
  return (
    <>
      <p className="eyebrow mb-4">Boshlash</p>
      <h1 className="text-[32px] font-semibold leading-[1.15] tracking-tight md:text-[44px]">
        Ozgina aniqlik.
        <br />
        Ancha kam tashvish.
      </h1>
      <p className="mt-4 text-[15px] text-muted">Telefon raqamingiz bilan ro‘yxatdan o‘ting.</p>
      <div className="mt-8 hidden rounded-2xl bg-panel p-5 md:mt-12 md:block md:bg-transparent md:p-0">
        <p className="font-medium">Barcha tahlillaringiz bir joyda.</p>
        <p className="mt-1 text-sm text-muted">Skanerlangan hujjatlarga istalgan vaqtda qayting.</p>
      </div>
    </>
  );
}

export default function Login() {
  const navigate = useNavigate();
  const me = useMe();
  const send = useSendOtp();
  const [country, setCountry] = useState(COUNTRIES[0]);
  const [digits, setDigits] = useState("");

  if (me.data) return <Navigate to="/hujjatlar" replace />;

  const valid = digits.length === country.digits;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    send.mutate(`+${country.code}${digits}`, {
      onSuccess: (r) => {
        sessionStorage.setItem("otp", JSON.stringify({ phone: r.phone, dev: r.dev_code, at: Date.now(), wait: r.resend_in }));
        navigate("/kirish/tasdiqlash");
      },
    });
  };

  return (
    <AuthLayout hero={<LoginHero />}>
      <form onSubmit={submit}>
        <h2 className="mb-6 hidden text-2xl font-semibold md:block">Hisob yaratish</h2>

        <Label htmlFor="country">Davlat / kod</Label>
        <select
          id="country"
          className="field mb-5 appearance-none"
          value={country.code + country.name}
          onChange={(e) => {
            setCountry(COUNTRIES.find((c) => c.code + c.name === e.target.value)!);
            setDigits("");
          }}
        >
          {COUNTRIES.map((c) => (
            <option key={c.code + c.name} value={c.code + c.name}>
              {c.name} +{c.code}
            </option>
          ))}
        </select>

        <Label htmlFor="phone">Telefon raqami</Label>
        <div className="flex items-center rounded-xl border border-line bg-white focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20">
          <span className="pl-4 text-[15px] text-muted">+{country.code}</span>
          <input
            id="phone"
            inputMode="tel"
            autoComplete="tel-national"
            autoFocus
            className="w-full rounded-xl bg-transparent px-3 py-3 text-[15px] outline-none"
            placeholder={country.placeholder}
            value={formatLocal(digits, country.code)}
            onChange={(e) => setDigits(e.target.value.replace(/\D/g, "").slice(0, country.digits))}
          />
        </div>
        <p className="mt-2 text-xs text-muted">Sizga tasdiqlash kodini yuboramiz.</p>

        <div className="mt-6 rounded-2xl bg-panel p-5 md:hidden">
          <p className="font-medium">Barcha tahlillaringiz bir joyda.</p>
          <p className="mt-1 text-sm text-muted">Skanerlangan hujjatlarga istalgan vaqtda qayting.</p>
        </div>

        <ErrorText error={send.error} />
        <Button type="submit" full className="mt-8" disabled={!valid} loading={send.isPending}>
          Tasdiqlash kodini yuborish
        </Button>
        <Footnote>SMS uchun operator to‘lovi olinishi mumkin.</Footnote>
      </form>
    </AuthLayout>
  );
}
