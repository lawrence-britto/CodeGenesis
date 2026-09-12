const authState = { promise: null };
const dashboardState = new Map();
const requestCache = new Map();

function getUser() {
  if (!authState.promise) authState.promise = AX.api('/api/auth/me').then(user => {
    try { sessionStorage.setItem('acceleratex-user', JSON.stringify(user)); } catch {}
    return user;
  });
  return authState.promise;
}

function getDashboard(days) {
  const key = String(days);
  if (!dashboardState.has(key)) dashboardState.set(key, AX.api(`/api/dashboard?days=${encodeURIComponent(key)}`));
  return dashboardState.get(key);
}

function clearDashboardCache(days) {
  const key = String(days);
  dashboardState.delete(key);
  requestCache.delete(`/api/dashboard?days=${encodeURIComponent(key)}`);
}

function prefetchInternalPage(url) {
  if (!url || url.origin !== window.location.origin || !url.pathname.startsWith('/static/') || !url.pathname.endsWith('.html')) return;
  if (document.head.querySelector(`link[rel="prefetch"][href="${url.pathname}"]`)) return;
  const link = document.createElement('link');
  link.rel = 'prefetch';
  link.href = `${url.pathname}${url.search}`;
  document.head.append(link);
}

function installNavigationMotion() {
  if (document.querySelector('#ax-navigation-motion')) return;
  const style = document.createElement('style');
  style.id = 'ax-navigation-motion';
  style.textContent = `
    @view-transition { navigation: auto; }
    ::view-transition-old(root), ::view-transition-new(root) { animation-duration: 200ms; }
    ::view-transition-old(root) { animation-name: ax-fade-out; }
    ::view-transition-new(root) { animation-name: ax-fade-in; }
    body { animation: ax-page-in 200ms ease-out both; }
    @keyframes ax-fade-out { to { opacity: 0; transform: translateY(-3px); } }
    @keyframes ax-fade-in { from { opacity: 0; transform: translateY(3px); } }
    @media (prefers-reduced-motion: reduce) {
      ::view-transition-old(root), ::view-transition-new(root), body { animation: none !important; }
    }
  `;
  document.head.append(style);
}

installNavigationMotion();

function setPageLoading(title = 'Loading dashboard', message = 'Preparing your workspace...') {
  const overlay = document.querySelector('#pageTransition');
  if (!overlay) return;
  document.querySelector('#pageTransitionTitle').textContent = title;
  document.querySelector('#pageTransitionMessage').textContent = message;
  overlay.hidden = false;
  overlay.classList.add('visible');
  document.body.classList.add('app-loading');
  document.body.classList.remove('app-ready');
}

function setPageReady() {
  const overlay = document.querySelector('#pageTransition');
  document.body.classList.remove('app-loading');
  document.body.classList.add('app-ready');
  if (!overlay) return;
  overlay.classList.remove('visible');
  overlay.addEventListener('transitionend', () => { overlay.hidden = true; }, { once: true });
}

window.AXPageTransition = { setPageLoading, setPageReady };

window.AX = {
  api: async function (url, options) {
    const method = String(options?.method || 'GET').toUpperCase();
    const cacheable = method === 'GET' && (url === '/api/auth/me' || url.startsWith('/api/dashboard?'));
    if (cacheable && requestCache.has(url)) return requestCache.get(url);
    const request = (async () => {
    try {
      const response = await fetch(url, { credentials: 'include', ...(options || {}) });
      if (response.status === 401) {
        throw Error('Authentication required');
      }
      if (!response.ok) {
        let detail = {};
        try { detail = await response.json(); } catch {}
        throw Error(detail.detail || `HTTP ${response.status}`);
      }
      return response.json();
    } catch (error) {
      throw error;
    }
    })();
    if (cacheable) requestCache.set(url, request);
    return request;
  },
  escapeHtml: function (value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[character]));
  },
  getUser,
  getDashboard,
  clearDashboardCache,
  toast: function (message, kind = 'info') {
    const element = document.createElement('div');
    element.className = `toast ${kind}`;
    element.textContent = message;
    document.body.append(element);
    setTimeout(() => element.remove(), 3500);
  },
  initShell: function (active) {
    const main = document.querySelector('main.shell');
    if (!main) return;
    const style = document.createElement('style');
    style.textContent = `
      .workspace-layout { display: grid; grid-template-columns: minmax(0,220px) minmax(0,1fr); width:100%; max-width:100%; min-height:100vh; overflow-x:hidden; }
      .workspace-rail { padding: 0 16px; border-right: 1px solid var(--line); background: rgba(7,16,25,.68); }
      .workspace-brand { display: flex; align-items: center; min-height: 72px; gap: 12px; font-weight: 700; padding: 0 10px; }
      .workspace-brand b { display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid var(--cyan); color: var(--cyan); }
      .workspace-label { font-size: .65rem; letter-spacing: .15em; color: #6d8190; padding: 0 10px; margin: 20px 0 8px; }
      .workspace-link { display: flex; gap: 10px; color: var(--muted); text-decoration: none; padding: 11px 10px; border-radius: 6px; font-size: .84rem; }
      .workspace-link:hover, .workspace-link.active { background: rgba(88,210,220,.1); color: var(--ink); }
      .workspace-main { display:flex; flex-direction:column; min-width: 0; height:100vh; overflow:hidden; }
      .workspace-main::-webkit-scrollbar { width:0; height:0; }
      .workspace-topbar { display: flex; flex-shrink:0; align-items: center; justify-content: space-between; min-width:0; min-height: 72px; padding: 0 34px; border-bottom: 1px solid var(--line); background: rgba(8,16,25,.62); color: var(--muted); font-size: .84rem; line-height: 1; visibility: hidden; }
      .workspace-topbar.is-ready { visibility: visible; animation: workspace-topbar-in 200ms ease-out both; }
      @keyframes workspace-topbar-in { from { opacity:0; transform:translateY(-3px); } to { opacity:1; transform:none; } }
      .workspace-topbar strong, .workspace-account { color: var(--ink); }
      .workspace-topbar > span:first-child { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .workspace-user { display:flex; align-items:center; gap:14px; white-space:nowrap; }
      .workspace-account { max-width:clamp(100px,20vw,220px); overflow:hidden; text-overflow:ellipsis; }
      .workspace-status { width:9px; height:9px; border-radius:50%; background:#7be0b5; box-shadow:0 0 12px #7be0b5; }
      .workspace-profile { position:relative; }
      .workspace-avatar { display:inline-flex; align-items:center; justify-content:center; width:34px; height:34px; padding:0; border:0; border-radius:50%; background:#b8e7e6; color:#09202a; font:inherit; font-weight:800; line-height:1; text-align:center; }
      .workspace-avatar:focus-visible,.workspace-profile-dropdown button:focus-visible { outline:2px solid var(--cyan); outline-offset:3px; }
      .workspace-profile-dropdown { position:absolute; right:0; top:calc(100% + 12px); z-index:20; width:240px; border:1px solid rgba(123,163,183,.3); border-radius:10px; background:rgba(16,28,40,.97); box-shadow:0 18px 48px rgba(0,0,0,.4); overflow:hidden; transform-origin:top right; }
      .workspace-profile-dropdown[hidden] { display:none; }
      .workspace-profile-heading { display:grid; gap:4px; padding:16px; }
      .workspace-profile-heading strong { color:var(--ink); font-size:.85rem; }
      .workspace-profile-heading span { color:var(--muted); font-size:.75rem; }
      .workspace-profile-divider { border-top:1px solid var(--line); }
      .workspace-profile-dropdown button { display:flex; gap:10px; width:100%; padding:12px 16px; border:0; border-radius:0; background:transparent; color:var(--muted); text-align:left; font:inherit; font-size:.8rem; }
      .workspace-profile-dropdown button:hover { background:rgba(88,210,220,.1); color:var(--ink); }
      .workspace-main > .shell { flex:1; min-height:0; overflow-y:auto; scrollbar-width:none; width: min(100%, 1400px); max-width:100%; min-width:0; margin: 0 auto; padding: 0 34px 56px; }
      .workspace-main > .shell::-webkit-scrollbar { width:0; height:0; }
      .workspace-main > .shell header { text-align: left; }
      @media (max-width: 800px) { .workspace-layout { grid-template-columns: minmax(0,1fr); } .workspace-rail { display: none; } .workspace-main > .shell { padding: 24px 18px 50px; } }
      @media (max-width: 560px) { .workspace-topbar { padding: 0 16px; gap:10px; } .workspace-user { gap:8px; } .workspace-account { max-width:145px; } }
    `;
    document.head.append(style);
    const layout = document.createElement('div');
    layout.className = 'workspace-layout';
    const rail = document.createElement('aside');
    rail.className = 'workspace-rail';
    rail.innerHTML = `
      <div class="workspace-brand"><b>AX</b><span>AccelerateX</span></div>
      <div class="workspace-label">OPERATIONS</div>
      <a class="workspace-link" href="/static/dashboard.html">▦ <span>Overview</span></a>
      <div class="workspace-label">WORKBENCHES</div>
      <a class="workspace-link ${active === 'validator' ? 'active' : ''}" href="/static/validator.html">✓ <span>Mapping Validator</span></a>
      <a class="workspace-link ${active === 'sqlgen' ? 'active' : ''}" href="/static/sqlgen.html">⌁ <span>SQL Generator</span></a>
      <a class="workspace-link ${active === 'dataforge' ? 'active' : ''}" href="/static/dataforge.html">◇ <span>Test Data Forge</span></a>
      <a class="workspace-link ${active === 'parity' ? 'active' : ''}" href="/static/parity.html">≋ <span>Prod Parity</span></a>
      `;
    const content = document.createElement('section');
    content.className = 'workspace-main';
    const titles = { validator: 'Mapping Validator', sqlgen: 'SQL Generator', parity: 'Prod Parity', dataforge: 'Test Data Forge' };
    const topbar = document.createElement('div');
    topbar.className = 'workspace-topbar';
    topbar.innerHTML = `<span>AccelerateX / <strong>${titles[active] || 'Workbench'}</strong></span><span class="workspace-user"><span class="workspace-account"></span><span class="workspace-status"></span><span class="workspace-profile"><button class="workspace-avatar" type="button" aria-label="Open profile menu" aria-haspopup="menu" aria-expanded="false"></button><span class="workspace-profile-dropdown" role="menu" hidden><span class="workspace-profile-heading"><strong class="workspace-profile-name"></strong><span>Signed in</span></span><span class="workspace-profile-divider"></span><button class="workspace-manage-account" type="button" role="menuitem">⚙ <span>Manage account</span></button><button class="workspace-sign-out" type="button" role="menuitem">↪ <span>Sign out</span></button></span></span></span>`;
    main.parentNode.insertBefore(layout, main);
    layout.append(rail, content);
    content.append(topbar, main);
    const applyWorkspaceUser = user => {
      const localPart = String(user.email || '').split('@')[0];
      const displayName = user.display_name || (localPart ? localPart.charAt(0).toUpperCase() + localPart.slice(1) : '');
      content.querySelector('.workspace-account').textContent = displayName;
      content.querySelector('.workspace-avatar').textContent = displayName.charAt(0).toUpperCase();
      content.querySelector('.workspace-profile-name').textContent = displayName;
      topbar.classList.add('is-ready');
    };
    try {
      const cachedUser = JSON.parse(sessionStorage.getItem('acceleratex-user') || 'null');
      if (cachedUser) applyWorkspaceUser(cachedUser);
    } catch {}
    getUser().then(applyWorkspaceUser).catch(() => { topbar.classList.add('is-ready'); });
    const profile = topbar.querySelector('.workspace-profile');
    const avatar = topbar.querySelector('.workspace-avatar');
    const dropdown = topbar.querySelector('.workspace-profile-dropdown');
    avatar.addEventListener('click', () => { dropdown.hidden = !dropdown.hidden; avatar.setAttribute('aria-expanded', String(!dropdown.hidden)); });
    topbar.querySelector('.workspace-manage-account').addEventListener('click', () => { window.location.assign('/static/dashboard.html?account=1'); });
    topbar.querySelector('.workspace-sign-out').addEventListener('click', () => AX.logout());
    document.addEventListener('click', event => { if (!profile.contains(event.target)) { dropdown.hidden = true; avatar.setAttribute('aria-expanded', 'false'); } });
  },
  logout: function () { try { sessionStorage.removeItem('acceleratex-user'); } catch {} setPageLoading('Signing out', 'Returning to sign in...'); window.location.assign('/api/auth/logout'); },
  onFileChosen: function (input, label) {
    input.addEventListener('change', () => { label.textContent = input.files[0]?.name || 'Choose a file'; });
  }
};

document.addEventListener('pointerover', event => {
  const link = event.target.closest('a[href]');
  if (link) prefetchInternalPage(new URL(link.href));
}, { passive: true });
document.addEventListener('focusin', event => {
  const link = event.target.closest('a[href]');
  if (link) prefetchInternalPage(new URL(link.href));
});

(function cleanDashboard() {
  if (!document.querySelector('.dashboard')) return;
  const breadcrumb = document.querySelector('.topbar > div:first-child');
  if (breadcrumb) breadcrumb.innerHTML = 'AccelerateX / <strong>Overview</strong>';
  const dashboardStyle = document.createElement('style');
  dashboardStyle.textContent = '.dashboard .topbar{display:flex;align-items:center;justify-content:space-between;min-height:72px;padding:0 34px;font-size:.84rem;line-height:1}.dashboard .top-actions{display:flex;align-items:center;gap:14px;font-size:.84rem;line-height:1;white-space:nowrap}.dashboard .account-name{font-weight:600}.dashboard .avatar{width:34px;height:34px}.throughput-bars{height:210px;display:flex;align-items:end;gap:4px;padding:8px 0 0}.throughput-bar{flex:1;min-width:3px;background:linear-gradient(to top,var(--cyan),#b8e7e6);border-radius:3px 3px 0 0;position:relative}.throughput-bar span{position:absolute;bottom:-22px;left:50%;transform:translateX(-50%);font-size:.58rem;color:var(--muted);white-space:nowrap}.throughput-empty{color:var(--muted);font-size:.8rem;padding-top:80px;text-align:center}';
  document.head.append(dashboardStyle);
  const dashboardRail = document.querySelector('.side-rail');
  const dashboardDataForge = dashboardRail?.querySelector('a[href="/static/dataforge.html"]');
  const dashboardParity = dashboardRail?.querySelector('a[href="/static/parity.html"]');
  if (dashboardDataForge && dashboardParity) dashboardRail.insertBefore(dashboardDataForge, dashboardParity);
  document.querySelectorAll('.kpi-trend').forEach(node => { node.textContent = ''; });
  const activity = document.querySelector('#activityList');
  if (activity && !activity.children.length) activity.textContent = 'No recent activities';
  const flowModal = document.querySelector('#flowModal');
  const flowTitle = document.querySelector('#flowModalTitle');
  const flowDescription = document.querySelector('#flowModalDescription');
  const flowSteps = document.querySelector('#flowModalSteps');
  const flowModalMark = document.querySelector('#flowModalMark');
  const flows = {
    validator: { mark: '✓', title: 'Mapping Validator', description: 'The mapping sheet is transformed into governed SQL with automated fixes and advisory review.', steps: ['Excel mapping sheet', 'Deterministic SQL Generator', 'SQL fixes, parameter resolution, join validation, audit', 'Generated SQL with TODOs where needed', 'Collect TODOs and warnings', 'Retrieve matching approved SQL rules', 'Send TODOs + matching rules to Ollama', 'LLM advisory result'] },
    sqlgen: { mark: '⌁', title: 'SQL Generator', description: 'The generator turns source SQL and mapping decisions into a deterministic, reviewable target artifact.', steps: ['Load the source SQL and mapping sheet', 'Parse parameters, tables, columns, and joins', 'Prune unused columns and validate join paths', 'Resolve parameters and repair SQL syntax', 'Generate deterministic target SQL', 'Audit the result and surface TODOs or warnings'] },
    parity: { mark: '≋', title: 'Prod Parity', description: 'Production and generated SQL are normalized and compared so release differences can be reviewed quickly.', steps: ['Upload the generated SQL and production SQL', 'Normalize formatting and comparable SQL structure', 'Compare statements, joins, filters, and selected columns', 'Classify additions, removals, and changed logic', 'Calculate parity status and risk signals', 'Open the traceable comparison report'] },
    dataforge: { mark: '◇', title: 'Test Data Forge', description: 'A production sample is profiled and converted into scalable synthetic fixtures for testing.', steps: ['Upload a representative sample CSV', 'Profile columns, types, nulls, ranges, and patterns', 'Choose primary-key attributes and generation settings', 'Build a generation plan from the observed patterns', 'Generate synthetic records in chunks', 'Validate the output and prepare downloadable CSV files'] }
  };
  const closeFlowModal = () => { if (!flowModal) return; flowModal.hidden = true; };
  const openFlowModal = workbench => {
    const flow = flows[workbench.dataset.flow];
    if (!flow || !flowModal) return;
    flowModalMark.textContent = flow.mark;
    flowTitle.textContent = flow.title;
    flowDescription.textContent = flow.description;
    flowSteps.innerHTML = flow.steps.map(step => `<li>${AX.escapeHtml(step)}</li>`).join('');
    flowModal.hidden = false;
    document.querySelector('#flowModalClose')?.focus();
  };
  document.querySelectorAll('.workbench[data-flow]').forEach(workbench => {
    workbench.addEventListener('click', () => openFlowModal(workbench));
    workbench.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openFlowModal(workbench); } });
  });
  document.querySelector('#flowModalClose')?.addEventListener('click', closeFlowModal);
  flowModal?.addEventListener('click', event => { if (event.target === flowModal) closeFlowModal(); });
  const applyUser = user => {
    const localPart = String(user.email || '').split('@')[0];
    const name = user.display_name || (localPart ? localPart.charAt(0).toUpperCase() + localPart.slice(1) : 'User');
    const account = document.querySelector('#accountName');
    const avatar = document.querySelector('#avatar');
    if (account) account.textContent = name;
    if (avatar) avatar.textContent = name.charAt(0).toUpperCase();
    const profileName = document.querySelector('#profileName');
    const accountUsername = document.querySelector('#accountUsername');
    if (profileName) profileName.textContent = name;
    if (accountUsername) accountUsername.textContent = name;
    const hour = Number(new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Kolkata', hour: 'numeric', hour12: false }).format(new Date()));
    const period = hour >= 6 && hour < 12 ? 'Good Morning' : hour >= 12 && hour < 15.5 ? 'Good Afternoon' : 'Good Evening';
    const greeting = document.querySelector('#greeting');
    if (greeting) greeting.textContent = `Hi ${name}, ${period}!`;
  };
  const statusRows = document.querySelector('#systemStatusRows');
  const statusChecked = document.querySelector('#systemStatusChecked');
  const statusRefresh = document.querySelector('#systemStatusRefresh');
  const statusDefinitions = [
    ['fastapi', 'FastAPI', 'Healthy'], ['model', 'Qwen 2.5', 'Ready'],
    ['embedding_model', 'BGE-M3', 'Ready'], ['rag', 'RAG', 'Ready'], ['chromadb', 'ChromaDB', 'Connected']
  ];
  const statusLabel = value => ({ healthy: 'Healthy', ready: 'Ready', connected: 'Connected', loading: 'Loading', unavailable: 'Unavailable', error: 'Error' }[String(value || '').toLowerCase()] || 'Unavailable');
  const renderSystemStatus = data => {
    if (!statusRows) return;
    statusRows.innerHTML = statusDefinitions.map(([key, name, fallback]) => {
      const state = statusLabel(data?.[key]?.status || fallback.toLowerCase());
      return `<div class="status-row${state === 'Unavailable' || state === 'Error' ? ' status-error' : ''}"><span class="status-service">${AX.escapeHtml(name)}</span><span class="status-state">${state}</span></div>`;
    }).join('');
    statusChecked.textContent = `Last checked: ${new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Kolkata', hour: 'numeric', minute: '2-digit', second: '2-digit' }).format(new Date())}`;
  };
  let statusRefreshing = false;
  const refreshSystemStatus = async () => {
    if (!statusRefresh || statusRefreshing) return;
    statusRefreshing = true;
    statusRefresh.disabled = true;
    statusRefresh.classList.add('is-refreshing');
    try { renderSystemStatus(await AX.api('/api/system/status')); } catch { renderSystemStatus({ fastapi: { status: 'error' }, model: { status: 'unavailable' }, embedding_model: { status: 'unavailable' }, rag: { status: 'unavailable' }, chromadb: { status: 'unavailable' } }); }
    statusRefresh.classList.remove('is-refreshing');
    statusRefresh.disabled = false;
    statusRefreshing = false;
  };
  statusRefresh?.addEventListener('click', refreshSystemStatus);
  refreshSystemStatus();
  const avatar = document.querySelector('#avatar');
  const dropdown = document.querySelector('#profileDropdown');
  const modal = document.querySelector('#accountModal');
  document.querySelectorAll('[data-password-toggle]').forEach(toggle => toggle.addEventListener('click', () => { const input = document.querySelector(`#${toggle.dataset.passwordToggle}`); const visible = input.type === 'text'; input.type = visible ? 'password' : 'text'; toggle.textContent = visible ? 'Show' : 'Hide'; toggle.setAttribute('aria-label', `${visible ? 'Show' : 'Hide'} password`); }));
  const closeDropdown = () => { if (!dropdown || dropdown.hidden) return; dropdown.hidden = true; avatar?.setAttribute('aria-expanded', 'false'); };
  const closeModal = () => { if (modal) modal.hidden = true; document.querySelector('#passwordForm')?.reset(); document.querySelector('#passwordError').textContent = ''; avatar?.focus(); };
  avatar?.addEventListener('click', () => { dropdown.hidden = !dropdown.hidden; avatar.setAttribute('aria-expanded', String(!dropdown.hidden)); if (!dropdown.hidden) dropdown.querySelector('button')?.focus(); });
  document.querySelector('#manageAccount')?.addEventListener('click', () => { closeDropdown(); modal.hidden = false; document.querySelector('#currentPassword')?.focus(); });
  document.querySelector('#signOut')?.addEventListener('click', () => AX.logout());
  document.querySelector('#accountModalClose')?.addEventListener('click', closeModal);
  document.querySelector('#accountCancel')?.addEventListener('click', closeModal);
  modal?.addEventListener('click', event => { if (event.target === modal) closeModal(); });
  if (new URLSearchParams(window.location.search).get('account') === '1' && modal) {
    modal.hidden = false;
    document.querySelector('#currentPassword')?.focus();
  }
  document.addEventListener('click', event => { if (!event.target.closest('.profile-menu')) closeDropdown(); });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (flowModal && !flowModal.hidden) closeFlowModal(); else if (modal && !modal.hidden) closeModal(); else closeDropdown();
  });
  document.querySelector('#passwordForm')?.addEventListener('submit', async event => {
    event.preventDefault();
    const error = document.querySelector('#passwordError');
    const button = document.querySelector('#changePassword');
    const newPassword = document.querySelector('#newPassword').value;
    error.textContent = newPassword !== document.querySelector('#confirmPassword').value ? 'New passwords do not match' : '';
    if (error.textContent) return;
    button.disabled = true;
    try { await AX.api('/api/auth/change-password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ current_password: document.querySelector('#currentPassword').value, new_password: newPassword }) }); closeModal(); AX.toast('Password changed successfully', 'success'); }
    catch (exception) { error.textContent = exception.message; }
    finally { button.disabled = false; }
  });
  const labels = ['Mapping Sheet Validated', 'Mapping to SQL Generated', 'Synthetic Data Generated', 'Production Parity Validated'];
  document.querySelectorAll('.kpi-label').forEach((node, index) => { node.textContent = labels[index] || node.textContent; });
  const range = document.querySelector('#dateRange');
  if (range) {
    range.innerHTML = '<option value="current">Current day</option><option value="5" selected>Last 5 days</option><option value="10">Last 10 days</option>';
    const chart = document.querySelector('.fake-chart');
    const cards = [...document.querySelectorAll('.kpi-value')];
    const parityCard = cards[3];
    if (parityCard) parityCard.textContent = '0';
    const renderDashboard = async () => {
      const data = await getDashboard(range.value);
      const keys = ['validated_mappings', 'sql_artifacts', 'active_workspaces', 'parity_passed'];
      cards.forEach((card, index) => { card.textContent = Number(data.metrics[keys[index]] || 0).toLocaleString(); });
      if (activity) {
        activity.className = data.activities.length ? '' : 'empty-state';
        activity.innerHTML = data.activities.length ? data.activities.map(item => `<div class="activity"><span class="activity-dot"></span><div><b>${AX.escapeHtml(item.title)}</b><p>${AX.escapeHtml(item.detail)} · ${AX.escapeHtml(item.created_at)}</p></div></div>`).join('') : 'No recent activities';
      }
      if (chart) {
        const values = data.throughput || [];
        const peak = Math.max(...values.map(item => Number(item.total)), 1);
        chart.innerHTML = values.length ? `<div class="throughput-bars">${values.map(item => `<div class="throughput-bar" style="height:${Math.max(4, Number(item.total) / peak * 100)}%"><span>${AX.escapeHtml(item.label || item.day.slice(5))}</span></div>`).join('')}</div>` : '<div class="throughput-empty">No activity in the selected period</div>';
      }
    };
    range.addEventListener('change', () => {
      clearDashboardCache(range.value);
      renderDashboard().catch(showFailure);
    });
    const status = document.querySelector('#dashboardStatus');
    const showFailure = () => {
      status.hidden = false;
      status.innerHTML = '<span>Unable to load dashboard data.</span><button type="button" id="dashboardRetry">Retry</button>';
      status.querySelector('#dashboardRetry').addEventListener('click', () => {
        status.hidden = true;
        clearDashboardCache(range.value);
        renderDashboard().catch(showFailure);
      });
    };
    const initialize = async () => {
      try {
        const [user] = await Promise.all([getUser(), renderDashboard()]);
        applyUser(user);
        window.AXPageTransition?.setPageReady();
      } catch (error) {
        if (error.message === 'Authentication required') {
          window.AXPageTransition?.setPageLoading('Your session has expired.', 'Redirecting to login...');
          window.requestAnimationFrame(() => window.location.replace('/'));
          return;
        }
        showFailure();
        window.AXPageTransition?.setPageReady();
      }
    };
    initialize();
  }
})();
