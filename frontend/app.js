// Pre-warm the Lambda the moment the page loads so the user's first real
// query doesn't pay the ~50s cold-start cost. The agent rejects empty
// queries with a 400, which is fine — we only care about waking up the
// container and warming the EDGAR chunk cache. Failures are silent.
(function preWarm() {
  try {
    fetch(window.FABOPS_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: '__warmup__' }),
    }).catch(() => {});
  } catch (_) {}
})();

document.getElementById('ask-btn').addEventListener('click', async () => {
  const query = document.getElementById('query-input').value.trim();
  if (!query) return;

  document.getElementById('results').style.display = 'none';
  document.getElementById('loading').style.display = 'block';

  try {
    const resp = await fetch(window.FABOPS_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
    const data = await resp.json();
    renderResults(data);
  } catch (e) {
    alert('Error: ' + e.message);
  } finally {
    document.getElementById('loading').style.display = 'none';
  }
});

function renderResults(data) {
  document.getElementById('results').style.display = 'block';

  const diag = data.diagnosis || {};
  document.getElementById('primary-driver').textContent = diag.primary_driver || 'unknown';
  document.getElementById('stockout-date').textContent = data.p90_stockout_date || 'not computed';
  document.getElementById('confidence').textContent = (diag.confidence || 0).toFixed(2);

  const plan = document.getElementById('agent-plan');
  plan.innerHTML = '';
  const steps = [
    'entry', 'check_policy_staleness', 'check_demand_drift',
    'check_supply_drift', 'ground_in_disclosures',
    'diagnose', 'prescribe_action', 'verify', 'finalize'
  ];
  steps.forEach(s => {
    const li = document.createElement('li');
    li.textContent = s;
    plan.appendChild(li);
  });

  const citesList = document.getElementById('citations-list');
  citesList.innerHTML = '';
  (data.citations || []).forEach(c => {
    const li = document.createElement('li');
    const source = c.url
      ? `<a href="${c.url}" target="_blank">${c.source}</a>`
      : c.source;
    li.innerHTML = `<strong>${source}</strong><br><em>${c.excerpt || ''}</em>`;
    citesList.appendChild(li);
  });

  document.getElementById('action-text').textContent =
    (diag.reasoning || '') + ' — ' + ((data.answer || '').split('\n').find(l => l.includes('ACTION')) || '');
  document.getElementById('answer-text').textContent = data.answer || '';
}
