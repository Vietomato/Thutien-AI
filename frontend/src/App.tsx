import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, jsonBody, tokenStore } from "@/lib/api";
import { ForecastPage, Invoices, Overview } from "@/FinancePages";
import { AdminUsers, Audit, Customers, Reminders, Tasks } from "@/Operations";
import { Action, errorMessage, roleName, Row } from "@/ui";

type Page = "overview" | "invoices" | "forecast" | "drafts" | "tasks" | "payments" | "users" | "audit";
type Profile = Row & { username: string; full_name: string; role: string; permissions: string[] };

function initialPage(profile: Profile): Page {
  const requested = window.location.hash.slice(1) as Page;
  const required: Partial<Record<Page, string[]>> = {
    overview: ["summary:read_all", "summary:read_own"], invoices: ["invoice:read_all", "invoice:read_own"],
    forecast: ["forecast:read"], drafts: ["draft:read_own", "draft:read_team"],
    tasks: ["task:read_own", "task:read_team"], payments: ["payment:read_own"],
    users: ["user:manage"], audit: ["audit:read"],
  };
  if (required[requested]?.some(permission => profile.permissions.includes(permission))) return requested;
  return profile.permissions.includes("user:manage") ? "users" : "overview";
}

const demoAccounts = [
  ["accountant1", "Nhân viên kế toán"], ["chief1", "Kế toán trưởng"],
  ["customer1", "Khách hàng"], ["admin1", "Quản trị viên"],
] as const;

export default function App() {
  const [me, setMe] = useState<Profile | null>(null);
  const [restoring, setRestoring] = useState(Boolean(tokenStore.get()));
  const [page, setPage] = useState<Page>("overview");
  const [data, setData] = useState<Row>({});
  const [busy, setBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [dataError, setDataError] = useState("");
  const [toast, setToast] = useState("");
  const [authTab, setAuthTab] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("accountant1");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [accountOpen, setAccountOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const requestId = useRef(0);
  const actionInFlight = useRef(false);

  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 3600);
  };

  const load = useCallback(async (profile: Profile) => {
    const current = ++requestId.current;
    setBusy(true);
    setDataError("");
    const p = new Set(profile.permissions);
    const jobs: Record<string, Promise<Row>> = {};
    if (p.has("summary:read_all") || p.has("summary:read_own")) jobs.summary = api("/api/summary");
    if (p.has("invoice:read_all") || p.has("invoice:read_own")) jobs.invoices = api("/api/invoices/open");
    if (p.has("payment:read_own")) jobs.payments = api("/api/payments/history");
    if (p.has("invoice:read_all")) jobs.priority = api("/api/f3/priority");
    if (p.has("forecast:read")) jobs.forecast = api("/api/forecast");
    if (p.has("draft:create")) jobs.candidates = api("/api/reminders/candidates");
    if (p.has("draft:read_own") || p.has("draft:read_team")) jobs.drafts = api("/api/reminders/drafts");
    if (p.has("task:read_own") || p.has("task:read_team")) jobs.tasks = api(`/api/tasks?scope=${p.has("task:read_team") ? "team" : "mine"}`);
    if (p.has("task:read_team")) jobs.team = api("/api/team");
    if (p.has("user:manage")) { jobs.users = api("/api/admin/users"); jobs.customers = api("/api/admin/customers"); }
    if (p.has("audit:read")) jobs.audit = api("/api/admin/audit?limit=100");
    const results = await Promise.all(Object.entries(jobs).map(async ([name, task]) => {
      const result = await task.then(value => ({ value }), error => ({ error }));
      if (current === requestId.current && "value" in result) {
        setData(previous => ({ ...previous, [name]: result.value }));
      }
      return { name, result };
    }));
    if (current !== requestId.current) return;
    const next: Row = {};
    const failed: string[] = [];
    for (const { name, result } of results) {
      if ("value" in result) next[name] = result.value;
      else if (result.error instanceof ApiError && result.error.status === 401) {
        tokenStore.clear(); setMe(null); setData({}); setBusy(false);
        setAuthError("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
        return;
      } else { failed.push(name); console.warn(`API ${name}`, result.error); }
    }
    setData(next);
    setDataError(failed.length ? `Không tải được: ${failed.join(", ")}. Kiểm tra /health, Odoo và PostgreSQL rồi tải lại.` : "");
    setBusy(false);
  }, []);

  useEffect(() => {
    if (!tokenStore.get()) { setRestoring(false); return; }
    api<Profile>("/api/auth/me").then(profile => { setMe(profile); setPage(initialPage(profile)); void load(profile); }).catch(() => {
      tokenStore.clear(); setAuthError("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
    }).finally(() => setRestoring(false));
  }, [load]);

  const perms = useMemo(() => new Set(me?.permissions ?? []), [me]);
  const can = (permission: string) => perms.has(permission);
  const navigate = (to: string) => { window.location.hash = to; setPage(to as Page); setDataError(""); };
  const refresh = () => { if (me) void load(me); };

  const act: Action = async (job, message) => {
    if (!me || actionInFlight.current) return false;
    actionInFlight.current = true;
    setBusy(true); setDataError("");
    try { await job(); notify(message); await load(me); return true; }
    catch (error) { setDataError(errorMessage(error)); return false; }
    finally { actionInFlight.current = false; setBusy(false); }
  };

  async function submitAuth(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setAuthError(""); setDataError("");
    try {
      if (authTab === "register") {
        await api("/api/auth/register", jsonBody({ username: username.trim(), full_name: fullName.trim(), password }), true);
        setAuthTab("login"); notify("Đã tạo tài khoản khách hàng. Quản trị viên cần liên kết khách hàng Odoo để xem dữ liệu.");
      } else {
        const profile = await api<Profile & { access_token: string }>("/api/auth/login", jsonBody({ username: username.trim(), password }), true);
        tokenStore.set(profile.access_token);
        setMe(profile); setPage(initialPage(profile)); setData({}); setPassword("");
        await load(profile);
      }
    } catch (error) { setAuthError(errorMessage(error)); }
    finally { setBusy(false); }
  }

  function logout() {
    requestId.current++;
    void api("/api/auth/logout", jsonBody({})).catch(() => {});
    tokenStore.clear(); setMe(null); setData({}); setAuthError(""); setDataError("");
    setAccountOpen(false); setPasswordOpen(false); setPage("overview"); window.history.replaceState(null, "", "/app/");
  }

  async function changePassword(event: React.FormEvent) {
    event.preventDefault();
    if (await act(() => api("/api/auth/change-password", jsonBody({ old_password: oldPassword, new_password: newPassword })), "Đã đổi mật khẩu.")) {
      setOldPassword(""); setNewPassword(""); setPasswordOpen(false);
    }
  }

  if (restoring) return <div className="auth"><div className="auth-panel"><div className="auth-card"><h2>Đang mở phiên làm việc…</h2></div></div></div>;
  if (!me) return <div className="auth">
    <section className="auth-brand"><div className="brand-row"><span className="brand-mark">✓</span><span className="brand-name">ThuTiền AI</span></div><div className="brand-body"><h1>Công nợ rõ ràng.<br />Quyết định có kiểm soát.</h1><p className="lead">Kết nối hóa đơn Odoo, xếp ưu tiên F3 và chuẩn bị nháp nhắc nợ để kế toán duyệt.</p><div className="bullets"><div className="bullet">Xem số dư, hạn thanh toán và lý do xếp hạng.</div><div className="bullet">Theo dõi dự báo thu tiền và nghĩa vụ trong 12 tuần.</div><div className="bullet">Ghi nhiệm vụ, nháp và nhật ký vào PostgreSQL của ứng dụng.</div></div></div><div className="brand-foot">Odoo chỉ đọc · Kế toán giữ quyền quyết định</div></section>
    <section className="auth-panel"><div className="auth-card"><div><span className="eyebrow">THUTIỀN AI · BẢN DEMO LOCAL</span><h2>{authTab === "login" ? "Đăng nhập" : "Tạo tài khoản khách hàng"}</h2><p className="sub">{authTab === "login" ? "Đăng nhập bằng tài khoản đã seed trong PostgreSQL." : "Tài khoản mới cần quản trị viên liên kết với khách hàng Odoo."}</p></div><div className="tabs"><button className="tab" aria-selected={authTab === "login"} onClick={() => { setAuthTab("login"); setAuthError(""); }}>Đăng nhập</button><button className="tab" aria-selected={authTab === "register"} onClick={() => { setAuthTab("register"); setAuthError(""); }}>Đăng ký</button></div><form onSubmit={submitAuth}>{authTab === "login" && <div className="demo"><span className="eyebrow">Thử từng vai trò</span><div className="chips">{demoAccounts.map(([id, label]) => <button type="button" className="chip" aria-pressed={username === id} key={id} onClick={() => setUsername(id)}>{label}</button>)}</div></div>}{authTab === "register" && <div className="field"><label>Họ tên</label><input className="input" value={fullName} onChange={e => setFullName(e.target.value)} required /></div>}<div className="field"><label>Tên đăng nhập</label><input className="input" autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} required /></div><div className="field"><label>Mật khẩu</label><input className="input" type="password" autoComplete={authTab === "login" ? "current-password" : "new-password"} value={password} onChange={e => setPassword(e.target.value)} minLength={authTab === "register" ? 8 : undefined} required /></div>{authError && <div className="alert alert-danger" role="alert">{authError}</div>}<button className="btn" disabled={busy}>{busy ? "Đang xử lý…" : authTab === "login" ? "Đăng nhập" : "Tạo tài khoản"}</button></form><div className="role-hint">Mật khẩu demo do người chạy <code>scripts/seed_users.py</code> thiết lập. Chọn vai trò chỉ điền tên đăng nhập, không đổi quyền tài khoản.</div></div></section>
    {toast && <div className="toast">{toast}</div>}
  </div>;

  const nav: { id: Page; label: string; visible: boolean }[] = [
    { id: "overview", label: "Tổng quan", visible: can("summary:read_all") || can("summary:read_own") },
    { id: "invoices", label: can("invoice:read_all") ? "Công nợ F3" : "Hóa đơn của tôi", visible: can("invoice:read_all") || can("invoice:read_own") },
    { id: "forecast", label: "Dự báo F4", visible: can("forecast:read") },
    { id: "drafts", label: "Nhắc nợ", visible: can("draft:read_own") || can("draft:read_team") },
    { id: "tasks", label: "Nhiệm vụ", visible: can("task:read_own") || can("task:read_team") },
    { id: "payments", label: "Thanh toán", visible: can("payment:read_own") && !can("payment:read_all") },
    { id: "users", label: "Người dùng", visible: can("user:manage") },
    { id: "audit", label: "Nhật ký", visible: can("audit:read") },
  ];
  return <div className="app"><aside className="sidebar"><div className="side-brand"><span className="brand-mark">✓</span><span>ThuTiền AI</span></div><nav className="side-nav" aria-label="Điều hướng chính">{nav.filter(x => x.visible).map(x => <button className="nav-link" key={x.id} aria-current={page === x.id ? "page" : undefined} onClick={() => navigate(x.id)}>{x.label}</button>)}</nav><div className="acct"><button className="acct-trigger" aria-expanded={accountOpen} onClick={() => setAccountOpen(v => !v)}><span className="avatar">{me.full_name.slice(0, 1).toUpperCase()}</span><span className="acct-text"><span className="acct-text-name">{me.full_name}</span><span className="acct-text-role">{roleName(me.role)}</span></span></button>{accountOpen && <div className="acct-menu"><div className="acct-head"><span className="acct-name">{me.full_name}</span><span className="acct-sub">@{me.username} · {roleName(me.role)}</span></div><div className="acct-items"><button className="acct-item" onClick={() => { setPasswordOpen(true); setAccountOpen(false); }}>Đổi mật khẩu</button><button className="acct-item acct-logout" onClick={logout}>Đăng xuất / đổi vai trò</button></div></div>}<button className="logout-btn" onClick={logout}>Đăng xuất</button></div></aside>
    <main className="content">{dataError && <div className="alert alert-danger inline-alert" role="alert"><span>{dataError}</span><button aria-label="Đóng thông báo" onClick={() => setDataError("")}>×</button></div>}{busy && <div className="loading">Đang đồng bộ dữ liệu…</div>}{page === "overview" && <Overview data={data} onNavigate={navigate} />}{page === "invoices" && <Invoices data={data} isStaff={can("invoice:read_all")} canDraft={can("draft:create")} canAssign={can("task:assign")} onDrafts={() => navigate("drafts")} onTasks={() => navigate("tasks")} act={act} />}{page === "forecast" && <ForecastPage forecast={data.forecast} />}{page === "drafts" && <Reminders data={data} viewerId={me.id} canCreate={can("draft:create")} canDecide={can("draft:decide")} act={act} />}{page === "tasks" && <Tasks data={data} canAssign={can("task:assign")} act={act} />}{page === "payments" && <Customers data={data} />}{page === "users" && <AdminUsers data={data} act={act} />}{page === "audit" && <Audit data={data} />}<div className="form-actions"><button className="btn btn-secondary btn-compact" onClick={refresh} disabled={busy}>Tải lại dữ liệu</button><span className="micro">Mọi số liệu Odoo được đọc lại khi tải trang hoặc bấm nút này.</span></div></main>
    {passwordOpen && <div className="modal-backdrop"><form className="auth-card modal-card" onSubmit={changePassword}><h2>Đổi mật khẩu</h2><div className="field"><label>Mật khẩu hiện tại</label><input className="input" type="password" value={oldPassword} onChange={e => setOldPassword(e.target.value)} required /></div><div className="field"><label>Mật khẩu mới</label><input className="input" type="password" minLength={8} value={newPassword} onChange={e => setNewPassword(e.target.value)} required /></div><div className="form-actions"><button className="btn" disabled={busy}>Lưu mật khẩu</button><button className="btn btn-secondary" type="button" onClick={() => setPasswordOpen(false)}>Hủy</button></div></form></div>}
    {toast && <div className="toast">✓ {toast}</div>}
  </div>;
}
