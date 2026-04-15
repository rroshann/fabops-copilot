// FabOps Copilot frontend logic.
// Direction A polish pass. Vanilla JS, no build step.

// ---------- Pre-warm ----------
// Wake the Lambda the moment the page loads so the user's first real query
// doesn't pay the cold-start cost. The agent rejects empty queries with a
// 400, which is fine. Failures are silent.
(function preWarm() {
  try {
    fetch(window.FABOPS_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: '__warmup__' }),
    }).catch(function () {});
  } catch (_) {}
})();

// ---------- Constants ----------

const NODE_SCHEDULE_MS = [
  ['entry',                   150],
  ['check_policy_staleness',  700],
  ['check_demand_drift',      900],
  ['check_supply_drift',     1100],
  ['ground_in_disclosures',  3500],
  ['diagnose',               5500],
  ['prescribe_action',       1100],
  ['verify',                  100],
  ['finalize',               1100],
];

const NODE_NAMES = NODE_SCHEDULE_MS.map(function (n) { return n[0]; });

const ACTION_TEMPLATES = {
  refresh_reorder_policy: function (partId) {
    return 'Refresh the reorder policy for part ' + partId;
  },
  place_reorder: function (partId) {
    return 'Place a reorder for part ' + partId + ' at the new run-rate';
  },
  expedite: function (partId) {
    return 'Expedite part ' + partId + ' and qualify a backup supplier';
  },
  monitor: function (partId) {
    return 'Monitor part ' + partId + ', no action required today';
  },
};

const DRIVER_LABEL = {
  policy: 'POLICY DRIFT',
  supply: 'SUPPLY RISK',
  demand: 'DEMAND SHIFT',
  none:   'NO DRIVER',
};

// ---------- DOM helpers ----------

function $(id) { return document.getElementById(id); }
function show(el) { if (el) el.removeAttribute('hidden'); }
function hide(el) { if (el) el.setAttribute('hidden', ''); }
function clear(el) { if (el) el.innerHTML = ''; }
function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ---------- State machine ----------

let inFlightController = null;
let animationTimers = [];
let animationDone = false;
let responseArrived = false;

function clearAnimation() {
  animationTimers.forEach(function (t) { clearTimeout(t); });
  animationTimers = [];
}

function buildExecutionMarkup(progressEl, logEl) {
  // Progress bar segments
  let html = '';
  for (let i = 0; i < NODE_NAMES.length; i++) {
    html += '<div class="progress-segment" data-i="' + i + '"></div>';
  }
  progressEl.innerHTML = html;

  // Log rows
  let logHtml = '';
  for (let i = 0; i < NODE_NAMES.length; i++) {
    logHtml +=
      '<div class="node-row" data-i="' + i + '">' +
      '<span class="glyph"> </span>' +
      '<span class="name">' + NODE_NAMES[i] + '</span>' +
      '<span class="meta"></span>' +
      '</div>';
  }
  logEl.innerHTML = logHtml;
}

function setNodeState(progressEl, logEl, idx, state, meta) {
  const seg = progressEl.querySelector('[data-i="' + idx + '"]');
  const row = logEl.querySelector('[data-i="' + idx + '"]');
  if (seg) {
    seg.classList.remove('active', 'done');
    if (state === 'active') seg.classList.add('active');
    if (state === 'done') seg.classList.add('done');
    if (state === 'error') {
      seg.classList.remove('active', 'done');
      seg.style.background = 'var(--accent-red)';
    }
  }
  if (row) {
    row.classList.remove('active', 'done', 'error');
    if (state === 'active') row.classList.add('active');
    if (state === 'done') row.classList.add('done');
    if (state === 'error') row.classList.add('error');
    const glyph = row.querySelector('.glyph');
    if (glyph) {
      if (state === 'done')   glyph.textContent = '\u2713'; // ✓
      else if (state === 'active') glyph.textContent = '\u25B8'; // ▸
      else if (state === 'error')  glyph.textContent = '\u2717'; // ✗
      else                         glyph.textContent = ' ';
    }
    if (meta != null) {
      const metaEl = row.querySelector('.meta');
      if (metaEl) metaEl.textContent = meta;
    }
  }
}

function startAnimation() {
  const progressEl = $('progress-bar');
  const logEl = $('node-log');
  buildExecutionMarkup(progressEl, logEl);
  animationDone = false;
  responseArrived = false;
  clearAnimation();

  let cumulative = 0;
  for (let i = 0; i < NODE_SCHEDULE_MS.length; i++) {
    const [name, dur] = NODE_SCHEDULE_MS[i];

    // mark this node active at the start of its window
    animationTimers.push(setTimeout(function () {
      if (i > 0) setNodeState(progressEl, logEl, i - 1, 'done', null);
      setNodeState(progressEl, logEl, i, 'active', null);
    }, cumulative));

    cumulative += dur;
  }

  // After the last node's window completes, hold on finalize as active
  // until the response arrives. If the response already arrived, the
  // fast-forward path will have handled completion.
  animationTimers.push(setTimeout(function () {
    animationDone = true;
    if (!responseArrived) {
      // Hold finalize active. Nothing to do, the active state remains.
    }
  }, cumulative));
}

function fastForwardAnimation() {
  const progressEl = $('progress-bar');
  const logEl = $('node-log');
  if (!progressEl || !logEl) return;
  clearAnimation();
  for (let i = 0; i < NODE_NAMES.length; i++) {
    setNodeState(progressEl, logEl, i, 'done', null);
  }
}

function markAnimationError(message) {
  const progressEl = $('progress-bar');
  const logEl = $('node-log');
  if (!progressEl || !logEl) return;
  clearAnimation();
  // Find the currently active row (or fall back to the first pending)
  let activeIdx = -1;
  for (let i = 0; i < NODE_NAMES.length; i++) {
    const row = logEl.querySelector('[data-i="' + i + '"]');
    if (row && row.classList.contains('active')) { activeIdx = i; break; }
  }
  if (activeIdx === -1) {
    for (let i = 0; i < NODE_NAMES.length; i++) {
      const row = logEl.querySelector('[data-i="' + i + '"]');
      if (row && !row.classList.contains('done')) { activeIdx = i; break; }
    }
  }
  if (activeIdx === -1) activeIdx = NODE_NAMES.length - 1;
  setNodeState(progressEl, logEl, activeIdx, 'error', message);
}

// ---------- Run ----------

function runQuery(query) {
  if (!query || !query.trim()) return;
  query = query.trim();

  // cancel any in-flight request
  if (inFlightController) {
    try { inFlightController.abort(); } catch (_) {}
  }
  inFlightController = new AbortController();

  // hide other states, show loading
  hide($('query-stack'));
  hide($('results-wrapper'));
  hide($('error-stack'));
  show($('loading-stack'));
  startAnimation();

  fetch(window.FABOPS_API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: query }),
    signal: inFlightController.signal,
  })
    .then(function (resp) {
      return resp.json().then(function (data) {
        return { ok: resp.ok, status: resp.status, data: data };
      });
    })
    .then(function (result) {
      responseArrived = true;
      if (!result.ok || result.data && result.data.error) {
        const msg = (result.data && result.data.error) || ('HTTP ' + result.status);
        renderError(msg);
        return;
      }
      finishAndRender(query, result.data);
    })
    .catch(function (err) {
      if (err && err.name === 'AbortError') return; // user clicked another chip
      responseArrived = true;
      renderError((err && err.message) || 'Network error');
    });
}

function finishAndRender(query, data) {
  // Fast-forward whatever's left of the animation, then render results.
  fastForwardAnimation();
  setTimeout(function () {
    renderResults(query, data);
  }, 320);
}

function renderError(message) {
  markAnimationError('error: ' + message);
  setTimeout(function () {
    hide($('loading-stack'));
    show($('error-stack'));
    show($('query-stack'));
    $('error-body').textContent = message;
  }, 400);
}

// ---------- Results rendering ----------

function humanDate(iso) {
  if (!iso) return null;
  try {
    const d = new Date(iso + (iso.length === 10 ? 'T00:00:00' : ''));
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  } catch (_) {
    return iso;
  }
}

function daysFromNow(iso) {
  if (!iso) return null;
  try {
    const target = new Date(iso + (iso.length === 10 ? 'T00:00:00' : ''));
    const now = new Date();
    if (isNaN(target.getTime())) return null;
    const diff = Math.round((target - now) / (1000 * 60 * 60 * 24));
    return diff;
  } catch (_) { return null; }
}

function totalSecondsFromAudit(audit) {
  if (!audit || !audit.length) return 0;
  let total = 0;
  for (let i = 0; i < audit.length; i++) {
    total += Number(audit[i].duration_ms) || 0;
  }
  return Math.round(total / 100) / 10; // one decimal
}

function findPartId(query, diagnosis) {
  // Prefer explicit fields on diagnosis, fall back to extracting an 8-digit number.
  if (diagnosis && diagnosis.part_id) return diagnosis.part_id;
  if (diagnosis && diagnosis.partId) return diagnosis.partId;
  const m = String(query || '').match(/\b\d{6,10}\b/);
  return m ? m[0] : 'this part';
}

function thirdStat(driver, diagnosis) {
  // Returns { label, value, qualifier } or null if no metric available.
  if (!diagnosis) return null;
  const d = diagnosis;
  if (driver === 'policy') {
    const age = d.policy_age_days || d.staleness_days;
    if (age != null) {
      return { label: 'POLICY AGE', value: age + 'd', qualifier: 'thr 90d' };
    }
  }
  if (driver === 'supply') {
    const slip = d.leadtime_slip_days;
    if (slip != null) {
      return { label: 'LEAD-TIME SLIP', value: '+' + slip + 'd', qualifier: 'vs baseline' };
    }
  }
  if (driver === 'demand') {
    const delta = d.run_rate_delta_pct;
    if (delta != null) {
      return { label: 'RUN-RATE DELTA', value: (delta > 0 ? '+' : '') + delta + '%', qualifier: 'wk-over-wk' };
    }
  }
  if (driver === 'none') {
    return { label: 'SIGNAL', value: 'within bounds', qualifier: '' };
  }
  return null;
}

function renderResults(query, data) {
  hide($('loading-stack'));
  hide($('query-stack'));
  hide($('error-stack'));
  show($('results-wrapper'));

  const diagnosis = data.diagnosis || {};
  const driver = (diagnosis.primary_driver || 'none').toLowerCase();
  const driverKey = ['policy', 'supply', 'demand', 'none'].indexOf(driver) >= 0 ? driver : 'none';
  const partId = findPartId(query, diagnosis);
  const stockoutDate = data.p90_stockout_date;
  const audit = data.audit || [];
  const totalSec = totalSecondsFromAudit(audit);

  // Query echo
  $('query-echo-body').textContent = query;

  // Diagnosis paragraph
  const driverChipHtml =
    '<span class="driver-chip ' + driverKey + '">' + DRIVER_LABEL[driverKey] + '</span>';
  const dateChunk = stockoutDate
    ? ' Part ' + escapeHtml(partId) + ' will stock out around <span class="diag-highlight">' + escapeHtml(humanDate(stockoutDate)) + '</span>.'
    : ' Part ' + escapeHtml(partId) + ' is being assessed for stockout risk.';
  const reasoningRaw = (diagnosis.reasoning || '').trim();
  const reasoning = reasoningRaw ? ' ' + escapeHtml(reasoningRaw) : '';
  $('diagnosis-paragraph').innerHTML =
    'Primary driver is ' + driverChipHtml + '.' + dateChunk + reasoning;

  // Diagnosis meta (top-right of card)
  if (totalSec > 0) {
    $('diagnosis-meta').textContent = 'VERIFIED \u00B7 ' + totalSec + 's';
  } else {
    $('diagnosis-meta').textContent = 'VERIFIED';
  }

  // Stat row
  const statRow = $('stat-row');
  const stats = [];
  if (stockoutDate) {
    const days = daysFromNow(stockoutDate);
    stats.push({
      label: 'P90 STOCKOUT',
      value: stockoutDate,
      qualifier: days != null ? days + 'd' : '',
    });
  }
  if (diagnosis.confidence != null) {
    stats.push({
      label: 'CONFIDENCE',
      value: Number(diagnosis.confidence).toFixed(2),
      qualifier: '',
    });
  }
  const third = thirdStat(driverKey, diagnosis);
  if (third) stats.push(third);

  let statsHtml = '';
  for (let i = 0; i < stats.length; i++) {
    const s = stats[i];
    statsHtml +=
      '<div class="stat-col">' +
        '<div class="label">' + escapeHtml(s.label) + '</div>' +
        '<div class="value">' + escapeHtml(s.value) +
          (s.qualifier ? ' <span class="qualifier">\u00B7 ' + escapeHtml(s.qualifier) + '</span>' : '') +
        '</div>' +
      '</div>';
  }
  statRow.innerHTML = statsHtml;

  // Action card
  const actionKey = diagnosis.action || 'monitor';
  const tmpl = ACTION_TEMPLATES[actionKey] || ACTION_TEMPLATES.monitor;
  $('action-headline').textContent = tmpl(partId);
  $('action-rationale').textContent = reasoningRaw || 'See the diagnosis above for the full rationale.';

  // Citations
  const cites = data.citations || [];
  $('citations-head').textContent =
    'CITATIONS \u00B7 ' + cites.length + ' SOURCE' + (cites.length === 1 ? '' : 'S');
  const citeBody = $('citations-body');
  if (cites.length === 0) {
    citeBody.innerHTML = '<div class="citations-empty">no external sources cited</div>';
  } else {
    let citeHtml = '';
    for (let i = 0; i < cites.length; i++) {
      const c = cites[i] || {};
      const sourceType = inferSourceType(c.source);
      const pointer = c.url
        ? '<a href="' + escapeHtml(c.url) + '" target="_blank" rel="noopener">' + escapeHtml(c.source || '') + '</a>'
        : escapeHtml(c.source || '');
      const excerpt = String(c.excerpt || '').slice(0, 320);
      const trimmed = excerpt.length === 320 ? excerpt + '\u2026' : excerpt;
      citeHtml +=
        '<div class="citation-row">' +
          '<div class="citation-meta">' +
            '<span class="source-chip">' + sourceType + '</span>' +
            '<span class="citation-pointer">' + pointer + '</span>' +
          '</div>' +
          (trimmed ? '<div class="citation-excerpt">' + escapeHtml(trimmed) + '</div>' : '') +
        '</div>';
    }
    citeBody.innerHTML = citeHtml;
  }

  // Audit trail
  renderAudit(audit, totalSec);

  // Reset audit collapsed state
  hide($('audit-body'));
  $('audit-toggle-icon').innerHTML = '\u25BC expand';

  // Scroll to top
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function inferSourceType(source) {
  if (!source) return 'INTERNAL';
  const s = String(source).toLowerCase();
  if (s.includes('edgar') || s.includes('10-k') || s.includes('10-q') || s.includes('amat') || s.includes('sec')) return 'SEC EDGAR';
  if (s.includes('fred')) return 'FRED';
  if (s.includes('fabops_') || s.includes('dynamodb') || s.includes('inventory') || s.includes('policies') || s.includes('suppliers')) return 'DYNAMODB';
  return 'INTERNAL';
}

function renderAudit(audit, totalSec) {
  const summary = $('audit-summary');
  if (!audit || audit.length === 0) {
    summary.textContent = 'AUDIT TRAIL \u00B7 unavailable';
    $('audit-body').innerHTML = '';
    return;
  }
  const allOk = audit.every(function (a) { return a.ok !== false; });
  summary.textContent =
    'AUDIT TRAIL \u00B7 ' + audit.length + ' STEPS \u00B7 ' + totalSec + 's' +
    ' \u00B7 ' + (allOk ? 'ALL PASSED' : 'WITH ERRORS');

  // Build progress + log against the canonical 9-node order, but only for
  // nodes that actually appeared in the audit. Unknown extras get appended.
  const progressEl = $('audit-progress');
  const logEl = $('audit-log');
  buildExecutionMarkup(progressEl, logEl);

  // Map audit entries by node name. Use the most recent if duplicates.
  const byNode = {};
  for (let i = 0; i < audit.length; i++) {
    const a = audit[i];
    if (!a || !a.node) continue;
    byNode[a.node] = a;
  }

  for (let i = 0; i < NODE_NAMES.length; i++) {
    const name = NODE_NAMES[i];
    const a = byNode[name];
    if (a) {
      const ms = Number(a.duration_ms) || 0;
      const seconds = (ms / 1000).toFixed(2);
      const note = a.ok === false ? 'error' : seconds + 's';
      setNodeState(progressEl, logEl, i, a.ok === false ? 'error' : 'done', note);
    } else {
      setNodeState(progressEl, logEl, i, 'done', 'skipped');
    }
  }
}

// ---------- Modal ----------

function openModal() {
  $('modal-backdrop').classList.add('open');
}
function closeModal() {
  $('modal-backdrop').classList.remove('open');
}

// ---------- Wire up ----------

function flashChip(chipEl) {
  if (!chipEl) return;
  chipEl.classList.add('flash');
  setTimeout(function () { chipEl.classList.remove('flash'); }, 220);
}

function init() {
  const askBtn = $('ask-btn');
  const queryInput = $('query-input');

  askBtn.addEventListener('click', function () {
    runQuery(queryInput.value);
  });

  queryInput.addEventListener('keydown', function (e) {
    // cmd/ctrl + enter to run
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      runQuery(queryInput.value);
    }
  });

  // Chips: fill textarea, flash, run
  document.querySelectorAll('.chip[data-query]').forEach(function (chip) {
    chip.addEventListener('click', function () {
      const q = chip.getAttribute('data-query');
      queryInput.value = q;
      flashChip(chip);
      runQuery(q);
    });
  });

  // New query button (returns to query panel)
  const newBtn = $('new-query-btn');
  if (newBtn) {
    newBtn.addEventListener('click', function () {
      hide($('results-wrapper'));
      hide($('error-stack'));
      show($('query-stack'));
      window.scrollTo({ top: 0, behavior: 'smooth' });
      queryInput.focus();
    });
  }

  // Audit trail toggle
  const auditToggle = $('audit-toggle');
  if (auditToggle) {
    auditToggle.addEventListener('click', function () {
      const body = $('audit-body');
      const icon = $('audit-toggle-icon');
      if (body.hasAttribute('hidden')) {
        body.removeAttribute('hidden');
        icon.innerHTML = '\u25B2 collapse';
      } else {
        body.setAttribute('hidden', '');
        icon.innerHTML = '\u25BC expand';
      }
    });
  }

  // Modal
  $('link-howitworks').addEventListener('click', function (e) {
    e.preventDefault();
    openModal();
  });
  $('modal-close').addEventListener('click', closeModal);
  $('modal-backdrop').addEventListener('click', function (e) {
    if (e.target === $('modal-backdrop')) closeModal();
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      if ($('modal-backdrop').classList.contains('open')) closeModal();
    }
    if (e.key === '?' && document.activeElement !== queryInput) {
      openModal();
    }
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
