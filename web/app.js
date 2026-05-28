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
    grid += `<polygon points="${poly(R * f)}" fill="none" stroke="#2a313b" stroke-width="1"/>`;
  });
  let axes = "";
  keys.forEach((_, i) => { const [x, y] = pt(i, R); axes += `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#2a313b" stroke-width="1"/>`; });

  const vals = keys.map((k) => { const v = (radar || {})[k]; return v == null ? 0 : Math.max(0, Math.min(100, v)); });
  const dpts = vals.map((v, i) => pt(i, R * v / 100).map((n) => n.toFixed(1)).join(",")).join(" ");
  const dataPoly = `<polygon points="${dpts}" fill="rgba(255,122,69,.30)" stroke="#ff7a45" stroke-width="2"/>`;
  let dots = "";
  vals.forEach((v, i) => { const [x, y] = pt(i, R * v / 100); dots += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.2" fill="#ff7a45"/>`; });

  let labels = "";
  keys.forEach((k, i) => {
    const [lx, ly] = pt(i, R + labOff);
    const v = (radar || {})[k];
    labels += `<text x="${lx.toFixed(1)}" y="${(ly - 1).toFixed(1)}" text-anchor="middle" font-size="9" fill="#8a919b">${k}</text>`;
    labels += `<text x="${lx.toFixed(1)}" y="${(ly + 10).toFixed(1)}" text-anchor="middle" font-size="12" font-weight="700" fill="#ffd08a">${v == null ? "—" : v}</text>`;
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
    listEl.innerHTML = "";
    resultEl.innerHTML = "";
    resultEl.appendChild(renderCard(body.player));
  } catch (e) { upmsg.textContent = "请求失败：" + e; }
};

// ---------- render ----------
function modeColumn(title, mode, m) {
  if (!m) return `<div class="mode"><h3>${title}</h3><div class="muted">（未上传该截图）</div></div>`;

  const rankStr = [m.rank_name, m.rank_star != null ? "★" + m.rank_star : ""].filter(Boolean).join(" ");
  const v = verdict(m);

  const kdCells = [0, 1, 2].map((i) => {
    const cls = kdClass((m.kd || [])[i]);
    return `<div class="kd ${cls}">
      <input data-mode="${mode}" data-kd="${i}" value="${esc((m.kd || [])[i] ?? "")}" />
      <span class="kdl">${KD_LABELS[i]}</span></div>`;
  }).join("");

  const details = [["段位分", m.rank_score], ...DETAIL_FIELDS.map(([lab, key]) => [lab, m[key]])]
    .map(([k, vv]) => `<div class="k">${k}</div><div class="v">${val(vv)}</div>`).join("");

  return `
    <div class="mode">
      <h3>${title}${v ? ` <span class="verdict ${v.c}">${v.t}</span>` : ""}</h3>

      <div class="kd-block">
        <div class="lab">KD · 普通 / 机密 / 绝密 <span class="tip">（绝密最能看真实水平）</span></div>
        <div class="kd-row">${kdCells}</div>
      </div>

      <div class="keyrow">
        <div class="kbig"><div class="lab">段位</div><div class="bv">${rankStr || "—"}</div></div>
        <div class="kbig"><div class="lab">撤离率</div><div class="bv ${rateClass(m.escape_rate)}">${val(m.escape_rate)}</div></div>
        <div class="kbig"><div class="lab">赚损比</div><div class="bv">${val(m.profit_ratio)}</div></div>
      </div>

      ${radarSVG(m.radar)}

      <button type="button" class="toggle">详细数据 ▾</button>
      <div class="grid details-hidden">${details}</div>
    </div>`;
}

function recentBlock(recent) {
  if (!recent || recent.hidden) return `<div class="recent"><h3>最近战绩</h3><span class="hidden-badge">⚠ 对方隐藏了战绩</span></div>`;
  const rows = (recent.matches || []).map((m) => {
    const ok = m.result === "撤离成功";
    return `<div class="match">
      <span class="${ok ? "res-ok" : "res-fail"}">${ok ? "✔ 撤离成功" : "✘ 撤离失败"}</span>
      <span class="mt">${val(m.map_time)}</span>
      <span class="hf">${m.hafu ? "哈夫币 " + esc(m.hafu) : ""}</span>
      <span class="rc">${val(m.rank_change)}</span>
    </div>`;
  }).join("");
  return `<div class="recent"><h3>最近战绩 · ${(recent.matches || []).length} 场</h3>${rows}</div>`;
}

function renderCard(p) {
  const d = p.data || {};
  const home = d.home || {};
  const el = document.createElement("div");
  el.className = "card";
  el.dataset.id = p.id;
  el.innerHTML = `
    <div class="top">
      <input class="nick" value="${esc(p.nickname)}" title="名字识别错了可直接改" />
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
      <span class="meta">更新于 ${p.updated_at ? new Date(p.updated_at).toLocaleString() : "—"}</span>
    </div>`;

  el.querySelectorAll(".toggle").forEach((btn) => {
    btn.onclick = () => {
      const grid = btn.nextElementSibling;
      const hidden = grid.classList.toggle("details-hidden");
      btn.textContent = hidden ? "详细数据 ▾" : "收起 ▴";
    };
  });
  // recolour KD box when user edits a value
  el.querySelectorAll(".kd input").forEach((inp) => {
    inp.oninput = () => {
      const box = inp.parentElement;
      box.classList.remove("good", "mid", "bad");
      const c = kdClass(inp.value);
      if (c) box.classList.add(c);
    };
  });
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
    el.replaceWith(renderCard(updated));
  } else { alert("保存失败"); }
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
