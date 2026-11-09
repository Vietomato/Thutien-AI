/* ThuTien AI: fetch wrapper, token, role and permissions.
   Token and profile live in sessionStorage only. Same-origin API, base URL "/".
   The server is the real gatekeeper: permissions kept here only decide what the UI shows. */
(function () {
  'use strict';

  var TOKEN_KEY = 'thutien.token';
  var PROFILE_KEY = 'thutien.profile';

  // Landing page per role.
  var ROLE_HOME = {
    accountant: 'dashboard.html',
    chief_accountant: 'dashboard.html',
    customer: 'summary.html',
    admin: 'admin.html'
  };

  var ROLE_LABEL = {
    accountant: 'Nhân viên kế toán',
    chief_accountant: 'Kế toán trưởng',
    customer: 'Khách hàng',
    admin: 'Quản trị'
  };

  var MESSAGES = {
    expired: 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.',
    forbidden: 'Bạn không có quyền xem mục này (403). Liên hệ quản trị viên nếu bạn cần quyền truy cập.'
  };

  // Server error details are English; these are the ones a person can act on.
  var DETAILS = {
    'invoice is disputed, no reminder': 'Hóa đơn đang tranh chấp nên không nhắc nợ.',
    'invoice is not overdue': 'Hóa đơn chưa quá hạn.',
    'invoice not found or already paid': 'Không tìm thấy hóa đơn, hoặc hóa đơn đã thanh toán.',
    'a pending draft already exists for this invoice': 'Hóa đơn này đã có bản nháp đang chờ duyệt.',
    'only pending drafts can be edited': 'Chỉ sửa được bản nháp đang chờ duyệt.',
    'draft was already decided': 'Bản nháp đã được quyết định trước đó.',
    'invoice data changed in Odoo since this draft was written; reject it and create a new one':
      'Số liệu hóa đơn trên Odoo đã thay đổi từ khi soạn. Hãy từ chối bản nháp này và tạo bản mới.',
    'assignee is not in your team': 'Người được giao không thuộc nhóm của bạn.',
    'username already taken': 'Tên đăng nhập đã được dùng.',
    'username must be 3-32 characters: a-z, 0-9, dot, dash, underscore':
      'Tên đăng nhập gồm 3 đến 32 ký tự: chữ thường a-z, số, dấu chấm, gạch ngang, gạch dưới.',
    'you cannot change your own role or deactivate yourself': 'Bạn không thể tự đổi vai trò hoặc tự khoá tài khoản của mình.',
    'at least one active admin must remain': 'Phải còn ít nhất một quản trị viên đang hoạt động.',
    'unknown Odoo customer id': 'Mã khách hàng không có trên Odoo.',
    'supervisor must be an active chief accountant': 'Người quản lý phải là kế toán trưởng đang hoạt động.',
    'only an accountant has a supervisor': 'Chỉ nhân viên kế toán mới có người quản lý.',
    'only a customer account can be linked to an Odoo customer': 'Chỉ tài khoản khách hàng mới liên kết được với khách hàng Odoo.',
    'old password is incorrect': 'Mật khẩu cũ không đúng.',
    'too many failed attempts, try again later': 'Nhập sai quá nhiều lần. Tài khoản tạm khoá, thử lại sau 15 phút.'
  };

  function ApiError(status, detail) {
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail || '';
    this.message = DETAILS[detail] || detail || ('HTTP ' + status);
  }
  ApiError.prototype = Object.create(Error.prototype);

  function getToken() { return sessionStorage.getItem(TOKEN_KEY); }
  function getProfile() {
    try { return JSON.parse(sessionStorage.getItem(PROFILE_KEY) || 'null'); } catch (e) { return null; }
  }
  function getRole() { var p = getProfile(); return p ? p.role : null; }
  function getUsername() { var p = getProfile(); return p ? p.username : null; }
  function getFullName() { var p = getProfile(); return p ? (p.full_name || p.username) : null; }
  function can(permission) { var p = getProfile(); return !!(p && p.permissions && p.permissions.indexOf(permission) !== -1); }

  function setSession(token, profile) {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
  }
  function clearSession() {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(PROFILE_KEY);
  }

  function homeFor(role) { return ROLE_HOME[role] || 'index.html'; }

  // No token or 401 -> clear session and go to login with the expiry message.
  function goLogin(reason) {
    clearSession();
    location.replace('index.html' + (reason ? '?reason=' + encodeURIComponent(reason) : ''));
  }

  // Resolves with parsed JSON, rejects with ApiError. A 401 on anything but login/register redirects.
  function request(method, path, body, opts) {
    opts = opts || {};
    var headers = { 'Accept': 'application/json' };
    var token = getToken();
    if (token && !opts.anonymous) headers['Authorization'] = 'Bearer ' + token;
    var init = { method: method, headers: headers };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    return fetch(path, init).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        if (text) { try { data = JSON.parse(text); } catch (e) { data = null; } }
        if (res.status === 401 && !opts.anonymous) {
          goLogin('expired');
          throw new ApiError(401, 'unauthorized');
        }
        if (!res.ok) {
          var detail = data && typeof data.detail === 'string' ? data.detail : null;
          if (!detail && data && Array.isArray(data.detail) && data.detail[0] && data.detail[0].msg) detail = data.detail[0].msg;
          throw new ApiError(res.status, detail);
        }
        return data;
      });
    });
  }

  function login(username, password) {
    return request('POST', '/api/auth/login', { username: username, password: password }, { anonymous: true })
      .then(function (data) {
        setSession(data.access_token, {
          username: data.username, full_name: data.full_name, role: data.role,
          customer_id: data.customer_id, permissions: data.permissions
        });
        return data;
      });
  }

  function register(fullName, username, password) {
    return request('POST', '/api/auth/register',
      { full_name: fullName, username: username, password: password }, { anonymous: true });
  }

  // Page guard: call at the top of every page except index.html.
  // Returns true when the page may render; sends the user to login when there is no session.
  function requireRole(allowedRoles) {
    if (!getToken() || !getRole()) { goLogin('expired'); return false; }
    return allowedRoles.indexOf(getRole()) !== -1;
  }

  window.Api = {
    ApiError: ApiError,
    MESSAGES: MESSAGES,
    ROLE_LABEL: ROLE_LABEL,
    getToken: getToken,
    getRole: getRole,
    getUsername: getUsername,
    getFullName: getFullName,
    can: can,
    clearSession: clearSession,
    homeFor: homeFor,
    goLogin: goLogin,
    requireRole: requireRole,
    login: login,
    register: register,
    get: function (path) { return request('GET', path); },
    post: function (path, body) { return request('POST', path, body === undefined ? {} : body); },
    patch: function (path, body) { return request('PATCH', path, body); }
  };
})();
