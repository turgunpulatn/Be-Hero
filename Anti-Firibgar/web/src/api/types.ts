export type Risk = "high" | "medium" | "low";
export type ReviewStatus = "pending" | "analyzing" | "done" | "failed";
export type Source = "pdf" | "docx" | "image" | "sample";

export interface User {
  id: number;
  phone: string;
  full_name: string;
  email: string;
  language: string;
  free_reviews_total: number;
  free_reviews_used: number;
  paid_reviews_left: number;
  reviews_left: number;
}

export interface ReviewBrief {
  id: number;
  status: ReviewStatus;
  goal: string;
  flags: number;
  created_at: string;
}

export interface DocumentListItem {
  id: number;
  title: string;
  source: Source;
  is_sample: boolean;
  created_at: string;
  latest_review: ReviewBrief | null;
}

export interface Clause {
  idx: number;
  title: string;
  text: string;
}

export interface DocumentFull extends DocumentListItem {
  filename: string;
  page_count: number;
  has_file: boolean;
  clauses: Clause[];
}

export interface Finding {
  id: number;
  clause_idx: number;
  risk: Risk;
  category: string;
  title: string;
  explanation: string;
  quote: string;
  suggested_question: string;
  law_refs: string[];
}

export interface Review {
  id: number;
  status: ReviewStatus;
  goal: string;
  summary: string;
  model: string;
  error: string;
  created_at: string;
  finished_at: string | null;
  document_id: number;
  document_title: string;
  document_source: Source;
  findings: Finding[];
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface Plan {
  free_reviews_total: number;
  free_reviews_used: number;
  paid_reviews_left: number;
  package_reviews: number;
  package_price_uzs: number;
  providers: string[];
}

export interface Payment {
  id: number;
  provider: "payme" | "click";
  amount_uzs: number;
  reviews_granted: number;
  status: "pending" | "paid";
}
