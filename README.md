# 明镜 Mingjing —— 疗愈师 AI 工作台

> MANDALA AI WORKBENCH ｜ 曼陀罗绘画解读报告生成 + 报告问答助手（疗愈师端）

明镜把疗愈师的解读工作流做成了一条可审计的 AI 链路：上传一幅曼陀罗绘画 →
视觉模型生成解读报告 → 第二条 AI 链路做合规红线与「超纲」核查 → 疗愈师终审后交付。
**AI 是辅助工具：不做诊断、不做承诺，最终判断永远在疗愈师。**

## 快速开始

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # 填 KIMI_API_KEY / DEEPSEEK_API_KEY
.venv/bin/python -m uvicorn app.main:app
# 浏览器打开 http://localhost:8000
```

每次生成的报告在 `runs/` 目录落盘完整追溯链（prompt、中间产物、审计结果、问答历史），
审计留痕设计即「每步可回放」。本开源快照不含历史 runs 与黄金集图（见「资产边界」）。

## 架构

```
通用底座（core/：agent 调度、护栏、知识库检索、LLM 适配）
  └── 流派插件（schools/mandala/：曼陀罗手册、直断法库、主题包）
        └── 三条工作流
              ├── input_prep   OpenCV 确定性流水线：矫正→裁切→基准圆检测→圈界提议（不经 AI）
              ├── report_gen   gen-audit 三步链：生成 → 合规与超纲核查 → 确定性渲染
              └── report_qa    报告问答：解读参谋 / 应答准备两场景，回答带规则引文
```

UI 是 `ui/` 目录的原生 JS 单页（零框架零构建零 CDN），由 FastAPI StaticFiles 托管——
一个 uvicorn 进程跑全栈。每步链路的 prompt 原文、产物、耗时、token、费用都在 UI 追溯链可查。

## 质量与评估

- 黄金集：10 组定稿图（`eval/golden-set/`，图像不进 git，manifest 进 git）
- 三层评定：红线回归 / 核心结论一致性 >80% / 疗愈师人工终审
- 问答评测：112 问实测（106 出分）——锚定率 4.94/5、安全越界专项 38 问零违规、
  边界标注 100%、硬性断言 0 失败；首轮 18 问延迟 P95 8.4s
  （数字可溯源到 eval-results/ 留痕，评测方法见 `docs/eval-suite.md`）
- 后端 131 个自动化测试，CI 全绿（130 项离线可跑，1 项依赖知识库自动跳过）

## 工程决策精选

完整决策日志（D-NNN 级联）未包含在开源快照中，以下是三个代表性决策的摘要：

- **D-013 审计臂管辖权收窄**：审计臂曾同时审合规与质量，实测假阳性率 94%——
  收窄为只审合规红线与超纲采掘，质量判断交还疗愈师。超纲清单同时成为知识库的采矿入口
- **D-015→D-016 撤销自己的决策**：三层评定的「锚定事实层」上线三天后被证明不可维护，
  新增 D-016 正式撤销 D-015。决策日志保留完整时间线，不掩饰
- **零框架零构建（D-111）**：刻意约束——localhost 单用户工具不引 React/npm，
  知道什么时候不引入复杂度

## 边界与隐私

- 所有 AI 输出遵守：不做诊断 / 不做承诺 / 不越界 / 危机信号立即转介
- 评测画作与来访者个案图像不进入版本库；`.env` 与密钥绝不提交
- 本地单用户：无账号、无多租户、无云端同步

## 示例与演示

- 报告样例：[docs/golden-report-exemplar-v1.html](docs/golden-report-exemplar-v1.html)（黄金报告样例，打印适配）
- 知识库因果图谱可视化：接入知识库后由 `knowledge/healing/本体/语义层/graph.html` 提供

## 文档地图

产品愿景 `docs/product-vision.md` ｜ 架构 `docs/architecture.md` ｜ 验收 `docs/acceptance.md` ｜
评测治理 `docs/eval-suite.md` ｜ 工作流 spec `docs/specs/`（report-gen / report-qa / input-prep / ui）｜
路线图 `roadmap.md`

## 资产边界（开源范围说明）

- **不含**疗愈知识库（解读方法、直断解读法库、范例案例）：运行时通过路径注入读取
  `knowledge/healing/`，放入自己的知识源即可运行。
- **不含**评测黄金集图片与历史评测运行数据（真实用户画作属用户数据）。
- 代码、spec、评测框架、审计链路全部在库且可直接运行；CI 在每次推送时自动验证。
