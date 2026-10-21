/* 一镜一梳本地工作台 · 原生 JS（spec: docs/specs/ui-v1.md，D-111）
   壳逻辑：表单 → API → 展示。零业务判断，质量门/渲染/校验全在后端。 */
'use strict';

const $ = (id) => document.getElementById(id);
let reports = [];           // /ui/reports 缓存
let currentReport = null;   // 报告视图当前选中
let prepImagePath = null;   // 预处理后定稿图路径

/* ---------- 基础工具 ---------- */
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = {};
  try { data = JSON.parse(text); } catch { data = { detail: text }; }
  if (!res.ok) throw new Error(data.detail || `请求失败 (${res.status})`);
  return data;
}
const esc = (s) => String(s ?? '').replace(/[&<>"]/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmtTime = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString('zh-CN', { hour12: false });
};

/* ---------- 健康状态 ---------- */
async function checkHealth() {
  const el = $('health');
  try {
    await api('/health');
    el.textContent = '后端已连接'; el.className = 'health ok';
    $('btn-gen').disabled = !prepImagePath;
  } catch {
    el.textContent = '后端不可达——请先启动: cd backend && .venv/bin/uvicorn app.main:app';
    el.className = 'health bad';
    $('btn-gen').disabled = true;
  }
}

/* ---------- 标签切换 ---------- */
document.querySelectorAll('.tab').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active',
      v.id === 'tab-' + btn.dataset.tab));
    if (btn.dataset.tab === 'cases') loadReports();
    if (btn.dataset.tab === 'qa') refreshQaReportOptions();
  });
});

/* ---------- 新建：上传 → 预处理（原始照片）或仅存盘（已定稿图，v0.1.4） ---------- */
$('final-toggle').addEventListener('change', () => {
  // 模式切换时重置预处理结果，避免用旧参数生成
  prepImagePath = null;
  $('btn-gen').disabled = true;
  $('prep-result').classList.add('hidden');
  $('prep-status').textContent = $('final-toggle').checked
    ? '已定稿模式：上传后不会画叠加圈，请在下方确认/手改五参数' : '';
  if ($('photo').files[0]) $('photo').dispatchEvent(new Event('change'));
});

$('photo').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const st = $('prep-status');
  const finalMode = $('final-toggle').checked;
  st.className = 'status';
  $('prep-result').classList.add('hidden');
  if (finalMode) {
    // 已定稿图：只存盘 + 本地预览，不跑预处理、不画圈
    st.textContent = '存盘中…';
    try {
      const form = new FormData();
      form.append('photo', file);
      const data = await api('/input-prep', { method: 'POST', body: form });
      prepImagePath = data.saved_to;
      $('prep-overlay').src = URL.createObjectURL(file);  // 本地预览原图，不经服务器
      $('p-cx').value = ''; $('p-cy').value = ''; $('p-radius').value = '';
      $('p-r1').value = 0.28; $('p-r2').value = 0.60;
      $('prep-result').classList.remove('hidden');
      $('prep-result').querySelector('.hint').textContent =
        '已定稿原图（无叠加）。五参数默认取图心+R=短边×0.47，请按实际标记核对修改（留空则由程序按图心自动估计）：';
      st.textContent = '已存盘：' + data.saved_to;
      $('btn-gen').disabled = false;
    } catch (err) {
      prepImagePath = null; $('btn-gen').disabled = true;
      st.className = 'status err'; st.textContent = '存盘失败：' + err.message;
    }
    return;
  }
  st.textContent = '预处理中（矫正→裁切→圈界提议）…';
  try {
    const form = new FormData();
    form.append('photo', file);
    const data = await api('/ui/input-prep/run', { method: 'POST', body: form });
    prepImagePath = data.image_path;
    $('prep-overlay').src = data.overlay_url + '?t=' + Date.now();
    $('p-cx').value = data.ring_params.cx;
    $('p-cy').value = data.ring_params.cy;
    $('p-radius').value = data.ring_params.radius;
    $('p-r1').value = data.ring_params.r1_ratio;
    $('p-r2').value = data.ring_params.r2_ratio;
    $('prep-result').classList.remove('hidden');
    $('prep-result').querySelector('.hint').textContent =
      '绿圈 = 基准圆；蓝圈 = 提议圈界。参数可手改：';
    st.textContent = `完成（rectified=${data.rectified}，axis_ratio=${data.axis_ratio}` +
      (data.ring_params.fallback ? '，圈界走了固定比例兜底' : '') + '）';
    $('btn-gen').disabled = false;
  } catch (err) {
    prepImagePath = null; $('btn-gen').disabled = true;
    st.className = 'status err'; st.textContent = '预处理失败：' + err.message;
  }
});

/* ---------- 新建：生成报告 ---------- */
$('btn-gen').addEventListener('click', async () => {
  const theme = $('theme').value.trim();
  if (!theme) { $('gen-status').className = 'status err'; $('gen-status').textContent = '请先填写主题'; return; }
  const ring_params = {};
  for (const [id, key] of [['p-cx', 'cx'], ['p-cy', 'cy'], ['p-radius', 'radius'],
                           ['p-r1', 'r1_ratio'], ['p-r2', 'r2_ratio']]) {
    const v = $(id).value.trim();
    if (v !== '') ring_params[key] = Number(v);  // 留空 → 不传 → 后端按图心/缺省比估计
  }
  const st = $('gen-status');
  st.className = 'status'; st.textContent = '报告生成中… 0s';
  $('gen-progress').classList.remove('hidden');
  $('btn-gen').disabled = true;
  const t0 = Date.now();
  const timer = setInterval(() =>
    st.textContent = `报告生成中… ${((Date.now() - t0) / 1000).toFixed(0)}s`, 1000);
  try {
    const payload = { agent: 'report_gen', payload: {
      image_path: prepImagePath, theme,
      manual_features: $('background').value.trim() || undefined,
      ring_params } };
    const data = await api('/dispatch', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload) });
    if (data.status === 'blocked') {
      clearInterval(timer);
      st.className = 'status err'; st.textContent = '护栏拦截：' + (data.message || '需要人工复核');
      return;
    }
    clearInterval(timer);
    st.textContent = `完成：${data.report_id}`;
    switchTab('cases');
    await loadReports(data.report_id);
  } catch (err) {
    clearInterval(timer);
    st.className = 'status err'; st.textContent = '生成失败：' + err.message;
  } finally {
    $('gen-progress').classList.add('hidden');
    $('btn-gen').disabled = false;
  }
});

function switchTab(name) {
  document.querySelector(`.tab[data-tab="${name}"]`).click();
}
/* ---------- 个案视图 ---------- */
/* 徽标口径（UI-013）：gen-audit-v1 run 无 g1 块（D-013 后质量信号在 audit.md），按 status 显示；
   旧 stage35 run 沿用 g1 质量门口径。 */
function runBadge(r) {
  if (r.pipeline === 'gen-audit-v1') {
    if (r.status === 'completed') return '<span class="badge ok">✓</span>';
    if (r.status === 'blocked') return '<span class="badge bad">✗ 拦截</span>';
    return '<span class="badge warn">⚠</span>';
  }
  const g1 = r.g1;
  if (!g1 || g1.passed === false && !g1.needs_review) return '<span class="badge bad">✗</span>';
  if (g1.needs_review) return '<span class="badge warn">⚠ 需复核</span>';
  return '<span class="badge ok">✓</span>';
}

async function loadReports(selectId) {
  const list = $('report-list');
  try {
    reports = await api('/ui/reports');
  } catch (err) {
    list.innerHTML = `<p class="status err">${esc(err.message)}</p>`; return;
  }
  if (!reports.length) {
    list.innerHTML = `<div class="empty-state" style="padding:2rem 1rem">
      <div class="glyph">◎</div>
      <div class="title">还没有个案</div>
      <p class="desc">到「新建个案」上传一幅曼陀罗，生成第一份解读报告。</p>
    </div>`;
    return;
  }
  list.innerHTML = reports.map((r) => `
    <div class="item" data-id="${esc(r.report_id)}">
      <div class="t">${esc(r.theme || '(无主题)')} ${runBadge(r)}</div>
      <div class="m">${esc(fmtTime(r.started_at))}${r.edited_at ? ' · 已编辑' : ''}</div>
    </div>`).join('');
  list.querySelectorAll('.item').forEach((el) =>
    el.addEventListener('click', () => showReport(el.dataset.id)));
  if (selectId) showReport(selectId);
  else if (currentReport) showReport(currentReport);
}

async function showReport(id) {
  currentReport = id;
  $('report-detail').classList.remove('hidden');
  $('trace-panels').classList.remove('hidden');
  document.querySelectorAll('#report-list .item').forEach((el) =>
    el.classList.toggle('sel', el.dataset.id === id));
  const head = $('report-head');
  head.innerHTML = '<p class="hint">加载中…</p>';
  $('trace-box').innerHTML = '<p class="hint">追溯链加载中…</p>';
  let d;
  try { d = await api('/ui/reports/' + encodeURIComponent(id)); }
  catch (err) {
    head.innerHTML = `<p class="status err">${esc(err.message)}</p>`; return;
  }

  const isGA = d.pipeline === 'gen-audit-v1';
  const g = d.g1 || {};
  const flags = g.flags || {};
  const flagNames = { orphan_accepted_claims: '孤儿 claim', forbidden_phrases: '禁语',
    marker_line_evidence_claims: '标记线证据', pending_terms_used_in_body: '待定术语',
    exemplar_copy_spans: '照搬片段', unanchored_statements: '未锚定画面句' };
  const flagRows = Object.entries(flags).map(([k, v]) =>
    `<div class="row"><span>${flagNames[k] || k}</span><b class="${v > 0 ? 'hot' : ''}">${v}</b></div>`).join('');

  // gen-audit run 无 g1 块：质量信号是 audit.md（合规核查 + 超纲清单，D-013），卡片指过去而非复制口径
  const gateHtml = isGA ? `
    <div class="gate">
      <div class="row"><span>生成链路</span><b>gen-audit 三步（D-013）</b></div>
      <div class="row"><span>状态</span><b>${esc(d.status)}</b></div>
      <div class="row"><span>合规与超纲核查</span><b>${d.has_audit_md ? 'audit.md · 见追溯链' : 'audit.md 缺失'}</b></div>
    </div>` : `
    <div class="gate">
      <div class="row"><span>G1 质量门</span><b class="${g.passed ? '' : 'hot'}">${g.passed ? '通过' : '未通过'}</b></div>
      <div class="row"><span>accepted claims</span><b>${g.accepted_claim_count ?? 0}</b></div>
      ${flagRows}
    </div>`;

  head.innerHTML = `
    <h2>${esc(d.theme || '(无主题)')} ${runBadge(d)}</h2>
    ${d.image_path ? `<img class="preview" src="/ui/reports/${encodeURIComponent(id)}/image" alt="画作" onerror="this.remove()">` : ''}
    ${gateHtml}
    <p>
      <button class="plain" id="btn-preview">预览 HTML</button>
      <button class="plain" id="btn-edit">编辑 md</button>
      <button class="plain" id="btn-rerender">重新渲染</button>
      <button class="plain" id="btn-toqa">去问答</button>
    </p>
    <div id="run-meta" class="run-meta"></div>
    <div id="edit-box" class="hidden">
      <textarea class="md" id="md-editor" rows="18"></textarea>
      <p><button class="primary" id="btn-save">保存并重渲</button>
         <span id="save-status" class="status"></span></p>
    </div>
    <p class="meta" id="rerender-status"></p>`;

  let pipeline = null;
  if (isGA) {
    try { pipeline = await api('/ui/reports/' + encodeURIComponent(id) + '/pipeline'); }
    catch (err) { pipeline = { legacy: false, steps: [], error: err.message }; }
  }
  renderRunMeta(d, pipeline);
  $('btn-preview').onclick = () => window.open('/ui/reports/' + encodeURIComponent(id) + '/html', '_blank');
  $('btn-edit').onclick = () => {
    $('edit-box').classList.toggle('hidden');
    $('md-editor').value = d.report_md || '';
  };
  $('btn-rerender').onclick = async () => {
    const st = $('rerender-status');
    st.textContent = '渲染中…';
    try {
      const r = await api(`/ui/reports/${encodeURIComponent(id)}/re-render`, { method: 'POST' });
      st.textContent = `已重渲（${r.render_ms}ms）`;
    } catch (err) { st.textContent = '渲染失败：' + err.message; }
  };
  $('btn-save').onclick = async () => {
    const st = $('save-status');
    st.className = 'status'; st.textContent = '保存中…';
    try {
      const r = await api(`/ui/reports/${encodeURIComponent(id)}/report-md`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ report_md: $('md-editor').value }) });
      st.textContent = `已保存并重渲（${r.render_ms}ms）`;
      await loadReports(id);
    } catch (err) { st.className = 'status err'; st.textContent = '保存失败：' + err.message; }
  };
  $('btn-toqa').onclick = () => {
    switchTab('qa');
    $('qa-report').value = id;
    $('qa-report').dispatchEvent(new Event('change'));
  };
  renderTrace(id, d, pipeline);
}

/* ---------- Round 详情（第二栏四按钮下方，v0.1.10）：耗时秒/分 + 每步拆解 + token/费用估算 ---------- */
/* 模型单价（元/百万 token，输入/输出）——官方价格随时间调整，展示口径待校准 */
const MODEL_PRICE = { 'kimi-k3': { in: 4.0, out: 16.0 }, 'k3': { in: 4.0, out: 16.0 },
  'deepseek-chat': { in: 1.0, out: 2.0 } };
/* 旧 stage35 run 的耗时/token 步键（gen-audit run 走 pipeline 端点，不经过这两张表） */
const TIMING_STEPS = [['kimi_perception', '画面感知'], ['deepseek_signals', '信号整理'],
  ['deepseek_hypotheses', '候选假设'], ['deepseek_report', '报告成文'], ['render', '渲染交付']];
const TOKEN_STEPS = [['kimi_perception', '画面感知', 'vision'], ['deepseek_signals', '信号整理', 'text'],
  ['deepseek_hypotheses', '候选假设', 'text'], ['deepseek_report', '报告成文', 'text']];

function fmtDur(ms) {
  if (ms == null) return '—';
  const s = ms / 1000;
  const sStr = s >= 100 ? `${s.toFixed(0)}s` : `${s.toFixed(1)}s`;
  if (s < 90) return sStr;
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return `${m}分${r}秒（${sStr}）`;
}

function renderRunMeta(d, pipeline) {
  const box = $('run-meta');
  if (!box) return;
  if (pipeline && !pipeline.legacy) return renderRunMetaGA(d, pipeline, box);
  const tm = d.timings_ms || {};
  const tu = d.token_usage || {};
  const recorded = TIMING_STEPS.reduce((n, [k]) => n + (tm[k] || 0), 0);
  const rest = (d.elapsed_ms != null && recorded) ? Math.max(0, d.elapsed_ms - recorded) : null;
  let tokIn = 0, tokOut = 0, cost = 0;
  const tokenRows = TOKEN_STEPS.map(([key, name, which]) => {
    const u = tu[key];
    if (!u) return '';
    const model = (d.models || {})[which] || which;
    const price = MODEL_PRICE[model] || { in: 0, out: 0 };
    const tin = u.prompt_tokens || 0, tout = u.completion_tokens || 0;
    tokIn += tin; tokOut += tout;
    cost += tin / 1e6 * price.in + tout / 1e6 * price.out;
    return `<div class="row"><span>${name}</span>` +
      `<b>入 ${(tin / 1000).toFixed(1)}k / 出 ${(tout / 1000).toFixed(1)}k</b></div>`;
  }).join('');
  box.innerHTML = `
    <h3>Round 详情</h3>
    <div class="row"><span>Round ID</span><b>${esc(d.report_id)}</b></div>
    <div class="row"><span>开始时间</span><b>${esc(fmtTime(d.started_at))}</b></div>
    <div class="row"><span>总耗时</span><b>${fmtDur(d.elapsed_ms)}</b></div>
    <div class="sec">
      <div class="row"><span>每步耗时</span><b></b></div>
      ${TIMING_STEPS.map(([k, name]) =>
        `<div class="row"><span>${name}</span><b>${tm[k] != null ? fmtDur(tm[k]) : '未计时'}</b></div>`).join('')}
      ${rest != null ? `<div class="row"><span>其余（程序步+开销）</span><b>${fmtDur(rest)}</b></div>` : ''}
    </div>
    <div class="sec">
      <div class="row"><span>Token 消耗</span><b></b></div>
      ${tokenRows || '<div class="row"><span>—</span><b></b></div>'}
      <div class="row"><span>合计</span><b>入 ${(tokIn / 1000).toFixed(1)}k / 出 ${(tokOut / 1000).toFixed(1)}k</b></div>
      ${cost ? `<div class="row"><span>费用估算</span><b class="cost">¥${cost.toFixed(3)}</b></div>` : ''}
    </div>`;
}

/* gen-audit run 的 Round 详情：逐步耗时/token 由 /pipeline 下发（UI-013，前端不复制步键口径） */
function renderRunMetaGA(d, pipeline, box) {
  const steps = pipeline.steps || [];
  const recorded = steps.reduce((n, s) => n + (s.cost_ms || 0), 0);
  const rest = (d.elapsed_ms != null && recorded) ? Math.max(0, d.elapsed_ms - recorded) : null;
  let tokIn = 0, tokOut = 0, cost = 0, costKnown = false;
  const tokenRows = steps.map((s) => {
    if (!s.tokens) return '';
    const price = MODEL_PRICE[s.tool];
    const tin = s.tokens.prompt || 0, tout = s.tokens.completion || 0;
    tokIn += tin; tokOut += tout;
    if (price) { cost += tin / 1e6 * price.in + tout / 1e6 * price.out; costKnown = true; }
    return `<div class="row"><span>${s.name}</span>` +
      `<b>入 ${(tin / 1000).toFixed(1)}k / 出 ${(tout / 1000).toFixed(1)}k</b></div>`;
  }).join('');
  box.innerHTML = `
    <h3>Round 详情</h3>
    <div class="row"><span>Round ID</span><b>${esc(d.report_id)}</b></div>
    <div class="row"><span>开始时间</span><b>${esc(fmtTime(d.started_at))}</b></div>
    <div class="row"><span>总耗时</span><b>${fmtDur(d.elapsed_ms)}</b></div>
    <div class="sec">
      <div class="row"><span>每步耗时</span><b></b></div>
      ${steps.map((s) =>
        `<div class="row"><span>${s.name}</span><b>${s.cost_ms != null ? fmtDur(s.cost_ms) : '未计时'}</b></div>`).join('')}
      ${rest != null ? `<div class="row"><span>其余（渲染+开销）</span><b>${fmtDur(rest)}</b></div>` : ''}
    </div>
    <div class="sec">
      <div class="row"><span>Token 消耗</span><b></b></div>
      ${tokenRows || '<div class="row"><span>—</span><b></b></div>'}
      <div class="row"><span>合计</span><b>入 ${(tokIn / 1000).toFixed(1)}k / 出 ${(tokOut / 1000).toFixed(1)}k</b></div>
      ${costKnown ? `<div class="row"><span>费用估算</span><b class="cost">¥${cost.toFixed(3)}</b></div>` : ''}
    </div>`;
}

/* ---------- 追溯链（spec UI-008）+ 审核备注（spec UI-009，v0.1.2） ---------- */
const HYP_NAMES = { direct_pattern_hits: '直读模式', five_elements: '五行分布',
  imbalance_hypotheses: '失衡假设', state_hypotheses: '状态假设', topic_hypotheses: '议题假设' };
let reviewCache = {};                    // key -> {checked, note}
const reviewTimers = new Map();          // key -> 各自防抖定时器（共享定时器会吞掉快速连续编辑）

/* 审核单元格：key 稳定标识；checked 打勾、note 备注 */
function rvCells(key) {
  const r = reviewCache[key] || {};
  return `<td class="rvc"><input type="checkbox" class="rv-check" data-key="${esc(key)}" ${r.checked ? 'checked' : ''}></td>` +
    `<td class="rvn"><input class="rv-note" data-key="${esc(key)}" value="${esc(r.note || '')}" placeholder="备注…"></td>`;
}
const rvHeads = '<th class="rvc">✓</th><th class="rvn">审核备注</th>';

async function saveReview(key, patch) {
  const cur = reviewCache[key] || {};
  reviewCache[key] = { ...cur, ...patch };
  clearTimeout(reviewTimers.get(key));
  reviewTimers.set(key, setTimeout(async () => {
    try { await api(`/ui/reports/${currentReport}/review`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, ...patch }) }); }
    catch (e) { console.error('审核保存失败', e); }
  }, 400));
}

function reviewSummary() {
  const items = Object.values(reviewCache);
  const n = items.filter((x) => x.checked).length;
  const m = items.filter((x) => x.note).length;
  return n || m ? `｜ 已勾 ${n} · 备注 ${m} 条` : '';
}

function bindReviewInputs(root) {
  root.querySelectorAll('.rv-check').forEach((el) =>
    el.addEventListener('change', () => saveReview(el.dataset.key, { checked: el.checked })));
  root.querySelectorAll('.rv-note').forEach((el) =>
    el.addEventListener('change', () => saveReview(el.dataset.key, { note: el.value })));
}

/* 链路面板映射（UI-013）：gen-audit 三步由 /pipeline 下发结构，前端只映射到面板；
   旧 stage35 run 保留七步历史浏览（产物以已落盘文件为准）。 */
const PANEL_OF_STEP_LEGACY = { 1: 'panel-perception', 2: 'panel-signals', 3: 'panel-observations',
  4: 'panel-hypotheses', 5: 'panel-claims', 6: 'panel-sourced', 7: null };
const PANEL_OF_STEP_GA = { 1: 'panel-report-md', 2: 'panel-audit', 3: null };
let currentPanelMap = PANEL_OF_STEP_LEGACY;
let traceCache = null;   // 当前报告 trace 数据（步骤按钮定位用）

/* gen-audit 链路渲染：步骤结构来自 /pipeline 端点（后端 _STEP_META 唯一定义） */
function genAuditPipelineHtml(p) {
  const fmtCost = (s) => {
    const parts = [];
    if (s.cost_ms != null) parts.push(`${(s.cost_ms / 1000).toFixed(1)}s`);
    if (s.tokens && s.tokens.total != null) parts.push(`${(s.tokens.total / 1000).toFixed(1)}k tok`);
    return parts.join(' · ') || '—';
  };
  const outText = (s) => (s.outputs || [])
    .map((o) => `${o.file}${o.exists ? '' : '（缺失）'}`).join(' + ');
  return `<div class="pipe"><div class="pipe-title">🧭 生成链路（gen-audit 三步，D-013）：查输入=prompt 原文/程序文件 · 查输出=该步产物 · 表格=结构化视图</div>` +
    p.steps.map((s) => `
      <div class="pipe-step">
        <div class="pipe-head"><b>${s.n}. ${esc(s.name)}</b><span class="pipe-tool">${esc(s.tool)}</span>
          <span class="pipe-cost">${esc(fmtCost(s))}</span></div>
        <div class="pipe-io"><span class="pipe-in">输入：${esc(s.input_note)}</span>
          <span class="pipe-arrow">→</span>
          <span class="pipe-out">输出：${esc(outText(s))}</span></div>
        <div class="pipe-btns">
          <button class="mini" data-step="${s.n}" data-view="input">查输入</button>
          <button class="mini" data-step="${s.n}" data-view="output">查输出</button>
          <button class="mini" data-step="${s.n}" data-view="table">表格</button>
        </div>
      </div>`).join('') + '</div>';
}

/* 旧 stage35 链路七步（仅历史 run 浏览用）：每步输入/输出/工具/成本 + 三个查看按钮（UI-012） */
function legacyPipelineHtml(t) {
  const m = t.run_meta || {};
  const tm = m.timings_ms || {};
  const tu = m.token_usage || {};
  const pick = (obj, keys) => { for (const k of keys) if (obj[k] != null) return obj[k]; return null; };
  const cost = (tKeys) => {
    const v = pick(tm, tKeys), tok = pick(tu, tKeys);
    const parts = [];
    if (v != null) parts.push(`${(v / 1000).toFixed(1)}s`);
    if (tok) parts.push(`${(tok.total_tokens / 1000).toFixed(1)}k tok`);
    return parts.join(' · ') || '—';
  };
  const vision = (m.models && m.models.vision) || '视觉模型';
  const text = (m.models && m.models.text) || '文本模型';
  const hypTotal = Object.values(t.hypotheses).reduce((n, v) => n + v.length, 0);
  const steps = [
    { n: 1, name: '画面感知', tool: vision, ai: true,
      input: 'prompt + 矫正定稿图（三圈参数已由输入预处理定稿）',
      output: `perception.md（${t.perception_md.length} 字，视觉模型的自然语言画面描述）`,
      cost: cost(['kimi_perception', 'kimi_shape']) },
    { n: 2, name: '信号整理', tool: text, ai: true,
      input: 'prompt（标记圆线说明 + perception.md）',
      output: `signals.json：色块 ${t.signals.blocks.length} 块、结构 ${t.signals.structures.length} 条（含 quote 引文）+ 模糊点 ${t.ambiguities.length}`,
      cost: cost(['deepseek_signals']) },
    { n: 3, name: '观察注册', tool: '程序 · 不经 AI',
      input: 'signals.json',
      output: `observations.json：观察 ${t.observations.length} 条（V-xxx 结构/渐变 · K-xxx 色块锚点）`,
      cost: '—' },
    { n: 4, name: '候选假设', tool: text, ai: true,
      input: 'prompt（描述 + 信号 + 知识库 8 文件 + 主题）',
      output: `hypotheses.json：候选 ${hypTotal} 条（直读/五行/失衡/状态/议题，各带置信度与支撑观察）`,
      cost: cost(['deepseek_hypotheses', 'deepseek_candidates']) },
    { n: 5, name: 'claim 校验', tool: '程序 · 确定性规则（D-097/098/108）',
      input: '候选假设 + 观察锚点',
      output: `claims.json：accepted ${t.claims.accepted.length} 条 / needs_human ${t.claims.needs_human.length} 条（置信度门+颜色五行一致性+推导链）`,
      cost: '—' },
    { n: 6, name: '报告成文', tool: text, ai: true,
      input: 'prompt（accepted claims + 黄金示范 + one-shot 写法示例）',
      output: 'report.md + report.sourced.md（〔来源：X〕行级标注）→ G1 反向核对（照搬/未锚定，见复核清单）',
      cost: cost(['deepseek_report']) },
    { n: 7, name: '渲染交付', tool: '程序 · 规则映射（D-110，不经 LLM）',
      input: 'report.md',
      output: 'report.html 单文件（米色鎏金主题，打印适配 = PDF 路径 D-109）',
      cost: cost(['render']) },
  ];
  return `<div class="pipe"><div class="pipe-title">🧭 生成链路：每步输入/输出（查输入=prompt/程序文件 · 查输出=该步产物 · 表格=结构化视图）</div>` +
    steps.map((st) => `
      <div class="pipe-step">
        <div class="pipe-head"><b>${st.n}. ${st.name}</b><span class="pipe-tool">${esc(st.tool)}</span>
          <span class="pipe-cost">${esc(st.cost)}</span></div>
        <div class="pipe-io"><span class="pipe-in">输入：${esc(st.input)}</span>
          <span class="pipe-arrow">→</span>
          <span class="pipe-out">输出：${esc(st.output)}</span></div>
        <div class="pipe-btns">
          <button class="mini" data-step="${st.n}" data-view="input">查输入</button>
          <button class="mini" data-step="${st.n}" data-view="output">查输出</button>
          <button class="mini" data-step="${st.n}" data-view="table">表格</button>
          ${st.n === 1 ? '<button class="mini" data-step="1" data-view="score">记分牌</button>' : ''}
        </div>
      </div>`).join('') + '</div>';
}

/* 步骤三按钮：查输入 / 查输出 → 右栏查看器；表格 → 右栏对应面板（第 7 步无面板，开 HTML 预览） */

/* 感知记分牌（D-119）：perception.md × 真值表自动对分，✓绿 ✗红 未提灰 */
async function renderScoreBoard() {
  const v = $('step-viewer');
  if (!v) return;
  v.classList.remove('hidden');
  v.innerHTML = '<p class="hint">记分牌加载中…</p>';
  v.scrollIntoView({ behavior: 'smooth', block: 'start' });
  let d;
  try { d = await api(`/ui/reports/${encodeURIComponent(currentReport)}/perception-score`); }
  catch (err) { v.innerHTML = `<p class="status err">${esc(err.message)}</p>`; return; }
  if (!d.enabled) {
    v.innerHTML = `<h3>1. 画面感知 · 记分牌</h3><p class="hint">${esc(d.reason)}</p>` +
      '<button class="plain" id="viewer-close">收起</button>';
    $('viewer-close').addEventListener('click', () => v.classList.add('hidden'));
    return;
  }
  const badge = (verdict) => verdict === '✓' ? '<span class="verdict ok">✓</span>'
    : verdict === '✗' ? '<span class="verdict bad">✗</span>' : '<span class="verdict mid">未提</span>';
  const rows = d.items.map((i) =>
    `<tr><td>${esc(i.region)}</td><td>${esc(i.item)}</td><td>${esc(i.truth_desc)}</td>` +
    `<td>${badge(i.verdict)}${i.note ? ' <span class="note">' + esc(i.note) + '</span>' : ''}</td></tr>`).join('');
  v.innerHTML = `<h3>1. 画面感知 · 记分牌（${esc(d.painting)} · 真值表 ${esc(d.truth)}）</h3>` +
    `<p class="meta">命中率 <b>${d.hit}/${d.total}</b> · 辅助判分最终以人工审定为准 · ✗/未提先核对是不是话术差异</p>` +
    `<table class="score"><thead><tr><th>区域</th><th>条目</th><th>真值</th><th>本 run 判定</th></tr></thead><tbody>${rows}</tbody></table>` +
    '<button class="plain" id="viewer-close">收起</button>';
  $('viewer-close').addEventListener('click', () => v.classList.add('hidden'));
}

async function onStepBtn(step, view) {
  if (view === 'score') { return renderScoreBoard(); }
  if (view === 'table') {
    const panelId = currentPanelMap[step];
    if (!panelId) { window.open('/ui/reports/' + encodeURIComponent(currentReport) + '/html', '_blank'); return; }
    const el = $(panelId);
    if (!el) return;
    el.open = true;
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    el.classList.add('flash');
    setTimeout(() => el.classList.remove('flash'), 1600);
    return;
  }
  const v = $('step-viewer');
  if (!v) return;
  v.classList.remove('hidden');
  v.innerHTML = '<p class="hint">加载中…</p>';
  v.scrollIntoView({ behavior: 'smooth', block: 'start' });
  let d;
  try { d = await api(`/ui/reports/${encodeURIComponent(currentReport)}/step/${step}`); }
  catch (err) { v.innerHTML = `<p class="status err">${esc(err.message)}</p>`; return; }
  const parts = [];
  if (view === 'input') {
    const i = d.input;
    parts.push(`<h3>${d.step}. ${esc(d.name)} · 输入</h3>` +
      `<p class="meta">${esc(i.label)}${i.note ? ' ｜ ' + esc(i.note) : ''}</p>`);
    if (i.rebuilt) parts.push(`<p class="hint">⚠ ${esc(i.rebuilt)}</p>`);
    parts.push(i.content == null
      ? `<p class="hint">${esc(i.missing_hint || '无内容')}</p>`
      : `<pre>${esc(i.content)}</pre>`);
  } else {
    parts.push(`<h3>${d.step}. ${esc(d.name)} · 输出</h3>`);
    for (const o of d.outputs) {
      parts.push(`<p class="meta">${esc(o.label)}</p>`);
      parts.push(o.content == null
        ? `<p class="hint">${esc(o.missing_hint)}</p>`
        : `<pre>${esc(o.content)}</pre>`);
    }
  }
  parts.push('<button class="plain" id="viewer-close">收起</button>');
  v.innerHTML = parts.join('');
  $('viewer-close').onclick = () => v.classList.add('hidden');
}

function reviewBlock(t) {
  const f = t.g1_flags_detail || {};
  const nh = t.claims.needs_human || [];
  const rows = [];
  const un = f.unanchored_statements || [];
  if (un.length) {
    rows.push(`<div class="rev"><b>⚠ 未锚定画面句（报告写了、证据链里没有，G1 反向核对 D-108）：</b><ul>` +
      un.map((x, i) => { const key = `flag:unanchored_statements:${i}`;
        return `<li>${esc(typeof x === 'string' ? x : JSON.stringify(x))} ${rvCells(key)}</li>`; }).join('') +
      '</ul></div>');
  }
  const ex = f.exemplar_copy_spans || [];
  const st = f.exemplar_structure_spans;   // v0.6.8 起分轻重；旧 run 无此字段 → 全部按真照搬展示
  if (ex.length) {
    const head = st === undefined
      ? `⚠ 与示范报告的相似片段（${ex.length} 处，旧口径未分轻重）：`
      : `⚠ 照搬示范片段（真照搬：≥15 个实义字连续重合，${ex.length} 处）：`;
    rows.push(`<div class="rev"><b>${head}</b>` +
      (st === undefined || ex.length <= 5 ? '' : '<details><summary>展开明细（可逐条标注）</summary>') +
      `<ul>` +
      ex.map((x, i) => { const key = `flag:exemplar_copy_spans:${i}`;
        return `<li>${esc(x)} ${rvCells(key)}</li>`; }).join('') + '</ul>' +
      (st === undefined || ex.length <= 5 ? '' : '</details>') + '</div>');
  }
  if (st && st.length) {
    rows.push(`<div class="rev structure"><b>结构重合（标点/markdown 骨架凑出的重合，${st.length} 处，不算照搬）：</b>` +
      `<details><summary>展开明细（可逐条标注）</summary><ul>` +
      st.map((x, i) => { const key = `flag:exemplar_structure_spans:${i}`;
        return `<li>${esc(x)} ${rvCells(key)}</li>`; }).join('') + '</ul></details></div>');
  }
  if ((f.orphan_accepted_claims || []).length) {
    rows.push(`<div class="rev"><b>⚠ 孤儿 claim（进了报告但证据链断裂）：</b> ${esc(JSON.stringify(f.orphan_accepted_claims))}</div>`);
  }
  if ((f.forbidden_phrases || []).length) {
    rows.push(`<div class="rev"><b>⚠ 命中禁语：</b> ${esc(JSON.stringify(f.forbidden_phrases))}</div>`);
  }
  if (nh.length) {
    rows.push(`<div class="rev"><b>⚠ needs_human 候选（未进报告，共 ${nh.length} 条——勾=同意纳入，备注=理由）：</b>` +
      `<table><tr><th>ID</th><th>类型</th><th>内容</th><th>置信度</th><th>原因</th>${rvHeads}</tr>` +
      nh.map((c) => `<tr><td>${esc(c.claim_id)}</td><td>${esc(c.claim_type)}</td><td>${esc(c.text)}</td>` +
        `<td>${c.confidence ?? '—'}</td><td>${esc(c.needs_human_reason || '')}</td>${rvCells('claim:' + c.claim_id)}</tr>`).join('') + '</table></div>');
  }
  return rows.length ? `<div class="review">${rows.join('')}</div>` : '';
}

function chainCounts(t) {
  const hypTotal = Object.values(t.hypotheses).reduce((n, v) => n + v.length, 0);
  return `<p class="meta">观察 ${t.observations.length}（视觉原始 ${t.vision_observations.length}）→ 信号块 ${t.signals.blocks.length}` +
    ` → 候选假设 ${hypTotal} → accepted claim ${t.claims.accepted.length}` +
    `${t.claims.needs_human.length ? `（另有 <b class="hot">${t.claims.needs_human.length}</b> 条 needs_human）` : ''}` +
    ` <span id="rv-summary">${reviewSummary()}</span></p>`;
}

async function renderTrace(id, d, pipeline) {
  const box = $('trace-box');
  const panels = $('trace-panels');
  if (!box || !panels) return;
  box.innerHTML = '<p class="hint">追溯链加载中…</p>';
  panels.innerHTML = '';

  /* gen-audit run：链路结构由 /pipeline 下发；证据面板 = audit.md 核查表 + report.md 初稿；
     条目级审核 key 体系待重做（spec 未决事项），本期仅总评注 */
  if (pipeline && !pipeline.legacy) {
    currentPanelMap = PANEL_OF_STEP_GA;
    let rv = { items: {} };
    try { rv = await api('/ui/reports/' + encodeURIComponent(id) + '/review'); }
    catch (e) { console.error('审核备注加载失败', e); }
    reviewCache = rv.items || {};
    if (pipeline.error) {
      box.innerHTML = `<p class="status err">链路信息加载失败：${esc(pipeline.error)}</p>`;
      return;
    }
    box.innerHTML = `<h2>追溯链</h2>${genAuditPipelineHtml(pipeline)}`;
    box.querySelectorAll('.mini').forEach((b) =>
      b.addEventListener('click', () => onStepBtn(+b.dataset.step, b.dataset.view)));
    panels.innerHTML = `
      <div id="step-viewer" class="step-viewer hidden"></div>
      <div class="general-rv">
        <label>总评注（整份报告审核意见）</label>
        <textarea id="general-note" rows="2" placeholder="例如：超纲 #1 直断逆用删除；#2 散水点断进账保留…">${esc(reviewCache.general?.note || '')}</textarea>
      </div>
      ${d.audit_md ? `<details id="panel-audit" open><summary>合规核查与超纲清单（audit.md · 疗愈师终审草稿，D-013）</summary><pre>${esc(d.audit_md)}</pre></details>` : ''}
      ${d.report_md ? `<details id="panel-report-md"><summary>报告初稿（report.md）</summary><pre>${esc(d.report_md)}</pre></details>` : ''}`;
    const gn = $('general-note');
    gn.addEventListener('change', () => saveReview('general', { note: gn.value }));
    return;
  }

  /* 旧 stage35 run：七步链路历史浏览（产物以已落盘文件为准，UI-008） */
  currentPanelMap = PANEL_OF_STEP_LEGACY;
  let t, rv;
  try {
    [t, rv] = await Promise.all([
      api('/ui/reports/' + encodeURIComponent(id) + '/trace'),
      api('/ui/reports/' + encodeURIComponent(id) + '/review')]);
  } catch (err) {
    box.innerHTML = `<p class="status err">追溯链加载失败：${esc(err.message)}</p>`; return;
  }
  if (!box.isConnected) return;
  reviewCache = rv.items || {};
  traceCache = t;

  const obsRows = t.observations.map((o) =>
    `<tr><td>${esc(o.observation_id)}</td><td>${esc(o.ring || '')}</td><td>${esc(o.kind || '')}</td>` +
    `<td>${esc(o.description || '')}</td><td>${o.confidence ?? '—'}</td>${rvCells('obs:' + o.observation_id)}</tr>`).join('');
  const hypRows = Object.entries(t.hypotheses).filter(([, v]) => v.length).map(([k, v]) =>
    v.map((h, i) => {
      const hid = h.pattern_id || i;
      const support = (h.support_observation_ids || h.source_observation_ids || []);
      return `<tr><td>${HYP_NAMES[k] || k}</td><td>${esc(h.pattern_id || h.text || '')}</td>` +
        `<td>${h.confidence ?? '—'}</td>` +
        `<td>${esc(support.join('+') || '无画面支撑')}</td>${rvCells(`hyp:${k}:${hid}`)}</tr>`;
    }).join('')).join('');
  const sigRows = t.signals.blocks.map((b, i) =>
    `<tr><td>${esc(b.ring || '')}</td><td>${esc(b.color_raw || '')}</td><td>${esc(b.shape_brief || '')}</td>` +
    `<td>${esc(b.position || '')}</td><td>${esc(b.quantity_tier || '')}</td>${rvCells('sig:' + (b.block_id ?? i))}</tr>`).join('');
  const accRows = t.claims.accepted.map((c) =>
    `<tr><td>${esc(c.claim_id)}</td><td>${esc(c.claim_type)}</td><td>${esc(c.text)}</td>` +
    `<td>${esc((c.source_observation_ids || []).join(',') || (c.knowledge_rule_refs || []).join(',') || '—')}</td>` +
    `${rvCells('claim:' + c.claim_id)}</tr>`).join('');

  box.innerHTML = `<h2>追溯链</h2>${legacyPipelineHtml(t)}`;
  box.querySelectorAll('.mini').forEach((b) =>
    b.addEventListener('click', () => onStepBtn(+b.dataset.step, b.dataset.view)));

  panels.innerHTML = `
    <div id="step-viewer" class="step-viewer hidden"></div>
    <div class="general-rv">
      <label>总评注（整份报告审核意见）</label>
      <textarea id="general-note" rows="2" placeholder="例如：整体方向可信；眼形句删除；五行木旺待核实…">${esc(reviewCache.general?.note || '')}</textarea>
    </div>
    ${reviewBlock(t) || '<p class="hint">✓ 无复核项</p>'}
    ${chainCounts(t)}
    ${t.perception_md ? `<details id="panel-perception"><summary>① 画面感知（视觉模型原始描述）</summary><pre>${esc(t.perception_md)}</pre></details>` : ''}
    ${t.observations.length ? `<details id="panel-observations" open><summary>② 画面观察（程序解析 V-xxx，共 ${t.observations.length} 条）</summary>
      <table><tr><th>ID</th><th>圈层</th><th>类型</th><th>描述</th><th>置信度</th>${rvHeads}</tr>${obsRows}</table></details>` : ''}
    ${sigRows ? `<details id="panel-signals"><summary>③ 颜色信号块（共 ${t.signals.blocks.length} 块）</summary>
      <table><tr><th>圈层</th><th>颜色</th><th>形状</th><th>位置</th><th>量级</th>${rvHeads}</tr>${sigRows}</table></details>` : ''}
    ${hypRows ? `<details id="panel-hypotheses"><summary>④ 候选假设（逐条：置信度与画面支撑）</summary>
      <table><tr><th>层</th><th>命中</th><th>置信度</th><th>支撑观察</th>${rvHeads}</tr>${hypRows}</table></details>` : ''}
    ${accRows ? `<details id="panel-claims"><summary>⑤ accepted claims（进报告的证据，共 ${t.claims.accepted.length} 条）</summary>
      <table><tr><th>ID</th><th>类型</th><th>内容</th><th>证据来源</th>${rvHeads}</tr>${accRows}</table></details>` : ''}
    ${t.report_sourced_md ? `<details id="panel-sourced" class="sourced"><summary>⑥ 带标注报告（〔来源：X〕行级标注）</summary><pre>${esc(t.report_sourced_md)}</pre></details>` : ''}
    ${(t.ambiguities.length || t.questions_for_healer.length) ? `<details><summary>⑦ 给疗愈师的模糊点与提问（共 ${t.ambiguities.length + t.questions_for_healer.length} 条）</summary>
      <pre>${esc([...t.ambiguities, ...t.questions_for_healer].map((x) => typeof x === 'string' ? x : JSON.stringify(x, null, 1)).join('\n\n'))}</pre></details>` : ''}`;
  bindReviewInputs(panels);
  const gn = $('general-note');
  gn.addEventListener('change', () => {
    saveReview('general', { note: gn.value });
    const sum = $('rv-summary');
    if (sum) sum.textContent = reviewSummary();
  });
  panels.addEventListener('change', (e) => {
    if (e.target.classList.contains('rv-check') || e.target.classList.contains('rv-note')) {
      const sum = $('rv-summary');
      if (sum) sum.textContent = reviewSummary();
    }
  });
}

/* ---------- 问答视图 ---------- */
function refreshQaReportOptions() {
  const sel = $('qa-report');
  const prev = sel.value;
  sel.innerHTML = reports.map((r) =>
    `<option value="${esc(r.report_id)}">${esc(r.theme || r.report_id)}</option>`).join('');
  if (prev) sel.value = prev;
  sel.dispatchEvent(new Event('change'));
}

$('qa-report').addEventListener('change', loadTurns);
$('qa-scenario').addEventListener('change', loadTurns);

async function loadTurns() {
  const id = $('qa-report').value;
  const flow = $('qa-flow');
  if (!id) { flow.innerHTML = '<p class="hint">先在「个案」视图生成或选择一份报告</p>'; return; }
  const { turns } = await api('/report-qa/turns?report_id=' + encodeURIComponent(id));
  if (!turns.length) { flow.innerHTML = '<p class="hint">该报告还没有问答记录</p>'; return; }
  flow.innerHTML = turns.map((t) => turnHtml(t)).join('');
}

function turnHtml(t) {
  const a = t.answer || t;
  return `<div class="turn">
    <div class="q">问：${esc(t.user_question || t.question || '')}</div>
    <div class="a">${esc(a.text || a.answer || JSON.stringify(a))}</div>
    <div class="tag">${esc(a.type || '')} ${esc(a.disclaimer_note || a.note || '')}</div>
  </div>`;
}

$('btn-ask').addEventListener('click', async () => {
  const id = $('qa-report').value;
  const q = $('qa-question').value.trim();
  if (!id || !q) return;
  const flow = $('qa-flow');
  flow.insertAdjacentHTML('beforeend',
    `<div class="turn"><div class="q">问：${esc(q)}</div><div class="a">思考中…</div></div>`);
  $('qa-question').value = '';
  try {
    const form = new FormData();
    form.append('report_id', id);
    form.append('user_question', q);
    form.append('scenario', $('qa-scenario').value);
    const data = await api('/report-qa', { method: 'POST', body: form });
    flow.lastElementChild.remove();
    flow.insertAdjacentHTML('beforeend', turnHtml(data.turn || data));
    flow.lastElementChild.scrollIntoView({ behavior: 'smooth' });
  } catch (err) {
    flow.lastElementChild.querySelector('.a').textContent = '失败：' + err.message;
  }
});

/* ---------- 报告列表折叠（四栏布局） ---------- */
$('list-collapse').addEventListener('click', () => {
  const s = $('split4');
  s.classList.toggle('list-collapsed');
  $('list-collapse').textContent = s.classList.contains('list-collapsed') ? '⇥' : '⇤';
});

/* ---------- 启动 ---------- */
(async () => {
  await checkHealth();
  await loadReports();
  refreshQaReportOptions();
  setInterval(checkHealth, 30000);
})();
