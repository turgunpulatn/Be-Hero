import { Link, NavLink, Navigate, Outlet, useLocation, useMatch } from "react-router-dom";

import { useDocument, useMe, useReview } from "../api/hooks";
import { cx, Spinner } from "../components/ui";

const CRUMBS: [RegExp, string][] = [
  [/^\/hujjatlar/, "Hujjatlarim"],
  [/^\/yuklash/, "Yuklash"],
  [/\/maqsad$/, "Tahlil maqsadi"],
  [/\/hujjat$/, "Hujjat"],
  [/\/chat$/, "AI chat"],
  [/^\/tahlil\/\d+$/, "Natijalar"],
  [/^\/hisob/, "Hisob"],
  [/^\/tolov/, "To‘lovlar"],
];

function SideLink({ to, children, end }: { to: string; children: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cx(
          "block rounded-lg px-3 py-2.5 text-[15px] transition",
          isActive ? "bg-panel-strong font-medium text-primary" : "text-ink/80 hover:bg-panel-strong/60",
        )
      }
    >
      {children}
    </NavLink>
  );
}

/** The "Current review" part of the sidebar, shown while a document/review is open. */
function CurrentReview() {
  const reviewMatch = useMatch("/tahlil/:reviewId/*");
  const goalMatch = useMatch("/hujjat/:docId/maqsad");
  const reviewId = Number(reviewMatch?.params.reviewId) || undefined;
  const review = useReview(reviewId).data;
  const docId = Number(goalMatch?.params.docId) || review?.document_id;
  const doc = useDocument(goalMatch ? docId : undefined).data;
  const rid = reviewId ?? doc?.latest_review?.id;
  if (!docId) return null;

  return (
    <div className="mt-8">
      <p className="eyebrow mb-2 px-3 text-[10px] text-ink/60">Joriy tahlil</p>
      <SideLink to={`/hujjat/${docId}/maqsad`}>Tahlil maqsadi</SideLink>
      {rid && (
        <>
          <SideLink to={`/tahlil/${rid}`} end>
            Natijalar
          </SideLink>
          <SideLink to={`/tahlil/${rid}/hujjat`}>Hujjat</SideLink>
          <SideLink to={`/tahlil/${rid}/chat`}>AI chat</SideLink>
        </>
      )}
    </div>
  );
}

export function TabBar() {
  const tab = (to: string, label: string) => (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cx("flex-1 rounded-xl py-2.5 text-center text-sm", isActive ? "bg-panel-strong font-medium text-primary" : "text-ink/70")
      }
    >
      {label}
    </NavLink>
  );
  return (
    <nav className="flex gap-2">
      {tab("/hujjatlar", "Hujjatlarim")}
      {tab("/hisob", "Hisob")}
    </nav>
  );
}

export default function WorkspaceLayout() {
  const me = useMe();
  const { pathname } = useLocation();

  if (me.isLoading)
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner />
      </div>
    );
  if (me.isError) return <Navigate to="/kirish" replace />;

  const crumb = CRUMBS.find(([re]) => re.test(pathname))?.[1] ?? "";

  return (
    <div className="min-h-screen md:grid md:grid-cols-[248px_1fr]">
      <aside className="sticky top-0 hidden h-screen flex-col bg-panel px-4 py-8 md:flex">
        <Link to="/hujjatlar" className="mb-10 block px-3">
          <span className="block text-xl font-semibold leading-tight">Anti-Firibgar</span>
          <span className="text-sm text-muted">Hujjat tahlili</span>
        </Link>
        <nav className="space-y-1">
          <SideLink to="/hujjatlar">Hujjatlarim</SideLink>
          <SideLink to="/yuklash">Hujjatni skanerlash</SideLink>
          <SideLink to="/hisob">Hisob</SideLink>
          <SideLink to="/tolov">To‘lovlar</SideLink>
        </nav>
        <CurrentReview />
        <div className="mt-auto px-3 text-xs text-muted">
          <p className="mb-1 text-ink/80">O‘zbekiston qonunchiligi</p>
          <p>AI tahlili, yuridik maslahat emas.</p>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="hidden items-center justify-between px-10 pt-8 text-sm text-ink/70 md:flex">
          <span>Ish maydoni{crumb && ` / ${crumb}`}</span>
          <span>O‘zbekiston · O‘zbekcha</span>
        </header>
        <main className="mx-auto max-w-md px-5 pb-6 pt-6 md:max-w-6xl md:px-10 md:pt-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
