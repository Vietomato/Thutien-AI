const TOKEN_KEY = "thutien.access-token";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = "ApiError"; }
}

export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (token: string) => sessionStorage.setItem(TOKEN_KEY, token),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

export async function api<T>(path: string, init: RequestInit = {}, anonymous = false): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = tokenStore.get();
  if (token && !anonymous) headers.set("Authorization", `Bearer ${token}`);
  let response: Response;
  try { response = await fetch(path, { ...init, headers }); }
  catch { throw new ApiError(0, "Không kết nối được backend. Kiểm tra server đang chạy."); }
  const text = await response.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!response.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : `Lỗi HTTP ${response.status}`;
    if (response.status === 401 && !anonymous) tokenStore.clear();
    const messages: Record<string, string> = {
      "missing token": "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.",
      "invalid or expired token": "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.",
      "role not allowed": "Tài khoản của bạn không có quyền thực hiện thao tác này.",
      "invoice is disputed, no reminder": "Hóa đơn đang tranh chấp nên không thể tạo nháp.",
      "invoice is not overdue": "Hóa đơn chưa quá hạn nên chưa thể tạo nháp.",
      "a pending draft already exists for this invoice": "Hóa đơn đã có nháp chờ duyệt.",
      "invoice data changed in Odoo since this draft was written; reject it and create a new one": "Dữ liệu hóa đơn đã đổi trên Odoo; hãy từ chối nháp cũ và tạo nháp mới.",
    };
    throw new ApiError(response.status, messages[detail] ?? detail);
  }
  return body as T;
}

export const jsonBody = (value: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(value) });
