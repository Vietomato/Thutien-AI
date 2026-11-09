/* Collection tasks. Accountants see and finish their own; the chief accountant also sees the whole team's.
   Tasks are created from the Công nợ page by the chief accountant. */
(function () {
  'use strict';

  var h = Shell.h, fmt = Shell.fmt;
  var main = Shell.mount(['accountant', 'chief_accountant']);
  if (!main) return;

  var isChief = Api.can('task:read_team');
  main.appendChild(h('div', { style: { display: 'flex', flexDirection: 'column', gap: '4px' } }, [
    h('h1', { class: 'page-title', text: 'Nhiệm vụ thu nợ' }),
    h('div', { class: 'page-sub', style: { marginTop: '0' }, text: isChief
      ? 'Việc của bạn và của nhân viên trong nhóm. Giao việc mới từ trang Công nợ.'
      : 'Các hóa đơn kế toán trưởng giao cho bạn theo dõi thu nợ.' })
  ]));

  var state = { scope: 'mine', items: [], error: '', busy: false };
  var tabs = h('div', { class: 'tabs-inline', role: 'group', 'aria-label': 'Phạm vi nhiệm vụ' });
  var list = h('div', { class: 'card', style: { padding: '0', gap: '0', overflow: 'hidden' }, 'aria-live': 'polite' });
  var errBox = h('div', { class: 'alert alert-danger', role: 'alert', hidden: true });

  function renderTabs() {
    tabs.textContent = '';
    [['mine', 'Của tôi'], ['team', 'Cả nhóm']].forEach(function (t) {
      tabs.appendChild(h('button', {
        type: 'button', class: 'tab', style: { padding: '0 16px' }, 'aria-selected': String(state.scope === t[0]), text: t[1],
        onclick: function () { state.scope = t[0]; load(); }
      }));
    });
  }

  function toggle(t) {
    if (state.busy) return;
    state.busy = true;
    Api.patch('/api/tasks/' + t.id, { status: t.status === 'done' ? 'open' : 'done' }).then(function () {
      state.error = '';
    }).catch(function (ex) {
      if (ex && ex.status === 401) return;
      state.error = ex.status ? ex.message : 'Không kết nối được máy chủ.';
    }).then(function () { state.busy = false; return load(); });
  }

  function render() {
    errBox.hidden = !state.error;
    errBox.textContent = state.error;
    list.textContent = '';
    if (!state.items.length) {
      list.appendChild(h('div', { class: 'empty-note', text: state.scope === 'team'
        ? 'Nhóm của bạn chưa có nhiệm vụ nào.' : 'Bạn chưa có nhiệm vụ nào.' }));
      return;
    }
    state.items.forEach(function (t) {
      var done = t.status === 'done';
      var meta = 'Giao cho ' + t.assignee_name + ' (' + t.assignee_username + ') bởi ' + t.created_by_username +
        ' · ' + fmt.dmy(t.created_at.slice(0, 10), true) +
        (done && t.done_at ? ' · xong ' + fmt.dmy(t.done_at.slice(0, 10), true) : '');
      list.appendChild(h('div', { class: 'task' + (done ? ' task-done' : '') }, [
        h('div', { style: { display: 'flex', flexDirection: 'column', gap: '4px', minWidth: '0', flex: '1 1 260px' } }, [
          h('div', { class: 'task-title', text: t.title }),
          h('div', { class: 'task-meta', text: meta }),
          t.note ? h('div', { class: 'task-meta', style: { color: '#344054' }, text: 'Ghi chú: ' + t.note }) : null
        ]),
        h('button', {
          type: 'button', class: 'btn-sm' + (done ? '' : ' btn-sm-hot'), disabled: state.busy,
          'aria-label': (done ? 'Mở lại nhiệm vụ ' : 'Đánh dấu hoàn thành nhiệm vụ ') + t.invoice_id,
          text: done ? 'Mở lại' : 'Hoàn thành', onclick: function () { toggle(t); }
        })
      ]));
    });
  }

  function load() {
    renderTabs();
    return Api.get('/api/tasks?scope=' + state.scope).then(function (r) {
      state.items = r.items;
      render();
    }).catch(function (ex) {
      if (ex && ex.status === 401) return;
      state.items = [];
      state.error = ex.status ? ex.message : 'Không kết nối được máy chủ.';
      render();
    });
  }

  if (isChief) main.appendChild(tabs);
  main.appendChild(errBox);
  main.appendChild(list);
  load();
})();
