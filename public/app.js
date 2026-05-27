const searchEl = document.getElementById('search');
const resultsEl = document.getElementById('results');
const dialog = document.getElementById('form-dialog');
const form = document.getElementById('player-form');
const formTitle = document.getElementById('form-title');
const formError = document.getElementById('form-error');

let editingId = null;

const NUM_FIELDS = ['matches', 'escape_count', 'escape_rate', 'kills', 'deaths', 'net_profit'];

async function fetchPlayers(q) {
  const res = await fetch(`/api/players?q=${encodeURIComponent(q)}`);
  return res.json();
}

function kd(p) {
  if (p.kills == null) return '—';
  if (!p.deaths) return String(p.kills);
  return (p.kills / p.deaths).toFixed(2);
}

function stat(label, value, suffix = '') {
  if (value == null || value === '') return '';
  return `<span>${label} <b>${value}${suffix}</b></span>`;
}

function render(players, query) {
  if (players.length === 0) {
    resultsEl.innerHTML = `
      <div class="empty">
        <p>没找到${query ? ` “${escapeHtml(query)}”` : '任何玩家'}</p>
        ${query ? `<button id="add-from-empty">＋ 记一笔这个玩家</button>` : ''}
      </div>`;
    const btn = document.getElementById('add-from-empty');
    if (btn) btn.onclick = () => openForm(null, { game_id: query });
    return;
  }
  resultsEl.innerHTML = players.map((p) => `
    <div class="card">
      <div class="card-head">
        <span class="name">${escapeHtml(p.game_id)}</span>
        ${p.tags.map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join('')}
      </div>
      <div class="stats">
        ${stat('段位', p.rank ? escapeHtml(p.rank) : null)}
        ${stat('场次', p.matches)}
        ${stat('撤离率', p.escape_rate, '%')}
        ${stat('KD', kd(p) === '—' ? null : kd(p))}
        ${stat('资产', p.net_profit)}
        ${stat('干员', p.favorite_operator ? escapeHtml(p.favorite_operator) : null)}
      </div>
      ${p.note ? `<div class="note">${escapeHtml(p.note)}</div>` : ''}
      <div class="meta">更新于 ${new Date(p.updated_at).toLocaleString()}</div>
      <div class="card-actions">
        <button data-edit="${p.id}">编辑</button>
        <button data-del="${p.id}">删除</button>
      </div>
    </div>`).join('');

  resultsEl.querySelectorAll('[data-edit]').forEach((b) => {
    b.onclick = () => {
      const p = players.find((x) => x.id === Number(b.dataset.edit));
      openForm(p.id, p);
    };
  });
  resultsEl.querySelectorAll('[data-del]').forEach((b) => {
    b.onclick = () => removePlayer(Number(b.dataset.del));
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function refresh() {
  const q = searchEl.value.trim();
  render(await fetchPlayers(q), q);
}

function openForm(id, data = {}) {
  editingId = id;
  formTitle.textContent = id ? '编辑玩家' : '记一笔';
  formError.textContent = '';
  form.reset();
  form.game_id.value = data.game_id ?? '';
  form.tags.value = (data.tags ?? []).join(', ');
  form.rank.value = data.rank ?? '';
  for (const f of NUM_FIELDS) form[f].value = data[f] ?? '';
  form.favorite_operator.value = data.favorite_operator ?? '';
  form.note.value = data.note ?? '';
  dialog.showModal();
}

function readForm() {
  const payload = {
    game_id: form.game_id.value.trim(),
    tags: form.tags.value.split(',').map((t) => t.trim()).filter(Boolean),
    rank: form.rank.value.trim() || null,
    favorite_operator: form.favorite_operator.value.trim() || null,
    note: form.note.value.trim() || null,
  };
  for (const f of NUM_FIELDS) {
    const raw = form[f].value;
    payload[f] = raw === '' ? null : Number(raw);
  }
  return payload;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = readForm();
  const url = editingId ? `/api/players/${editingId}` : '/api/players';
  const method = editingId ? 'PUT' : 'POST';
  const res = await fetch(url, {
    method,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (res.ok) {
    dialog.close();
    refresh();
  } else {
    const body = await res.json().catch(() => ({}));
    formError.textContent = body.error || (body.errors && body.errors.join('；')) || '保存失败';
  }
});

async function removePlayer(id) {
  if (!confirm('确定删除这个玩家档案？')) return;
  await fetch(`/api/players/${id}`, { method: 'DELETE' });
  refresh();
}

document.getElementById('add-btn').onclick = () => openForm(null, {});
document.getElementById('cancel-btn').onclick = () => dialog.close();
searchEl.addEventListener('input', refresh);

refresh();
