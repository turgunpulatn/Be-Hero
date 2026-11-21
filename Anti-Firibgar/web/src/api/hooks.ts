import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, patch, post } from "./client";
import type { DocumentFull, DocumentListItem, Message, Payment, Plan, Review, User } from "./types";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api<User>("/me"), retry: false });

export const useDocuments = (q: string) =>
  useQuery({
    queryKey: ["documents", q],
    queryFn: () => api<DocumentListItem[]>(`/documents?q=${encodeURIComponent(q)}`),
    placeholderData: (prev) => prev,
  });

export const useDocument = (id: number | undefined) =>
  useQuery({ queryKey: ["document", id], queryFn: () => api<DocumentFull>(`/documents/${id}`), enabled: !!id });

export const useReview = (id: number | undefined) =>
  useQuery({
    queryKey: ["review", id],
    queryFn: () => api<Review>(`/reviews/${id}`),
    enabled: !!id,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "pending" || s === "analyzing" ? 2000 : false;
    },
  });

export const useMessages = (reviewId: number | undefined) =>
  useQuery({
    queryKey: ["messages", reviewId],
    queryFn: () => api<Message[]>(`/reviews/${reviewId}/messages`),
    enabled: !!reviewId,
  });

export const usePlan = () => useQuery({ queryKey: ["plan"], queryFn: () => api<Plan>("/payments/plan") });

export function useSendOtp() {
  return useMutation({
    mutationFn: (phone: string) =>
      post<{ phone: string; resend_in: number; dev_code: string | null }>("/auth/otp/send", { phone }),
  });
}

export function useVerifyOtp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { phone: string; code: string }) => post<User>("/auth/otp/verify", v),
    onSuccess: (user) => {
      qc.clear();
      qc.setQueryData(["me"], user);
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post<void>("/auth/logout"),
    onSuccess: () => qc.clear(),
  });
}

export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { full_name: string; email: string }) => patch<User>("/me", v),
    onSuccess: (user) => qc.setQueryData(["me"], user),
  });
}

export function useUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<DocumentFull>("/documents", { method: "POST", body: form });
    },
    onSuccess: (doc) => {
      qc.setQueryData(["document", doc.id], doc);
      qc.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}

export function useStartReview(documentId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (goal: string) => post<Review>(`/documents/${documentId}/reviews`, { goal }),
    onSuccess: (review) => {
      qc.setQueryData(["review", review.id], review);
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["document", documentId] });
      qc.invalidateQueries({ queryKey: ["me"] });
      qc.invalidateQueries({ queryKey: ["plan"] });
    },
  });
}

export function useSendMessage(reviewId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (content: string) => post<Message[]>(`/reviews/${reviewId}/messages`, { content }),
    onSuccess: (pair) =>
      qc.setQueryData<Message[]>(["messages", reviewId], (old = []) => [...old, ...pair]),
  });
}

export function usePay() {
  const qc = useQueryClient();
  return {
    create: useMutation({ mutationFn: (provider: string) => post<Payment>("/payments", { provider }) }),
    confirm: useMutation({
      mutationFn: (id: number) => post<Payment>(`/payments/${id}/confirm`),
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: ["me"] });
        qc.invalidateQueries({ queryKey: ["plan"] });
      },
    }),
  };
}
