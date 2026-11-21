export const API = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function detailMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "Kiritilgan ma’lumot noto‘g‘ri";
  return "Xatolik yuz berdi. Qaytadan urinib ko‘ring";
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = init.body instanceof FormData;
  let res: Response;
  try {
    res = await fetch(API + path, {
      credentials: "include",
      ...init,
      headers: isForm ? init.headers : { "Content-Type": "application/json", ...init.headers },
    });
  } catch {
    throw new ApiError(0, "Server bilan aloqa yo‘q. Internet yoki serverni tekshiring");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, detailMessage(data.detail));
  return data as T;
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const patch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
