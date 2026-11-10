export type Row = Record<string, any>;
export type Action = (job: () => Promise<unknown>, message: string) => Promise<boolean>;

const number = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 });
export const money = (value: number | string | undefined) => `${number.format(Number(value ?? 0))} đ`;
export const score = (value: number | string | undefined) => number.format(Number(value ?? 0));
export const date = (value?: string) => value ? new Intl.DateTimeFormat("vi-VN").format(new Date(`${value.slice(0, 10)}T00:00:00`)) : "—";
export const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Có lỗi xảy ra.";
export const roleName = (role: string) => ({
  accountant: "Nhân viên kế toán", chief_accountant: "Kế toán trưởng",
  customer: "Khách hàng", admin: "Quản trị viên",
}[role] ?? role);
export const draftStatus = (status: string) => ({ pending: "Chờ duyệt", approved: "Đã duyệt", rejected: "Đã từ chối" }[status] ?? status);
export const holdName = (reason: string) => ({
  no_remaining_balance: "Đã hết nợ", not_overdue: "Chưa quá hạn", disputed: "Đang tranh chấp",
  missing_contact: "Thiếu email liên hệ", active_draft_exists: "Đã có nháp chờ duyệt",
}[reason] ?? reason);
export const methodName = (method: string) => ({
  customer_median: "Lịch sử của khách", global_median: "Lịch sử chung", no_history: "Chưa đủ lịch sử",
}[method] ?? method);

export function Head({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  return <div className="page-head"><div><h1 className="page-title">{title}</h1>{subtitle && <div className="page-sub">{subtitle}</div>}</div>{right}</div>;
}

export function Tag({ kind, children }: { kind: string; children: React.ReactNode }) {
  return <span className={`tag tag-${kind}`}>{children}</span>;
}
