const $ = (id) => document.getElementById(id);
const searchEl = $("search");
const dropEl = $("drop");
const filesEl = $("files");
const thumbsEl = $("thumbs");
const countEl = $("count");
const upmsg = $("upmsg");
const resultEl = $("result");
const listEl = $("list");

let collected = [];

const RADAR_KEYS = ["战斗", "生存", "合作", "搜索", "财富"];
const KD_LABELS = ["普通", "机密", "绝密"];
const OTHER_FIELDS = [
  ["战局数", "matches"], ["游戏时长", "play_hours"], ["撤离率", "escape_rate"],
  ["击败干员", "kills"], ["命中率", "hit_rate"], ["精准击败率", "precise_kill_rate"],
  ["带出价值", "carry_value"], ["累计行动报酬", "action_reward"], ["曼德尔砖", "mandel_bricks"],
  ["带出队友价值", "carry_teammate_value"], ["救助队友", "rescue_teammate"], ["复活队友", "revive_teammate"],
];

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const val = (v) => (v == null || v === "" ? "—" : esc(v));

// ---------- upload ----------
function addFiles(list) {
  for (const f of list) if (f && (f.type || "").startsWith("image/")) collected.push(f);
  renderThumbs();
}
function renderThumbs() {
  thumbsEl.innerHTML = "";
  collected.forEach((f) => { const i = new Image(); i.src = URL.createObjectURL(f); thumbsEl.appendChild(i); });
  countEl.textContent = collected.length;
}
filesEl.onchange = () => { addFiles(filesEl.files); filesEl.value = ""; };
dropEl.addEventListener("dragover", (e) => { e.preventDefault(); dropEl.classList.add("hot"); });
dropEl.addEventListener("dragleave", () => dropEl.classList.remove("hot"));
dropEl.addEventListener("drop", (e) => {
  e.preventDefault(); dropEl.classList.remove("hot");
  const dt = e.dataTransfer; let got = [];
  if (dt.files && dt.files.length) got = [...dt.files];
  else if (dt.items) for (const it of dt.items) if (it.kind === "file") { const f = it.getAsFile(); if (f) got.push(f); }
  if (got.length) addFiles(got);
  else upmsg.textContent = "没拿到图片文件，微信图片请用「右键复制 → Ctrl+V 粘贴」。";
});
window.addEventListener("paste", (e) => {
  const items = (e.clipboardData || {}).items || []; const got = [];
  for (const it of items) if (it.kind === "file") { const f = it.getAsFile(); if (f) got.push(f); }
  if (got.length) { addFiles(got); upmsg.textContent = "已粘贴 " + got.length + " 张"; }
});
$("clear").onclick = () => { collected = []; renderThumbs(); upmsg.textContent = ""; };

$("analyze").onclick = async () => {
  if (!collected.length) { upmsg.textContent = "请先选择/拖入/粘贴图片"; return; }
  const fd = new FormData();
  collected.forEach((f, i) => fd.append("images", f, f.name || ("paste_" + i + ".png")));
  upmsg.textContent = "识别中…（本地 OCR，首次稍慢）";
  try {
    const r = await fetch("/api/lookup", { method: "POST", body: fd });
    const body = await r.json();
    if (!r.ok) { upmsg.textContent = body.error || "识别失败"; return; }
    collected = []; renderThumbs();
    upmsg.textContent = body.recognized_nickname
      ? "已识别并记录：" + body.recognized_nickname
      : "未能识别昵称，请在下方填写昵称后保存。";
    listEl.innerHTML = "";
    resultEl.innerHTML = "";
    resultEl.appendChild(renderCard(body.player));
  } catch (e) { upmsg.textContent = "请求失败：" + e; }
};

// ---------- render player ----------
function modeColumn(title, mode, m) {
  if (!m) return `<div class="mode"><h3>${title}</h3><div class="muted">（未上传该截图）</div></div>`;
  const kd = m.kd || [];
  const kdInputs = [0, 1, 2].map((i) =>
    `<input data-mode="${mode}" data-kd="${i}" value="${esc(kd[i] ?? "")}" />` +
    (i < 2 ? `<span class="sep">|</span>` : "")).join("");
  const kdSub = KD_LABELS.map((l) => `<span>${l}</span>`).join("");
  const radar = RADAR_KEYS.map((k) => {
    const v = (m.radar || {})[k];
    return `<div class="r"><div class="rv">${v == null ? "—" : v}</div><div class="rl">${k}</div></div>`;
  }).join("");
  const rankStr = [m.rank_name, m.rank_star != null ? "★" + m.rank_star : "", m.rank_score != null ? "(" + m.rank_score + ")" : ""].filter(Boolean).join(" ");
  const grid = [["段位", rankStr || "—"], ...OTHER_FIELDS.map(([lab, key]) => [lab, val(m[key])])]
    .map(([k, v]) => `<div class="k">${k}</div><div class="v">${v}</div>`).join("");
  return `
    <div class="mode">
      <h3>${title}</h3>
      <div class="hl">
        <div class="blk"><div class="lab">KD（普通/机密/绝密）</div>
          <div class="kd-inputs">${kdInputs}</div>
          <div class="kd-sub">${kdSub}</div>
        </div>
        <div class="blk"><div class="lab">赚损比</div><div class="big">${val(m.profit_ratio)}</div></div>
      </div>
      <div class="hl"><div class="blk"><div class="lab">五维</div>
        <div class="radar5">${radar}</div></div></div>
      <div class="grid">${grid}</div>
    </div>`;
}

function recentBlock(recent) {
  if (!recent || recent.hidden) return `<div class="recent"><h3>最近战绩</h3><span class="hidden-badge">对方隐藏了战绩</span></div>`;
  const rows = (recent.matches || []).map((m) => {
    const ok = m.result === "撤离成功";
    return `<div class="match">
      <span class="${ok ? "res-ok" : "res-fail"}">${esc(m.result)}</span>
      <span class="mt">${val(m.map_time)}</span>
      <span class="hf">${m.hafu ? "哈夫币 " + esc(m.hafu) : ""}</span>
      <span class="rc">${val(m.rank_change)}</span>
    </div>`;
  }).join("");
  return `<div class="recent"><h3>最近战绩（${(recent.matches || []).length}）</h3>${rows}</div>`;
}

function renderCard(p) {
  const d = p.data || {};
  const home = d.home || {};
  const el = document.createElement("div");
  el.className = "card";
  el.dataset.id = p.id;
  el.innerHTML = `
    <div class="top">
      <input class="nick" value="${esc(p.nickname)}" />
      ${home.title ? `<span class="title-badge">${esc(home.title)}</span>` : ""}
      <input class="tags-input" placeholder="标签，逗号分隔（老六, 演员）" value="${esc((p.tags || []).join(", "))}" />
    </div>
    <div class="modes">
      ${modeColumn("数据总览", "overview", d.overview)}
      ${modeColumn("排位赛", "ranked", d.ranked)}
    </div>
    ${recentBlock(d.recent)}
    <textarea class="note" rows="2" placeholder="备注（打狙很准，别硬刚…）">${esc(p.note || "")}</textarea>
    <div class="actions">
      <button class="save">保存</button>
      <button class="del danger">删除</button>
    </div>
    <div class="meta">更新于 ${p.updated_at ? new Date(p.updated_at).toLocaleString() : "—"}</div>`;

  el.querySelector(".save").onclick = () => saveCard(el, p);
  el.querySelector(".del").onclick = () => delCard(el, p);
  return el;
}

async function saveCard(el, p) {
  const data = JSON.parse(JSON.stringify(p.data || {}));
  ["overview", "ranked"].forEach((mode) => {
    if (!data[mode]) return;
    data[mode].kd = [0, 1, 2].map((i) => {
      const inp = el.querySelector(`input[data-mode="${mode}"][data-kd="${i}"]`);
      return inp && inp.value.trim() !== "" ? inp.value.trim() : null;
    });
  });
  const body = {
    nickname: el.querySelector(".nick").value.trim(),
    tags: el.querySelector(".tags-input").value.split(",").map((t) => t.trim()).filter(Boolean),
    note: el.querySelector(".note").value.trim() || null,
    data,
  };
  const r = await fetch(`/api/players/${p.id}`, {
    method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  if (r.ok) {
    const updated = await r.json();
    const fresh = renderCard(updated);
    el.replaceWith(fresh);
    fresh.querySelector(".meta").style.color = "#b6e39a";
  } else {
    alert("保存失败");
  }
}

async function delCard(el, p) {
  if (!confirm(`删除「${p.nickname}」的档案？`)) return;
  await fetch(`/api/players/${p.id}`, { method: "DELETE" });
  el.remove();
}

// ---------- search ----------
async function doSearch() {
  resultEl.innerHTML = "";
  const q = searchEl.value.trim();
  const r = await fetch(`/api/players?q=${encodeURIComponent(q)}`);
  const players = await r.json();
  listEl.innerHTML = "";
  if (!players.length) { listEl.innerHTML = `<div class="empty">${q ? "没找到「" + esc(q) + "」" : "还没有任何记录，上传截图开始记录吧"}</div>`; return; }
  players.forEach((p) => listEl.appendChild(renderCard(p)));
}
searchEl.addEventListener("input", doSearch);

doSearch();
