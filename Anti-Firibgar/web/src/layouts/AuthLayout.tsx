import type { ReactNode } from "react";

/** Logged-out screens: hero panel on the left (desktop only), form card on the right. */
export default function AuthLayout({ hero, children }: { hero: ReactNode; children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5 text-sm text-ink/80 md:px-10">
        <span className="flex items-center gap-2 font-semibold text-ink">
          <img src="/favicon.svg" alt="" className="h-6 w-6" />
          Anti-Firibgar
        </span>
        <span className="hidden md:inline">O‘zbekiston · O‘zbekcha</span>
      </header>
      <main className="mx-auto grid max-w-6xl items-center gap-10 px-5 pb-10 md:min-h-[calc(100vh-80px)] md:grid-cols-[1.1fr_1fr] md:px-10">
        <section className="md:rounded-3xl md:bg-panel md:p-12">{hero}</section>
        <section className="md:card md:p-8">{children}</section>
      </main>
    </div>
  );
}
