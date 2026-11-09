/* Reminder drafts. Accountants write drafts; the chief accountant approves or rejects them.
   Everything comes from /api/reminders/*. Approving only records the decision: no email is sent. */
(function () {
  'use strict';

  var h = Shell.h, fmt = Shell.fmt;
  var main = Shell.mount(['accountant', 'chief_accountant']);
  if (!main) return;

  main.appendChild(h('div', { style: { display: 'flex', flexDirection: 'column', gap: '4px' } }, [
    h('h1', { class: 'page-title', text: 'Bản nháp nhắc nợ' }),
    h('div', { class: 'page-sub', style: { marginTop: '0' }, text: 'Hệ thống điền số liệu từ Odoo, kế toán soạn và kế toán trưởng quyết định. Không có thư nào tự gửi đi.' })
  ]));
  var body = h('div', { style: { display: 'flex', flexDirection: 'column', gap: '20px' } },
    [h('div', { class: 'loading', role: 'status', text: 'Đang tải...' })]);
  main.appendChild(body);

  var STATUS_TEXT = { pending: 'Chờ duyệt', approved: 'Đã duyệt', rejected: 'Đã từ chối' };
  var state = { drafts: [], candidates: [], disputed: [], selected: null, editing: false, busy: false, error: '', notice: '' };

  var queueBox = h('div', { class: 'queue' });
  var detail = h('div', { class: 'card', style: { flex: '3 1 560px', minWidth: '0', padding: '24px', gap: '18px' } });

  function current() {
    return state.drafts.filter(function (d) { return d.id === state.selected; })[0] || null;
  }
  function fail(ex) {
    if (ex && ex.status === 401) return;
    state.error = ex && ex.status ? ex.message : 'Không kết nối được máy chủ.';
  }
  function reload(keepSelection) {
    return Promise.all([Api.get('/api/reminders/drafts'), Api.get('/api/reminders/candidates')]).then(function (r) {
      state.drafts = r[0].items;
      state.candidates = r[1].items;
      state.disputed = r[1].disputed;
      if (!keepSelection || !current()) state.selected = state.drafts.length ? state.drafts[0].id : null;
    });
  }
  function act(fn) {
    if (state.busy) return;
    state.busy = true; state.error = ''; state.notice = '';
    render();
    fn().catch(fail).then(function () { state.busy = false; render(); });
  }

  /* ---------- Queue ---------- */
  function renderQueue() {
    queueBox.textContent = '';
    var pending = state.drafts.filter(function (d) { return d.status === 'pending'; }).length;
    queueBox.appendChild(h('div', { class: 'eyebrow', text: 'Bản nháp (' + pending + ' chờ duyệt)' }));
    state.drafts.forEach(function (d) {
      queueBox.appendChild(h('button', {
        type: 'button', class: 'queue-item', 'aria-pressed': String(d.id === state.selected),
        onclick: function () { state.selected = d.id; state.editing = false; state.error = ''; state.notice = ''; render(); }
      }, [
        h('div', { class: 'queue-row' }, [
          h('span', { class: 'queue-id', text: d.invoice_id }),
          h('span', { class: 'queue-st st-' + d.status, text: STATUS_TEXT[d.status] })
        ]),
        h('div', { class: 'queue-who', text: d.customer_name + ' · ' + fmt.money(d.amount) }),
        h('div', { class: 'queue-late', text: 'Quá hạn ' + d.overdue_days + ' ngày · soạn bởi ' + d.created_by_username })
      ]));
    });
    if (!state.drafts.length) queueBox.appendChild(h('div', { class: 'loading', text: 'Chưa có bản nháp nào.' }));

    if (Api.can('draft:create')) {
      queueBox.appendChild(h('div', { class: 'eyebrow', style: { marginTop: '8px' }, text: 'Hóa đơn quá hạn chưa có bản nháp' }));
      state.candidates.forEach(function (c) {
        var btn = h('button', { type: 'button', class: 'btn-sm', disabled: state.busy, text: 'Soạn nháp',
          'aria-label': 'Soạn bản nháp cho ' + c.invoice_id });
        btn.addEventListener('click', function () {
          act(function () {
            return Api.post('/api/reminders/drafts', { invoice_id: c.invoice_id }).then(function (d) {
              return reload(false).then(function () { state.selected = d.id; state.notice = 'Đã tạo bản nháp cho ' + c.invoice_id + '.'; });
            });
          });
        });
        queueBox.appendChild(h('div', { class: 'queue-item', style: { cursor: 'default' } }, [
          h('div', { class: 'queue-row' }, [h('span', { class: 'queue-id', text: c.invoice_id }), btn]),
          h('div', { class: 'queue-who', text: c.display_name + ' · ' + fmt.money(c.remaining_amount) }),
          h('div', { class: 'queue-late', text: 'Quá hạn ' + c.overdue_days + ' ngày' })
        ]));
      });
      if (!state.candidates.length) queueBox.appendChild(h('div', { class: 'loading', text: 'Không còn hóa đơn nào cần soạn.' }));
    }
    state.disputed.forEach(function (id) {
      queueBox.appendChild(h('div', { class: 'alert alert-warning', text: id + ' đang tranh chấp nên không có bản nháp nhắc nợ.' }));
    });
  }

  /* ---------- Detail ---------- */
  function when(iso) {
    return iso ? fmt.dmy(iso.slice(0, 10), true) + ' ' + iso.slice(11, 16) : '';
  }

  function renderDetail() {
    detail.textContent = '';
    var d = current();
    if (!d) { detail.appendChild(h('p', { class: 'note', text: 'Chọn một bản nháp trong danh sách.' })); return; }

    detail.appendChild(h('div', { style: { display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: '8px', alignItems: 'center' } }, [
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px' } }, [
        h('h2', { style: { fontSize: '18px' }, text: 'Gửi tới ' + d.customer_name }),
        h('div', { class: 'note', text: (d.contact_email || 'Chưa có email') + ' · ' + d.invoice_id })
      ]),
      h('span', { class: 'tag tag-ai', text: 'Soạn bởi ' + d.created_by_username })
    ]));

    var mail = h('div', { class: 'mail' }, [h('div', { class: 'mail-label', text: 'Tiêu đề' })]);
    var ta = null, subj = null;
    if (state.editing) {
      subj = h('input', { id: 'mail-subject', class: 'input', type: 'text', maxlength: '200' });
      subj.value = d.subject;
      ta = h('textarea', { id: 'mail-edit', class: 'mail-edit', maxlength: '5000' });
      ta.value = d.body;
      mail.appendChild(h('label', { for: 'mail-subject', class: 'sr-only', text: 'Tiêu đề thư' }));
      mail.appendChild(subj);
      mail.appendChild(h('label', { for: 'mail-edit', class: 'mail-label', text: 'Nội dung thư' }));
      mail.appendChild(ta);
    } else {
      mail.appendChild(h('div', { class: 'mail-subject', text: d.subject }));
      mail.appendChild(h('div', { class: 'mail-body' }, d.body.split(/\n\s*\n/).map(function (p) { return h('p', { text: p }); })));
    }
    detail.appendChild(mail);

    detail.appendChild(h('div', { class: 'verify' }, [
      h('div', { class: 'verify-title', text: d.checks_ok ? 'Số liệu trong thư khớp với Odoo ngay lúc này' : 'Số liệu trong thư KHÔNG còn khớp với Odoo' }),
      h('div', { class: 'verify-chips' }, d.checks.map(function (c) {
        return h('span', { class: 'verify-chip' + (c.ok ? '' : ' verify-bad'), text: c.label });
      }))
    ]));

    if (state.notice) detail.appendChild(h('div', { class: 'alert alert-success', role: 'status', text: state.notice }));
    if (state.error) detail.appendChild(h('div', { class: 'alert alert-danger', role: 'alert', text: state.error }));

    if (d.status === 'pending') {
      if (state.editing) {
        detail.appendChild(h('div', { class: 'actions' }, [
          h('button', { type: 'button', class: 'btn btn-md', disabled: state.busy, text: 'Lưu nội dung', onclick: function () {
            var text = ta.value.trim(), title = subj.value.trim();
            if (!text || !title) { state.error = 'Tiêu đề và nội dung thư không được để trống.'; render(); return; }
            act(function () {
              return Api.patch('/api/reminders/drafts/' + d.id, { subject: title, body: text }).then(function () {
                state.editing = false;
                return reload(true);
              });
            });
          } }),
          h('button', { type: 'button', class: 'btn btn-md btn-plain', text: 'Hủy', onclick: function () { state.editing = false; state.error = ''; render(); } })
        ]));
        detail.appendChild(h('div', { class: 'note', text: 'Số liệu được kiểm tra với Odoo khi duyệt. Nếu sửa số tiền hoặc ngày trong nội dung, hãy kiểm tra kỹ trước khi duyệt.' }));
      } else {
        var actions = [];
        if (Api.can('draft:decide')) {
          var noteIn = h('input', { id: 'decision-note', class: 'input', type: 'text', maxlength: '500', placeholder: 'Ghi chú quyết định (không bắt buộc)' });
          actions.push(h('button', { type: 'button', class: 'btn btn-md', disabled: state.busy || !d.checks_ok, text: 'Duyệt', onclick: function () {
            act(function () { return Api.post('/api/reminders/drafts/' + d.id + '/approve', { note: noteIn.value.trim() || null }).then(function () { return reload(true); }); });
          } }));
          actions.push(h('button', { type: 'button', class: 'btn btn-md btn-outline', disabled: state.busy, text: 'Từ chối', onclick: function () {
            act(function () { return Api.post('/api/reminders/drafts/' + d.id + '/reject', { note: noteIn.value.trim() || null }).then(function () { return reload(true); }); });
          } }));
          detail.appendChild(h('div', { class: 'field' }, [h('label', { for: 'decision-note', text: 'Ghi chú quyết định' }), noteIn]));
        } else {
          detail.appendChild(h('div', { class: 'alert alert-warning', text: 'Bản nháp đang chờ kế toán trưởng duyệt. Bạn không có quyền duyệt hoặc từ chối.' }));
        }
        if (Api.can('draft:create')) {
          actions.push(h('button', { type: 'button', class: 'btn btn-md btn-plain', disabled: state.busy, text: 'Sửa nội dung', onclick: function () { state.editing = true; render(); } }));
        }
        if (actions.length) detail.appendChild(h('div', { class: 'actions' }, actions));
        if (!d.checks_ok && Api.can('draft:decide')) {
          detail.appendChild(h('div', { class: 'note', text: 'Không thể duyệt vì số liệu trên Odoo đã thay đổi. Hãy từ chối bản nháp này và soạn bản mới.' }));
        }
      }
    } else {
      var ok = d.status === 'approved';
      detail.appendChild(h('div', { class: 'decision ' + (ok ? 'decision-ok' : 'decision-no'), role: 'status' }, [
        h('div', { class: 'decision-title', text: ok ? 'Đã duyệt' : 'Đã từ chối, thư không được gửi' }),
        h('div', { class: 'decision-text', text: 'Người quyết định: ' + d.decided_by_username + ' lúc ' + when(d.decided_at) +
          '. Đã ghi vào nhật ký.' + (d.decision_note ? ' Ghi chú: ' + d.decision_note : '') }),
        ok ? h('div', { class: 'decision-text', text: 'Lưu ý: hệ thống chưa kết nối dịch vụ gửi email, nên duyệt chỉ ghi nhận quyết định. Thư cần được gửi ngoài hệ thống.' }) : null
      ]));
    }
  }

  function render() { renderQueue(); renderDetail(); }

  reload(false).then(function () {
    render();
    body.textContent = '';
    body.appendChild(h('div', { class: 'cols' }, [queueBox, detail]));
    body.appendChild(h('div', { class: 'note', text: 'Hệ thống chỉ đọc từ Odoo, không ghi gì vào Odoo.' }));
  }).catch(function (ex) {
    if (ex && ex.status === 401) return;
    body.textContent = '';
    body.appendChild(Shell.apiErrorAlert(ex));
  });
})();
