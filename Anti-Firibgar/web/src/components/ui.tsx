import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { Risk } from "../api/types";
import { RISK_LABEL } from "../lib/format";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
  loading?: boolean;
  full?: boolean;
};

export function Button({ variant = "primary", loading, full, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-xl px-6 py-3.5 text-[15px] font-medium transition disabled:cursor-not-allowed disabled:opacity-60",
        variant === "primary" && "bg-primary text-white hover:bg-primary-dark",
        variant === "secondary" && "border border-primary/40 bg-white text-primary hover:bg-panel",
        variant === "ghost" && "text-primary hover:bg-panel",
        full && "w-full",
        className,
      )}
    >
      {loading && <Spinner className="h-4 w-4 border-current" />}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cx("inline-block animate-spin rounded-full border-2 border-primary border-r-transparent", className ?? "h-6 w-6")}
    />
  );
}

export function Label({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-2 block text-sm font-medium text-ink">
      {children}
    </label>
  );
}

export function ArrowRight({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" className={cx("h-4 w-4", className)} aria-hidden>
      <path d="M4 10h12m-5-5 5 5-5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function BackLink({ to, children = "Orqaga" }: { to?: string; children?: ReactNode }) {
  const navigate = useNavigate();
  const cls = "inline-flex items-center gap-1.5 text-[15px] text-primary hover:text-primary-dark";
  const arrow = <ArrowRight className="rotate-180" />;
  return to ? (
    <Link to={to} className={cls}>
      {arrow}
      {children}
    </Link>
  ) : (
    <button type="button" onClick={() => navigate(-1)} className={cls}>
      {arrow}
      {children}
    </button>
  );
}

export function PageTitle({ eyebrow, title, sub }: { eyebrow?: ReactNode; title: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mb-6">
      {eyebrow && <p className="eyebrow mb-3">{eyebrow}</p>}
      <h1 className="text-[28px] font-semibold leading-tight tracking-tight md:text-[32px]">{title}</h1>
      {sub && <p className="mt-2 text-[15px] text-muted">{sub}</p>}
    </div>
  );
}

export function RiskTag({ risk, prefix }: { risk: Risk; prefix?: string }) {
  const color = risk === "high" ? "text-danger" : risk === "medium" ? "text-warn" : "text-muted";
  return (
    <p className={cx("text-[11px] font-semibold uppercase tracking-wide", color)}>
      {prefix ? `${prefix} · ` : ""}
      {RISK_LABEL[risk]}
    </p>
  );
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="mt-3 rounded-lg bg-danger-bg px-3 py-2 text-sm text-danger">
      {error instanceof Error ? error.message : String(error)}
    </p>
  );
}

export function Footnote({ children }: { children: ReactNode }) {
  return <p className="mt-3 text-center text-xs text-muted">{children}</p>;
}

/**
 * Primary action area. On phones it is pinned to the bottom of the screen like in the design;
 * on desktop it flows inline where it is placed.
 */
export function StickyAction({ children, tabs }: { children?: ReactNode; tabs?: ReactNode }) {
  return (
    <>
      <div className="h-40 md:hidden" aria-hidden />
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-line/60 bg-bg/95 px-4 pb-4 pt-3 backdrop-blur md:static md:z-auto md:border-0 md:bg-transparent md:p-0 md:backdrop-blur-none">
        <div className="mx-auto max-w-md md:max-w-none">
          {children}
          {tabs && <div className="mt-3 md:hidden">{tabs}</div>}
        </div>
      </div>
    </>
  );
}
