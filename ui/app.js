/* 一镜一梳本地工作台 · 原生 JS（spec: docs/specs/ui-v1.md，D-111）
   壳逻辑：表单 → API → 展示。零业务判断，质量门/渲染/校验全在后端。
   v0.3.0：完整产品形态（live + 规划中模块同栏）+ 精工视觉（图标/曼陀罗母题/定制控件）。 */
'use strict';

const $ = (id) => document.getElementById(id);
let reports = [];           // /ui/reports 缓存
let currentReport = null;   // 报告视图当前选中
let prepImagePath = null;   // 预处理后定稿图路径

/* ================= 图标（inline SVG，stroke 1.5 圆角线帽） ================= */
const ICON_PATHS = {
  home: '<path d="M3.5 10.5 12 3l8.5 7.5"/><path d="M5.5 9.5V20h13V9.5"/><path d="M10 20v-5h4v5"/>',
  cases: '<rect x="5" y="3.5" width="14" height="17" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',
  qa: '<path d="M4.5 5.5h15v10H10l-5.5 4.5z"/>',
  clients: '<circle cx="12" cy="8" r="3.6"/><path d="M5 20c.8-3.8 3.6-6 7-6s6.2 2.2 7 6"/>',
  review: '<path d="M4.5 5.5c2.6-1 5.2-1 7.5.8 2.3-1.8 4.9-1.8 7.5-.8v13c-2.6-1-5.2-1-7.5.8-2.3-1.8-4.9-1.8-7.5-.8z"/><path d="M12 6.3v13"/>',
  coaching: '<path d="M12 21v-8"/><path d="M12 13c0-3.6 2.8-5.6 6.8-5.6 0 3.8-2.8 5.6-6.8 5.6z"/><path d="M12 13c0-3.6-2.8-5.6-6.8-5.6 0 3.8 2.8 5.6 6.8 5.6z"/>',
  agents: '<rect x="5" y="8.5" width="14" height="10" rx="2.5"/><path d="M12 8.5V5"/><circle cx="12" cy="3.6" r="1"/><circle cx="9.2" cy="13" r="1"/><circle cx="14.8" cy="13" r="1"/><path d="M9.5 16.4h5"/>',
  knowledge: '<circle cx="6" cy="6" r="2.2"/><circle cx="18" cy="7" r="2.2"/><circle cx="12" cy="17.5" r="2.2"/><path d="M8.1 6.6 15.9 7M7 8l3.9 7.4M16.9 9l-3.7 6.4"/>',
  eval: '<path d="M12 3.5 19 6v6c0 4.2-3 7.2-7 8.5-4-1.3-7-4.3-7-8.5V6z"/><path d="m9 11.8 2.2 2.2 4-4.2"/>',
  about: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/><path d="M12 7.8h.01"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  arrow: '<path d="M5 12h13M13 6.5 18.5 12 13 17.5"/>',
  back: '<path d="M19 12H6M11 6.5 5.5 12l5.5 5.5"/>',
};
function icon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" ` +
    `stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS[name] || ''}</svg>`;
}

/* ================= 曼陀罗线稿（程序生成，全站母题） ================= */
function mandalaSVG() {
  const parts = ['<circle cx="60" cy="60" r="56" opacity=".85"/>',
    '<circle cx="60" cy="60" r="44" opacity=".55"/>',
    '<circle cx="60" cy="60" r="20" opacity=".8"/>',
    '<circle cx="60" cy="60" r="7"/>'];
  for (let i = 0; i < 12; i++) {
    parts.push(`<ellipse cx="60" cy="31" rx="7" ry="15" transform="rotate(${i * 30} 60 60)" opacity=".7"/>`);
    const a = i * 30 * Math.PI / 180;
    const x = (60 + Math.sin(a) * 50).toFixed(1), y = (60 - Math.cos(a) * 50).toFixed(1);
    parts.push(`<circle cx="${x}" cy="${y}" r="2" opacity=".8"/>`);
  }
  return `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="1.2">${parts.join('')}</svg>`;
}
function decorateStatic() {
  document.querySelectorAll('[data-ic]').forEach((el) => { el.innerHTML = icon(el.dataset.ic); });
  document.querySelectorAll('[data-mandala]').forEach((el) => decorateMandala(el));
}
/* 曼陀罗装饰统一入口：读 data-mandala 尺寸并注入线稿（el 或选择器根均可） */
function decorateMandala(el, fallback = 64) {
  const size = +el.dataset.mandala || fallback;
  el.style.width = size + 'px'; el.style.height = size + 'px';
  el.innerHTML = mandalaSVG();
}

/* ---------- toast（一次性轻提示，如「报告已生成」「已自动保存」） ---------- */
let toastTimer = null;
function toast(msg, kind = 'ok') {
  let el = $('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
}

/* ================= 基础工具 ================= */
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
/* 列表用短格式：10/19 21:49（秒级是工程噪音） */
const fmtShort = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getMonth() + 1}/${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}`;
};
/* 个案显示名：有来访者称呼则「来访者 · 主题」，否则仅主题（存量 run 无 client 字段） */
const caseLabel = (r) => r.client ? `${r.client} · ${r.theme || '(无主题)'}` : (r.theme || '(无主题)');

/* ================= 健康状态 ================= */
let generating = false;   // 报告生成中：防 checkHealth 每 30s 把按钮重新点亮（重复 dispatch 竞态）
async function checkHealth() {
  const el = $('health');
  const label = el.querySelector('.hl-label');
  try {
    await api('/health');
    label.textContent = '后端已连接'; el.className = 'health ok';
    $('btn-gen').disabled = generating || !prepImagePath;
  } catch {
    label.textContent = '后端不可达';
    el.title = '请先启动: cd backend && .venv/bin/python -m uvicorn app.main:app';
    el.className = 'health bad';
    $('btn-gen').disabled = true;
  }
}

/* ================= 导航（侧栏路由） ================= */
const NAV_FALLBACK = { new: 'cases' };   // 无独立导航项的视图 → 高亮归属
let kgLoaded = false;

function switchTab(name) {
  document.querySelectorAll('.view').forEach((v) =>
    v.classList.toggle('active', v.id === 'tab-' + name));
  const hl = NAV_FALLBACK[name] || name;
  document.querySelectorAll('.nav-item').forEach((b) =>
    b.classList.toggle('active', b.dataset.tab === hl));
  if (name === 'cases') loadReports();
  if (name === 'qa') refreshQaReportOptions();
  if (name === 'knowledge' && !kgLoaded) {
    $('kg-frame').src = '/ui/knowledge-graph';
    kgLoaded = true;
  }
  window.scrollTo({ top: 0 });
}
document.querySelectorAll('.nav-item').forEach((btn) =>
  btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
document.querySelectorAll('[data-go]').forEach((btn) =>
  btn.addEventListener('click', () => switchTab(btn.dataset.go)));

/* 侧栏折叠 */
$('side-collapse').setAttribute('aria-expanded', 'true');
$('side-collapse').addEventListener('click', () => {
  const collapsed = document.body.classList.toggle('side-collapsed');
  $('side-collapse').setAttribute('aria-expanded', String(!collapsed));
});

/* ================= 首页 dashboard ================= */
function renderHome() {
  const d = new Date();
  const h = d.getHours();
  const greet = h < 6 ? '夜深了' : h < 12 ? '早上好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好';
  $('home-greet').textContent = `${greet}，疗愈师`;
  $('home-date').textContent = d.toLocaleDateString('zh-CN',
    { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' });
}
function renderHomeRecent() {
  const box = $('home-recent');
  if (!box) return;
  if (!reports.length) {
    box.innerHTML = `<div class="empty-state" style="padding:28px 16px">
      <div class="glyph" data-mandala="56"></div>
      <div class="title">还没有个案</div>
      <p class="desc">上传一幅曼陀罗，生成第一份解读报告。</p></div>`;
    box.querySelectorAll('[data-mandala]').forEach((el) => decorateMandala(el));
    return;
  }
  box.innerHTML = reports.slice(0, 4).map((r) => `
    <div class="hr-item" data-id="${esc(r.report_id)}">
      <span class="hr-t">${esc(caseLabel(r))}</span>
      ${runBadge(r)}
      <span class="hr-m">${esc(fmtShort(r.started_at))}</span>
      <span class="hr-arrow">›</span>
    </div>`).join('');
  box.querySelectorAll('.hr-item').forEach((el) =>
    el.addEventListener('click', () => { switchTab('cases'); showReport(el.dataset.id); }));
}

/* ================= 规划中模块页 ================= */
const PLANNED = {
  clients: {
    kicker: 'CLIENTS · 服务', title: '来访者', badge: '规划中', variant: 'v1',
    lead: '工作台的「人」维度：个案只是单次解读，来访者才是关系的载体。档案、预约、个案准备与个案督导，都挂在来访者的时间线上。现在不做，是因为先把解读质量打磨到 eval 达标——个案量起来后，这个模块就是下一站。',
    cards: [
      { ic: 'clients', name: '档案', desc: '每位来访者的基础信息、画作历史与议题追踪——个案不再是孤立的 run。', rel: '上线后：个案列表按来访者聚合，解读报告自动归档进时间线' },
      { ic: 'cases', name: '预约', desc: '个案预约与日程管理，预约单关联本次主题与背景。', rel: '上线后：新建个案的「主题 / 背景」从预约单自动带入' },
      { ic: 'qa', name: '个案准备', desc: '会谈前的备课视图：历史画作对比、上次遗留议题、本次切入建议。', rel: '复用问答智能体的解读参谋场景，从「答」延伸到「备」' },
      { ic: 'review', name: '个案督导', desc: '个案后的结构化回顾：报告命中度、画者反馈、疗愈师自评。', rel: '督导记录沉淀为教学复盘与质量评测的标注数据' },
    ],
    basis: '产品地图主线：预约 → 准备 → 个案 → 跟进（见首页产品地图）。个案表单的「来访者称呼」字段已先行，为这个模块埋数据',
  },
  review: {
    kicker: 'GROWTH · 成长', title: '教学复盘', badge: '规划中', variant: 'v2',
    lead: '同一幅画，两个版本：来访者拿到疗愈报告，疗愈师拿到教学复盘——师父口吻拆「看见 → 规则 → 推理 → 直觉点 → 校准提问」。排在来访者模块之后，因为复盘需要个案时间线作原料。',
    cards: [
      { ic: 'review', name: '双版本产出', desc: '同一底层证据产出来访者版与疗愈师版，教学版仅疗愈师可见。', rel: '挂在 gen-audit 链路之后，复用同一 run 的画作与初稿' },
      { ic: 'coaching', name: '教练非监考', desc: '解读时不干扰临在，事后回放校准；长期目标是疗愈师摆脱 AI、独立临在。', rel: '与私教陪跑共享校准记录' },
      { ic: 'eval', name: '审计即学习', desc: '合规与超纲核查过程本身就是学习材料，超纲清单是知识库的采掘矿源。', rel: '已上线：个案页的 audit.md 终审草稿' },
    ],
    basis: '依据 <b>D-011</b>（双版本与教学层定位）· <b>D-013</b>（审计臂 = 超纲采掘）',
  },
  coaching: {
    kicker: 'GROWTH · 成长', title: '私教陪跑', badge: '规划中', variant: 'v3',
    lead: '面向疗愈师的陪跑：带新手从「会用工具」走到「独立临在」。解读校准、实战陪伴、阶段评估——AI 做教练，不做监考。排在教学复盘之后，因为校准记录是它的教材。',
    cards: [
      { ic: 'eval', name: '解读校准', desc: '陪跑期疗愈师的解读与 AI / 师父解读对照，偏差即教材。', rel: '对照材料来自个案 run 的报告与 audit.md' },
      { ic: 'clients', name: '实战陪伴', desc: '真实个案的事前备课与事后复盘节奏管理。', rel: '与来访者模块的个案准备 / 督导共用时间线' },
      { ic: 'knowledge', name: '阶段评估', desc: '从依赖 AI 到独立解读的成长轨迹可视化。', rel: '数据来自教学复盘与督导记录的长期沉淀' },
    ],
    basis: '与 <b>D-011</b>「教练非监考、AI 不制造依赖」同向',
  },
  agents: {
    kicker: 'SYSTEM · 系统', title: '智能体', badge: '部分可用', variant: 'v4',
    lead: '工作台的能力以智能体为单位生长：两个已上线，更多在规划里。每个智能体都是「确定性交给代码、判断留给人」原则的一次实例化。',
    cards: [
      { ic: 'cases', name: '曼陀罗解读 Agent', live: true, desc: '上传画作 → 解读报告。gen-audit 三步链：生成 → 合规与超纲核查 → 确定性渲染，每步 prompt 与产物落盘可追溯。', rel: '链路：OpenCV 预处理 + 视觉模型 + 审计臂', go: ['new', '新建个案'] },
      { ic: 'qa', name: '报告问答 Agent', live: true, desc: '基于报告内容的问答：解读参谋 / 应答准备两场景，回答带规则引文与口径提醒。', rel: '实测：锚定 4.94/5 · 越界 0/38', go: ['qa', '去问答'] },
      { ic: 'review', name: '备课 Agent', desc: '个案前生成备课提要：历史画作对比 + 切入建议，是问答智能体向「事前」的延伸。', rel: '依赖：来访者模块的时间线数据' },
      { ic: 'coaching', name: '陪跑 Agent', desc: '面向疗愈师的校准教练：对照解读、点评偏差、追踪成长。', rel: '依赖：教学复盘的数据沉淀' },
    ],
    basis: '共享底座：知识库 RAG · 转介红线 · 输出分级（见「知识库」与「关于本项目」）',
  },
  eval: {
    kicker: 'SYSTEM · 系统', title: '质量评测', badge: '部分可用', variant: 'v5',
    lead: '评测是 CLI 工程链路，三层评定：红线回归 / 核心结论一致性 >80% / 疗愈师人工终审。面板化在规划中，以下是最近一次实测数据。',
    metrics: [
      ['112 问', '问答评测实测规模（106 出分）'], ['4.94 / 5', '回答锚定率（LLM judge）'],
      ['0 / 38', '安全越界专项违规'], ['8.4s', '单轮延迟 P95（18 问轮）'],
      ['10 组', '黄金集定稿图'], ['131', '后端自动化测试'],
    ],
    cards: [
      { ic: 'eval', name: '红线回归', desc: '每次改动重跑：生成 → 审计合规核查稳定通过，不做诊断/不承诺/危机转介。', rel: '已上线：评测脚本 + 实验留痕（eval-results）' },
      { ic: 'knowledge', name: '结论一致性', desc: '同图多次生成的核心结论一致率 >80%，防止模型「看心情解读」。', rel: '已上线：黄金集 10 组定稿图' },
      { ic: 'clients', name: '人工终审', desc: '疗愈师终审是最终质量门——AI 评测只负责筛，不负责判。', rel: '面板化后：终审结论回写本页' },
    ],
    basis: '依据 <b>D-015 → D-016</b>（三层评定的定稿与自我修正）；数字可溯源 eval-results',
  },
};

function plannedHtml(cfg) {
  const metrics = cfg.metrics ? `<div class="metrics">${cfg.metrics.map(([b, s]) =>
    `<div class="metric-tile"><b>${b}</b><span>${s}</span></div>`).join('')}</div>` : '';
  const heroChip = cfg.badge === '部分可用' ? 'chip-partial' : 'chip-plan';
  return `<div class="planned">
    <div class="pl-hero ${cfg.variant || ''}">
      <div class="pl-glyph" data-mandala="88"></div>
      <div class="kicker">${cfg.kicker}</div>
      <h2>${cfg.title}<span class="chip ${heroChip}">${cfg.badge}</span></h2>
      <p class="lead">${cfg.lead}</p>
    </div>
    ${metrics}
    <div class="pl-cards">${cfg.cards.map((c) => `
      <div class="pl-card${c.live ? ' live' : ''}">
        <div class="plc-head"><span class="ic">${icon(c.ic)}</span><b>${c.name}</b>
          <span class="chip ${c.live ? 'chip-live' : 'chip-plan'}">${c.live ? '已上线' : '规划中'}</span></div>
        <p>${c.desc}</p>
        <div class="plc-rel">${c.rel}</div>
        ${c.go ? `<div class="plc-actions"><button class="btn-secondary" data-go="${c.go[0]}">${c.go[1]}</button></div>` : ''}
      </div>`).join('')}
    </div>
    <div class="pl-basis">${cfg.basis}</div>
  </div>`;
}

function renderPlannedAll() {
  for (const [tab, cfg] of Object.entries(PLANNED)) {
    const sec = $('tab-' + tab);
    if (!sec) continue;
    sec.innerHTML = plannedHtml(cfg);
  }
  // 渲染后补：曼陀罗装饰 + data-go 跳转
  document.querySelectorAll('.planned [data-mandala]').forEach((el) => decorateMandala(el));
  document.querySelectorAll('.planned [data-go]').forEach((btn) =>
    btn.addEventListener('click', () => switchTab(btn.dataset.go)));
}

/* ================= 新建：拖拽上传区 ================= */
function dzShowFile(file) {
  const thumb = $('dz-thumb');
  if (thumb.src.startsWith('blob:')) URL.revokeObjectURL(thumb.src);
  if (!file) {
    $('dz-preview').classList.add('hidden');
    $('dz-inner').classList.remove('hidden');
    return;
  }
  thumb.src = URL.createObjectURL(file);
  $('dz-name').textContent = file.name;
  $('dz-preview').classList.remove('hidden');
  $('dz-inner').classList.add('hidden');
}
/* 生成按钮引导：让用户知道按钮为什么不可点 */
function updateGenGuide() {
  $('gen-guide').textContent = prepImagePath
    ? '照片就绪，填写主题即可生成' : '先在第 1 步上传照片';
}
(function initDropzone() {
  const dz = $('dropzone'), input = $('photo');
  dz.addEventListener('click', () => input.click());
  dz.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  ['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => {
    e.preventDefault(); dz.classList.add('drag');
  }));
  ['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => {
    e.preventDefault(); dz.classList.remove('drag');
  }));
  dz.addEventListener('drop', (e) => {
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      input.dispatchEvent(new Event('change'));
    }
  });
  input.addEventListener('change', () => dzShowFile(input.files[0]));
})();

/* ================= 新建：上传 → 预处理（原始照片）或仅存盘（已定稿图，v0.1.4） ================= */
let prepSeq = 0;   // 上传竞态守卫：只认最后一次选择的结果（慢响应不得覆盖快的）
$('final-toggle').addEventListener('change', () => {
  // 模式切换时重置预处理结果，避免用旧参数生成
  prepSeq++;
  prepImagePath = null;
  $('btn-gen').disabled = true;
  updateGenGuide();
  $('prep-result').classList.add('hidden');
  $('prep-status').textContent = $('final-toggle').checked
    ? '已定稿模式：上传后不会画叠加圈，如需微调圈界再展开下方参数' : '';
  if ($('photo').files[0]) $('photo').dispatchEvent(new Event('change'));
});

$('photo').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const seq = ++prepSeq;
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
      if (seq !== prepSeq) return;   // 期间用户又选了别的图
      prepImagePath = data.saved_to;
      const overlay = $('prep-overlay');
      if (overlay.src.startsWith('blob:')) URL.revokeObjectURL(overlay.src);
      overlay.src = URL.createObjectURL(file);  // 本地预览原图，不经服务器
      $('p-cx').value = ''; $('p-cy').value = ''; $('p-radius').value = '';
      $('p-r1').value = 0.28; $('p-r2').value = 0.60;
      $('prep-result').classList.remove('hidden');
      st.textContent = '已存盘：' + data.saved_to;
      $('btn-gen').disabled = false;
      updateGenGuide();
    } catch (err) {
      if (seq !== prepSeq) return;
      prepImagePath = null; $('btn-gen').disabled = true;
      updateGenGuide();
      st.className = 'status err'; st.textContent = '存盘失败：' + err.message;
    }
    return;
  }
  st.textContent = '预处理中（矫正→裁切→圈界提议）…';
  try {
    const form = new FormData();
    form.append('photo', file);
    const data = await api('/ui/input-prep/run', { method: 'POST', body: form });
    if (seq !== prepSeq) return;
    prepImagePath = data.image_path;
    $('prep-overlay').src = data.overlay_url + '?t=' + Date.now();
    $('p-cx').value = data.ring_params.cx;
    $('p-cy').value = data.ring_params.cy;
    $('p-radius').value = data.ring_params.radius;
    $('p-r1').value = data.ring_params.r1_ratio;
    $('p-r2').value = data.ring_params.r2_ratio;
    $('prep-result').classList.remove('hidden');
    st.textContent = `完成（rectified=${data.rectified}，axis_ratio=${data.axis_ratio}` +
      (data.ring_params.fallback ? '，圈界走了固定比例兜底' : '') + '）';
    $('btn-gen').disabled = false;
    updateGenGuide();
  } catch (err) {
    if (seq !== prepSeq) return;
    prepImagePath = null; $('btn-gen').disabled = true;
    updateGenGuide();
    st.className = 'status err'; st.textContent = '预处理失败：' + err.message;
  }
});

/* ================= 新建：生成报告 ================= */
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
  generating = true;
  const t0 = Date.now();
  const timer = setInterval(() =>
    st.textContent = `报告生成中… ${((Date.now() - t0) / 1000).toFixed(0)}s`, 1000);
  try {
    const payload = { agent: 'report_gen', payload: {
      image_path: prepImagePath, theme,
      client: $('client').value.trim() || undefined,
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
    toast('报告已生成，合规核查完成', 'ok');
    switchTab('cases');
    await loadReports(data.report_id);
  } catch (err) {
    clearInterval(timer);
    st.className = 'status err'; st.textContent = '生成失败：' + err.message;
  } finally {
    generating = false;
    $('gen-progress').classList.add('hidden');
    $('btn-gen').disabled = false;
  }
});

/* ================= 个案视图 ================= */
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
    list.innerHTML = `<p class="status err">${esc(err.message)}</p>`;
    renderHomeRecent();
    return;
  }
  renderHomeRecent();
  if (!reports.length) {
    list.innerHTML = `<div class="empty-state" style="padding:2rem 1rem">
      <div class="glyph" data-mandala="56"></div>
      <div class="title">还没有个案</div>
      <p class="desc">点上方「新建个案」上传一幅曼陀罗，生成第一份解读报告。</p>
    </div>`;
    list.querySelectorAll('[data-mandala]').forEach((el) => decorateMandala(el));
    return;
  }
  list.innerHTML = `<div class="list-legend">✓ 核查通过 · ⚠ 需复核 · ✗ 护栏拦截</div>` + reports.map((r) => `
    <div class="item" data-id="${esc(r.report_id)}" title="${esc(caseLabel(r))}">
      <div class="t">${esc(caseLabel(r))} ${runBadge(r)}</div>
      <div class="m">${esc(fmtShort(r.started_at))}${r.edited_at ? ' · 已编辑' : ''}</div>
    </div>`).join('');
  list.querySelectorAll('.item').forEach((el) =>
    el.addEventListener('click', () => showReport(el.dataset.id)));
  if (selectId) showReport(selectId);
  else if (currentReport) showReport(currentReport);
  else $('split4').classList.add('no-panels');   // 未选中个案：空态占满主区（CSS 隐藏右栏）
}

/* ================= markdown 轻渲染（audit.md / report.md 面板用，不引库） ================= */
function mdToHtml(md) {
  const inline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
  const out = [];
  let tableRows = [], listItems = [];
  const flushTable = () => {
    if (!tableRows.length) return;
    const rows = tableRows.filter((l) => !/^\|[\s:-]+\|$/.test(l.trim().replace(/[^|:-\s]/g, '')) && !/^\|[\s-|]+\|$/.test(l.trim()));
    const cells = (l) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
    const html = rows.map((l, i) => {
      const tag = i === 0 ? 'th' : 'td';
      return `<tr>${cells(l).map((c) => `<${tag}>${inline(c)}</${tag}>`).join('')}</tr>`;
    }).join('');
    out.push(`<table class="md-table">${html}</table>`);
    tableRows = [];
  };
  const flushList = () => {
    if (!listItems.length) return;
    out.push(`<ul>${listItems.map((x) => `<li>${inline(x)}</li>`).join('')}</ul>`);
    listItems = [];
  };
  for (const line of md.split('\n')) {
    const t = line.trim();
    if (t.startsWith('|')) { flushList(); tableRows.push(line); continue; }
    flushTable();
    if (t.startsWith('- ')) { listItems.push(t.slice(2)); continue; }
    flushList();
    if (!t) continue;
    const h = t.match(/^(#{1,4})\s+(.*)$/);
    if (h) { const lv = Math.min(h[1].length + 2, 6); out.push(`<h${lv}>${inline(h[2])}</h${lv}>`); continue; }
    out.push(`<p>${inline(t)}</p>`);
  }
  flushTable(); flushList();
  return out.join('');
}

/* audit.md → 一行合规摘要：合规状态 + 超纲条数（启发式解析，仅做展示指引） */
function auditSummary(auditMd) {
  if (!auditMd) return '';
  const chips = [];
  if (/合规通过/.test(auditMd)) chips.push('<span class="chip chip-live">合规核查通过</span>');
  else chips.push('<span class="chip chip-partial">合规核查见明细</span>');
  const beyond = auditMd.split('超纲清单')[1] || '';
  const n = (beyond.match(/^\|\s*\d+/gm) || []).length;
  if (n) chips.push(`<span class="chip chip-plan">超纲 ${n} 则 · 待终审</span>`);
  else chips.push('<span class="chip chip-live">无超纲条目</span>');
  return `<div class="case-chips">${chips.join('')}</div>`;
}

/* ================= 个案详情 ================= */
let reportSeq = 0;   // 陈旧响应守卫：连续点个案时慢的那个不得盖掉快的
async function showReport(id) {
  currentReport = id;
  const seq = ++reportSeq;
  if (!$('tab-cases').classList.contains('active')) switchTab('cases');
  $('report-detail').classList.remove('hidden');
  $('trace-panels').classList.remove('hidden');
  $('split4').classList.remove('no-panels');
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
  if (seq !== reportSeq) return;

  const isGA = d.pipeline === 'gen-audit-v1';
  const g = d.g1 || {};
  const flags = g.flags || {};
  const flagNames = { orphan_accepted_claims: '孤儿 claim', forbidden_phrases: '禁语',
    marker_line_evidence_claims: '标记线证据', pending_terms_used_in_body: '待定术语',
    exemplar_copy_spans: '照搬片段', unanchored_statements: '未锚定画面句' };
  const flagRows = Object.entries(flags).map(([k, v]) =>
    `<div class="row"><span>${esc(flagNames[k] || k)}</span><b class="${v > 0 ? 'hot' : ''}">${esc(String(v))}</b></div>`).join('');

  // gen-audit run 无 g1 块：质量信号是 audit.md（合规核查 + 超纲清单，D-013），卡片指过去而非复制口径
  const gateHtml = isGA ? `
    <div class="gate">
      <div class="row"><span>生成链路</span><b>gen-audit 三步（D-013）</b></div>
      <div class="row"><span>状态</span><b>${esc(d.status)}</b></div>
      <div class="row"><span>合规与超纲核查</span><b>${d.has_audit_md ? 'audit.md · 见右栏' : 'audit.md 缺失'}</b></div>
    </div>` : `
    <div class="gate">
      <div class="row"><span>G1 质量门</span><b class="${g.passed ? '' : 'hot'}">${g.passed ? '通过' : '未通过'}</b></div>
      <div class="row"><span>accepted claims</span><b>${g.accepted_claim_count ?? 0}</b></div>
      ${flagRows}
    </div>`;

  // 首屏 = 报告本体（疗愈师视角）；工程元数据整包折叠（面试官视角展开仍有全部深度）
  const reportUrl = '/ui/reports/' + encodeURIComponent(id) + '/html';
  head.innerHTML = `
    <h2>${esc(caseLabel(d))} ${runBadge(d)}</h2>
    ${isGA ? auditSummary(d.audit_md) : ''}
    ${d.has_report_html
      ? `<iframe class="report-frame" src="${reportUrl}" title="解读报告" loading="lazy"></iframe>`
      : (d.image_path ? `<img class="preview" src="/ui/reports/${encodeURIComponent(id)}/image" alt="画作" onerror="this.remove()">` : '')}
    <p class="case-actions">
      <button class="plain" id="btn-preview">新标签打开报告</button>
      <button class="plain" id="btn-edit">编辑 md</button>
      <button class="plain" id="btn-rerender">重新渲染</button>
      <button class="plain" id="btn-toqa">去问答</button>
    </p>
    <div id="edit-box" class="hidden">
      <textarea class="md" id="md-editor" rows="18"></textarea>
      <p><button class="primary" id="btn-save">保存并重渲</button>
         <span id="save-status" class="status"></span></p>
    </div>
    <details class="tech-fold">
      <summary>技术详情（生成链路 · 耗时 · token）</summary>
      ${gateHtml}
      <div id="run-meta" class="run-meta"></div>
    </details>
    <p class="meta" id="rerender-status"></p>`;

  let pipeline = null;
  if (isGA) {
    try { pipeline = await api('/ui/reports/' + encodeURIComponent(id) + '/pipeline'); }
    catch (err) { pipeline = { legacy: false, steps: [], error: err.message }; }
    if (seq !== reportSeq) return;
  }
  renderRunMeta(d, pipeline);
  $('btn-preview').onclick = () => window.open(reportUrl, '_blank');
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
      const frame = head.querySelector('.report-frame');
      if (frame) frame.src = reportUrl + '?t=' + Date.now();
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
      const frame = head.querySelector('.report-frame');
      if (frame) frame.src = reportUrl + '?t=' + Date.now();
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

/* ================= Round 详情 ================= */
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
  // 「其余」≈0 或没计时数据时不显示——「其余 0.0s」是纯噪音
  const rest = (d.elapsed_ms != null && recorded && d.elapsed_ms - recorded > 1000)
    ? d.elapsed_ms - recorded : null;
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
      ${TIMING_STEPS.filter(([k]) => tm[k] != null).map(([k, name]) =>
        `<div class="row"><span>${name}</span><b>${fmtDur(tm[k])}</b></div>`).join('') || '<div class="row"><span>（各步未计时）</span><b></b></div>'}
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
  const rest = (d.elapsed_ms != null && recorded && d.elapsed_ms - recorded > 1000)
    ? d.elapsed_ms - recorded : null;
  let tokIn = 0, tokOut = 0, cost = 0, costKnown = false;
  const tokenRows = steps.map((s) => {
    if (!s.tokens) return '';
    const price = MODEL_PRICE[s.tool];
    const tin = s.tokens.prompt || 0, tout = s.tokens.completion || 0;
    tokIn += tin; tokOut += tout;
    if (price) { cost += tin / 1e6 * price.in + tout / 1e6 * price.out; costKnown = true; }
    return `<div class="row"><span>${esc(s.name)}</span>` +
      `<b>入 ${(tin / 1000).toFixed(1)}k / 出 ${(tout / 1000).toFixed(1)}k</b></div>`;
  }).join('');
  box.innerHTML = `
    <h3>Round 详情</h3>
    <div class="row"><span>Round ID</span><b>${esc(d.report_id)}</b></div>
    <div class="row"><span>开始时间</span><b>${esc(fmtTime(d.started_at))}</b></div>
    <div class="row"><span>总耗时</span><b>${fmtDur(d.elapsed_ms)}</b></div>
    <div class="sec">
      <div class="row"><span>每步耗时</span><b></b></div>
      ${steps.filter((s) => s.cost_ms != null).map((s) =>
        `<div class="row"><span>${esc(s.name)}</span><b>${fmtDur(s.cost_ms)}</b></div>`).join('') || '<div class="row"><span>（各步未计时）</span><b></b></div>'}
      ${rest != null ? `<div class="row"><span>其余（渲染+开销）</span><b>${fmtDur(rest)}</b></div>` : ''}
    </div>
    <div class="sec">
      <div class="row"><span>Token 消耗</span><b></b></div>
      ${tokenRows || '<div class="row"><span>—</span><b></b></div>'}
      <div class="row"><span>合计</span><b>入 ${(tokIn / 1000).toFixed(1)}k / 出 ${(tokOut / 1000).toFixed(1)}k</b></div>
      ${costKnown ? `<div class="row"><span>费用估算</span><b class="cost">¥${cost.toFixed(3)}</b></div>` : ''}
    </div>`;
}

/* ================= 追溯链（spec UI-008）+ 审核备注（spec UI-009） ================= */
const HYP_NAMES = { direct_pattern_hits: '直读模式', five_elements: '五行分布',
  imbalance_hypotheses: '失衡假设', state_hypotheses: '状态假设', topic_hypotheses: '议题假设' };
let reviewCache = {};                    // key -> {checked, note}
const reviewTimers = new Map();          // key -> 各自防抖定时器（共享定时器会吞掉快速连续编辑）

/* 审核单元格：key 稳定标识；checked 打勾、note 备注。表格里用 td 变体，列表里用 span 变体（li 里放 td 是非法 HTML） */
function rvCells(key) {
  const r = reviewCache[key] || {};
  return `<td class="rvc"><input type="checkbox" class="rv-check" data-key="${esc(key)}" ${r.checked ? 'checked' : ''}></td>` +
    `<td class="rvn"><input class="rv-note" data-key="${esc(key)}" value="${esc(r.note || '')}" placeholder="备注…"></td>`;
}
function rvCellsInline(key) {
  const r = reviewCache[key] || {};
  return `<span class="rvc"><input type="checkbox" class="rv-check" data-key="${esc(key)}" ${r.checked ? 'checked' : ''}></span>` +
    `<span class="rvn"><input class="rv-note" data-key="${esc(key)}" value="${esc(r.note || '')}" placeholder="备注…"></span>`;
}
const rvHeads = '<th class="rvc">✓</th><th class="rvn">审核备注</th>';

async function saveReview(key, patch) {
  const cur = reviewCache[key] || {};
  reviewCache[key] = { ...cur, ...patch };
  // 总评注有可见的保存状态行（UI 审核备注零反馈是出戏点）
  const st = key === 'general' ? $('rv-status') : null;
  if (st) { st.textContent = '编辑中…'; st.className = 'rv-status'; }
  clearTimeout(reviewTimers.get(key));
  reviewTimers.set(key, setTimeout(async () => {
    try { await api(`/ui/reports/${currentReport}/review`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, ...patch }) });
      if (st) {
        const d = new Date();
        st.textContent = `已自动保存 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
      }
    }
    catch (e) {
      console.error('审核保存失败', e);
      if (st) { st.textContent = '保存失败，请重试'; st.className = 'rv-status err'; }
    }
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
  return `<div class="pipe"><div class="pipe-title">生成链路（gen-audit 三步，D-013）：查输入 = prompt 原文 / 程序文件 · 查输出 = 该步产物 · 表格 = 结构化视图</div>` +
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
  return `<div class="pipe"><div class="pipe-title">生成链路（旧 stage35 七步，历史浏览）：查输入 = prompt / 程序文件 · 查输出 = 该步产物 · 表格 = 结构化视图</div>` +
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
        return `<li>${esc(typeof x === 'string' ? x : JSON.stringify(x))} ${rvCellsInline(key)}</li>`; }).join('') +
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
        return `<li>${esc(x)} ${rvCellsInline(key)}</li>`; }).join('') + '</ul>' +
      (st === undefined || ex.length <= 5 ? '' : '</details>') + '</div>');
  }
  if (st && st.length) {
    rows.push(`<div class="rev structure"><b>结构重合（标点/markdown 骨架凑出的重合，${st.length} 处，不算照搬）：</b>` +
      `<details><summary>展开明细（可逐条标注）</summary><ul>` +
      st.map((x, i) => { const key = `flag:exemplar_structure_spans:${i}`;
        return `<li>${esc(x)} ${rvCellsInline(key)}</li>`; }).join('') + '</ul></details></div>');
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
        <label>总评注（整份报告审核意见）<span class="rv-status" id="rv-status"></span></label>
        <textarea id="general-note" rows="2" placeholder="例如：超纲 #1 直断逆用删除；#2 散水点断进账保留…">${esc(reviewCache.general?.note || '')}</textarea>
      </div>
      ${d.audit_md ? `<details id="panel-audit" open><summary>合规核查与超纲清单（audit.md · 疗愈师终审草稿，D-013）</summary><div class="md-view">${mdToHtml(d.audit_md)}</div></details>` : ''}
      ${d.report_md ? `<details id="panel-report-md"><summary>报告初稿（report.md）</summary><div class="md-view">${mdToHtml(d.report_md)}</div></details>` : ''}`;
    const gn = $('general-note');
    gn.addEventListener('input', () => saveReview('general', { note: gn.value }));
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
      <label>总评注（整份报告审核意见）<span class="rv-status" id="rv-status"></span></label>
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
  gn.addEventListener('input', () => {
    saveReview('general', { note: gn.value });
    const sum = $('rv-summary');
    if (sum) sum.textContent = reviewSummary();
  });
}

/* ================= 问答视图 ================= */
function refreshQaReportOptions() {
  const sel = $('qa-report');
  const prev = sel.value;
  sel.innerHTML = reports.map((r) =>
    `<option value="${esc(r.report_id)}">${esc(caseLabel(r))} · ${esc(fmtShort(r.started_at))}</option>`).join('');
  if (prev) sel.value = prev;
  sel.dispatchEvent(new Event('change'));
}

/* 空状态示例问题：点一下直接填入输入框（降低第一次提问的门槛，也让录屏有抓手） */
const QA_EXAMPLES = {
  advisor: ['这份报告里，哪几条结论最需要我先和来访者核对？', '画面里哪个特征支撑了关于主题的结论？'],
  reply_prep: ['帮我起草一段给来访者的开场解读，语气温和、不做承诺', '来访者问「我该怎么办」时，怎么回应才不越界？'],
};

$('qa-report').addEventListener('change', loadTurns);
$('qa-scenario').addEventListener('change', loadTurns);

async function loadTurns() {
  const id = $('qa-report').value;
  const flow = $('qa-flow');
  if (!id) { flow.innerHTML = '<p class="hint">先在「个案」视图生成或选择一份报告</p>'; return; }
  let turns;
  try { ({ turns } = await api('/report-qa/turns?report_id=' + encodeURIComponent(id))); }
  catch (err) { flow.innerHTML = `<p class="status err">问答记录加载失败：${esc(err.message)}</p>`; return; }
  if (!turns.length) {
    const examples = QA_EXAMPLES[$('qa-scenario').value] || QA_EXAMPLES.advisor;
    flow.innerHTML = `<div class="empty-state" style="padding:36px 20px">
      <div class="glyph qa-glyph"></div>
      <div class="title">该报告还没有问答记录</div>
      <p class="desc">解读参谋帮你吃透报告，应答准备帮你起草给来访者的回复。不知道从哪问起？</p>
      <div class="qa-examples">${examples.map((q) =>
        `<button class="qa-example" data-q="${esc(q)}">${esc(q)}</button>`).join('')}</div>
    </div>`;
    const g = flow.querySelector('.qa-glyph');
    g.style.width = '56px'; g.style.height = '56px'; g.innerHTML = mandalaSVG();
    flow.querySelectorAll('.qa-example').forEach((b) =>
      b.addEventListener('click', () => { $('qa-question').value = b.dataset.q; $('qa-question').focus(); }));
    return;
  }
  flow.innerHTML = turns.map((t) => turnHtml(t)).join('');
}

function turnHtml(t) {
  const a = t.answer || t;
  // 模型有时把换行写成字面 \n 两字符（JSON 习惯）——渲染前还原成真换行，配合 pre-wrap
  const raw = (typeof a === 'string' ? a : (a.text || a.answer || JSON.stringify(a)));
  const txt = raw.replace(/\\n/g, '\n');
  const meta = typeof a === 'object' ? `${a.type || ''} ${a.disclaimer_note || a.note || ''}` : '';
  const body = esc(txt).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');   // 回答里的 **加粗** 渲染出来
  return `<div class="turn">
    <div class="q">问：${esc(t.user_question || t.question || '')}</div>
    <div class="a">${body}</div>
    <div class="tag">${esc(meta)}</div>
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
  const turnEl = flow.lastElementChild;
  try {
    const form = new FormData();
    form.append('report_id', id);
    form.append('user_question', q);
    form.append('scenario', $('qa-scenario').value);
    const data = await api('/report-qa', { method: 'POST', body: form });
    turnEl.remove();
    flow.insertAdjacentHTML('beforeend', turnHtml(data.turn || data));
    flow.lastElementChild.scrollIntoView({ behavior: 'smooth' });
  } catch (err) {
    turnEl.querySelector('.a').innerHTML =
      `<span class="err">失败：${esc(err.message)}</span> <button class="plain qa-retry">重试</button>`;
    turnEl.querySelector('.qa-retry').addEventListener('click', () => {
      $('qa-question').value = q;
      turnEl.remove();
      $('btn-ask').click();
    });
  }
});

/* ================= 个案列表折叠 ================= */
$('list-collapse').setAttribute('aria-expanded', 'true');
$('list-collapse').addEventListener('click', () => {
  const collapsed = $('split4').classList.toggle('list-collapsed');
  $('list-collapse').setAttribute('aria-expanded', String(!collapsed));
});

/* rv 勾选/备注 → 汇总计数。事件委托在面板上只注册一次——面板每次 renderTrace 都重渲染，
   若在渲染函数里直接 addEventListener 会每看一个旧 run 叠加一个监听器 */
$('trace-panels').addEventListener('change', (e) => {
  if (e.target.classList.contains('rv-check') || e.target.classList.contains('rv-note')) {
    const sum = $('rv-summary');
    if (sum) sum.textContent = reviewSummary();
  }
});

/* ================= 启动 ================= */
(async () => {
  decorateStatic();
  renderPlannedAll();
  renderHome();
  await checkHealth();
  await loadReports();
  refreshQaReportOptions();
  setInterval(checkHealth, 30000);
})();
