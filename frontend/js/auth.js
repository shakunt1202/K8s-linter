/**
 * auth.js — Login / logout / session + user-store (localStorage-backed)
 *
 * Exports: initAuth, doLogin, doLogout, getCurrentUser
 * Reads from/writes to: k8s_linter_users, k8s_linter_session
 */

'use strict';

/* ── User store ─────────────────────────────────────────────────────── */

function loadUsers() {
  try { return JSON.parse(localStorage.getItem('k8s_linter_users') || 'null'); }
  catch (e) { return null; }
}
function saveUsers(u) { localStorage.setItem('k8s_linter_users', JSON.stringify(u)); }

function initUsers() {
  if (!loadUsers()) {
    saveUsers([
      { username: 'admin', password: 'admin123', role: 'admin',    active: true },
      { username: 'demo',  password: 'demo',     role: 'viewer',   active: true },
      { username: 'k8s',   password: 'linter',   role: 'operator', active: true },
    ]);
  }
}

/* ── Current user (module-level) ────────────────────────────────────── */
let _currentUser = null;
function getCurrentUser() { return _currentUser; }

/* ── Auth flow ──────────────────────────────────────────────────────── */

function initAuth({ onSuccess } = {}) {
  initUsers();
  const remembered = localStorage.getItem('k8s_linter_session');
  if (remembered) {
    const u = (loadUsers() || []).find(x => x.username === remembered && x.active);
    if (u) {
      showApp(u);          // show the app and update UI
      onSuccess && onSuccess(u);
      return;
    }
  }
  _showLoginScreen();
}

function _showLoginScreen() {
  document.getElementById('main-app').style.display   = 'none';
  const ls = document.getElementById('login-screen');
  ls.style.display = 'flex';
  ls.classList.remove('hidden');
  setTimeout(() => document.getElementById('login-user')?.focus(), 400);
}

function showApp(user) {
  _currentUser = user;
  document.getElementById('main-app').style.display = 'grid';
  const ls = document.getElementById('login-screen');
  ls.classList.add('hidden');
  setTimeout(() => { ls.style.display = 'none'; }, 450);
  // update avatar/role in the header
  window.__updateUserUI && window.__updateUserUI();
}

function doLogin() {
  const user   = document.getElementById('login-user').value.trim();
  const pass   = document.getElementById('login-pass').value;
  const btn    = document.getElementById('login-btn');
  const label  = document.getElementById('login-btn-label');
  const uInput = document.getElementById('login-user');
  const pInput = document.getElementById('login-pass');

  if (!user || !pass) { showLoginError('Please enter your username and password.'); return; }

  btn.disabled = true;
  label.innerHTML = '<span class="spinner"></span>&nbsp; Signing in…';
  document.getElementById('login-error').classList.remove('show');
  uInput.classList.remove('error');
  pInput.classList.remove('error');

  setTimeout(() => {
    const found = (loadUsers() || []).find(x => x.username === user && x.password === pass && x.active);
    if (found) {
      label.innerHTML = '✓ Authenticated';
      if (document.getElementById('login-remember')?.checked) {
        localStorage.setItem('k8s_linter_session', user);
      }
      setTimeout(() => {
        showApp(found);
        window.__updateUserUI && window.__updateUserUI();
        window.__onAuthSuccess && window.__onAuthSuccess();
      }, 500);
    } else {
      btn.disabled = false;
      label.textContent = 'Sign in';
      uInput.classList.add('error');
      pInput.classList.add('error');
      pInput.value = '';
      pInput.focus();
      showLoginError('Incorrect username or password. Please try again.');
    }
  }, 900);
}

function doLogout() {
  localStorage.removeItem('k8s_linter_session');
  _currentUser = null;
  // Reset login form
  const lbl = document.getElementById('login-btn-label');
  if (lbl) lbl.textContent = 'Sign in';
  const btn = document.getElementById('login-btn');
  if (btn) btn.disabled = false;
  const u = document.getElementById('login-user');
  const p = document.getElementById('login-pass');
  if (u) u.value = '';
  if (p) p.value = '';
  document.getElementById('login-error')?.classList.remove('show');
  _showLoginScreen();
}

function showLoginError(msg) {
  const el = document.getElementById('login-error');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
}

/* ── User management CRUD (localStorage) ───────────────────────────── */

function addUser(name, pass, role) {
  if (!name || !pass) return { ok: false, msg: 'Username and password required.' };
  const users = loadUsers() || [];
  if (users.find(u => u.username === name)) return { ok: false, msg: 'Username already exists.' };
  users.push({ username: name, password: pass, role, active: true });
  saveUsers(users);
  return { ok: true };
}

function deleteUser(username) {
  const users = (loadUsers() || []).filter(u => u.username !== username);
  saveUsers(users);
}

function toggleUserActive(username) {
  const users = loadUsers() || [];
  const u = users.find(x => x.username === username);
  if (u) { u.active = !u.active; saveUsers(users); }
}

function renderUserTable() {
  const tbody = document.getElementById('user-table-body');
  if (!tbody) return;
  const users = loadUsers() || [];
  const me    = _currentUser?.username;
  tbody.innerHTML = users.map(u => `
    <tr>
      <td><span style="font-family:'Geist Mono',monospace;font-size:11px">${esc(u.username)}</span></td>
      <td><span class="role-badge ${u.role}">${esc(u.role)}</span></td>
      <td><span style="color:${u.active ? 'var(--green)' : 'var(--t4)'};font-size:10px">${u.active ? 'Active' : 'Disabled'}</span></td>
      <td style="display:flex;gap:4px;align-items:center">
        <button class="tbl-action" onclick="window.__toggleUserActive('${esc(u.username)}')">${u.active ? 'Disable' : 'Enable'}</button>
        ${u.username !== me
          ? `<button class="tbl-action del" onclick="window.__deleteUser('${esc(u.username)}')">Delete</button>`
          : '<span style="font-size:10px;color:var(--t3)">(you)</span>'
        }
      </td>
    </tr>`).join('');
}

/* helpers exposed to global for inline onclick */
function esc(s) { return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// Expose via window so the HTML module can call them
window.__deleteUser = function(username) {
  if (!confirm(`Delete user "${username}"?`)) return;
  deleteUser(username);
  renderUserTable();
};
window.__toggleUserActive = function(username) {
  toggleUserActive(username);
  renderUserTable();
};

/* ── Exports (global namespace pattern for single-file HTML) ─────────── */
window.Auth = {
  initAuth, doLogin, doLogout, showLoginError, getCurrentUser,
  loadUsers, saveUsers, addUser, renderUserTable,
};
