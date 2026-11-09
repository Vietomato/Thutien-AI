/* Customer view: only this customer's own invoices and payments. The server filters by the account's
   Odoo customer link, so nothing about other customers is ever sent to the browser. */
(function () {
  'use strict';

  var h = Shell.h, fmt = Shell.fmt;
  var main = Shell.mount(['customer']);
  if (!main) return;

  var sub = h('div', { class: 'page-sub', text: 'Đang tải dữ liệu...' });
  main.appendChild(h('div', { class: 'page-head' }, [
    h('div', {}, [h('h1', { class: 'page-title', text: 'Công nợ của tôi' }), sub])
  ]));
  var body = h('div', { style: { display: 'flex', flexDirection: 'column', gap: '24px' } },
    [h('div', { class: 'loading', role: 'status', text: 'Đang tải...' })]);
  main.appendChild(body);

  function kpi(label, value, cls, note) {
    return h('div', { class: 'kpi' }, [
      h('div', { class: 'kpi-label', text: label }),
      h('div', { class: 'kpi-value ' + cls, text: value }),
      h('div', { class: 'kpi-note', text: note })
    ]);
  }
  function th(text, cls) { return h('th', { scope: 'col', class: cls || '', text: text }); }
  function tableCard(title, caption, heads, rows, emptyText) {
    return h('div', { class: 'table-card' }, [
      h('div', { class: 'panel-head' }, [h('h2', { text: title })]),
      rows.length
        ? h('div', { class: 'table-scroll' }, [h('table', { class: 'table', style: { minWidth: '480px' } }, [
            h('caption', { class: 'sr-only', text: caption }),
            h('thead', {}, [h('tr', {}, heads)]),
            h('tbody', {}, rows)
          ])])
        : h('div', { class: 'empty', text: emptyText })
    ]);
  }

  Promise.all([Api.get('/api/summary'), Api.get('/api/invoices/open'), Api.get('/api/payments/history')]).then(function (r) {
    var s = r[0], env = r[1], pays = r[2].items;
    sub.textContent = 'Ngày tính toán ' + fmt.dmy(s.as_of_date) + ' · Chỉ hiển thị hóa đơn và khoản thanh toán của bạn';
    body.textContent = '';

    var profile = Api.getFullName() || '';
    var linked = env.items.length > 0 || pays.length > 0;
    if (!linked) {
      body.appendChild(h('div', { class: 'alert alert-warning', role: 'status' }, [
        h('div', { class: 'alert-title', text: 'Chưa có dữ liệu công nợ cho tài khoản ' + profile }),
        h('div', { text: 'Tài khoản chưa được liên kết với hồ sơ khách hàng, hoặc bạn không còn khoản nợ nào. Liên hệ quản trị viên nếu bạn cần liên kết tài khoản.' })
      ]));
    }

    body.appendChild(h('div', { class: 'kpis kpis-3' }, [
      kpi('Tổng nợ còn lại', fmt.money(s.total_remaining) + ' VND', '', s.open_count + ' hóa đơn đang mở'),
      kpi('Đã quá hạn', fmt.money(s.overdue_amount) + ' VND', s.overdue_amount ? 'c-danger' : '',
        s.overdue_count ? s.overdue_count + ' hóa đơn, quá hạn ' + (s.min_overdue_days === s.max_overdue_days ? s.min_overdue_days : s.min_overdue_days + ' đến ' + s.max_overdue_days) + ' ngày' : 'Không có hóa đơn quá hạn'),
      kpi('Đang tranh chấp', fmt.money(s.disputed_amount) + ' VND', s.disputed_amount ? 'c-warning' : '', s.disputed_count + ' hóa đơn')
    ]));

    var invRows = env.items.map(function (i) {
      var late = fmt.overdueDays(env.as_of_date, i.due_date);
      var disputed = i.dispute_status === 'disputed';
      var tag = disputed ? ['Tranh chấp', 'tag-disp'] : late > 0 ? ['Quá hạn', 'tag-late'] : ['Chưa đến hạn', 'tag-ok'];
      return h('tr', { style: { cursor: 'default' } }, [
        h('td', { class: 'cell-strong', text: i.invoice_id }),
        h('td', {}, [fmt.dmy(i.due_date), h('div', { class: 'cell-sub', text: late > 0 ? 'quá hạn ' + late + ' ngày' : late === 0 ? 'đến hạn hôm nay' : 'còn ' + (-late) + ' ngày' })]),
        h('td', { class: 'num', style: { fontWeight: '700' } }, [
          fmt.money(i.remaining_amount),
          i.remaining_amount < i.invoice_amount ? h('div', { class: 'cell-sub', text: 'trên tổng ' + fmt.money(i.invoice_amount) }) : null
        ]),
        h('td', {}, [h('span', { class: 'tag ' + tag[1], text: tag[0] })])
      ]);
    });
    body.appendChild(tableCard('Hóa đơn còn nợ', 'Hóa đơn còn nợ của bạn',
      [th('Hóa đơn'), th('Hạn trả'), th('Còn nợ (VND)', 'num'), th('Trạng thái')], invRows, 'Bạn không có hóa đơn nào còn nợ.'));

    var payRows = pays.slice().reverse().map(function (p) {
      return h('tr', { style: { cursor: 'default' } }, [
        h('td', { text: fmt.dmy(p.payment_date) }),
        h('td', { class: 'cell-strong', text: p.invoice_id }),
        h('td', { class: 'num', style: { fontWeight: '700' }, text: fmt.money(p.amount) })
      ]);
    });
    body.appendChild(tableCard('Lịch sử thanh toán', 'Các khoản bạn đã thanh toán',
      [th('Ngày thanh toán'), th('Hóa đơn'), th('Số tiền (VND)', 'num')], payRows, 'Chưa có khoản thanh toán nào.'));
    body.appendChild(h('div', { class: 'note', text: 'Số liệu đọc trực tiếp từ hệ thống kế toán (Odoo), chỉ để xem.' }));
  }).catch(function (ex) {
    if (ex && ex.status === 401) return;
    sub.textContent = '';
    body.textContent = '';
    body.appendChild(Shell.apiErrorAlert(ex));
  });
})();
