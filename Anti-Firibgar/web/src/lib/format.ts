import type { Risk, Source } from "../api/types";

const MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"];

export function formatDay(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const days = Math.round(
    (new Date(today.toDateString()).getTime() - new Date(d.toDateString()).getTime()) / 86_400_000,
  );
  if (days === 0) return "Bugun";
  if (days === 1) return "Kecha";
  return `${d.getDate()}-${MONTHS[d.getMonth()]}`;
}

export const formatSum = (n: number) => `${String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " ")} so‘m`;

export const SOURCE_LABEL: Record<Source, string> = { pdf: "PDF", docx: "Word", image: "Skan", sample: "Namuna" };

export const RISK_LABEL: Record<Risk, string> = {
  high: "Yuqori xavf",
  medium: "O‘rta xavf",
  low: "Past xavf",
};

const CATEGORY_LABEL: Record<string, string> = {
  payment_timing: "To‘lov muddati",
  non_refundable: "Pulni qaytarish",
  unilateral: "Bir tomonlama o‘zgartirish",
  penalty: "Jarima",
  salary_delay: "Ish haqi",
  ownership: "Mulk huquqi",
  prepayment: "Oldindan to‘lov",
  probation: "Sinov muddati",
  // LegalAI
  shart: "Xavfli shart",
  etishmayotgan: "Yetishmayotgan band",
  huquqiy: "Qonun talabi",
};

export const categoryLabel = (c: string) => CATEGORY_LABEL[c] ?? (c ? c.replace(/_/g, " ") : "Xavf");

/** "+998901234567" -> "+998 90 123 45 67" */
export function formatPhone(phone: string): string {
  const m = phone.match(/^\+998(\d{2})(\d{3})(\d{2})(\d{2})$/);
  return m ? `+998 ${m[1]} ${m[2]} ${m[3]} ${m[4]}` : phone;
}

export const pluralFlags = (n: number) => (n === 0 ? "Xavf yo‘q" : `${n} ta xavf`);
