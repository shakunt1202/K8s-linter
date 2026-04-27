/**
 * tokens.js — AI provider API-key management
 * Keys stored per-provider in localStorage under k8s_linter_tok_<provider>_<field>
 */

'use strict';

const PROVIDER_FIELDS = {
  openai:    ['key', 'org', 'model'],
  anthropic: ['key', 'model'],
  azure:     ['key', 'endpoint', 'deploy', 'version'],
  custom:    ['url', 'key', 'model'],
};

function tokKey(p, k) { return `k8s_linter_tok_${p}_${k}`; }

function loadTokenFields() {
  for (const [p, keys] of Object.entries(PROVIDER_FIELDS)) {
    for (const k of keys) {
      const el = document.getElementById(`tok-${p}-${k}`);
      if (el) el.value = localStorage.getItem(tokKey(p, k)) || el.defaultValue || '';
    }
  }
}

function saveTokens() {
  for (const [p, keys] of Object.entries(PROVIDER_FIELDS)) {
    for (const k of keys) {
      const el = document.getElementById(`tok-${p}-${k}`);
      if (!el) continue;
      if (el.value) localStorage.setItem(tokKey(p, k), el.value);
      else          localStorage.removeItem(tokKey(p, k));
    }
  }
  window.closeModal?.('modal-tokens');
  window.__addLog?.('info', 'AI API keys saved');
}

function getProviderCredentials(provider) {
  const g = k => localStorage.getItem(tokKey(provider, k)) || '';
  switch (provider) {
    case 'openai':    return { provider_api_key: g('key'), provider_base_url: 'https://api.openai.com/v1' };
    case 'anthropic': return { provider_api_key: g('key'), provider_base_url: 'https://api.anthropic.com' };
    case 'azure':     return { provider_api_key: g('key'), provider_base_url: g('endpoint') };
    case 'custom':    return { provider_api_key: g('key'), provider_base_url: g('url') };
    default:          return { provider_api_key: '', provider_base_url: '' };
  }
}

function setProviderTab(p) {
  document.querySelectorAll('#provider-tabs .ptab').forEach(el => {
    el.classList.toggle('active', el.dataset.p === p);
  });
  ['openai', 'anthropic', 'azure', 'custom'].forEach(id => {
    const el = document.getElementById('tok-' + id);
    if (el) el.style.display = id === p ? 'block' : 'none';
  });
}

function toggleTokenVisibility(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.type = el.type === 'password' ? 'text' : 'password';
}

window.Tokens = { loadTokenFields, saveTokens, getProviderCredentials, setProviderTab, toggleTokenVisibility };
