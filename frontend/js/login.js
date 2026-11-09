/* Login / register page logic. Only textContent is used for dynamic text. */
(function () {
  'use strict';

  // Usernames only. Passwords are never stored here: the user types the demo value.
  var DEMO = [
    { u: 'accountant1', role: 'accountant', label: 'Nhân viên KT' },
    { u: 'chief1', role: 'chief_accountant', label: 'Kế toán trưởng' },
    { u: 'customer1', role: 'customer', label: 'Khách hàng' },
    { u: 'admin1', role: 'admin', label: 'Quản trị' }
  ];
  var HINTS = {
    accountant: 'Nhân viên kế toán: xem công nợ, dự đoán, dòng tiền, soạn bản nháp nhắc nợ và làm nhiệm vụ được giao.',
    chief_accountant: 'Kế toán trưởng: như nhân viên, thêm duyệt hoặc từ chối bản nháp, giao việc và xem nhiệm vụ của nhóm.',
    customer: 'Khách hàng: chỉ xem hóa đơn và các khoản thanh toán của chính mình.',
    admin: 'Quản trị: quản lý người dùng, cấp vai trò và xem nhật ký, không xem dữ liệu tài chính.'
  };

  var $ = function (id) { return document.getElementById(id); };
  var tabLogin = $('tab-login'), tabReg = $('tab-register');
  var panelLogin = $('panel-login'), panelReg = $('panel-register');
  var userIn = $('u'), passIn = $('p');

  function show(el, text) {
    el.textContent = text;
    el.hidden = false;
  }

  /* ---------- Tabs ---------- */
  function setMode(mode) {
    var isLogin = mode === 'login';
    tabLogin.setAttribute('aria-selected', String(isLogin));
    tabReg.setAttribute('aria-selected', String(!isLogin));
    tabLogin.tabIndex = isLogin ? 0 : -1;
    tabReg.tabIndex = isLogin ? -1 : 0;
    panelLogin.hidden = !isLogin;
    panelReg.hidden = isLogin;
    panelLogin.style.display = isLogin ? 'flex' : 'none';
    panelReg.style.display = isLogin ? 'none' : 'flex';
  }
  tabLogin.addEventListener('click', function () { setMode('login'); });
  tabReg.addEventListener('click', function () { setMode('register'); });
  [tabLogin, tabReg].forEach(function (t) {
    t.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        var next = t === tabLogin ? tabReg : tabLogin;
        next.click();
        next.focus();
      }
    });
  });

  /* ---------- Demo chips ---------- */
  var chipsBox = $('chips');
  var chipEls = [];
  function pick(d) {
    userIn.value = d.u;
    $('role-hint').textContent = HINTS[d.role];
    chipEls.forEach(function (c) { c.el.setAttribute('aria-pressed', String(c.d === d)); });
    passIn.focus();
  }
  DEMO.forEach(function (d) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip';
    b.textContent = d.label;
    b.setAttribute('aria-pressed', 'false');
    b.addEventListener('click', function () { pick(d); });
    chipsBox.appendChild(b);
    chipEls.push({ d: d, el: b });
  });
  $('role-hint').textContent = 'Chọn một tài khoản demo để xem mô tả vai trò.';

  /* ---------- Reason from redirect (401 / 403) ---------- */
  var reason = new URLSearchParams(location.search).get('reason');
  if (reason === 'expired') show($('login-notice'), Api.MESSAGES.expired);
  else if (reason === 'forbidden') show($('login-notice'), Api.MESSAGES.forbidden);

  /* ---------- Login ---------- */
  $('login-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var err = $('login-error'), btn = $('login-btn');
    err.hidden = true;
    var username = userIn.value.trim(), password = passIn.value;
    if (!username || !password) {
      show(err, 'Vui lòng nhập tên đăng nhập và mật khẩu.');
      return;
    }
    btn.disabled = true;
    btn.textContent = 'Đang đăng nhập...';
    Api.login(username, password).then(function (data) {
      location.replace(Api.homeFor(data.role));
    }).catch(function (ex) {
      btn.disabled = false;
      btn.textContent = 'Đăng nhập';
      if (ex.status === 401) show(err, 'Sai tên đăng nhập hoặc mật khẩu.');
      else if (ex.status === 429) show(err, ex.message);
      else if (ex.status) show(err, 'Không đăng nhập được (lỗi ' + ex.status + '). Thử lại sau.');
      else show(err, 'Không kết nối được máy chủ. Kiểm tra backend đang chạy.');
    });
  });

  /* ---------- Register ---------- */
  $('register-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var err = $('register-error'), btn = $('register-btn');
    err.hidden = true;
    var name = $('rn').value.trim(), user = $('ru').value.trim(), pass = $('rp').value;
    if (!name || !user || !pass) { show(err, 'Vui lòng nhập đầy đủ họ tên, tên đăng nhập và mật khẩu.'); return; }
    if (pass.length < 8) { show(err, 'Mật khẩu cần tối thiểu 8 ký tự.'); return; }
    btn.disabled = true;
    Api.register(name, user, pass).then(function (res) {
      btn.disabled = false;
      $('register-form').reset();
      setMode('login');
      userIn.value = res.username;
      passIn.value = '';
      show($('login-notice'), 'Đã tạo tài khoản. Bạn đăng nhập với vai trò Khách hàng; quản trị viên sẽ liên kết tài khoản với hồ sơ khách hàng của bạn.');
      $('login-notice').className = 'alert alert-success';
      passIn.focus();
    }).catch(function (ex) {
      btn.disabled = false;
      if (ex.status === 422) show(err, 'Thông tin chưa hợp lệ: ' + ex.message);
      else if (ex.status) show(err, ex.message);
      else show(err, 'Không kết nối được máy chủ. Kiểm tra backend đang chạy.');
    });
  });
})();
