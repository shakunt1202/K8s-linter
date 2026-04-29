/**
 * ui.js — Findings rendering, score display, tabs, filters, env state
 */
const STORAGE_KEY = 'k8s-linter-ui';

function saveUIState() {
  const state = {
    namespace: document.getElementById('ns-select')?.value,
    ollamaUrl: document.getElementById('ollama-url')?.value,
    model: document.getElementById('model-select')?.value,
    provider: document.getElementById('ai-provider-select')?.value,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function loadUIState() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return;

  const state = JSON.parse(raw);

  if (state.namespace)
    document.getElementById('ns-select').value = state.namespace;

  if (state.ollamaUrl)
    document.getElementById('ollama-url').value = state.ollamaUrl;

  if (state.model)
    document.getElementById('model-select').value = state.model;

  if (state.provider)
    document.getElementById('ai-provider-select').value = state.provider;
}


'use strict';

const CAT_MAP = {
  security: 'security', 'pod-security': 'security',
  reliability: 'reliability', networking: 'networking',
  rbac: 'rbac', general: 'rbac',
  resources: 'resource', resource: 'resource', secrets: 'security',
};
const CAT_LABELS = {
  security: 'Security', reliability: 'Reliability',
  networking: 'Networking', rbac: 'RBAC & IAM', resource: 'Resources',
};

/* Per-environment isolated state */
const envState = {
  production:  { findings: [], scores: null, aiSummary: '', gateData: null, hasData: false },
  staging:     { findings: [], scores: null, aiSummary: '', gateData: null, hasData: false },
  development: { findings: [], scores: null, aiSummary: '', gateData: null, hasData: false },
};

let currentTab    = 'all';
let currentFilter = 'all';
let currentEnv    = 'production';

function setTab(t) {
  currentTab = t;
  document.querySelectorAll('.tab').forEach(el => el.classList.toggle('active', el.dataset.tab === t));
  renderFindings();
}

function setFilter(f) {
  currentFilter = f;
  document.querySelectorAll('.fchip').forEach(el => el.classList.toggle('active', el.dataset.f === f));
  renderFindings();
}

function setEnv(e) {
  currentEnv = e;

  /* pill styles */
  ['prod', 'stage', 'dev'].forEach(k => {
    const el = document.getElementById('pill-' + k);
    if (el) el.className = 'env-pill';
  });
  const m = { production: 'prod', staging: 'stage', development: 'dev' };
  const pill = document.getElementById('pill-' + m[e]);
  if (pill) pill.className = 'env-pill active-' + m[e];

  /* env badge in header */
  const badgeCls = { production: 'prod', staging: 'stage', development: 'dev' };
  const envEl = document.getElementById('sc-env');
  if (envEl) envEl.innerHTML = `<span class="env-badge ${badgeCls[e]}">${e.slice(0,4).toUpperCase()}</span>`;

  const st = envState[e];
  if (st.hasData) {
    updateScores(st.scores);
    const aiBar  = document.getElementById('ai-bar');
    const aiText = document.getElementById('ai-text');
    if (aiBar && aiText) {
      if (st.aiSummary) { aiText.textContent = st.aiSummary; aiBar.className = 'ai-bar show'; }
      else              { aiBar.className = 'ai-bar'; }
    }
    if (st.gateData) showGate(st.gateData);
    else { const g = document.getElementById('gate-bar'); if (g) g.className = 'gate-bar'; }
  } else {
    /* blank scores for empty environments */
    ['sc-score','sc-grade','sc-pass','sc-fail','sc-warn','sc-resources'].forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = '—';
      el.className = 'sm-val cyan';
    });
    const aiBar = document.getElementById('ai-bar');
    const gBar  = document.getElementById('gate-bar');
    if (aiBar) aiBar.className = 'ai-bar';
    if (gBar)  gBar.className  = 'gate-bar';
  }
  renderFindings();
}

function storeEnvResult(env, data) {
  envState[env].findings   = data.findings || [];
  envState[env].scores     = data;
  envState[env].aiSummary  = data.ai_summary || '';
  envState[env].gateData   = data;
  envState[env].hasData    = true;
}

function updateScores(data) {
  if (!data) return;
  const s  = data.summary || {};
  const sc = Math.round(data.score || 0);

  const scoreEl = document.getElementById('sc-score');
  if (scoreEl) { scoreEl.textContent = sc + '%'; scoreEl.className = 'sm-val ' + (sc >= 80 ? 'green' : sc >= 60 ? 'amber' : 'red'); }

  const grEl = document.getElementById('sc-grade');
  if (grEl) { grEl.textContent = data.grade || '—'; grEl.className = 'sm-val ' + (['A','B'].includes(data.grade) ? 'green' : data.grade === 'C' ? 'amber' : 'red'); }

  const pass = document.getElementById('sc-pass'); if (pass) pass.textContent = s.pass ?? 0;
  const fail = document.getElementById('sc-fail'); if (fail) fail.textContent = s.fail ?? 0;
  const warn = document.getElementById('sc-warn'); if (warn) warn.textContent = s.warn ?? 0;
  const res  = document.getElementById('sc-resources'); if (res) res.textContent = data.resources_scanned || '—';
}

function showGate(data) {
  const gate = document.getElementById('gate-select')?.value || 'high';
  const sr   = { critical: 0, high: 1, medium: 2, low: 3 };
  const gIdx = sr[gate] ?? 1;
  const blocked = (data.findings || []).filter(f => f.status === 'fail' && (sr[f.severity] ?? 9) <= gIdx);
  const el = document.getElementById('gate-bar');
  if (!el) return;
  if (blocked.length) { el.textContent = `CI gate FAILED — ${blocked.length} blocking finding(s) at or above "${gate}"`; el.className = 'gate-bar fail-gate'; }
  else                { el.textContent = `CI gate PASSED — no blocking findings at or above "${gate}"`; el.className = 'gate-bar pass-gate'; }
}

function renderFindings() {
  const area     = document.getElementById('results');
  if (!area) return;
  area.innerHTML = '';
  const findings = envState[currentEnv].findings;
  const cats     = currentTab === 'all' ? ['security','reliability','networking','rbac','resource'] : [currentTab];
  let total = 0;

  cats.forEach(cat => {
    let cf = findings.filter(f => (CAT_MAP[f.category] || 'resource') === cat);
    if (currentFilter !== 'all') cf = cf.filter(f => f.status === currentFilter);
    if (!cf.length) return;

    const pass = cf.filter(f => f.status === 'pass').length;
    const fail = cf.filter(f => f.status === 'fail').length;
    const warn = cf.filter(f => f.status === 'warn').length;

    const block = document.createElement('div');
    block.className = 'cat-block';

    const sr = { critical: 0, high: 1, medium: 2, low: 3 };
    cf.sort((a,b) => {
      if (a.status === 'fail' && b.status !== 'fail') return -1;
      if (b.status === 'fail' && a.status !== 'fail') return  1;
      return (sr[a.severity] ?? 9) - (sr[b.severity] ?? 9);
    });

    block.innerHTML = `<div class="cat-head"><span class="cat-name">${CAT_LABELS[cat]||cat}</span><div class="cat-counts"><span style="color:var(--green)">${pass}p</span><span style="color:var(--red)">${fail}f</span><span style="color:var(--amber)">${warn}w</span></div></div>`;

    cf.forEach((f, idx) => {
      const uid   = `fd-${(f.rule_id||idx)}-${(f.resource_kind||'')}-${(f.resource_name||'').replace(/[^a-z0-9]/gi,'-')}-${idx}`;
      const item  = document.createElement('div');
      item.className = `finding status-${f.status}`;
      const detail   = f.detail || '';
      const desc     = detail.slice(0, 110) + (detail.length > 110 ? '…' : '');
      const remAI    = f.remediation_ai     ? `<div class="d-sec"><div class="d-ttl">AI Remediation</div><div class="d-ai">${esc(f.remediation_ai)}</div></div>` : '';
      const remSt    = f.remediation_static ? `<div class="d-sec"><div class="d-ttl">Static Hint</div><div class="d-body">${esc(f.remediation_static)}</div></div>` : '';
      const detTxt   = detail               ? `<div class="d-sec"><div class="d-ttl">Detail</div><div class="d-body">${esc(detail)}</div></div>` : '';
      const resLine  = `<div class="d-sec"><div class="d-ttl">Resource</div><div class="d-body" style="font-family:'Geist Mono',monospace;color:var(--accent)">${esc((f.resource_kind||'?')+'/'+( f.resource_name||'?'))}<span style="color:var(--t3);margin-left:10px">ns:${esc(f.namespace||'default')}</span></div></div>`;

      item.innerHTML = `
        <div class="s-icon ${f.status}">${f.status==='pass'?'✓':f.status==='fail'?'✕':f.status==='warn'?'!':'–'}</div>
        <div class="f-body">
          <div class="f-name">${esc(f.rule_name||f.rule_id||'—')}</div>
          <div class="f-meta"><span class="f-res">${esc((f.resource_kind||'')+'/'+( f.resource_name||''))}</span><span style="color:var(--t4)">${esc(f.namespace||'')}</span></div>
          <div class="f-desc">${esc(desc)}</div>
          <div class="f-detail" id="${uid}">${remAI}${remSt}${detTxt}${resLine}</div>
        </div>
        <span class="sev-pill ${f.severity||'low'}">${f.severity||'low'}</span>`;

      item.addEventListener('click', () => {
        const d = document.getElementById(uid);
        item.classList.toggle('expanded', d.classList.toggle('show'));
      });
      block.appendChild(item);
      total++;
    });
    area.appendChild(block);
  });

  if (!total) {
    area.innerHTML = `<div class="empty-state"><div class="empty-glyph">&#9671;</div><div>${findings.length ? 'No findings match current filter.' : 'Press Run Audit to begin.'}</div></div>`;
  }
}

function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

window.UI = { setTab, setFilter, setEnv, storeEnvResult, updateScores, showGate, renderFindings, getCurrentEnv: () => currentEnv, getEnvState: () => envState };
