import { useRef, type ClipboardEvent, type KeyboardEvent } from "react";

export default function OtpInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const chars = value.padEnd(6, " ").slice(0, 6).split("");

  const setAt = (i: number, ch: string) => {
    const next = chars.slice();
    next[i] = ch || " ";
    onChange(next.join("").trimEnd());
  };

  const onKey = (i: number, e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && chars[i] === " " && i > 0) {
      setAt(i - 1, "");
      refs.current[i - 1]?.focus();
      e.preventDefault();
    } else if (e.key === "ArrowLeft" && i > 0) refs.current[i - 1]?.focus();
    else if (e.key === "ArrowRight" && i < 5) refs.current[i + 1]?.focus();
  };

  const onPaste = (e: ClipboardEvent) => {
    const digits = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
    if (digits) {
      e.preventDefault();
      onChange(digits);
      refs.current[Math.min(digits.length, 5)]?.focus();
    }
  };

  return (
    <div className="flex gap-2" onPaste={onPaste}>
      {chars.map((ch, i) => (
        <input
          key={i}
          ref={(el) => (refs.current[i] = el)}
          inputMode="numeric"
          autoComplete={i === 0 ? "one-time-code" : "off"}
          aria-label={`${i + 1}-raqam`}
          autoFocus={i === 0}
          maxLength={1}
          value={ch.trim()}
          onKeyDown={(e) => onKey(i, e)}
          onChange={(e) => {
            const d = e.target.value.replace(/\D/g, "").slice(-1);
            setAt(i, d);
            if (d && i < 5) refs.current[i + 1]?.focus();
          }}
          className="h-14 w-full min-w-0 rounded-xl border border-line bg-white text-center text-2xl outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 md:h-16"
        />
      ))}
    </div>
  );
}
