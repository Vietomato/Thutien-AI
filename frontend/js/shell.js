/* ThuTien AI: app shell (sidebar, account menu, logout, 401/403 messages) and small helpers.
   Needs api.js loaded first. All dynamic text goes through textContent. */
(function () {
  'use strict';

  /* ---------- DOM helper ---------- */
  // h('div', {class:'x', text:'..', onclick:fn, style:{...}}, [children])
  function h(tag, props, children) {
    var el = document.createElement(tag);
    props = props || {};
    Object.keys(props).forEach(function (k) {
      var v = props[k];
      if (v === undefined || v === null || v === false) return;
      if (k === 'text') el.textContent = v;
      else if (k === 'class') el.className = v;
      else if (k === 'style') Object.keys(v).forEach(function (s) { el.style[s] = v[s]; });
      else if (k.indexOf('on') === 0 && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    });
    (children || []).forEach(function (c) {
      if (c === null || c === undefined) return;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return el;
  }

  /* ---------- Formatting ---------- */
  var nf = new Intl.NumberFormat('vi-VN');
  function money(n) { return nf.format(Math.round(n)); }
  function millions(n) {
    var m = n / 1e6;
    return (Math.abs(m) >= 10 ? nf.format(Math.round(m)) : nf.format(Math.round(m * 10) / 10)) + ' triệu';
  }
  // "2026-11-09" -> "09/11/2026" (string split, no timezone surprises)
  function dmy(iso, short) {
    var p = String(iso).split('-');
    if (p.length !== 3) return String(iso);
    return short ? p[2] + '/' + p[1] : p[2] + '/' + p[1] + '/' + p[0];
  }
  function dayNumber(iso) {
    var p = String(iso).split('-');
    return Date.UTC(+p[0], +p[1] - 1, +p[2]) / 86400000;
  }
  function addDays(iso, n) {
    var d = new Date((dayNumber(iso) + n) * 86400000);
    return d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0') + '-' + String(d.getUTCDate()).padStart(2, '0');
  }
  // Overdue days from the API's as_of_date, never the browser clock.
  function overdueDays(asOf, due) { return dayNumber(asOf) - dayNumber(due); }

  /* ---------- Navigation per role ---------- */
  var STAFF_NAV = [
    { key: 'dashboard', label: 'Tổng quan', href: 'dashboard.html' },
    { key: 'invoices', label: 'Công nợ', href: 'invoices.html' },
    { key: 'reminders', label: 'Nhắc nợ', href: 'reminders.html' },
    { key: 'tasks', label: 'Nhiệm vụ', href: 'tasks.html' }
  ];
  var NAV = {
    accountant: STAFF_NAV,
    chief_accountant: STAFF_NAV,
    customer: [
      { key: 'summary', label: 'Công nợ của tôi', href: 'summary.html' }
    ],
    admin: [
      { key: 'users', label: 'Người dùng', href: 'admin.html#users' },
      { key: 'audit', label: 'Nhật ký thao tác', href: 'admin.html#audit' }
    ]
  };
  var INITIALS = { accountant: 'NV', chief_accountant: 'KT', customer: 'KH', admin: 'QT' };

  /* ---------- Alerts ---------- */
  function forbiddenAlert() {
    return h('div', { class: 'alert alert-danger', role: 'alert' }, [
      h('div', { class: 'alert-title', text: 'Bạn không có quyền xem mục này (403)' }),
      h('div', { text: 'Liên hệ quản trị viên nếu bạn cần quyền truy cập.' })
    ]);
  }
  function errorAlert(title, detail) {
    return h('div', { class: 'alert alert-danger', role: 'alert' }, [
      h('div', { class: 'alert-title', text: title }),
      detail ? h('div', { text: detail }) : null
    ]);
  }
  // Turn an API failure into an alert element (403 gets the standard message).
  function apiErrorAlert(ex) {
    if (ex && ex.status === 403) return forbiddenAlert();
    if (ex && ex.status === 502) return errorAlert('Không đọc được dữ liệu từ Odoo (502)', 'Thử lại sau ít phút.');
    if (ex && ex.status) return errorAlert('Không tải được dữ liệu (lỗi ' + ex.status + ')', 'Thử lại sau.');
    return errorAlert('Không kết nối được máy chủ', 'Kiểm tra backend đang chạy.');
  }

  /* ---------- Logout ---------- */
  function logout() {
    // The server records the logout in the audit log; the token is discarded here either way.
    var done = function () { Api.clearSession(); location.replace('index.html'); };
    Api.post('/api/auth/logout').then(done, done);
  }

  /* ---------- Change password dialog ---------- */
  function openPasswordDialog(opener) {
    var err = h('div', { class: 'alert alert-danger', role: 'alert', hidden: true });
    var ok = h('div', { class: 'alert alert-success', role: 'status', hidden: true });
    var oldIn = h('input', { id: 'pw-old', class: 'input', type: 'password', autocomplete: 'current-password', required: true });
    var newIn = h('input', { id: 'pw-new', class: 'input', type: 'password', autocomplete: 'new-password', minlength: '8', required: true });
    var save = h('button', { type: 'submit', class: 'btn btn-md', text: 'Đổi mật khẩu' });
    var dlg = h('dialog', { class: 'dlg', 'aria-labelledby': 'pw-title' });
    var form = h('form', { class: 'dlg-body', novalidate: true }, [
      h('h2', { id: 'pw-title', text: 'Đổi mật khẩu' }),
      h('div', { class: 'field' }, [h('label', { for: 'pw-old', text: 'Mật khẩu hiện tại' }), oldIn]),
      h('div', { class: 'field' }, [h('label', { for: 'pw-new', text: 'Mật khẩu mới' }), newIn,
        h('span', { class: 'field-hint', text: 'Tối thiểu 8 ký tự.' })]),
      err, ok,
      h('div', { class: 'actions' }, [save,
        h('button', { type: 'button', class: 'btn btn-md btn-plain', text: 'Đóng', onclick: function () { dlg.close(); } })])
    ]);
    dlg.appendChild(form);
    document.body.appendChild(dlg);
    dlg.addEventListener('close', function () { dlg.remove(); if (opener) opener.focus(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      err.hidden = true; ok.hidden = true;
      if (newIn.value.length < 8) { err.textContent = 'Mật khẩu mới cần tối thiểu 8 ký tự.'; err.hidden = false; return; }
      save.disabled = true;
      Api.post('/api/auth/change-password', { old_password: oldIn.value, new_password: newIn.value }).then(function () {
        form.reset();
        ok.textContent = 'Đã đổi mật khẩu.';
        ok.hidden = false;
      }).catch(function (ex) {
        if (ex && ex.status === 401) return;
        err.textContent = ex.status ? ex.message : 'Không kết nối được máy chủ.';
        err.hidden = false;
      }).then(function () { save.disabled = false; });
    });
    dlg.showModal();
    oldIn.focus();
  }

  /* ---------- Account menu ---------- */
  function buildAccount(role, username) {
    var roleLabel = Api.ROLE_LABEL[role] || role;
    var menu = h('div', { class: 'acct-menu', id: 'acct-menu', role: 'menu', hidden: true }, [
      h('div', { class: 'acct-head' }, [
        h('div', { class: 'acct-name', text: username }),
        h('div', { class: 'acct-sub', text: roleLabel })
      ]),
      h('div', { class: 'acct-items' }, [
        h('button', { type: 'button', class: 'acct-item', role: 'menuitem',
          onclick: function (e) { close(false); openPasswordDialog(e.currentTarget.closest('.acct').querySelector('.acct-trigger')); } },
          [h('span', { text: 'Đổi mật khẩu' })]),
        h('div', { class: 'acct-item acct-static' }, [
          h('span', { text: 'Vai trò hiện tại' }),
          h('span', { class: 'acct-role', text: roleLabel })
        ])
      ]),
      h('div', { class: 'acct-items acct-foot' }, [
        h('button', { type: 'button', class: 'acct-item acct-logout', role: 'menuitem', text: 'Đăng xuất', onclick: logout })
      ])
    ]);

    var trigger = h('button', {
      type: 'button', class: 'acct-trigger', 'aria-haspopup': 'true', 'aria-expanded': 'false', 'aria-controls': 'acct-menu'
    }, [
      h('span', { class: 'avatar', 'aria-hidden': 'true', text: INITIALS[role] || '?' }),
      h('span', { class: 'acct-text' }, [
        h('span', { class: 'acct-text-name', text: username }),
        h('span', { class: 'acct-text-role', text: roleLabel })
      ])
    ]);

    function close(refocus) {
      menu.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      if (refocus) trigger.focus();
    }
    trigger.addEventListener('click', function () {
      var open = menu.hidden;
      menu.hidden = !open;
      trigger.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', function (e) {
      if (!menu.hidden && !menu.contains(e.target) && !trigger.contains(e.target)) close(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !menu.hidden) close(true);
    });

    return h('div', { class: 'acct' }, [
      menu,
      trigger,
      h('button', { type: 'button', class: 'logout-btn', text: 'Đăng xuất', onclick: logout })
    ]);
  }

  /* ---------- Sidebar ---------- */
  function currentKey(items) {
    var file = location.pathname.split('/').pop() || 'index.html';
    var hash = location.hash;
    var best = null;
    items.forEach(function (n) {
      var parts = n.href.split('#');
      if (parts[0] !== file) return;
      if (parts[1] && ('#' + parts[1]) === hash) best = n.key;
      else if (!best && !parts[1]) best = n.key;
    });
    if (!best) {
      items.forEach(function (n) { if (!best && n.href.split('#')[0] === file) best = n.key; });
    }
    return best;
  }

  function buildSidebar(role, username) {
    var items = NAV[role] || [];
    var active = currentKey(items);
    var links = items.map(function (n) {
      return h('a', {
        class: 'nav-link', href: n.href, text: n.label, 'data-key': n.key,
        'aria-current': n.key === active ? 'page' : null
      });
    });
    return [
      h('a', { class: 'side-brand', href: Api.homeFor(role), 'aria-label': 'ThuTien AI, về trang chính' }, [
        h('span', { class: 'logo-holder' }),
        h('span', { text: 'ThuTien AI' })
      ]),
      h('nav', { class: 'side-nav', 'aria-label': 'Menu chính' }, links),
      buildAccount(role, username)
    ];
  }

  // The logo needs SVG namespace children, so build it separately.
  function fillLogo(root) {
    var holder = root.querySelector('.side-brand .logo-holder');
    if (!holder) return;
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('width', '30'); svg.setAttribute('height', '30'); svg.setAttribute('viewBox', '0 0 36 36');
    svg.setAttribute('aria-hidden', 'true');
    var rect = document.createElementNS(ns, 'rect');
    rect.setAttribute('width', '36'); rect.setAttribute('height', '36'); rect.setAttribute('rx', '10'); rect.setAttribute('fill', '#14B8A6');
    var line = document.createElementNS(ns, 'polyline');
    line.setAttribute('points', '10,19 16,25 26,12'); line.setAttribute('fill', 'none'); line.setAttribute('stroke', '#0B1F3A');
    line.setAttribute('stroke-width', '3.2'); line.setAttribute('stroke-linecap', 'round'); line.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(rect); svg.appendChild(line);
    holder.replaceWith(svg);
  }

  /* ---------- Mount ---------- */
  // Call first on every protected page.
  // Returns the <main> element when the page may render, or null (redirecting, or showing 403).
  function mount(allowedRoles) {
    Api.requireRole(allowedRoles);
    if (!Api.getToken()) return null; // no session: api.js is redirecting to login
    var role = Api.getRole();
    var username = Api.getFullName() || Api.getUsername() || '';
    var side = document.getElementById('sidebar');
    var main = document.getElementById('main');
    if (!side || !main) return null;

    buildSidebar(role, username).forEach(function (n) { side.appendChild(n); });
    fillLogo(side);
    // Pages with hash sections (admin) switch the active menu item when the hash changes.
    window.addEventListener('hashchange', function () {
      var key = currentKey(NAV[role] || []);
      Array.prototype.forEach.call(side.querySelectorAll('.nav-link'), function (a) {
        if (a.getAttribute('data-key') === key) a.setAttribute('aria-current', 'page');
        else a.removeAttribute('aria-current');
      });
    });

    if (allowedRoles.indexOf(role) === -1) {
      main.appendChild(h('h1', { class: 'page-title', text: 'Không có quyền truy cập' }));
      main.appendChild(forbiddenAlert());
      main.appendChild(h('div', {}, [h('a', { href: Api.homeFor(role), text: 'Về trang của bạn' })]));
      return null;
    }
    return main;
  }

  window.Shell = {
    h: h, mount: mount, logout: logout,
    forbiddenAlert: forbiddenAlert, errorAlert: errorAlert, apiErrorAlert: apiErrorAlert,
    fmt: { money: money, millions: millions, dmy: dmy, addDays: addDays, overdueDays: overdueDays }
  };
})();
