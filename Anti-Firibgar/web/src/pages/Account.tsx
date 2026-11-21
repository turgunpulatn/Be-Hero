import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useLogout, useMe, useUpdateMe } from "../api/hooks";
import { Button, ErrorText, Label, PageTitle, StickyAction } from "../components/ui";
import { TabBar } from "../layouts/WorkspaceLayout";
import { formatPhone } from "../lib/format";

export default function Account() {
  const navigate = useNavigate();
  const me = useMe().data!;
  const update = useUpdateMe();
  const logout = useLogout();
  const [name, setName] = useState(me.full_name);
  const [email, setEmail] = useState(me.email);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(false), 2500);
    return () => clearTimeout(t);
  }, [saved]);

  const signOut = () => logout.mutate(undefined, { onSuccess: () => navigate("/kirish", { replace: true }) });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    update.mutate({ full_name: name, email }, { onSuccess: () => setSaved(true) });
  };

  const saveBtn = (
    <>
      <ErrorText error={update.error} />
      <Button type="submit" form="account" full loading={update.isPending} className="md:w-auto">
        {saved ? "Saqlandi ✓" : "O‘zgarishlarni saqlash"}
      </Button>
    </>
  );

  return (
    <>
      <PageTitle eyebrow="Shaxsiy ma’lumotlar" title="Hisob" />

      <form id="account" onSubmit={submit} className="md:card md:grid md:grid-cols-2 md:gap-x-6 md:p-8">
        <div className="mb-5">
          <Label htmlFor="name">To‘liq ism</Label>
          <input id="name" className="field" placeholder="Ismingizni kiriting" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="mb-5">
          <Label htmlFor="email">Email · ixtiyoriy</Label>
          <input id="email" type="email" className="field" placeholder="Emailingizni kiriting" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="mb-5">
          <Label htmlFor="phone">Telefon raqami</Label>
          <input id="phone" className="field bg-bg" value={formatPhone(me.phone)} readOnly />
          <button type="button" onClick={signOut} className="link mt-2 text-xs">
            Telefon raqamini o‘zgartirish
          </button>
        </div>
        <div className="mb-5">
          <Label htmlFor="lang">Ilova tili</Label>
          <select id="lang" className="field" value="uz" disabled>
            <option value="uz">O‘zbekcha</option>
          </select>
        </div>
        <div className="mb-5 text-sm text-muted md:col-span-2">
          Qolgan tahlillar: <b className="text-ink">{me.reviews_left}</b> ·{" "}
          <Link to="/tolov" className="link">
            Ko‘proq olish
          </Link>
        </div>
        <button type="button" onClick={signOut} className="link w-fit text-sm">
          Chiqish
        </button>
      </form>

      <div className="mt-6 hidden md:block">{saveBtn}</div>
      <div className="md:hidden">
        <StickyAction tabs={<TabBar />}>{saveBtn}</StickyAction>
      </div>
    </>
  );
}
