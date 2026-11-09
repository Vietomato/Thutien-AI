/* Invoices (accountant, chief accountant): open invoices and payment predictions, both from the API.
   Actions: write a reminder draft (draft:create), assign a collection task (task:assign, chief accountant). */
(function () {
  'use strict';

  var h = Shell.h, fmt = Shell.fmt;
  var main = Shell.mount(['accountant', 'chief_accountant']);
  if (!main) return;

  var sub = h('div', { class: 'page-sub', text: 'Đang tải dữ liệu...' });
  var badge = h('span', { class: 'pill pill-success', hidden: true });
  main.appendChild(h('div', { class: 'page-head' }, [
    h('div', {}, [h('h1', { class: 'page-title', text: 'Công nợ' }), sub]),
    badge
  ]));
  var body = h('div', { style: { display: 'flex', flexDirection: 'column', gap: '20px' } },
    [h('div', { class: 'loading', role: 'status', text: 'Đang tải...' })]);
  main.appendChild(body);

  var state = { rows: [], preds: {}, priority: {}, team: [], filter: 'all', q: '', selected: null, asOf: '', notice: null };
  var holdLabels = {
    no_remaining_balance: 'Đã tất toán', not_overdue: 'Chưa quá hạn', disputed: 'Đang tranh chấp',
    missing_contact: 'Thiếu email liên hệ', active_draft_exists: 'Đã có nháp chờ duyệt'
  };

  /* ---------- Row model ---------- */
  function statusOf(r) {
    if (r.inv.dispute_status === 'disputed') return { text: 'Tranh chấp', cls: 'tag-disp' };
    if (r.inv.remaining_amount < r.inv.invoice_amount) return { text: 'Trả một phần', cls: 'tag-part' };
    if (r.late > 0) return { text: 'Quá hạn', cls: 'tag-late' };
    return { text: 'Chưa đến hạn', cls: 'tag-ok' };
  }
  function matchFilter(r) {
    switch (state.filter) {
      case 'overdue': return r.late > 0;
      case 'disputed': return r.inv.dispute_status === 'disputed';
      case 'notdue': return r.late <= 0;
      default: return true;
    }
  }
  function matchQuery(r) {
    if (!state.q) return true;
    return (r.inv.invoice_id + ' ' + r.inv.display_name + ' ' + r.inv.customer_id).toLowerCase().indexOf(state.q) !== -1;
  }
  function counts() {
    var c = { all: state.rows.length, overdue: 0, disputed: 0, notdue: 0 };
    state.rows.forEach(function (r) {
      if (r.late > 0) c.overdue++; else c.notdue++;
      if (r.inv.dispute_status === 'disputed') c.disputed++;
    });
    return c;
  }

  /* ---------- Toolbar ---------- */
  var searchIn = h('input', { id: 'q', class: 'input', type: 'search', placeholder: 'Tìm mã hóa đơn hoặc tên khách', autocomplete: 'off' });
  var filtersBox = h('div', { class: 'filters', role: 'group', 'aria-label': 'Lọc hóa đơn' });
  var FILTERS = [
    { key: 'all', label: 'Tất cả' }, { key: 'overdue', label: 'Quá hạn' },
    { key: 'disputed', label: 'Tranh chấp' }, { key: 'notdue', label: 'Chưa đến hạn' }
  ];
  function renderFilters() {
    var c = counts();
    filtersBox.textContent = '';
    FILTERS.forEach(function (f) {
      filtersBox.appendChild(h('button', {
        type: 'button', class: 'filter', 'aria-pressed': String(state.filter === f.key),
        text: f.label + ' (' + c[f.key] + ')',
        onclick: function () { state.filter = f.key; renderFilters(); renderTable(); }
      }));
    });
  }
  searchIn.addEventListener('input', function () { state.q = searchIn.value.trim().toLowerCase(); renderTable(); });
  var toolbar = h('div', { class: 'toolbar' }, [
    h('div', { class: 'search' }, [h('label', { for: 'q', class: 'sr-only', text: 'Tìm hóa đơn hoặc khách' }), searchIn]),
    filtersBox
  ]);

  /* ---------- Table ---------- */
  var tbody = h('tbody');
  var emptyMsg = h('div', { class: 'empty', text: 'Không có hóa đơn phù hợp.', hidden: true });
  function th(text, cls) { return h('th', { scope: 'col', class: cls || '', text: text }); }
  var tableCard = h('div', { class: 'table-card', style: { flex: '3 1 640px', minWidth: '0' } }, [
    h('div', { class: 'table-scroll' }, [
      h('table', { class: 'table' }, [
        h('caption', { class: 'sr-only', text: 'Danh sách hóa đơn còn nợ' }),
        h('thead', {}, [h('tr', {}, [th('Ưu tiên'), th('Hóa đơn'), th('Khách hàng'), th('Hạn trả'), th('Còn nợ (VND)', 'num'), th('Dự đoán trả'), th('Trạng thái'), th('Đủ điều kiện nhắc')])]),
        tbody
      ])
    ]),
    emptyMsg
  ]);

  function select(id) { state.selected = id; state.notice = null; renderTable(); renderExplain(); }

  function renderTable() {
    tbody.textContent = '';
    var shown = state.rows.filter(function (r) { return matchFilter(r) && matchQuery(r); });
    emptyMsg.hidden = shown.length > 0;
    shown.forEach(function (r) {
      var inv = r.inv, st = statusOf(r), p = state.preds[inv.invoice_id], priority = r.priority;
      var dueNote = r.late > 0 ? 'quá hạn ' + r.late + ' ngày' : (r.late === 0 ? 'đến hạn hôm nay' : 'còn ' + (-r.late) + ' ngày');
      var partial = inv.remaining_amount < inv.invoice_amount;
      var predCell;
      if (inv.dispute_status === 'disputed') {
        predCell = [h('div', { class: 'cell-strong', text: 'Không dự đoán' }), h('div', { class: 'cell-sub', text: 'Đang tranh chấp' })];
      } else if (p) {
        predCell = [
          h('div', { class: 'cell-strong', text: fmt.dmy(p.predicted_date_p50) }),
          h('div', { class: 'cell-sub', text: p.method === 'no_history' ? 'Chưa có lịch sử thanh toán'
            : p.low_history ? 'Ít lịch sử, dùng trung vị chung'
            : fmt.dmy(p.predicted_date_p25, true) + ' đến ' + fmt.dmy(p.predicted_date_p75, true) })
        ];
      } else {
        predCell = [h('div', { class: 'cell-sub', text: 'Chưa có dự đoán' })];
      }
      var sel = state.selected === inv.invoice_id;
      tbody.appendChild(h('tr', { class: sel ? 'selected' : '', onclick: function () { select(inv.invoice_id); } }, [
        h('td', {}, [
          h('div', { class: 'cell-strong', text: '#' + priority.rank }),
          h('div', { class: 'cell-sub', text: fmt.money(Number(priority.priority_score)) + ' điểm' })
        ]),
        h('td', {}, [h('button', {
          type: 'button', class: 'row-btn', text: inv.invoice_id, 'aria-pressed': String(sel),
          'aria-label': 'Xem chi tiết hóa đơn ' + inv.invoice_id,
          onclick: function (e) { e.stopPropagation(); select(inv.invoice_id); }
        })]),
        h('td', {}, [inv.display_name, h('div', { class: 'cell-sub', text: inv.customer_id })]),
        h('td', {}, [fmt.dmy(inv.due_date), h('div', { class: 'cell-sub', text: dueNote })]),
        h('td', { class: 'num', style: { fontWeight: '700' } }, [
          fmt.money(inv.remaining_amount),
          partial ? h('div', { class: 'cell-sub', text: 'trên tổng ' + fmt.money(inv.invoice_amount) }) : null
        ]),
        h('td', {}, predCell),
        h('td', {}, [h('span', { class: 'tag ' + st.cls, text: st.text })]),
        h('td', {}, [priority.eligible_for_reminder
          ? h('span', { class: 'tag tag-ok', text: 'Có thể tạo nháp' })
          : h('span', { class: 'tag tag-part', text: priority.hold_reasons.map(function (reason) { return holdLabels[reason] || reason; }).join(', ') })])
      ]));
    });
  }

  /* ---------- Detail panel ---------- */
  var explain = h('div', { class: 'card explain', style: { flex: '1 1 300px', minWidth: '0', gap: '14px' }, 'aria-live': 'polite' });

  function noticeEl() {
    if (!state.notice) return null;
    var el = h('div', { class: 'alert alert-' + state.notice.kind, role: state.notice.kind === 'danger' ? 'alert' : 'status' });
    el.appendChild(document.createTextNode(state.notice.text + ' '));
    if (state.notice.link) el.appendChild(h('a', { href: state.notice.link, text: 'Mở trang Nhắc nợ' }));
    return el;
  }

  function actions(r) {
    var inv = r.inv, nodes = [];
    var canDraft = Api.can('draft:create') && r.priority.eligible_for_reminder;
    if (canDraft) {
      var btn = h('button', { type: 'button', class: 'btn-ghost', text: 'Soạn bản nháp nhắc nợ' });
      btn.addEventListener('click', function () {
        btn.disabled = true;
        Api.post('/api/reminders/drafts', { invoice_id: inv.invoice_id }).then(function () {
          state.notice = { kind: 'success', text: 'Đã tạo bản nháp, đang chờ kế toán trưởng duyệt.', link: 'reminders.html' };
        }).catch(function (ex) {
          if (ex && ex.status === 401) return;
          state.notice = { kind: 'danger', text: ex.status ? ex.message : 'Không kết nối được máy chủ.' };
        }).then(function () { renderExplain(); });
      });
      nodes.push(btn);
    }
    if (Api.can('task:assign') && state.team.length) {
      var sel = h('select', { id: 'assignee', class: 'select', 'aria-label': 'Giao cho' });
      state.team.forEach(function (m) {
        sel.appendChild(h('option', { value: String(m.id), text: m.full_name + (m.is_self ? ' (tôi)' : '') }));
      });
      var note = h('input', { class: 'input', type: 'text', maxlength: '500', placeholder: 'Ghi chú (không bắt buộc)', 'aria-label': 'Ghi chú nhiệm vụ', style: { height: '36px', fontSize: '13px' } });
      var assignBtn = h('button', { type: 'button', class: 'btn-sm', text: 'Giao việc' });
      assignBtn.addEventListener('click', function () {
        assignBtn.disabled = true;
        Api.post('/api/tasks', { invoice_id: inv.invoice_id, assignee_id: parseInt(sel.value, 10), note: note.value.trim() || null })
          .then(function () { state.notice = { kind: 'success', text: 'Đã giao việc thu nợ ' + inv.invoice_id + '.', link: 'tasks.html' }; })
          .catch(function (ex) {
            if (ex && ex.status === 401) return;
            state.notice = { kind: 'danger', text: ex.status ? ex.message : 'Không kết nối được máy chủ.' };
          }).then(function () { renderExplain(); });
      });
      nodes.push(h('div', { class: 'explain-label', style: { marginTop: '4px' }, text: 'Giao việc thu nợ' }));
      nodes.push(h('div', { class: 'inline-form' }, [sel, assignBtn]));
      nodes.push(note);
    }
    return nodes;
  }

  function renderExplain() {
    explain.textContent = '';
    var r = state.rows.filter(function (x) { return x.inv.invoice_id === state.selected; })[0];
    if (!r) { explain.appendChild(h('p', { text: 'Chọn một hóa đơn để xem vì sao hệ thống dự đoán như vậy.' })); return; }
    var inv = r.inv, p = state.preds[inv.invoice_id];
    explain.appendChild(h('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px' } }, [
      h('div', { class: 'explain-label', text: 'Vì sao dự đoán này' }),
      h('h2', { text: inv.invoice_id + ' · ' + inv.display_name })
    ]));
    explain.appendChild(h('p', { text: 'Ưu tiên F3: ' + fmt.money(Number(r.priority.priority_score)) + ' điểm · tỷ lệ trả trễ ' +
      Math.round(Number(r.priority.late_rate) * 100) + '% (' + r.priority.late_rate_source.replaceAll('_', ' ') + ') · quá hạn ' + r.priority.days_overdue + ' ngày.' }));
    if (!r.priority.eligible_for_reminder) {
      explain.appendChild(h('div', { class: 'note', text: 'Chưa đủ điều kiện nhắc: ' + r.priority.hold_reasons.map(function (reason) { return holdLabels[reason] || reason; }).join(', ') + '.' }));
    }

    if (inv.dispute_status === 'disputed' || !p) {
      explain.appendChild(h('p', { text: 'Hóa đơn đang tranh chấp nên hệ thống không dự đoán ngày trả và không nhắc nợ tự động.' }));
    } else {
      var intro = p.method === 'no_history'
        ? 'Chưa có lịch sử thanh toán nào để tham chiếu. Hệ thống giả định khách trả vào ngày hạn, hoặc hôm nay nếu đã quá hạn.'
        : p.method === 'global_median'
          ? 'Khách này mới trả ' + p.history_count + ' hóa đơn, chưa đủ lịch sử. Hệ thống dùng trung vị số ngày trễ của tất cả khách.'
          : 'Khách này đã trả ' + p.history_count + ' hóa đơn trước đây. Hệ thống lấy phân vị số ngày trễ của chính khách này.';
      explain.appendChild(h('p', { text: intro }));
      var stat = function (k, date, hi) {
        var late = fmt.overdueDays(date, inv.due_date);
        return h('div', { class: 'stat' + (hi ? ' stat-hi' : '') }, [
          h('div', { class: 'stat-k', text: k }),
          h('div', { class: 'stat-v', text: fmt.dmy(date, true) }),
          h('div', { class: 'stat-k', text: (late >= 0 ? '+' : '') + late + ' ngày so với hạn' })
        ]);
      };
      explain.appendChild(h('div', { class: 'stat3' }, [
        stat('P25', p.predicted_date_p25), stat('P50', p.predicted_date_p50, true), stat('P75', p.predicted_date_p75)
      ]));
      if (p.overdue_adjusted) {
        explain.appendChild(h('div', { class: 'note', text: 'Hóa đơn đã quá hạn ' + r.late + ' ngày, lâu hơn mọi lần trả trước đây của khách. Ngày dự đoán được tính từ ngày tính toán (điều chỉnh vì quá hạn).' }));
      }
      explain.appendChild(h('div', { class: 'tags' }, [
        h('span', { class: 'tag tag-teal', text: p.method === 'customer_median' ? 'Phương pháp: theo lịch sử của khách' : p.method === 'global_median' ? 'Phương pháp: trung vị chung' : 'Phương pháp: chưa có lịch sử' }),
        h('span', { class: 'tag tag-ok', text: 'Số liệu do hệ thống tính' })
      ]));
    }
    var n = noticeEl();
    if (n) explain.appendChild(n);
    actions(r).forEach(function (a) { explain.appendChild(a); });
  }

  /* ---------- Load ---------- */
  var team = Api.can('task:assign') ? Api.get('/api/team').then(function (t) { return t.items; }) : Promise.resolve([]);
  Promise.all([Api.get('/api/invoices/open'), Api.get('/api/predictions'), Api.get('/api/f3/priority'), team]).then(function (r) {
    var env = r[0];
    state.asOf = env.as_of_date;
    r[2].items.forEach(function (item) { state.priority[item.invoice_id] = item; });
    state.rows = env.items.map(function (i) {
      return { inv: i, late: fmt.overdueDays(env.as_of_date, i.due_date), priority: state.priority[i.invoice_id] };
    }).sort(function (a, b) { return a.priority.rank - b.priority.rank; });
    r[1].items.forEach(function (p) { state.preds[p.invoice_id] = p; });
    state.team = r[3];

    var eligibleCount = state.rows.filter(function (row) { return row.priority.eligible_for_reminder; }).length;
    sub.textContent = env.items.length + ' hóa đơn còn nợ · ' + eligibleCount + ' đủ điều kiện nhắc · Ngày tính toán ' + fmt.dmy(env.as_of_date) +
      ' · Dự đoán do hệ thống tính từ lịch sử thanh toán của từng khách';
    badge.hidden = false;
    badge.textContent = '';
    badge.appendChild(h('span', { class: 'pill-dot' }));
    badge.appendChild(document.createTextNode('Nguồn: Odoo (chỉ đọc)'));

    state.selected = state.rows.length ? state.rows[0].inv.invoice_id : null;
    renderFilters(); renderTable(); renderExplain();
    body.textContent = '';
    body.appendChild(toolbar);
    body.appendChild(h('div', { class: 'cols' }, [tableCard, explain]));
  }).catch(function (ex) {
    if (ex && ex.status === 401) return;
    sub.textContent = '';
    body.textContent = '';
    body.appendChild(Shell.apiErrorAlert(ex));
  });
})();
