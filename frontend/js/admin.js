/* Admin: users, roles and audit log, all from /api/admin/*. No financial data is requested here. */
(function () {
  'use strict';

  var h = Shell.h;
  var main = Shell.mount(['admin']);
  if (!main) return;

  var ROLES = ['accountant', 'chief_accountant', 'customer', 'admin'];
  var ROLE_TAG = { accountant: 'tag-teal', chief_accountant: 'tag-part', customer: 'tag-ok', admin: 'tag-ai' };
  var ACTION_TAG = {
    login: 'tag-ok2', logout: 'tag-ok', approve_draft: 'tag-ok2', reject_draft: 'tag-ok', create_draft: 'tag-info', edit_draft: 'tag-info',
    login_failed: 'tag-late', login_blocked: 'tag-late', forbidden: 'tag-disp', set_role: 'tag-info', register: 'tag-info',
    create_user: 'tag-info', update_user: 'tag-info', reset_password: 'tag-disp', change_password: 'tag-ok',
    assign_task: 'tag-info', update_task: 'tag-ok'
  };

  main.appendChild(h('div', { style: { display: 'flex', flexDirection: 'column', gap: '4px' } }, [
    h('h1', { class: 'page-title', text: 'Quản trị hệ thống' }),
    h('div', { class: 'page-sub', style: { marginTop: '0' }, text: 'Cấp vai trò và theo dõi ai đã làm gì. Vai trò này không xem được hóa đơn hay dòng tiền.' })
  ]));

  var state = { users: [], customers: [], audit: [], editing: null, creating: false, busy: false, error: '', notice: '', actionFilter: '' };
  var usersPanel = h('section', { class: 'panel', id: 'users', 'aria-labelledby': 'users-h' });
  var auditPanel = h('section', { class: 'panel', id: 'audit', 'aria-labelledby': 'audit-h' });
  main.appendChild(h('div', { class: 'loading', id: 'loading', role: 'status', text: 'Đang tải...' }));

  function th(text, cls) { return h('th', { scope: 'col', class: cls || '', text: text }); }
  function roleLabel(r) { return Api.ROLE_LABEL[r] || r; }
  function fail(ex) {
    if (ex && ex.status === 401) return;
    state.error = ex && ex.status ? ex.message : 'Không kết nối được máy chủ.';
  }
  function select(id, label, options, value) {
    var sel = h('select', { id: id, class: 'select', 'aria-label': label });
    options.forEach(function (o) {
      var el = h('option', { value: o[0], text: o[1] });
      if (String(o[0]) === String(value === null || value === undefined ? '' : value)) el.selected = true;
      sel.appendChild(el);
    });
    return sel;
  }
  var chiefs = function () { return state.users.filter(function (u) { return u.role === 'chief_accountant' && u.is_active; }); };
  var customerOptions = function () { return [['', '— chưa liên kết —']].concat(state.customers.map(function (c) { return [c.customer_id, c.customer_id + ' · ' + c.name]; })); };
  var chiefOptions = function () { return [['', '— chưa có —']].concat(chiefs().map(function (c) { return [String(c.id), c.full_name + ' (' + c.username + ')']; })); };

  function reloadAll() {
    return Promise.all([Api.get('/api/admin/users'), Api.get('/api/admin/audit?limit=100' + (state.actionFilter ? '&action=' + encodeURIComponent(state.actionFilter) : ''))])
      .then(function (r) { state.users = r[0].items; state.audit = r[1].items; });
  }
  function run(fn, okText) {
    if (state.busy) return;
    state.busy = true; state.error = ''; state.notice = '';
    render();
    fn().then(function () { if (okText) state.notice = okText; return reloadAll(); }).catch(fail)
      .then(function () { state.busy = false; render(); });
  }

  /* ---------- Create form ---------- */
  function createForm() {
    var u = h('input', { id: 'nu-user', class: 'input', type: 'text', autocomplete: 'off', required: true });
    var n = h('input', { id: 'nu-name', class: 'input', type: 'text', required: true });
    var p = h('input', { id: 'nu-pass', class: 'input', type: 'password', autocomplete: 'new-password', minlength: '8', required: true });
    var role = select('nu-role', 'Vai trò', ROLES.map(function (r) { return [r, roleLabel(r)]; }), 'accountant');
    var cust = select('nu-cust', 'Khách hàng Odoo', customerOptions(), '');
    var boss = select('nu-boss', 'Người quản lý', chiefOptions(), '');
    var custF = h('div', { class: 'field', hidden: true }, [h('label', { for: 'nu-cust', text: 'Liên kết khách hàng Odoo' }), cust]);
    var bossF = h('div', { class: 'field' }, [h('label', { for: 'nu-boss', text: 'Kế toán trưởng quản lý' }), boss]);
    role.addEventListener('change', function () {
      custF.hidden = role.value !== 'customer';
      bossF.hidden = role.value !== 'accountant';
    });
    var err = h('div', { class: 'alert alert-danger', role: 'alert', hidden: true });
    var form = h('form', { novalidate: true, style: { padding: '18px 22px', display: 'flex', flexDirection: 'column', gap: '14px', borderBottom: '1px solid #EEF1F5' } }, [
      h('div', { class: 'form-grid' }, [
        h('div', { class: 'field' }, [h('label', { for: 'nu-user', text: 'Tên đăng nhập' }), u]),
        h('div', { class: 'field' }, [h('label', { for: 'nu-name', text: 'Họ và tên' }), n]),
        h('div', { class: 'field' }, [h('label', { for: 'nu-pass', text: 'Mật khẩu ban đầu' }), p]),
        h('div', { class: 'field' }, [h('label', { for: 'nu-role', text: 'Vai trò' }), role]),
        custF, bossF
      ]),
      err,
      h('div', { class: 'actions' }, [
        h('button', { type: 'submit', class: 'btn-sm btn-sm-hot', disabled: state.busy, text: 'Tạo người dùng' }),
        h('button', { type: 'button', class: 'btn-sm', text: 'Hủy', onclick: function () { state.creating = false; render(); } })
      ])
    ]);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!u.value.trim() || !n.value.trim() || p.value.length < 8) {
        err.textContent = 'Nhập đủ tên đăng nhập, họ tên và mật khẩu từ 8 ký tự.'; err.hidden = false; return;
      }
      var payload = { username: u.value.trim(), full_name: n.value.trim(), password: p.value, role: role.value,
        customer_id: role.value === 'customer' && cust.value ? cust.value : null,
        supervisor_id: role.value === 'accountant' && boss.value ? parseInt(boss.value, 10) : null };
      run(function () {
        return Api.post('/api/admin/users', payload).then(function () { state.creating = false; });
      }, 'Đã tạo người dùng ' + payload.username + '.');
    });
    return form;
  }

  /* ---------- Users ---------- */
  function linkText(u) {
    if (u.role === 'customer') return u.customer_id ? 'Khách hàng ' + u.customer_id : null;
    if (u.role === 'accountant') return u.supervisor_username ? 'Thuộc nhóm ' + u.supervisor_username : 'Chưa có người quản lý';
    return '—';
  }

  function editCells(u) {
    var role = select('ed-role', 'Vai trò mới của ' + u.username, ROLES.map(function (r) { return [r, roleLabel(r)]; }), u.role);
    var cust = select('ed-cust', 'Khách hàng Odoo', customerOptions(), u.customer_id || '');
    var boss = select('ed-boss', 'Người quản lý', chiefOptions(), u.supervisor_id || '');
    var active = h('input', { id: 'ed-active', type: 'checkbox' });
    active.checked = u.is_active;
    var extra = h('div', { class: 'inline-form' });
    function syncExtra() {
      extra.textContent = '';
      if (role.value === 'customer') extra.appendChild(cust);
      if (role.value === 'accountant') extra.appendChild(boss);
    }
    role.addEventListener('change', syncExtra);
    syncExtra();
    var roleTd = h('td', {}, [role]);
    var linkTd = h('td', {}, [extra]);
    var statusTd = h('td', {}, [h('label', { class: 'inline-form', for: 'ed-active', style: { fontSize: '13px' } }, [active, 'Hoạt động'])]);
    var actTd = h('td', { class: 'num' }, [h('div', { class: 'row-actions' }, [
      h('button', { type: 'button', class: 'btn-sm btn-sm-hot', disabled: state.busy, text: 'Lưu', onclick: function () {
        var patch = { role: role.value, is_active: active.checked };
        if (role.value === 'customer') patch.customer_id = cust.value || null;
        if (role.value === 'accountant') patch.supervisor_id = boss.value ? parseInt(boss.value, 10) : null;
        run(function () { return Api.patch('/api/admin/users/' + u.id, patch).then(function () { state.editing = null; }); }, 'Đã cập nhật ' + u.username + '.');
      } }),
      h('button', { type: 'button', class: 'btn-sm', disabled: state.busy, text: 'Hủy', onclick: function () { state.editing = null; render(); } })
    ])]);
    return [roleTd, linkTd, statusTd, actTd];
  }

  function resetDialog(u) {
    var pass = h('input', { id: 'rp-pass', class: 'input', type: 'password', autocomplete: 'new-password', minlength: '8' });
    var err = h('div', { class: 'alert alert-danger', role: 'alert', hidden: true });
    var dlg = h('dialog', { class: 'dlg', 'aria-labelledby': 'rp-title' });
    var form = h('form', { class: 'dlg-body', novalidate: true }, [
      h('h2', { id: 'rp-title', text: 'Đặt lại mật khẩu cho ' + u.username }),
      h('div', { class: 'field' }, [h('label', { for: 'rp-pass', text: 'Mật khẩu mới' }), pass, h('span', { class: 'field-hint', text: 'Tối thiểu 8 ký tự. Tài khoản đang bị khoá do nhập sai sẽ được mở lại.' })]),
      err,
      h('div', { class: 'actions' }, [
        h('button', { type: 'submit', class: 'btn btn-md', text: 'Đặt lại' }),
        h('button', { type: 'button', class: 'btn btn-md btn-plain', text: 'Hủy', onclick: function () { dlg.close(); } })
      ])
    ]);
    dlg.appendChild(form);
    document.body.appendChild(dlg);
    dlg.addEventListener('close', function () { dlg.remove(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (pass.value.length < 8) { err.textContent = 'Mật khẩu cần tối thiểu 8 ký tự.'; err.hidden = false; return; }
      Api.post('/api/admin/users/' + u.id + '/password', { password: pass.value }).then(function () {
        dlg.close();
        state.notice = 'Đã đặt lại mật khẩu cho ' + u.username + '.'; state.error = '';
        render();
      }).catch(function (ex) {
        if (ex && ex.status === 401) return;
        err.textContent = ex.status ? ex.message : 'Không kết nối được máy chủ.'; err.hidden = false;
      });
    });
    dlg.showModal();
    pass.focus();
  }

  function renderUsers() {
    usersPanel.textContent = '';
    var unlinked = state.users.filter(function (u) { return u.role === 'customer' && !u.customer_id && u.is_active; }).length;
    usersPanel.appendChild(h('div', { class: 'panel-head' }, [
      h('h2', { id: 'users-h', text: 'Người dùng (' + state.users.length + ')' }),
      h('div', { class: 'row-actions' }, [
        unlinked ? h('span', { class: 'tag tag-disp', style: { fontSize: '13px', padding: '4px 10px' }, text: unlinked + ' tài khoản khách hàng chưa liên kết' }) : null,
        h('button', { type: 'button', class: 'btn-sm btn-sm-hot', text: 'Thêm người dùng', 'aria-expanded': String(state.creating), onclick: function () { state.creating = !state.creating; render(); } })
      ])
    ]));
    if (state.notice) usersPanel.appendChild(h('div', { class: 'alert alert-success', role: 'status', style: { margin: '14px 22px' }, text: state.notice }));
    if (state.error) usersPanel.appendChild(h('div', { class: 'alert alert-danger', role: 'alert', style: { margin: '14px 22px' }, text: state.error }));
    if (state.creating) usersPanel.appendChild(createForm());

    var me = Api.getUsername();
    var rows = state.users.map(function (u) {
      var editing = state.editing === u.id;
      var cells = [
        h('td', { class: 'cell-strong', text: u.username }),
        h('td', { text: u.full_name })
      ];
      if (editing) {
        cells = cells.concat(editCells(u));
      } else {
        var link = linkText(u);
        cells.push(h('td', {}, [h('span', { class: 'tag tag-b ' + ROLE_TAG[u.role], text: roleLabel(u.role) })]));
        cells.push(h('td', {}, [link === null ? h('span', { class: 'tag tag-disp', text: 'Chưa liên kết' }) : h('span', { class: 'cell-sub', style: { fontSize: '14px' }, text: link })]));
        cells.push(h('td', {}, [h('span', { class: 'tag ' + (u.is_active ? 'tag-ok2' : 'tag-late'), text: u.is_active ? 'Hoạt động' : 'Đã khoá' })]));
        cells.push(h('td', { class: 'num' }, [h('div', { class: 'row-actions' }, [
          h('button', { type: 'button', class: 'btn-sm', disabled: state.busy || u.username === me,
            title: u.username === me ? 'Không tự đổi vai trò của chính mình' : null,
            'aria-label': 'Sửa người dùng ' + u.username, text: 'Sửa', onclick: function () { state.editing = u.id; state.error = ''; render(); } }),
          h('button', { type: 'button', class: 'btn-sm', disabled: state.busy, 'aria-label': 'Đặt lại mật khẩu của ' + u.username,
            text: 'Đặt lại mật khẩu', onclick: function () { resetDialog(u); } })
        ])]));
      }
      return h('tr', { class: u.role === 'customer' && !u.customer_id && u.is_active ? 'row-new' : '' }, cells);
    });
    usersPanel.appendChild(h('div', { class: 'table-scroll' }, [
      h('table', { class: 'table table-plain', style: { minWidth: '820px' } }, [
        h('caption', { class: 'sr-only', text: 'Danh sách người dùng' }),
        h('thead', {}, [h('tr', {}, [th('Tên đăng nhập'), th('Họ tên'), th('Vai trò'), th('Liên kết'), th('Trạng thái'), th('Thao tác', 'num')])]),
        h('tbody', {}, rows)
      ])
    ]));
  }

  /* ---------- Audit ---------- */
  function stamp(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    var p = function (n) { return String(n).padStart(2, '0'); };
    return p(d.getDate()) + '/' + p(d.getMonth() + 1) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }
  function detailText(d) {
    var keys = Object.keys(d || {});
    if (!keys.length) return '';
    return keys.map(function (k) { return k + ': ' + (typeof d[k] === 'object' ? JSON.stringify(d[k]) : d[k]); }).join(', ');
  }

  function renderAudit() {
    auditPanel.textContent = '';
    var filter = select('audit-filter', 'Lọc theo hành động',
      [['', 'Tất cả hành động']].concat(Object.keys(ACTION_TAG).sort().map(function (a) { return [a, a]; })), state.actionFilter);
    filter.addEventListener('change', function () { state.actionFilter = filter.value; run(function () { return Promise.resolve(); }); });
    auditPanel.appendChild(h('div', { class: 'panel-head' }, [
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px' } }, [
        h('h2', { id: 'audit-h', text: 'Nhật ký thao tác' }),
        h('div', { class: 'note', text: 'Chỉ thêm, không sửa hay xoá (cơ sở dữ liệu chặn). Mật khẩu và token luôn bị che. Hiện 100 dòng mới nhất.' })
      ]),
      filter
    ]));
    auditPanel.appendChild(h('div', { class: 'table-scroll' }, [
      h('table', { class: 'table table-plain', style: { minWidth: '720px' } }, [
        h('caption', { class: 'sr-only', text: 'Nhật ký thao tác' }),
        h('thead', {}, [h('tr', {}, [th('Thời gian'), th('Người thực hiện'), th('Hành động'), th('Đối tượng'), th('Chi tiết')])]),
        h('tbody', {}, state.audit.length ? state.audit.map(function (a) {
          return h('tr', { style: { cursor: 'default' } }, [
            h('td', { class: 'cell-sub nowrap', style: { fontSize: '14px' }, text: stamp(a.ts) }),
            h('td', { class: 'cell-strong', text: a.actor }),
            h('td', {}, [h('span', { class: 'tag ' + (ACTION_TAG[a.action] || 'tag-ok'), text: a.action })]),
            h('td', { style: { color: '#344054', overflowWrap: 'anywhere' }, text: a.target }),
            h('td', { class: 'cell-sub', style: { overflowWrap: 'anywhere' }, text: detailText(a.detail) })
          ]);
        }) : [h('tr', {}, [h('td', { colspan: '5', class: 'empty', text: 'Chưa có dòng nhật ký nào.' })])])
      ])
    ]));
  }

  function render() {
    var keepFocus = document.activeElement && document.activeElement.id;
    renderUsers(); renderAudit();
    if (keepFocus) { var el = document.getElementById(keepFocus); if (el) el.focus(); }
  }

  /* ---------- Load ---------- */
  Promise.all([reloadAll(), Api.get('/api/admin/customers')]).then(function (r) {
    state.customers = r[1].items;
    var loading = document.getElementById('loading');
    if (loading) loading.remove();
    render();
    main.appendChild(usersPanel);
    main.appendChild(auditPanel);
    if (location.hash === '#audit') auditPanel.scrollIntoView();
  }).catch(function (ex) {
    var loading = document.getElementById('loading');
    if (loading) loading.remove();
    if (ex && ex.status === 401) return;
    main.appendChild(Shell.apiErrorAlert(ex));
  });
})();
