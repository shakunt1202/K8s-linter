/**
 * audit.js — Run audit, stop audit, SSE stream parsing, server health checks
 */

'use strict';

let isRunning        = false;
let abortController  = null;
let fakeP            = 0;
let ticker           = null;

/* ── Helpers ────────────────────────────────────────────────────────── */
function getApiBase()   { return (document.getElementById('api-base')?.value   || 'http://localhost:8000').replace(/\/$/, ''); }
function getOllamaUrl() { return document.getElementById('ollama-url')?.value  || 'http://localhost:11434'; }
function getModel()     { return document.getElementById('model-select')?.value || 'llama3'; }

function ts() { return new Date().toLocaleTimeString('en-GB', { hour12: false }); }

function addLog(type, msg) {
  const area = document.getElementById('log-area');
  if (!area) return;
  const el  = document.createElement('div');
  el.className = 'log-entry ' + type;
  const tags = { pass:'PASS', fail:'FAIL', warn:'WARN', info:'INFO', rule:'RULE', resource:'RES ' };
  el.innerHTML = `<span class="log-ts">${ts()}</span><span class="log-tag">${tags[type]||'INFO'}</span><span class="log-msg">${esc(msg)}</span>`;
  area.appendChild(el);
  area.scrollTop = area.scrollHeight;
}
window.__addLog = addLog;  // expose for other modules

function classifyLog(text) {
  if (/^CHECK\s/.test(text))    return 'rule';
  if (/^RULE\s/.test(text))     return 'rule';
  if (/^RESOURCE\s/.test(text)) return 'resource';
  if (/^FETCHED\s/.test(text))  return 'resource';
  if (/^PROFILE\s/.test(text))  return 'info';
  if (/^RULES\s/.test(text))    return 'info';
  if (/^ENGINE\s/.test(text))   return 'info';
  if (/^COMPLETE\s/.test(text)) return 'pass';
  if (/^AI-REM\s/.test(text))   return 'info';
  if (/^AI\s/.test(text))       return 'info';
  if (/^\[/.test(text))         return 'info';
  if (/^PASS\s/.test(text))     return 'pass';
  if (/^FAIL\s/.test(text))     return 'fail';
  if (/^WARN\s/.test(text))     return 'warn';
  if (/✔|PASS/.test(text))      return 'pass';
  if (/✖|FAIL/.test(text))      return 'fail';
  return 'info';
}

function setProgress(pct, lbl) {
  const fill = document.getElementById('prog-fill');
  const pctEl = document.getElementById('prog-pct');
  const lblEl = document.getElementById('prog-lbl');
  if (fill)  fill.style.width = pct + '%';
  if (pctEl) pctEl.textContent = pct > 0 ? Math.round(pct) + '%' : '';
  if (lbl && lblEl) lblEl.textContent = String(lbl).replace(/[^\x20-\x7E]/g, '').trim().slice(0, 90);
}

function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

/* ── Server / namespace / model checks ─────────────────────────────── */

async function checkServer() {
  try {
    const r = await fetch(getApiBase() + '/health', { signal: AbortSignal.timeout(3000) });
    document.getElementById('srv-dot').className  = 'dot' + (r.ok ? ' alive' : '');
    document.getElementById('srv-txt').textContent = r.ok ? 'online' : 'error';
  } catch {
    document.getElementById('srv-dot').className   = 'dot';
    document.getElementById('srv-txt').textContent  = 'offline';
  }
}

async function loadNamespaces() {
  try {
    const r = await fetch(getApiBase() + '/api/namespaces');
    if (!r.ok) return;
    const d   = await r.json();
    const sel = document.getElementById('ns-select');
    if (sel) sel.innerHTML = d.namespaces.map(n => `<option value="${n}">${n}</option>`).join('');
  } catch {
    const sel = document.getElementById('ns-select');
    if (sel && !sel.options.length) sel.innerHTML = '<option value="default">default</option>';
  }
}

async function loadModels() {
  try {
    const r = await fetch(getOllamaUrl() + '/api/tags', { signal: AbortSignal.timeout(4000) });
    if (!r.ok) return;
    const d      = await r.json();
    const models = (d.models || []).map(m => m.name);
    if (!models.length) return;
    const sel = document.getElementById('model-select');
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = models.map(m => `<option value="${m}"${m===cur?' selected':''}>${m}</option>`).join('');
    addLog('info', `Loaded ${models.length} model(s) from Ollama`);
  } catch { addLog('warn', 'Could not fetch Ollama models'); }
}

/* ── Stop ───────────────────────────────────────────────────────────── */

function stopAudit() {
  if (abortController) abortController.abort();
  clearInterval(ticker);
  setProgress(0, 'Stopped by user');
  addLog('warn', 'Audit stopped by user');
  _resetButtons();
  isRunning = false;
}

function _resetButtons() {
  const btn = document.getElementById('run-btn');
  if (btn) { btn.disabled = false; btn.className = 'run-btn'; }
  const inner = document.getElementById('btn-inner');
  if (inner) inner.innerHTML = '&#9654;&nbsp; Run Audit';
  const stop = document.getElementById('stop-btn');
  if (stop) stop.classList.remove('visible');
}

/* ── Run audit ──────────────────────────────────────────────────────── */

async function runLint() {
  if (isRunning) return;
  isRunning = true;
  abortController = new AbortController();

  const btn   = document.getElementById('run-btn');
  const inner = document.getElementById('btn-inner');
  const stop  = document.getElementById('stop-btn');
  if (btn)   { btn.disabled = true; btn.className = 'run-btn running'; }
  if (inner) inner.innerHTML = '<span class="spinner"></span>&nbsp; Running…';
  if (stop)  stop.classList.add('visible');

  /* clear display */
  const logArea = document.getElementById('log-area');
  const results = document.getElementById('results');
  if (logArea) logArea.innerHTML = '';
  if (results) results.innerHTML = '';
  document.getElementById('ai-bar')?.setAttribute('class', 'ai-bar');
  document.getElementById('gate-bar')?.setAttribute('class', 'gate-bar');

  const env     = window.UI.getCurrentEnv();
  const ns      = document.getElementById('ns-select')?.value      || 'default';
  const prof    = document.getElementById('profile-select')?.value  || 'custom';
  const aiProv  = document.getElementById('ai-provider-select')?.value || 'ollama';
  const aiOn    = document.getElementById('toggle-ai')?.classList.contains('on') ?? true;
  const creds   = window.Tokens.getProviderCredentials(aiProv);

  addLog('info', `Starting — env=${env} ns=${ns} profile=${prof} model=${getModel()} provider=${aiProv} ai=${aiOn}`);

  fakeP = 0;
  ticker = setInterval(() => { fakeP = Math.min(fakeP + 0.9, 88); setProgress(fakeP); }, 700);

  const payload = {
    source: 'cluster', namespace: ns, manifest_path: './manifests',
    profile: prof,
    provider: aiProv === 'ollama' ? 'ollama' : aiProv,
    model: getModel(),
    ollama_url: getOllamaUrl(),
    provider_base_url: creds.provider_base_url,
    provider_api_key:  creds.provider_api_key,
    ai_remediation: aiOn,
  };

  try {
    const resp = await fetch(getApiBase() + '/api/lint/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: abortController.signal,
    });
    if (!resp.ok) {
      const e = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(e.detail || resp.statusText);
    }

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();

      for (const part of parts) {
        if (!part.trim()) continue;
        let evType = 'log', dataLine = '';
        for (const line of part.split('\n')) {
          if (line.startsWith('event: ')) evType    = line.slice(7).trim();
          if (line.startsWith('data: '))  dataLine  = line.slice(6).trim();
        }
        if (!dataLine) continue;
        let text; try { text = JSON.parse(dataLine); } catch { text = dataLine; }

        if (evType === 'log') {
          addLog(classifyLog(text), text);
          setProgress(fakeP, text);

        } else if (evType === 'result') {
          clearInterval(ticker);
          const data = typeof text === 'string' ? JSON.parse(text) : text;

          window.UI.storeEnvResult(env, data);
          setProgress(100, 'Audit complete');
          window.UI.updateScores(data);

          if (data.ai_summary) {
            const aiText = document.getElementById('ai-text');
            const aiBar  = document.getElementById('ai-bar');
            if (aiText) aiText.textContent = data.ai_summary;
            if (aiBar)  aiBar.className = 'ai-bar show';
          }
          window.UI.showGate(data);
          window.UI.renderFindings();
          addLog('pass', `Complete — ${(data.findings||[]).length} findings, score ${Math.round(data.score||0)}% [${data.grade}]`);

        } else if (evType === 'error') {
          clearInterval(ticker);
          addLog('fail', 'Error: ' + text);
          setProgress(0, 'Error');
        }
      }
    }
  } catch (e) {
    clearInterval(ticker);
    if (e.name !== 'AbortError') {
      setProgress(0, 'Connection error');
      addLog('fail', 'API error: ' + e.message);
      addLog('warn', 'Is uvicorn running? (uvicorn server:app --port 8000)');
    }
  }

  if (inner) inner.innerHTML = '&#9654;&nbsp; Re-run';
  _resetButtons();
  isRunning = false;
}

window.Audit = { runLint, stopAudit, checkServer, loadNamespaces, loadModels, addLog };
