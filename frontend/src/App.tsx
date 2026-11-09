import { useEffect, useState } from 'react'
import { getPriority, getPriorityMock, type PriorityResponse } from './api/client'

type Page = 'Đăng nhập' | 'Tổng quan' | 'Ưu tiên thu' | 'Dự báo thu' | 'Nhật ký'

const pages: Page[] = ['Đăng nhập', 'Tổng quan', 'Ưu tiên thu', 'Dự báo thu', 'Nhật ký']
const holdLabels: Record<string, string> = {
  no_remaining_balance: 'Đã tất toán',
  not_overdue: 'Chưa quá hạn',
  disputed: 'Đang tranh chấp',
  missing_contact: 'Thiếu liên hệ',
  active_draft_exists: 'Đã có nháp nhắc',
}

function formatMoney(value: number, currency: string) {
  return new Intl.NumberFormat('vi-VN', {
    style: 'currency', currency, maximumFractionDigits: 0,
  }).format(value)
}

function toNumber(value: number | string) {
  return typeof value === 'number' ? value : Number(value)
}

function PriorityPage() {
  const [result, setResult] = useState<PriorityResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    getPriority(controller.signal)
      .then(setResult)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setResult(null)
          setError(reason instanceof Error ? reason.message : 'Có lỗi khi tải dữ liệu')
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [reload])

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">F3 · CÔNG NỢ</p>
          <h2>Khoản cần ưu tiên xử lý</h2>
          <p className="muted">Điểm ưu tiên là heuristic: số còn nợ × tỷ lệ trả trễ × số ngày quá hạn.</p>
        </div>
        <button className="secondary-button" onClick={() => setReload((n) => n + 1)}>Tải lại</button>
      </div>
      {loading && <p className="state-message">Đang tải danh sách…</p>}
      {!loading && error && (
        <div className="state-message error" role="alert">
          <strong>Chưa lấy được dữ liệu live.</strong><br />{error}
          <br /><button className="secondary-button mock-button" onClick={() => { setResult(getPriorityMock()); setError('') }}>Xem fixture mẫu (mock)</button>
        </div>
      )}
      {!loading && !error && result && result.items.length === 0 && (
        <p className="state-message">Không có hóa đơn phù hợp tại ngày {result.as_of_date}.</p>
      )}
      {!loading && !error && result && result.items.length > 0 && (
        <>
          <div className={`data-badge ${result.data_mode === 'live' ? 'live' : 'mock'}`}>
            {result.data_mode === 'live' ? 'DỮ LIỆU LIVE' : `DỮ LIỆU ${result.data_mode.toUpperCase()}`}
            <span> · Chốt ngày {result.as_of_date}</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>#</th><th>Khách hàng</th><th>Hóa đơn</th><th>Còn nợ</th><th>Quá hạn</th><th>Tỷ lệ trễ</th><th>Trạng thái</th></tr></thead>
              <tbody>{result.items.map((item) => (
                <tr key={item.invoice_id}>
                  <td className="rank-cell">{item.rank}</td>
                  <td><strong>{item.display_name}</strong><small>{item.customer_id}</small></td>
                  <td>{item.invoice_id}<small>Hạn {item.due_date}</small></td>
                  <td>{formatMoney(toNumber(item.remaining_amount), item.currency)}</td>
                  <td>{item.days_overdue} ngày</td>
                  <td>{Math.round(toNumber(item.late_rate) * 100)}%<small>{item.late_rate_source.replaceAll('_', ' ')}</small></td>
                  <td>{item.eligible_for_reminder
                    ? <span className="pill ready">Có thể tạo nháp</span>
                    : <span className="pill held">{item.hold_reasons.map((reason) => holdLabels[reason] ?? reason).join(', ')}</span>}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}

function PlaceholderPage({ page }: { page: Page }) {
  return (
    <section className="panel placeholder">
      <p className="eyebrow">THU TIỀN AI · V1</p>
      <h2>{page}</h2>
      <p className="muted">Khung trang đã sẵn sàng. Phần dữ liệu và thao tác sẽ được nối qua API theo contract chung.</p>
    </section>
  )
}

export default function App() {
  const [page, setPage] = useState<Page>('Ưu tiên thu')
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#home" onClick={(event) => { event.preventDefault(); setPage('Tổng quan') }}>
          <span className="brand-mark">₫</span><span>ThuTiền <b>AI</b></span>
        </a>
        <p className="nav-label">KHÔNG GIAN LÀM VIỆC</p>
        <nav aria-label="Điều hướng chính">
          {pages.map((item, index) => (
            <button key={item} className={`nav-item ${page === item ? 'active' : ''}`} onClick={() => setPage(item)}>
              <span className="nav-icon">{['↪', '⌂', '↗', '▥', '≡'][index]}</span>{item}
              {item === 'Ưu tiên thu' && <span className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer"><span className="avatar">H</span><span><strong>Phiên demo</strong><small>Chưa kết nối đăng nhập</small></span></div>
      </aside>
      <main className="main-area">
        <header className="topbar"><span>Quản lý dòng tiền</span><span className="date-chip">Bản V1 · chỉ đọc Odoo</span></header>
        <div className="content">
          <div className="page-title"><div><p className="eyebrow">THỨ HAI, 09 THÁNG 11, 2026</p><h1>{page}</h1></div><span className="demo-chip">BẢN DEMO</span></div>
          {page === 'Ưu tiên thu' ? <PriorityPage /> : <PlaceholderPage page={page} />}
          <footer className="footnote">ThuTiền AI · Không gửi nhắc tự động · Không ghi dữ liệu ngược vào Odoo</footer>
        </div>
      </main>
    </div>
  )
}
