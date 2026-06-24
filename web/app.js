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
const DETAIL_FIELDS = [
  ["总场次", "matches"], ["游戏时长", "play_hours"], ["命中率", "hit_rate"],
  ["精准击败率", "precise_kill_rate"], ["带出价值", "carry_value"], ["累计行动报酬", "action_reward"],
  ["曼德尔砖", "mandel_bricks"], ["带出队友价值", "carry_teammate_value"],
  ["救助队友", "rescue_teammate"], ["复活队友", "revive_teammate"],
];

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const val = (v) => (v == null || v === "" ? "—" : esc(v));
const num = (v) => { const n = parseFloat(v); return isNaN(n) ? null : n; };

// ---- pentagon radar chart (game-style), one labelled series ----
function radarSVG(radar) {
  const keys = RADAR_KEYS;            // 战斗(top) 生存 合作 搜索 财富, clockwise
  const cx = 90, cy = 82, R = 54, labOff = 17, W = 180, H = 168;
  const ang = (i) => (-90 + i * 72) * Math.PI / 180;
  const pt = (i, r) => [cx + r * Math.cos(ang(i)), cy + r * Math.sin(ang(i))];
  const poly = (r) => keys.map((_, i) => pt(i, r).map((n) => n.toFixed(1)).join(",")).join(" ");

  let grid = "";
  [0.25, 0.5, 0.75, 1].forEach((f) => {
    grid += `<polygon points="${poly(R * f)}" fill="none" stroke="#262e31" stroke-width="1"/>`;
  });
  let axes = "";
  keys.forEach((_, i) => { const [x, y] = pt(i, R); axes += `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#262e31" stroke-width="1"/>`; });

  const vals = keys.map((k) => { const v = (radar || {})[k]; return v == null ? 0 : Math.max(0, Math.min(100, v)); });
  const dpts = vals.map((v, i) => pt(i, R * v / 100).map((n) => n.toFixed(1)).join(",")).join(" ");
  const dataPoly = `<polygon points="${dpts}" fill="rgba(37,224,141,.16)" stroke="#25e08d" stroke-width="2"/>`;
  let dots = "";
  vals.forEach((v, i) => { const [x, y] = pt(i, R * v / 100); dots += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.2" fill="#25e08d"/>`; });

  let labels = "";
  keys.forEach((k, i) => {
    const [lx, ly] = pt(i, R + labOff);
    const v = (radar || {})[k];
    labels += `<text x="${lx.toFixed(1)}" y="${(ly - 1).toFixed(1)}" text-anchor="middle" font-size="9" fill="#93a0a4">${k}</text>`;
    labels += `<text x="${lx.toFixed(1)}" y="${(ly + 10).toFixed(1)}" text-anchor="middle" font-size="12" font-weight="700" fill="#e8edee">${v == null ? "—" : v}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" class="radar-svg">${grid}${axes}${dataPoly}${dots}${labels}</svg>`;
}

// ---- skill colour heuristics (green=strong, amber=mid, red=weak) ----
function kdClass(v) { const n = num(v); if (n == null) return ""; return n >= 2 ? "good" : n >= 1 ? "mid" : "bad"; }
function rateClass(v) { const n = num(v); if (n == null) return ""; return n >= 45 ? "good" : n >= 30 ? "mid" : "bad"; }

// 强度参考：以绝密KD（最高难度，最能体现真实水平）+ 撤离率综合判断
function verdict(m) {
  if (!m) return null;
  const kd = num((m.kd || [])[2]) ?? num((m.kd || [])[1]) ?? num((m.kd || [])[0]);
  const esc2 = num(m.escape_rate);
  if (kd == null && esc2 == null) return null;
  let s = 0;
  if (kd != null) s += kd >= 2 ? 2 : kd >= 1.3 ? 1.4 : kd >= 0.8 ? 0.7 : 0;
  if (esc2 != null) s += esc2 >= 45 ? 2 : esc2 >= 33 ? 1.2 : esc2 >= 25 ? 0.6 : 0;
  if (s >= 3.2) return { t: "大佬", c: "v-top" };
  if (s >= 2) return { t: "高手", c: "v-good" };
  if (s >= 1) return { t: "普通", c: "v-mid" };
  return { t: "萌新", c: "v-low" };
}

// ---------- upload ----------
function addFiles(list) {
  for (const f of list) if (f && (f.type || "").startsWith("image/")) collected.push(f);
  const up = $("upload");
  if (up && up.tagName === "DETAILS") up.open = true;   // reveal pasted thumbs
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
  else upmsg.textContent = "没拿到图片文件，微信图片请用「右键复制图片 → Ctrl+V 粘贴」。";
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
      ? "已识别并记录：" + body.recognized_nickname + "（如名字识别有误，可在卡片上直接改后保存）"
      : "未能识别昵称，请在下方填写昵称后保存。";
    await refreshList();
    showInDetail(body.player);
  } catch (e) { upmsg.textContent = "请求失败：" + e; }
};

// ---------- render: dossier components ----------

// the at-a-glance verdict for the header: the better of the two modes
function bestVerdict(d) {
  const order = { "v-top": 3, "v-good": 2, "v-mid": 1, "v-low": 0 };
  const vs = [verdict(d.overview), verdict(d.ranked)].filter(Boolean);
  if (!vs.length) return null;
  return vs.sort((a, b) => order[b.c] - order[a.c])[0];
}

// hero numbers: what you check before deciding to fight or run.
// 总览 and 排位 KD get EQUAL billing, side by side, first in line.
function statStrip(p, d) {
  const home = d.home || {}, ov = d.overview || {}, rk = d.ranked || {};
  const kdOv = (ov.kd || [])[2];
  const kdRk = (rk.kd || [])[2];
  const escR = ov.escape_rate ?? rk.escape_rate;
  const star = rk.rank_star ?? ov.rank_star;
  const rank = [rk.rank_name || ov.rank_name, star != null ? "★" + star : ""].filter(Boolean).join(" ");
  const items = [
    ["总览 绝密KD", kdOv, kdClass(kdOv) + " kd"],
    ["排位 绝密KD", kdRk, kdClass(kdRk) + " kd"],
    ["撤离率", escR, rateClass(escR)],
    ["段位", rank || null, "rank"],
    ["赚损比", ov.profit_ratio ?? rk.profit_ratio, ""],
    ["总场次", home.total_matches ?? ov.matches, ""],
    ["总资产", home.total_assets, ""],
  ].filter(([, v]) => v != null && v !== "");
  if (!items.length) return "";
  return `<div class="strip">${items.map(([k, v, c]) =>
    `<div class="si"><i>${k}</i><b class="${c}">${esc(v)}</b></div>`).join("")}</div>`;
}

function kdInput(mode, i, m) {
  const v = (m.kd || [])[i] ?? "";
  return `<input class="kd-in ${kdClass(v)}" data-mode="${mode}" data-kd="${i}" value="${esc(v)}" />`;
}

// one comparison table instead of two parallel cards: rows = metrics,
// columns = 数据总览 | 排位赛 — differences pop instantly.
function cmpTable(d) {
  const ov = d.overview, rk = d.ranked;
  if (!ov && !rk) return "";
  const vo = verdict(ov), vr = verdict(rk);
  const td = (m, html, cls = "") => `<td class="${cls}">${m ? html : '<span class="na">—</span>'}</td>`;

  const kdRows = [0, 1, 2].map((i) => `<tr>
    <th>KD · ${KD_LABELS[i]}${i === 2 ? '<em class="tip">真实水平</em>' : ""}</th>
    ${td(ov, ov ? kdInput("overview", i, ov) : "")}
    ${td(rk, rk ? kdInput("ranked", i, rk) : "")}
  </tr>`).join("");

  const row = (label, get, cls) => {
    const a = ov ? get(ov) : null, b = rk ? get(rk) : null;
    if (a == null && b == null) return "";
    const c = (m, v) => td(m, `<span class="${cls ? cls(v) : ""}">${val(v)}</span>`);
    return `<tr><th>${label}</th>${c(ov, a)}${c(rk, b)}</tr>`;
  };
  const rankStr = (m) => [m.rank_name, m.rank_star != null ? "★" + m.rank_star : ""].filter(Boolean).join(" ") || null;

  const mainRows =
    kdRows +
    row("段位", rankStr) +
    row("段位分", (m) => m.rank_score) +
    row("撤离率", (m) => m.escape_rate, rateClass) +
    row("赚损比", (m) => m.profit_ratio) +
    row("场次", (m) => m.matches) +
    row("时长", (m) => m.play_hours);

  const xtraRows = DETAIL_FIELDS
    .filter(([, key]) => !["matches", "play_hours"].includes(key))
    .map(([lab, key]) => row(lab, (m) => m[key])).join("");

  return `<table class="cmp">
    <thead><tr><th></th>
      <th>数据总览 ${vo ? `<span class="verdict ${vo.c}">${vo.t}</span>` : ""}</th>
      <th>排位赛 ${vr ? `<span class="verdict ${vr.c}">${vr.t}</span>` : ""}</th>
    </tr></thead>
    <tbody>${mainRows}</tbody>
    <tbody class="xtra details-hidden">${xtraRows}</tbody>
  </table>
  <button type="button" class="toggle">更多数据 ▾</button>`;
}

function radarsBlock(d) {
  const ov = d.overview, rk = d.ranked;
  if (!(ov && ov.radar) && !(rk && rk.radar)) return "";
  const fig = (m, cap) => (m && m.radar && Object.keys(m.radar).length)
    ? `<figure>${radarSVG(m.radar)}<figcaption>${cap}</figcaption></figure>` : "";
  return `<div class="radars">${fig(ov, "总览 五维")}${fig(rk, "排位 五维")}</div>`;
}

function recentBlock(recent) {
  if (!recent || recent.hidden) return `<div class="recent"><h3>最近战绩</h3><span class="hidden-badge">⚠ 对方隐藏了战绩</span></div>`;
  const ms = recent.matches || [];
  const wins = ms.filter((m) => m.result === "撤离成功").length;
  const kills = ms.reduce((s, m) => s + (m.kills || 0), 0);
  const winPct = ms.length ? Math.round(wins / ms.length * 100) : 0;

  const rows = ms.map((m) => {
    const ok = m.result === "撤离成功";
    // map_time arrives merged like '航天基地-机密 昨天 23:20' — split into columns
    const mt = m.map_time || "";
    const dm = mt.match(/^(.*?)[-－](机密|绝密|常规|普通)\s*(.*)$/);
    const map = dm ? dm[1] : mt, diff = dm ? dm[2] : "", time = dm ? dm[3] : "";
    const diffCls = diff === "绝密" ? "d-top" : diff === "机密" ? "d-mid" : "d-low";
    return `<div class="match ${ok ? "m-ok" : "m-fail"}">
      <span class="m-res">${ok ? "✔ 撤离" : "✘ 阵亡"}</span>
      <span class="m-map">${esc(map) || "—"}</span>
      <span class="m-diff ${diff ? diffCls : ""}">${esc(diff)}</span>
      <span class="m-kill">${m.kills != null ? `<b>${esc(m.kills)}</b> 击杀` : '<i>—</i>'}</span>
      <span class="m-hafu">${m.hafu ? `<b>${esc(m.hafu)}</b> 哈夫币` : '<i>—</i>'}</span>
      <span class="m-rc">${m.rank_change ? esc(m.rank_change) : ""}</span>
      <span class="m-time">${esc(time)}</span>
    </div>`;
  }).join("");

  return `<div class="recent">
    <h3>最近战绩</h3>
    <div class="recent-sum">
      <span class="rs">${ms.length} 场</span>
      <span class="rs ${winPct >= 50 ? "good" : winPct >= 30 ? "mid" : "bad"}">撤离 ${wins} 场 · ${winPct}%</span>
      <span class="rs good">总击杀 ${kills}</span>
    </div>
    <div class="match match-head">
      <span class="m-res">结果</span><span class="m-map">地图</span><span class="m-diff">难度</span>
      <span class="m-kill">击杀</span><span class="m-hafu">带出</span><span class="m-rc">排位分</span><span class="m-time">时间</span>
    </div>${rows}</div>`;
}

function renderCard(p, opts = {}) {
  const d = p.data || {};
  const home = d.home || {};
  const v = bestVerdict(d);
  const el = document.createElement("div");
  el.className = "card";
  el.dataset.id = p.id;
  el.innerHTML = `
    <header class="dhead">
      <input class="nick" value="${esc(p.nickname)}" title="名字识别错了可直接改" />
      ${v ? `<span class="verdict ${v.c}">${v.t}</span>` : ""}
      ${home.title ? `<span class="title-badge">${esc(home.title)}</span>` : ""}
      ${home.uid ? `<span class="uid-block">
        <span class="uid-l">UID</span>
        <code class="uid">${esc(home.uid)}</code>
        <button type="button" class="copy-btn" title="复制 UID">复制</button></span>` : ""}
    </header>
    ${statStrip(p, d)}
    <div class="dbody">
      <section class="sec-cmp">
        <h3>总览 / 排位 对比</h3>
        ${cmpTable(d)}
        ${radarsBlock(d)}
      </section>
      ${recentBlock(d.recent)}
    </div>
    <footer class="dfoot">
      <input class="tags-input" placeholder="标签，逗号分隔（老六, 演员）" value="${esc((p.tags || []).join(", "))}" />
      <textarea class="note" rows="2" placeholder="备注（打狙很准，别硬刚…）">${esc(p.note || "")}</textarea>
      <div class="actions">
        <button class="save">保存</button>
        <button class="del danger">删除</button>
        <span class="meta">更新于 ${p.updated_at ? new Date(p.updated_at).toLocaleString() : "—"}</span>
      </div>
    </footer>`;

  el.querySelectorAll(".toggle").forEach((btn) => {
    btn.onclick = () => {
      const xtra = el.querySelector("tbody.xtra");
      if (!xtra) return;
      const hidden = xtra.classList.toggle("details-hidden");
      btn.textContent = hidden ? "更多数据 ▾" : "收起 ▴";
    };
  });
  // recolour a KD input as the user edits it
  el.querySelectorAll("input[data-kd]").forEach((inp) => {
    inp.oninput = () => {
      inp.classList.remove("good", "mid", "bad");
      const c = kdClass(inp.value);
      if (c) inp.classList.add(c);
    };
  });
  if (opts.onCollapse) {
    const collapse = document.createElement("button");
    collapse.className = "ghost";
    collapse.textContent = "收起";
    collapse.onclick = (ev) => { ev.stopPropagation(); opts.onCollapse(); };
    el.querySelector(".actions").insertBefore(collapse, el.querySelector(".actions").firstChild);
  }
  el.querySelector(".save").onclick = () => saveCard(el, p, opts);
  el.querySelector(".del").onclick = () => delCard(el, p);
  const copyBtn = el.querySelector(".copy-btn");
  if (copyBtn) copyBtn.onclick = (ev) => {
    ev.stopPropagation();
    const uid = (home || {}).uid || "";
    navigator.clipboard.writeText(uid).then(() => {
      copyBtn.textContent = "已复制 ✔"; copyBtn.classList.add("copied");
      setTimeout(() => { copyBtn.textContent = "复制"; copyBtn.classList.remove("copied"); }, 1200);
    }).catch(() => { copyBtn.textContent = "复制失败"; setTimeout(() => { copyBtn.textContent = "复制"; }, 1500); });
  };
  return el;
}

async function saveCard(el, p, opts = {}) {
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
    el.replaceWith(renderCard(updated, opts));
  } else { alert("保存失败"); }
}

async function delCard(el, p) {
  if (!confirm(`删除「${p.nickname}」的档案？`)) return;
  await fetch(`/api/players/${p.id}`, { method: "DELETE" });
  el.remove();
}

// ---------- compact list + click-to-expand ----------
function renderRow(p) {
  const d = p.data || {};
  const ov = d.overview || d.ranked || {};
  const v = verdict(ov);
  const kdSec = (ov.kd || [])[2];
  const esc2 = ov.escape_rate;
  const div = document.createElement("div");
  div.className = "row-item";
  div.dataset.id = p.id;
  div.innerHTML = `
    <div class="r1">
      <span class="rn">${esc(p.nickname)}</span>
      ${d.home && d.home.title ? `<span class="title-mini">${esc(d.home.title)}</span>` : ""}
      ${v ? `<span class="verdict ${v.c}">${v.t}</span>` : ""}
      <span class="row-arrow">›</span>
    </div>
    <div class="r2">
      ${kdSec != null ? `<span class="row-kd ${kdClass(kdSec)}">绝密 <b>${esc(kdSec)}</b></span>` : ""}
      ${esc2 ? `<span class="row-esc ${rateClass(esc2)}">撤离 <b>${esc(esc2)}</b></span>` : ""}
      ${(p.tags || []).length ? `<span class="row-tags">${p.tags.map((t) => `<i class="tag">${esc(t)}</i>`).join("")}</span>` : ""}
      <span class="row-time">${p.updated_at ? new Date(p.updated_at).toLocaleDateString() : ""}</span>
    </div>
  `;
  div.onclick = () => expandRow(div, p);
  return div;
}

function setActiveRow(id) {
  listEl.querySelectorAll(".row-item.active").forEach((e) => e.classList.remove("active"));
  const row = id != null ? listEl.querySelector(`.row-item[data-id="${id}"]`) : null;
  if (row) row.classList.add("active");
}

function showInDetail(p) {
  setActiveRow(p.id);
  const card = renderCard(p, { onCollapse: () => { resultEl.innerHTML = ""; setActiveRow(null); } });
  resultEl.innerHTML = "";
  resultEl.appendChild(card);
  if (window.innerWidth < 820) resultEl.scrollIntoView({ behavior: "smooth", block: "start" });
}

function expandRow(rowEl, p) { showInDetail(p); }

async function refreshList() {
  const q = searchEl.value.trim();
  const r = await fetch(`/api/players?q=${encodeURIComponent(q)}`);
  const players = await r.json();
  listEl.innerHTML = "";
  if (!players.length) {
    listEl.innerHTML = `<div class="empty">${q ? "没找到「" + esc(q) + "」" : "还没有任何记录，上传截图开始记录吧"}</div>`;
    return;
  }
  players.forEach((p) => listEl.appendChild(renderRow(p)));
}

async function doSearch() {
  await refreshList();
  // re-highlight whichever player is currently shown in the detail pane
  const open = resultEl.querySelector(".card[data-id]");
  if (open) setActiveRow(open.dataset.id);
}
searchEl.addEventListener("input", doSearch);

// ---------- auto-lookup (drive game client) ----------
// keys must match the step names emitted by automate.run_auto_lookup.
// "lead_in" is intentionally absent so its countdown message (j.msg) shows.
const STEP_LABELS = {
  focus: "激活游戏", open_social: "打开社交", open_add_friend: "加好友",
  type_id: "输入ID", search: "搜索", open_result: "点开结果",
  open_info: "进角色信息", tab_profile: "截首页", tab_details: "截详细数据",
  switch_mode: "切换数据模式", switch_ranked: "切排位赛",
  tab_history: "截最近战绩", return_home: "退回主页",
  ocr: "本地 OCR 识别中",
};

async function refreshAutoStats() {
  try {
    const r = await fetch("/api/auto-stats");
    if (!r.ok) return;
    const s = await r.json();
    const modeTxt = s.auto_mode === "ocr"
      ? `<span style="color:#6ee787">自动识别 ✔</span>`
      : "手动校准";
    document.getElementById("al-stats").innerHTML =
      `${modeTxt} · 今日 ${s.today_count}/${s.daily_cap} · 间隔 ${s.config.min_interval | 0}–${s.config.max_interval | 0}s`;
  } catch (_) {}
}
refreshAutoStats();
setInterval(refreshAutoStats, 10000);

const alInput = document.getElementById("al-input");
const alStatus = document.getElementById("al-status");
const alGo = document.getElementById("al-go");
const alStop = document.getElementById("al-stop");
let currentJobId = null;          // the job the 停止 button targets

// Toggle the input row between idle and "a job is in flight": show 停止, lock 查询.
function setBusy(busy) {
  alStop.hidden = !busy;
  alStop.disabled = false;
  alGo.disabled = busy;
}

alGo.onclick = autoLookup;
alInput.addEventListener("keydown", (e) => { if (e.key === "Enter") autoLookup(); });
alStop.onclick = async () => {
  if (!currentJobId) return;
  alStop.disabled = true;        // debounce the click; pollJob shows the real state
  alStatus.innerHTML = `<span class="pill pill-run">停止中…</span>`;
  try {
    await fetch(`/api/job/${currentJobId}/cancel`, { method: "POST" });
  } catch (_) { alStop.disabled = false; }   // let them retry if the request itself failed
};

async function autoLookup() {
  const q = alInput.value.trim();
  if (!q) { alStatus.innerHTML = `<span class="pill pill-err">先输入要查的 ID</span>`; return; }
  alStatus.innerHTML = `<span class="pill pill-run">提交中…</span>`;
  try {
    const r = await fetch("/api/auto-lookup", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ query: q }) });
    const body = await r.json();
    if (!r.ok) { alStatus.innerHTML = `<span class="pill pill-err">✘ ${esc(body.error || "失败")}</span>`; return; }
    currentJobId = body.job_id;
    setBusy(true);
    pollJob(body.job_id);
  } catch (e) {
    alStatus.innerHTML = `<span class="pill pill-err">✘ ${esc(String(e))}</span>`;
  }
}

async function pollJob(id) {
  while (true) {
    await new Promise((r) => setTimeout(r, 600));
    let r, j;
    try {
      r = await fetch(`/api/job/${id}`);
      if (!r.ok) { alStatus.innerHTML = `<span class="pill pill-err">任务消失</span>`; setBusy(false); currentJobId = null; return; }
      j = await r.json();
    } catch (_) { continue; }

    if (j.state === "pending") {
      alStatus.innerHTML = `<span class="pill pill-run">排队 · ${esc(j.msg || "")}</span>`;
    } else if (j.state === "running") {
      if (j.step === "lead_in") {
        // grace countdown: prompt the user to bring the game forward
        alStatus.innerHTML = `<span class="pill pill-run">⏳ ${esc(j.msg || "准备中")}</span>`;
      } else {
        const lab = STEP_LABELS[j.step] || j.msg || j.step || "进行中";
        alStatus.innerHTML = `<span class="pill pill-run">🎮 ${esc(lab)}</span>`;
      }
    } else if (j.state === "done") {
      alStatus.innerHTML = `<span class="pill pill-ok">✔ 完成: ${esc(j.player ? j.player.nickname : "")}</span>`;
      setBusy(false); currentJobId = null;
      await refreshList();
      if (j.player) showInDetail(j.player);
      refreshAutoStats();
      return;
    } else if (j.state === "cancelled") {
      alStatus.innerHTML = `<span class="pill pill-warn">■ 已停止</span>`;
      setBusy(false); currentJobId = null;
      refreshAutoStats();
      return;
    } else if (j.state === "error") {
      alStatus.innerHTML = `<span class="pill pill-err">✘ ${esc(j.error || "失败")}</span>`;
      setBusy(false); currentJobId = null;
      refreshAutoStats();
      return;
    }
  }
}

doSearch();
