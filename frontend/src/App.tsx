import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, jsonBody, tokenStore } from "@/lib/api";

type Obj = Record<string, any>;
const money = (n = 0) => new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(Number(n)) + " ₫";
const points = (n = 0) => new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(Number(n)) + " điểm";
const date = (s?: string) => s ? new Intl.DateTimeFormat("vi-VN").format(new Date(`${s.slice(0,10)}T00:00:00`)) : "—";
const serverMsg = (e: unknown) => e instanceof Error ? e.message : "Có lỗi xảy ra";
const statusText = (s: string) => ({ pending:"Chờ duyệt", approved:"Đã duyệt", rejected:"Đã từ chối" }[s] ?? s);
const roleText = (s: string) => ({ accountant:"Kế toán viên", chief_accountant:"Kế toán trưởng", customer:"Khách hàng", admin:"Quản trị viên" }[s] ?? s);
const short = (s: string) => (s ?? "").replaceAll("₫", "đ");
const homePage = (profile: Obj) => {
  const permissions = new Set<string>(profile.permissions ?? []);
  if (permissions.has("summary:read_all") || permissions.has("summary:read_own")) return "overview";
  if (permissions.has("user:manage")) return "users";
  return "invoices";
};

export default function App() {
  const [me, setMe] = useState<Obj|null>(null);
  const [page, setPage] = useState("overview");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [username, setUsername] = useState("accountant1");
  const [password, setPassword] = useState("");
  const [data, setData] = useState<Obj>({});
  const notify = (s: string) => { setToast(s); window.setTimeout(() => setToast(""), 3500); };
  const load = useCallback(async (profile = me) => {
    if (!profile) return;
    setBusy(true); setError("");
    const perms = new Set<string>(profile.permissions ?? []);
    const jobs: Record<string, Promise<any>> = {};
    if (perms.has("summary:read_all") || perms.has("summary:read_own")) jobs.summary = api("/api/summary");
    if (perms.has("invoice:read_all") || perms.has("invoice:read_own")) jobs.invoices = api("/api/invoices/open");
    if (perms.has("invoice:read_all")) jobs.priority = api("/api/f3/priority");
    if (perms.has("forecast:read")) jobs.forecast = api("/api/forecast");
    if (perms.has("draft:create")) jobs.candidates = api("/api/reminders/candidates");
    if (perms.has("draft:read_own") || perms.has("draft:read_team")) jobs.drafts = api("/api/reminders/drafts");
    if (perms.has("task:read_own") || perms.has("task:read_team")) jobs.tasks = api(`/api/tasks?scope=${perms.has("task:read_team") ? "team" : "mine"}`);
    if (perms.has("task:read_team")) jobs.team = api("/api/team");
    if (perms.has("user:manage")) { jobs.users = api("/api/admin/users"); jobs.customers = api("/api/admin/customers"); }
    if (perms.has("audit:read")) jobs.audit = api("/api/admin/audit?limit=100");
    const entries = await Promise.all(Object.entries(jobs).map(async ([key,p]) => [key, await p.then(v=>({value:v}),e=>({error:e}))] as const));
    const next: Obj = {};
    const failed: string[] = [];
    for (const [key,result] of entries) {
      if ("value" in result) next[key] = result.value;
      else if (result.error instanceof ApiError && result.error.status === 401) { tokenStore.clear(); setMe(null); setData({}); setError("Phiên đăng nhập hết hạn, vui lòng đăng nhập lại."); setBusy(false); return; }
      else { failed.push(key); console.warn(`API ${key}:`, result.error); }
    }
    setData(next); setError(failed.length ? `Không tải được một số dữ liệu (${failed.join(", ")}). Kiểm tra API/Odoo rồi bấm tải lại.` : ""); setBusy(false);
  }, [me]);
  useEffect(() => { if (me) void load(me); }, [me, load]);
  useEffect(() => {
    const token = tokenStore.get(); if (!token) return;
    api<Obj>("/api/auth/me").then(profile => { setMe(profile); setPage(homePage(profile)); }).catch(() => tokenStore.clear());
  }, []);
  const perms = useMemo(() => new Set<string>(me?.permissions ?? []), [me]);
  const canSee = (p: string) => perms.has(p);
  const refresh = async () => { await load(me); };
  const act = async (fn: () => Promise<unknown>, success: string) => {
    setBusy(true); setError("");
    try { await fn(); notify(success); await load(me); }
    catch(e) { setError(serverMsg(e)); }
    finally { setBusy(false); }
  };
  const login = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try {
      const result = await api<Obj>("/api/auth/login", jsonBody({ username, password }), true);
      tokenStore.set(result.access_token); setMe(result);
      setPage(homePage(result));
    } catch(e) { setError(serverMsg(e)); }
    finally { setBusy(false); }
  };
  const logout = async () => { try { await api("/api/auth/logout", jsonBody({})); } catch {} tokenStore.clear(); setMe(null); setData({}); };
  if (!me) return <main className="login-wrap"><form className="login-card" onSubmit={login}><div className="brand-mark">✓</div><p className="eyebrow">THUTIEN AI · DEMO ODOO</p><h1>Đăng nhập</h1><p className="muted">Đăng nhập bằng tài khoản backend đã seed.</p><label>Tên đăng nhập<input value={username} onChange={e=>setUsername(e.target.value)} autoComplete="username" /></label><label>Mật khẩu<input type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password" /></label>{error && <div className="alert error">{error}</div>}<button className="primary full" disabled={busy}>{busy ? "Đang đăng nhập…" : "Đăng nhập"}</button><p className="hint">Tài khoản demo: accountant1 / chief1 · Mật khẩu demo thường là demo12345.</p></form></main>;
  const nav = [
    ["overview","Tổng quan", "summary:read_all"], ["invoices","Công nợ F3", "invoice:read_all"],
    ["forecast","Dự báo F4", "forecast:read"], ["drafts","Nhắc nợ & duyệt", "draft:read_own"],
    ["tasks","Nhiệm vụ", "task:read_own"], ["users","Người dùng", "user:manage"], ["audit","Nhật ký", "audit:read"],
  ].filter(([id, , p]) => canSee(p as string) || (id === "overview" && canSee("summary:read_own")) || (id === "invoices" && canSee("invoice:read_own")) || (p === "draft:read_own" && canSee("draft:read_team")) || (p === "task:read_own" && canSee("task:read_team")));
  const title = ({overview:"Tổng quan",invoices:"Ưu tiên thu nợ · F3",forecast:"Dự báo dòng tiền · F4",drafts:"Nhắc nợ & phê duyệt",tasks:"Nhiệm vụ",users:"Quản lý người dùng",audit:"Nhật ký kiểm toán"} as Obj)[page] ?? "ThuTien AI";
  const items: Obj[] = data.priority?.items ?? data.invoices?.items ?? [];
  const createDraft = (invoiceId:string) => act(() => api("/api/reminders/drafts",jsonBody({invoice_id:invoiceId})), "Đã tạo nháp từ dữ liệu Odoo; chưa gửi email.");
  return <div className="app-shell"><aside className="sidebar"><div className="logo"><span className="brand-mark">✓</span><span>ThuTien AI</span></div><div className="nav-label">WORKSPACE</div><nav>{nav.map(([id,label])=><button key={id} className={page===id?"nav-item active":"nav-item"} onClick={()=>setPage(id as string)}><span className="nav-dot"/>{label}</button>)}</nav><div className="side-bottom"><div className="avatar">{(me.full_name??me.username).slice(0,1).toUpperCase()}</div><div className="who"><b>{me.full_name}</b><small>{roleText(me.role)}</small></div><button className="logout" onClick={logout}>Đăng xuất</button></div></aside>
  <main className="main"><header className="topbar"><div><div className="eyebrow">THUTIEN AI / WORKSPACE</div><h1>{title}</h1></div><div className="top-actions"><span className="source-pill"><i/> Odoo · chỉ đọc</span><button className="icon-btn" onClick={()=>void refresh()} title="Tải lại">↻</button><span className="avatar small">{(me.full_name??me.username).slice(0,1).toUpperCase()}</span></div></header>
  <section className="content">{error&&<div className="alert error">{error}<button onClick={()=>setError("")}>×</button></div>}{busy&&<div className="loading-line">Đang đồng bộ dữ liệu…</div>}
  {page==="overview"&&<><div className="hero"><div><div className="eyebrow">BẢNG ĐIỀU KHIỂN</div><h2>Chào {me.full_name?.split(" ").slice(-1)[0] ?? me.username}</h2><p>Dữ liệu công nợ được đọc trực tiếp từ Odoo. Mọi nháp cần người có thẩm quyền duyệt.</p></div><span className="hero-icon">↗</span></div><div className="kpis">{[["Còn phải thu",money(data.summary?.total_remaining),"tổng số dư mở"],["Hóa đơn mở",data.summary?.open_count??items.length,"hóa đơn"],["Đã quá hạn",money(data.summary?.overdue_amount),`${data.summary?.overdue_count??0} hóa đơn`],["Tranh chấp",money(data.summary?.disputed_amount),`${data.summary?.disputed_count??0} hóa đơn`]].map(([a,b,c])=><div className="kpi" key={a as string}><span>{a}</span><strong>{b}</strong><small>{c}</small></div>)}</div><InvoicesTable items={(data.priority?.items??data.invoices?.items??[]).slice(0,5)} createDraft={createDraft} onSelect={()=>setPage("invoices")} canDraft={canSee("draft:create")} /></>}
  {page==="invoices"&&<><div className="section-heading"><div><h2>Danh sách ưu tiên F3</h2><p>Xếp hạng theo số dư còn nợ, tỷ lệ trả trễ và số ngày quá hạn.</p></div><span className="source-pill"><i/> {data.priority?.source??data.invoices?.source??"Đang tải"} · {date(data.priority?.as_of_date??data.invoices?.as_of_date)}</span></div><InvoicesTable items={items} createDraft={createDraft} onSelect={()=>{}} canDraft={canSee("draft:create")} /></>}
  {page==="forecast"&&<Forecast data={data.forecast}/ >}
  {page==="drafts"&&<Drafts data={data} canCreate={canSee("draft:create")} canDecide={canSee("draft:decide")} act={act} />}
  {page==="tasks"&&<Tasks data={data} canAssign={canSee("task:assign")} act={act} />}
  {page==="users"&&<Users data={data} act={act} />}
  {page==="audit"&&<Audit items={data.audit?.items??[]} />}
  </section></main>{toast&&<div className="toast">✓ {toast}</div>}</div>;
}

function InvoicesTable({items,createDraft,onSelect,canDraft}:{items:Obj[];createDraft:(id:string)=>void;onSelect:()=>void;canDraft:boolean}) {
 const [query,setQuery]=useState(""); const rows=items.filter(i=>`${i.invoice_id} ${i.display_name} ${i.customer_id}`.toLowerCase().includes(query.toLowerCase()));
 return <div className="panel"><div className="table-tools"><input placeholder="Tìm hóa đơn hoặc khách hàng…" value={query} onChange={e=>setQuery(e.target.value)}/><span className="muted">{rows.length} hóa đơn</span></div><div className="table-scroll"><table><thead><tr><th>ƯU TIÊN</th><th>HÓA ĐƠN</th><th>KHÁCH HÀNG</th><th>HẠN TRẢ</th><th>CÒN NỢ</th><th>DỰ ĐOÁN P50</th><th>TRẠNG THÁI</th><th>NHẮC NỢ</th></tr></thead><tbody>{rows.map((i,n)=>{const hold=i.hold_reasons??[];return <tr key={i.invoice_id} onClick={onSelect}><td><b className="rank">#{i.rank??n+1}</b><small>{points(i.priority_score)} điểm</small></td><td><b>{i.invoice_id}</b><small>{money(i.invoice_amount)} tổng</small></td><td>{i.display_name}<small>{i.customer_id}</small></td><td>{date(i.due_date)}<small>{i.days_overdue>0?`Quá hạn ${i.days_overdue} ngày`:"Chưa đến hạn"}</small></td><td className="amount">{money(i.remaining_amount)}</td><td>{i.prediction?.predicted_date_p50?date(i.prediction.predicted_date_p50):"—"}<small>{i.late_rate_source??""}</small></td><td><span className={`badge ${i.dispute_status==="disputed"?"amber":i.days_overdue>0?"red":"blue"}`}>{i.dispute_status==="disputed"?"Tranh chấp":i.days_overdue>0?"Quá hạn":"Chưa đến hạn"}</span></td><td>{hold.length?<span className="badge amber">{hold.join(", ")}</span>:i.eligible_for_reminder?<button className="secondary small-btn" disabled={!canDraft} onClick={e=>{e.stopPropagation();createDraft(i.invoice_id)}}>Tạo nháp</button>:<span className="muted">Chưa đủ điều kiện</span>}</td></tr>})}{!rows.length&&<tr><td colSpan={8} className="empty">Chưa có hóa đơn để hiển thị. Kiểm tra kết nối Odoo và quyền tài khoản.</td></tr>}</tbody></table></div></div>
}
function Forecast({data}:{data?:Obj}) { const weeks:Obj[]=data?.weeks??[]; const max=Math.max(1,...weeks.map(w=>w.receipt_p75));return <><div className="section-heading"><div><h2>Dự báo 12 tuần</h2><p>Phân vị thu tiền P25, P50, P75 do backend tính; nghĩa vụ lấy từ hóa đơn nhà cung cấp Odoo.</p></div><span className="source-pill"><i/> Odoo · chỉ đọc</span></div><div className="forecast-grid">{weeks.map((w,i)=><article className="week-card" key={w.week_start}><span className="eyebrow">TUẦN {i+1} · {date(w.week_start)}</span><div className="bars"><i style={{height:`${Math.max(3,w.receipt_p25/max*100)}%`}}/><i style={{height:`${Math.max(3,w.receipt_p50/max*100)}%`}}/><i style={{height:`${Math.max(3,w.receipt_p75/max*100)}%`}}/></div><div className="week-legend"><span>P25 <b>{short(money(w.receipt_p25))}</b></span><span>P50 <b>{short(money(w.receipt_p50))}</b></span><span>P75 <b>{short(money(w.receipt_p75))}</b></span></div><div className="week-foot">Nghĩa vụ {short(money(w.obligations))} · chênh lệch {short(money(w.gap_p75))}</div></article>)}</div>{!weeks.length&&<div className="panel empty">Backend chưa trả dữ liệu dự báo.</div>}</> }
function Drafts({data,canCreate,canDecide,act}:{data:Obj;canCreate:boolean;canDecide:boolean;act:(fn:()=>Promise<unknown>,s:string)=>void}) { const drafts:Obj[]=data.drafts?.items??[]; const candidates:Obj[]=data.candidates?.items??[]; const [sel,setSel]=useState<Obj|null>(null); const [subject,setSubject]=useState("");const [body,setBody]=useState("");const [tab,setTab]=useState("pending"); const shown=drafts.filter(d=>d.status===tab); const chosen=shown.find(d=>d.id===sel?.id)??shown[0]; useEffect(()=>{if(chosen){setSubject(chosen.subject);setBody(chosen.body)}},[chosen?.id,chosen?.subject,chosen?.body]);return <><div className="section-heading"><div><h2>Nháp nhắc nợ và duyệt</h2><p>Backend tạo nội dung theo mẫu cố định, kế toán trưởng duyệt. Không có email tự gửi hoặc LLM trong backend hiện tại.</p></div></div><div className="draft-layout"><div className="panel"><div className="tabs">{["pending","approved","rejected"].map(s=><button className={tab===s?"selected":""} key={s} onClick={()=>{setTab(s);setSel(null)}}>{statusText(s)} <b>{drafts.filter(d=>d.status===s).length}</b></button>)}</div>{shown.map(d=><button className={`draft-list-item ${chosen?.id===d.id?"chosen":""}`} key={d.id} onClick={()=>setSel(d)}><b>{d.invoice_id}</b><span>{d.customer_name} · {money(d.amount)}</span><small>{statusText(d.status)} · {date(d.created_at?.slice(0,10))}</small></button>)}{!shown.length&&<div className="empty">Không có nháp trong mục này.</div>}</div><div className="panel draft-detail"><h3>{chosen?`Nháp hóa đơn ${chosen.invoice_id}`:"Chi tiết nháp"}</h3>{chosen?<><p className="muted">{chosen.customer_name} · còn nợ {money(chosen.amount)} · hạn {date(chosen.due_date)}</p><label>Tiêu đề<input value={subject} onChange={e=>setSubject(e.target.value)} disabled={chosen.status!=="pending"||!canCreate}/></label><label>Nội dung<textarea rows={9} value={body} onChange={e=>setBody(e.target.value)} disabled={chosen.status!=="pending"||!canCreate}/></label><div className="checks">{(chosen.checks??[]).map((c:Obj)=><span className={c.ok?"ok":"bad"} key={c.label}>{c.ok?"✓":"!"} {c.label}</span>)}</div><div className="actions">{chosen.status==="pending"&&canCreate&&<button className="secondary" onClick={()=>act(()=>api(`/api/reminders/drafts/${chosen.id}`,{method:"PATCH",body:JSON.stringify({subject,body})}),"Đã lưu nội dung nháp.")}>Lưu chỉnh sửa</button>}{chosen.status==="pending"&&canDecide&&<><button className="primary" disabled={!chosen.checks_ok} onClick={()=>act(()=>api(`/api/reminders/drafts/${chosen.id}/approve`,jsonBody({})),"Đã duyệt nháp.")}>Duyệt</button><button className="danger" onClick={()=>act(()=>api(`/api/reminders/drafts/${chosen.id}/reject`,jsonBody({note:"Từ chối từ giao diện"})),"Đã từ chối nháp.")}>Từ chối</button></>}</div><p className="hint">Duyệt chỉ ghi nhận trạng thái và nhật ký. Không gửi email.</p></>:<p className="muted">Chọn nháp ở danh sách bên trái.</p>}</div></div>{canCreate&&<div className="panel candidate-panel"><h3>Hóa đơn có thể tạo nháp</h3><p className="muted">Dữ liệu kiểm tra từ Odoo; nháp bị chặn nếu hóa đơn chưa quá hạn, tranh chấp hoặc đã có nháp chờ duyệt.</p><div className="candidate-list">{candidates.map(i=><div className="candidate" key={i.invoice_id}><span><b>{i.invoice_id}</b> · {i.display_name}<small>Quá hạn {i.overdue_days} ngày · {money(i.remaining_amount)}</small></span><button className="secondary small-btn" onClick={()=>act(()=>api("/api/reminders/drafts",jsonBody({invoice_id:i.invoice_id})),"Đã tạo nháp từ hóa đơn Odoo.")}>Tạo nháp mẫu</button></div>)}{!candidates.length&&<div className="empty">Không có hóa đơn quá hạn đủ điều kiện tạo nháp.</div>}</div></div>}</>}
function Tasks({data,canAssign,act}:{data:Obj;canAssign:boolean;act:(fn:()=>Promise<unknown>,s:string)=>void}) { const tasks:Obj[]=data.tasks?.items??[]; const [invoice,setInvoice]=useState("");const [assignee,setAssignee]=useState(""); const [note,setNote]=useState("");return <><div className="section-heading"><div><h2>Nhiệm vụ thu hồi công nợ</h2><p>Trạng thái và người phụ trách được lưu ở backend.</p></div></div>{canAssign&&<form className="panel task-form" onSubmit={e=>{e.preventDefault();act(()=>api("/api/tasks",jsonBody({invoice_id:invoice,assignee_id:Number(assignee),note})),"Đã giao nhiệm vụ.")}}><h3>Giao nhiệm vụ</h3><input placeholder="Mã hóa đơn" value={invoice} onChange={e=>setInvoice(e.target.value)} required/><select value={assignee} onChange={e=>setAssignee(e.target.value)} required><option value="">Chọn người phụ trách</option>{(data.team?.items??[]).map((u:Obj)=><option key={u.id} value={u.id}>{u.full_name} · {u.username}</option>)}</select><input placeholder="Ghi chú" value={note} onChange={e=>setNote(e.target.value)}/><button className="primary">Giao việc</button></form>}<div className="panel table-scroll"><table><thead><tr><th>HÓA ĐƠN</th><th>NỘI DUNG</th><th>NGƯỜI PHỤ TRÁCH</th><th>TRẠNG THÁI</th><th></th></tr></thead><tbody>{tasks.map(t=><tr key={t.id}><td>{t.invoice_id}</td><td>{t.note||t.title}</td><td>{t.assignee_name}</td><td>{t.status==="done"?"Hoàn tất":"Đang mở"}</td><td><button className="secondary small-btn" onClick={()=>act(()=>api(`/api/tasks/${t.id}`,{method:"PATCH",body:JSON.stringify({status:t.status==="done"?"open":"done"})}),"Đã cập nhật nhiệm vụ.")}>{t.status==="done"?"Mở lại":"Hoàn tất"}</button></td></tr>)}</tbody></table>{!tasks.length&&<div className="empty">Chưa có nhiệm vụ.</div>}</div></>}
function Users({data,act}:{data:Obj;act:(fn:()=>Promise<unknown>,s:string)=>void}){const users:Obj[]=data.users?.items??[];const [name,setName]=useState("");const [full,setFull]=useState("");const [pw,setPw]=useState("demo12345");const [role,setRole]=useState("accountant");return <><div className="section-heading"><div><h2>Tài khoản hệ thống</h2><p>Quản lý tài khoản theo quyền API hiện có; không hỗ trợ tự đặt quyền tùy biến.</p></div></div><form className="panel task-form" onSubmit={e=>{e.preventDefault();act(()=>api("/api/admin/users",jsonBody({username:name,full_name:full,password:pw,role})),"Đã tạo tài khoản.")}}><h3>Tạo tài khoản</h3><input placeholder="Tên đăng nhập" value={name} onChange={e=>setName(e.target.value)} required/><input placeholder="Họ tên" value={full} onChange={e=>setFull(e.target.value)} required/><input type="password" value={pw} onChange={e=>setPw(e.target.value)} minLength={8} required/><select value={role} onChange={e=>setRole(e.target.value)}>{["accountant","chief_accountant","customer","admin"].map(x=><option key={x} value={x}>{roleText(x)}</option>)}</select><button className="primary">Tạo tài khoản</button></form><div className="panel table-scroll"><table><thead><tr><th>TÊN ĐĂNG NHẬP</th><th>HỌ TÊN</th><th>VAI TRÒ</th><th>TRẠNG THÁI</th><th></th></tr></thead><tbody>{users.map(u=><tr key={u.id}><td>{u.username}</td><td>{u.full_name}</td><td>{roleText(u.role)}</td><td>{u.is_active?"Hoạt động":"Đã khóa"}</td><td><button className="secondary small-btn" onClick={()=>act(()=>api(`/api/admin/users/${u.id}`,{method:"PATCH",body:JSON.stringify({is_active:!u.is_active})}),"Đã cập nhật tài khoản.")}>{u.is_active?"Khóa":"Mở khóa"}</button></td></tr>)}</tbody></table></div></>}
function Audit({items}:{items:Obj[]}){return <><div className="section-heading"><div><h2>Nhật ký kiểm toán</h2><p>Nhật ký được ghi ở backend; dữ liệu nhạy cảm không hiển thị ở đây.</p></div></div><div className="panel table-scroll"><table><thead><tr><th>THỜI GIAN</th><th>NGƯỜI DÙNG</th><th>HÀNH ĐỘNG</th><th>ĐỐI TƯỢNG</th></tr></thead><tbody>{items.map((x,i)=><tr key={x.id??i}><td>{new Date(x.at).toLocaleString("vi-VN")}</td><td>{x.actor}</td><td>{x.action}</td><td>{x.target}</td></tr>)}</tbody></table>{!items.length&&<div className="empty">Chưa có nhật ký.</div>}</div></>}
