/* Dashboard (accountant, chief accountant). All numbers come from the API:
   /api/summary, /api/invoices/open and /api/forecast (computed on real Odoo data). */
(function () {
  'use strict';

  var h = Shell.h, fmt = Shell.fmt;
  var main = Shell.mount(['accountant', 'chief_accountant']);
  if (!main) return;

  var sub = h('div', { class: 'page-sub', text: 'Đang tải dữ liệu...' });
  var badge = h('span', { class: 'pill pill-success', hidden: true });
  main.appendChild(h('div', { class: 'page-head' }, [
    h('div', {}, [h('h1', { class: 'page-title', text: 'Tổng quan' }), sub]),
    badge
  ]));
  var body = h('div', { style: { display: 'flex', flexDirection: 'column', gap: '24px' } },
    [h('div', { class: 'loading', role: 'status', text: 'Đang tải...' })]);
  main.appendChild(body);

  var M = 1e6; // charts are in million VND

  function kpi(label, value, cls, note) {
    return h('div', { class: 'kpi' }, [
      h('div', { class: 'kpi-label', text: label }),
      h('div', { class: 'kpi-value ' + cls, text: value }),
      h('div', { class: 'kpi-note', text: note })
    ]);
  }

  function buildKpis(s, risky) {
    var overNote = s.overdue_count === 0 ? 'Không có hóa đơn quá hạn'
      : s.overdue_count + ' hóa đơn, quá hạn ' +
        (s.min_overdue_days === s.max_overdue_days ? s.min_overdue_days : s.min_overdue_days + ' đến ' + s.max_overdue_days) + ' ngày';
    return h('div', { class: 'kpis' }, [
      kpi('Tổng nợ còn lại', fmt.millions(s.total_remaining), '', s.open_count + ' hóa đơn đang mở'),
      kpi('Đã quá hạn', fmt.millions(s.overdue_amount), 'c-danger', overNote),
      kpi('Đang tranh chấp', fmt.millions(s.disputed_amount), 'c-warning', s.disputed_count + ' hóa đơn, không nhắc tự động'),
      kpi('Tuần có nguy cơ thiếu', risky.length + ' / ' + 12, risky.length ? 'c-danger' : '', 'Theo kịch bản thu muộn (P75)')
    ]);
  }

  function buildChart(weeks, risky) {
    var maxV = 1;
    weeks.forEach(function (w) {
      maxV = Math.max(maxV, w.receipt_p25 / M, w.receipt_p50 / M, w.receipt_p75 / M, w.obligations / M);
    });
    var plotH = 230, k = (plotH - 20) / maxV;
    var noObligations = weeks.every(function (w) { return w.obligations === 0; });

    var cols = weeks.map(function (w) {
      var p50 = w.receipt_p50 / M, obl = w.obligations / M, gap = w.gap_p75 / M;
      var lo = Math.min(w.receipt_p25, w.receipt_p50, w.receipt_p75) / M;
      var hi = Math.max(w.receipt_p25, w.receipt_p50, w.receipt_p75) / M;
      var label = 'Tuần bắt đầu ' + fmt.dmy(w.week_start, true) + ': thu dự kiến ' + Math.round(p50) +
        ' triệu (khoảng ' + Math.round(lo) + ' đến ' + Math.round(hi) + '), phải chi ' + Math.round(obl) + ' triệu' +
        (gap > 0 ? ', có nguy cơ thiếu ' + Math.round(gap) + ' triệu' : '');
      return h('div', { class: 'wk', role: 'img', 'aria-label': label, title: label }, [
        h('div', { class: 'wk-plot' }, [
          h('div', { class: 'wk-band', style: { bottom: (lo * k).toFixed(1) + 'px', height: ((hi - lo) * k).toFixed(1) + 'px' } }),
          h('div', { class: 'wk-bar', style: { height: (p50 * k).toFixed(1) + 'px' } }),
          obl > 0 ? h('div', { class: 'wk-obl', style: { bottom: (obl * k).toFixed(1) + 'px' } }) : null
        ]),
        h('div', { class: 'wk-date', text: fmt.dmy(w.week_start, true) }),
        h('div', { class: 'wk-gap', 'aria-hidden': 'true', text: gap > 0 ? '-' + Math.round(gap) : '' })
      ]);
    });

    var warn;
    if (risky.length) {
      warn = h('div', { class: 'risk' }, [
        h('div', { class: 'risk-dot' }),
        h('div', {}, [
          h('b', { text: risky.length + ' tuần có nguy cơ thiếu tiền' }),
          ' (tuần bắt đầu ' + risky.map(function (w) { return fmt.dmy(w.week_start, true); }).join(', ') +
          '): ngay cả khi khách trả muộn nhất, số thu vẫn thấp hơn số phải chi.'
        ])
      ]);
    } else {
      warn = h('div', { class: 'risk risk-ok' }, [
        h('div', { class: 'risk-dot' }),
        h('div', { text: 'Không có tuần nào có nguy cơ thiếu tiền trong 12 tuần tới.' })
      ]);
    }

    var notes = [
      h('div', { class: 'note', text: 'Ngày thu dự đoán tính từ lịch sử thanh toán của từng khách trên Odoo. Hóa đơn tranh chấp không được tính.' })
    ];
    if (noObligations) {
      notes.push(h('div', { class: 'note', text: 'Chưa có hóa đơn nhà cung cấp nào chưa thanh toán trên Odoo, nên số phải chi đang bằng 0 và không có tuần nào báo thiếu.' }));
    }

    return h('div', { class: 'card', style: { flex: '2 1 560px', minWidth: '0' } }, [
      h('div', { class: 'chart-head' }, [
        h('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px' } }, [
          h('h2', { text: 'Dòng tiền 12 tuần tới' }),
          h('div', { class: 'note', text: 'Đơn vị: triệu đồng. Dải màu nhạt là khoảng thu sớm nhất đến muộn nhất (P25 đến P75).' })
        ]),
        h('div', { class: 'legend' }, [
          h('span', {}, [h('span', { class: 'sw sw-p50' }), 'Thu dự kiến (P50)']),
          h('span', {}, [h('span', { class: 'sw sw-band' }), 'Khoảng P25 đến P75']),
          h('span', {}, [h('span', { class: 'sw sw-obl' }), 'Phải chi'])
        ])
      ]),
      h('div', { class: 'chart-scroll' }, [h('div', { class: 'chart' }, cols)]),
      warn
    ].concat(notes));
  }

  function buildPriority(env) {
    var asOf = env.as_of_date;
    var list = env.items
      .map(function (i) { return { inv: i, late: fmt.overdueDays(asOf, i.due_date) }; })
      .filter(function (x) { return x.late > 0; })
      .sort(function (a, b) { return (b.inv.remaining_amount - a.inv.remaining_amount) || (b.late - a.late); })
      .slice(0, 3);
    var maxAmt = list.length ? list[0].inv.remaining_amount : 1;

    var rows = list.map(function (x) {
      var disputed = x.inv.dispute_status === 'disputed';
      return h('div', { class: 'prio' }, [
        h('div', { class: 'prio-top' }, [
          h('div', { class: 'prio-who', text: x.inv.display_name }),
          h('div', { class: 'prio-amt', text: fmt.money(x.inv.remaining_amount) })
        ]),
        h('div', { class: 'prio-meta' }, [
          h('span', { text: x.inv.invoice_id + ' · quá hạn ' + x.late + ' ngày' }),
          h('span', { class: 'prio-tag ' + (disputed ? 'c-warning' : 'c-teal'), text: disputed ? 'Tranh chấp' : 'Cần nhắc' })
        ]),
        h('div', { class: 'bar-track' }, [
          h('div', { class: 'bar-fill', style: { width: Math.max(4, Math.round(x.inv.remaining_amount / maxAmt * 100)) + '%' } })
        ])
      ]);
    });
    if (!rows.length) rows.push(h('div', { class: 'loading', text: 'Không có hóa đơn quá hạn cần thu.' }));

    return h('div', { class: 'card', style: { flex: '1 1 320px', minWidth: '0', gap: '14px' } }, [
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px' } }, [
        h('h2', { text: 'Ưu tiên thu hôm nay' }),
        h('div', { class: 'note', text: 'Xếp theo số tiền còn nợ và số ngày quá hạn.' })
      ])
    ].concat(rows, [
      h('div', { class: 'note', text: 'Hóa đơn đang tranh chấp không bị nhắc tự động.' })
    ]));
  }

  Promise.all([Api.get('/api/summary'), Api.get('/api/invoices/open'), Api.get('/api/forecast')]).then(function (r) {
    var summary = r[0], env = r[1], fc = r[2];
    sub.textContent = 'Ngày tính toán ' + fmt.dmy(env.as_of_date) + ' · Nguồn dữ liệu: Odoo (chỉ đọc)';
    badge.hidden = false;
    badge.textContent = '';
    badge.appendChild(h('span', { class: 'pill-dot' }));
    badge.appendChild(document.createTextNode('Đọc trực tiếp từ Odoo'));

    var risky = fc.weeks.filter(function (w) { return w.gap_p75 > 0; });
    body.textContent = '';
    body.appendChild(buildKpis(summary, risky));
    body.appendChild(h('div', { class: 'cols' }, [buildChart(fc.weeks, risky), buildPriority(env)]));
  }).catch(function (ex) {
    if (ex && ex.status === 401) return; // api.js is redirecting to login
    sub.textContent = '';
    body.textContent = '';
    body.appendChild(Shell.apiErrorAlert(ex));
  });
})();
