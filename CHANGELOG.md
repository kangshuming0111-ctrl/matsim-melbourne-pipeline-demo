# 2026.10-p2 · 19 October 2026

- Fix missing-value aggregation while preserving valid zero values and explicit unavailable results.
- Add the DuckDB analysis layer, ten SQL queries, nine-run aggregate evidence and the detour investigation.
- Add local Qwen3 read-only tool routing, explicit parameter constraints and bounded explanations.
- Retain 30 development / 20 reserved evaluations, early failures, baseline comparison and frozen source hashes.
- Publish a recruiter-facing static showcase and source download; live model inference remains local.
- Preserve the original repository history and upstream notices. No native individual outputs, database, runtime or model weights are added.

---

# 更新记录

## 2026.10-p2 · 2026-10-19

- Added a real local Qwen3/Ollama assistant for reviewed run queries, metric comparisons, missing-value examples and bounded detour explanations.
- Bound model plans to explicit parameters; kept calculations in read-only SQL/Python with run IDs, units, denominators and source hashes.
- Added API/UI, evidence download, unavailable-model fallback and 33 unit tests. Full suite: 367 passed, one optional osmium skip.
- Locked 30 development / 20 reserved questions; retained failed versions and deterministic baselines. Frozen holdout: 20/20, numeric 14/14; baseline also 20/20, with eight AI parameter corrections.
- Added evaluation/interview materials and offline recorded-answer review. No new simulations, model training, external human review or deployment.

## 2026.10-p1

- Added optional DuckDB ingestion, source/schema fingerprints, transactional rollback and unchanged-run skipping.
- Added ten SQL analyses, metric dictionary, 18 regression tests, source provenance and Python reconciliation.
- Added a two-page detour explanation, Chinese analysis, English interview notes and an interactive offline SQL evidence section.
- Retained all native run outputs; no new simulation or AI model.


## 2026-10-18 — 求职展示版 2026.10-p0

- 统一时间/距离/方式解析：缺失与非法值分别计数，真实零有效，无有效值返回 null。
- 修复总体均值的有效样本加权、空值比较、旧结果回放、网页和报告显示。
- 新增缺失值、异常值、零值、模式回退、不同分母和历史回放回归测试。
- 提供离线英文展示、单页介绍、两分钟字幕演示、架构说明及九次实验的可追溯汇总。
- 更新中英文说明，区分历史小场景、扩网十迭代案例和 Windows/WSL 短仿真。
- 本版基于迁移快照制作；不重建或虚构早期 Git 历史。

## 2026-09-09 — 可交付性完善

- 新增网页运行环境检查和 CLI `doctor` 自检命令。
- 新增已有 MATSim 结果扫描、历史结果选择和直接打开功能。
- 任务状态持久化到本机 `output/.job_history.json`，最多保留 100 条。
- 网页刷新后可以恢复当前任务轮询。
- 改进 API 输入验证和错误提示。
- 改进双击启动器：避免重复启动、绑定正确 Python 环境、检查全部依赖；Docker 未启动时仍可查看历史结果。
- 网页增加环境“重新检查”按钮，启动 Docker 后无需重启整个软件。
- 修复多次切换 3D 结果时旧渲染器和事件监听器没有释放的问题。
- 为六个网页区域生成并纳入真实 OSM 建筑和地标缓存。
- 地标重建脚本支持 `--all`，一次扫描 Victoria OSM 数据即可更新六个区域，避免重复解析六次。
- 3D 场景升级为城市建造游戏式表现：真实建筑轮廓按住宅、办公、商业、公共和工业用途分色，并加入窗格、屋顶、塔冠、树木、路灯与标志性建筑细节。
- 道路拆成路缘、深色沥青、导航式交通色带和车道标线；交通颜色不再改变道路物理宽度。
- 车辆动画默认从本次仿真的车辆活动峰值开始，增加当前活动车辆数、三级速度、城市视角和交通俯视控制。
- 修复车辆高度计算顺序导致 3D 场景中断，以及浏览器缓存旧场景数据的问题。
- 新增 `requirements-data.txt`，将一次性数据工具依赖与普通运行依赖分开。
- 新增自动化测试。
