import { useEffect, useRef, useState } from "react";
import { FlightPath } from "@/FlightPath";
import { addDays, type WeekRow } from "@/forecast/forecastMath";
import { Icon } from "@/icons";
import { Logo } from "@/Logo";
import "./landing.css";

// Sample figures for the public page (simulated company). They are drawn here, not read from any customer's data.
const M = 1_000_000;
const SAMPLE_ROWS: [number, number][] = [[895, 1545], [727, 2571], [996, 1083], [680, 570], [1929, 977], [554, 1124], [593, 1624], [233, 54], [114, 63], [0, 0], [0, 61], [0, 667]];
const SAMPLE_WEEKS: WeekRow[] = SAMPLE_ROWS.map(([late, out], i) => ({
  week_start: addDays("2026-11-09", i * 7), receipt_p25: late * M, receipt_p50: late * M, receipt_p75: late * M, obligations: out * M, gap_p75: Math.max(out - late, 0) * M,
}));

const go = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

/** Fades blocks in as they scroll into view (skipped when the visitor prefers reduced motion). */
function useReveal() {
  useEffect(() => {
    const els = Array.from(document.querySelectorAll<HTMLElement>(".lp .rv"));
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !("IntersectionObserver" in window)) { els.forEach(e => e.classList.add("is-in")); return; }
    const io = new IntersectionObserver(entries => entries.forEach(en => { if (en.isIntersecting) { en.target.classList.add("is-in"); io.unobserve(en.target); } }), { threshold: 0.12 });
    els.forEach(e => io.observe(e));
    return () => io.disconnect();
  }, []);
}

/** Counts up to `to` the first time it is visible. */
function CountUp({ to, suffix = "" }: { to: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [value, setValue] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || to === 0 || !("IntersectionObserver" in window)) { setValue(to); return; }
    let raf = 0;
    const io = new IntersectionObserver(([en]) => {
      if (!en.isIntersecting) return;
      io.disconnect();
      const start = performance.now();
      const tick = (now: number) => {
        const p = Math.min((now - start) / 1100, 1);
        setValue(Math.round(to * (1 - Math.pow(1 - p, 3))));
        if (p < 1) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    }, { threshold: 0.4 });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [to]);
  return <span ref={ref}>{value}{suffix}</span>;
}

const RIBBON = ["Chỉ đọc Odoo", "12 tuần dự báo", "3 kịch bản", "Kế toán trưởng duyệt", "Nhật ký đầy đủ", "Số do code tính"];

export function Landing({ onLogin, onTrial }: { onLogin: () => void; onTrial: () => void }) {
  useReveal();
  return <div className="lp lp-js">
    <header className="lp-nav"><div className="lp-wrap lp-nav-in">
      <a className="lp-brand" href="/app/" onClick={e => { e.preventDefault(); window.scrollTo({ top: 0, behavior: "smooth" }); }}><Logo size={38} /></a>
      <nav className="lp-links" aria-label="Trang chủ">
        <button onClick={() => go("tinh-nang")}>Tính năng</button>
        <button onClick={() => go("an-toan")}>An toàn</button>
        <button onClick={() => go("hoi-dap")}>Hỏi đáp</button>
      </nav>
      <button className="lp-btn lp-btn-ink" onClick={onLogin}>Đăng nhập</button>
    </div></header>

    <section className="lp-hero">
      <div className="lp-wrap lp-hero-grid">
        <div className="lp-hero-text">
          <span className="lp-chip"><i />Trợ lý công nợ và dòng tiền cho doanh nghiệp dùng Odoo</span>
          <h1>Biết khoản nào <mark>cần thu trước</mark>, <em>tuần nào sắp thiếu tiền.</em></h1>
          <p className="lp-lead">CashPilot đọc hóa đơn trong Odoo, dự đoán khách sẽ trả vào lúc nào và đối chiếu với tiền phải chi trong 12 tuần tới. Mọi nội dung nhắc nợ đều do kế toán trưởng duyệt trước khi dùng.</p>
          <div className="lp-cta"><button className="lp-btn lp-btn-lime" onClick={onTrial}>Đăng nhập</button><button className="lp-btn lp-btn-line" onClick={() => go("tinh-nang")}>Xem tính năng</button></div>
        </div>
        <div className="lp-art" aria-label="Minh họa kế hoạch bay 12 tuần trên dữ liệu giả lập">
          <div className="lp-blob" />
          <div className="lp-deck">
            <div className="lp-deck-bar"><i /><b>KẾ HOẠCH BAY · 12 TUẦN</b><em>Dữ liệu giả lập</em></div>
            <FlightPath weeks={SAMPLE_WEEKS} />
          </div>
          <div className="lp-float lp-float-a" aria-hidden="true"><span className="lp-float-ic bad"><Icon name="alert" size={18} /></span><div><strong>Thiếu 1,84 tỷ</strong><small>Tuần 16/11 – 22/11, nếu khách trả muộn</small></div></div>
          <div className="lp-float lp-float-b" aria-hidden="true"><span className="lp-float-ic ok"><Icon name="check" size={18} /></span><div><strong>Nháp đã được duyệt</strong><small>Kế toán trưởng · vừa xong</small></div></div>
        </div>
      </div>
    </section>

    <div className="lp-ribbon" aria-hidden="true"><div className="lp-ribbon-track">
      {[0, 1].map(k => <div className="lp-ribbon-group" key={k}>{RIBBON.map(r => <span key={r + k}>{r}<i /></span>)}</div>)}
    </div></div>

    <section className="lp-section lp-figs-section">
      <div className="lp-wrap lp-figs">
        <div className="lp-fig lp-fig-mint rv"><strong><CountUp to={12} /></strong><span>tuần dự báo dòng tiền</span></div>
        <div className="lp-fig lp-fig-butter rv"><strong><CountUp to={3} /></strong><span>kịch bản: sớm, thường lệ, muộn</span></div>
        <div className="lp-fig lp-fig-peach rv"><strong><CountUp to={100} suffix="%" /></strong><span>nháp nhắc nợ qua kế toán trưởng duyệt</span></div>
        <div className="lp-fig lp-fig-ink rv"><strong>0</strong><span>dữ liệu ghi ngược vào Odoo</span></div>
      </div>
    </section>

    <section className="lp-section" id="tinh-nang">
      <div className="lp-wrap">
        <div className="lp-head rv"><h2>Mọi thứ cho công nợ và dòng tiền, <em>trong một nơi.</em></h2></div>
        <div className="lp-bento">
          <article className="lp-tile lp-tile-forest lp-tile-wide rv">
            <div className="lp-tile-copy">
              <h3>Dự báo dòng tiền 12 tuần</h3>
              <p>Tiền thu dự kiến được cộng theo từng tuần ở ba kịch bản, rồi so với tiền phải chi để báo tuần nào còn thiếu bao nhiêu. Chi lấy từ hóa đơn nhà cung cấp trong Odoo và khoản kế toán nhập tay.</p>
              <ul><li>Cảnh báo dựa trên kịch bản khách trả muộn</li><li>Thử sức chịu đựng, không phải cam kết</li></ul>
            </div>
            <div className="lp-tile-plan"><div className="lp-deck lp-deck-flat"><div className="lp-deck-bar"><i /><b>KẾ HOẠCH BAY · 12 TUẦN</b><em>Dữ liệu giả lập</em></div><FlightPath weeks={SAMPLE_WEEKS} /></div></div>
          </article>

          <article className="lp-tile lp-tile-mint rv">
            <div className="lp-mini">
              {[["01", "Cửa hàng VLXD Thành Đạt", "183.450.000"], ["02", "Công ty TNHH Xây dựng Bình Minh", "219.997.000"], ["03", "Công ty TNHH Xây dựng Tiến Đạt", "96.037.500"]].map(r => <div className="lp-mini-row" key={r[0]}><span>{r[0]}</span><b>{r[1]}</b><i>{r[2]}</i></div>)}
            </div>
            <h3>Xếp hạng khoản cần thu</h3>
            <p>Điểm ưu tiên từ số dư, mức hay trả trễ của khách và số ngày quá hạn.</p>
          </article>

          <article className="lp-tile lp-tile-butter rv">
            <div className="lp-mini lp-mini-mail">
              <div className="lp-mini-line"><i /><i style={{ width: "78%" }} /><i style={{ width: "52%" }} /></div>
              <div className="lp-mini-checks"><span><Icon name="check" size={12} />Số tiền</span><span><Icon name="check" size={12} />Hạn trả</span><span><Icon name="check" size={12} />Khách hàng</span></div>
              <div className="lp-mini-btns"><span className="p">Duyệt</span><span>Từ chối</span></div>
            </div>
            <h3>Nhắc nợ có kiểm soát</h3>
            <p>AI hỗ trợ soạn nháp. Người tạo nháp không tự duyệt được nháp của mình.</p>
          </article>

          <article className="lp-tile lp-tile-peach rv">
            <div className="lp-mini">
              {[["chief1", "Duyệt nháp INV/…00573"], ["accountant1", "Tạo nháp INV/…00607"], ["chief1", "Từ chối nháp INV/…00658"]].map((r, i) => <div className="lp-mini-row lp-mini-log" key={i}><span><Icon name="audit" size={14} /></span><b>{r[0]}</b><i>{r[1]}</i></div>)}
            </div>
            <h3>Nhật ký và phân quyền</h3>
            <p>Mỗi thao tác ghi người và thời điểm. Mỗi vai trò chỉ thấy phần việc của mình.</p>
          </article>
        </div>
        <p className="lp-note">Hình và số liệu trên trang này là minh họa, vẽ từ dữ liệu giả lập.</p>
      </div>
    </section>

    <section className="lp-section lp-check" id="an-toan">
      <div className="lp-wrap lp-check-grid">
        <div className="lp-check-head rv">
          <span className="lp-mono-tag">NGUYÊN TẮC VẬN HÀNH</span>
          <h2>Máy tính toán, <em>người quyết định.</em></h2>
          <p>AI đọc và đề xuất, chương trình tính toán, kế toán kiểm soát. Năm nguyên tắc luôn được giữ trước khi một con số hay một bản nháp được dùng.</p>
        </div>
        <ul className="lp-checklist rv">
          {[["Chỉ đọc Odoo", "Kết nối bằng quyền chỉ đọc, không có đường ghi ngược."], ["Số do code tính", "Ngày trả, điểm ưu tiên, tiền theo tuần và cảnh báo do chương trình tính, AI không tự tính số."], ["Kế toán trưởng duyệt", "Nháp nhắc nợ chỉ được dùng sau khi duyệt. Người tạo nháp không tự duyệt được."], ["Phân quyền theo vai trò", "Kế toán, kế toán trưởng, khách hàng và quản trị viên chỉ thấy phần việc của mình."], ["Nhật ký thao tác", "Tạo nháp, duyệt, từ chối, giao việc đều được ghi lại theo người và thời điểm."]].map(([title, text]) => <li key={title}>
            <span className="lp-box"><Icon name="check" size={18} /></span><div><strong>{title}</strong><small>{text}</small></div><em>LUÔN BẬT</em>
          </li>)}
        </ul>
      </div>
    </section>

    <section className="lp-section lp-faq-section" id="hoi-dap">
      <div className="lp-wrap lp-faq-wrap">
        <div className="lp-faq-head rv"><h2>Những điều nên biết <em>trước khi dùng thử.</em></h2></div>
        <div className="lp-faq rv">
          <details><summary>Dữ liệu trong bản demo có phải dữ liệu thật không?</summary><p>Không. Công ty “Minh Phát”, khách hàng và hóa đơn là dữ liệu giả lập do nhóm tạo. Bộ dữ liệu công khai Kaggle chỉ dùng để kiểm thử thuật toán dự đoán, và đó là dữ liệu Bắc Mỹ.</p></details>
          <details><summary>Hệ thống có ghi dữ liệu vào Odoo không?</summary><p>Không. Hệ thống chỉ đọc từ Odoo. Nháp nhắc nợ, nhiệm vụ, khoản chi nhập tay và nhật ký được lưu trong cơ sở dữ liệu riêng của ứng dụng.</p></details>
          <details><summary>Ba kịch bản thu tiền có phải là khoảng tin cậy không?</summary><p>Không. Ba kịch bản (sớm, theo thói quen, muộn) là phép thử sức chịu đựng dòng tiền dựa trên thói quen trả tiền trước đây của từng khách. Đó không phải cam kết và không phải số dư tiền mặt.</p></details>
          <details><summary>AI làm gì trong hệ thống?</summary><p>AI hỗ trợ soạn bản nháp nhắc nợ và diễn giải. Con số trong bản nháp được kiểm tra lại với dữ liệu Odoo trước khi kế toán trưởng duyệt.</p></details>
        </div>
      </div>
    </section>

    <footer className="lp-footer">
      <div className="lp-wrap lp-foot-in">
        <p className="lp-foot-line">Hệ thống chỉ đọc dữ liệu Odoo, không ghi ngược.</p>
        <button className="lp-btn lp-btn-lime" onClick={onLogin}>Đăng nhập</button>
      </div>
      <div className="lp-wrap"><div className="lp-giant" aria-hidden="true">CashPilot</div></div>
    </footer>
  </div>;
}
