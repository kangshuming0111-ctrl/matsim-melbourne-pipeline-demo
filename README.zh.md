> 历史中文说明。当前 P2 功能、评估结果与运行入口请以 [README.md](README.md) 为准；下文 P0 部分描述其发布时状态。

# MATSim Melbourne unified framework

## P2：本地 AI 分析助手（2026.10-p2）

启动项目后打开 [AI 分析助手](http://127.0.0.1:8000/assistant)：查询已有运行、比较时间和距离、解释绕行结果、指出证据不足。Qwen3 负责问题路由与受限解释组织，SQL/Python 计算数值；回答附单位、分母、运行 ID 和来源哈希，可下载证据 JSON。本机已安装模型，无需 API Key。

冻结后的内部预留题 20/20 通过（数值题 14/14），无降级、无引用检查失败。其中 8 题需要程序纠正模型参数；无 AI 基线也是 20/20，不能说 AI 提高了计算准确性。完整代码测试 368 项：367 通过、1 项可选 osmium 依赖跳过。[评估报告和失败记录](portfolio/reports/MATSim-ai-evaluation.html) · [运行与设计](docs/AI_ASSISTANT.md) · [面试讲解](docs/AI_INTERVIEW.md) · [离线展示](portfolio/index.html#ai)。源码包不含模型权重或原始个人级记录。下方 P0/P1 内容保留各阶段的历史范围。

## P1：SQL 分析与面试报告（2026.10）

新增 DuckDB 数据模型、事务式幂等导入、10 条分析 SQL、两页英文报告与中英面试材料。入口：[SQL 使用说明](docs/ANALYTICS.md)、[中文分析](docs/DETOUR_ANALYSIS_ZH.md)、[英文讲稿与追问](docs/INTERVIEW_P1.md)、[离线展示](portfolio/index.html#sql)。现有 9 次仿真导入 32,607 条出行；数值经 Python 分析核对。没有新增仿真、校准或 AI 模型。


一个范围有限但证据清楚的本地技术原型：为同一个墨尔本区域生成路网和合成出行需求，运行 MATSim，生成统计，并在网页中查看该次运行的结果与 3D 回放。

本项目不声称已经校准墨尔本交通模型，也不把合成代理称为真实用户。现在的产品主线是**可核对的交通方案讨论**：自由提出道路干预，在同一批合成出行需求下重新仿真，查看谁的出行变快/变慢、哪些路段出现变化，同时看见数据缺口与适用范围。3D 城市用于空间编辑与定位，不替代交通证据。

## 求职展示入口 · 2026.10-p0

- [离线展示页](portfolio/index.html)：无需安装 Docker 或下载原始数据。
- [一页英文项目介绍](portfolio/brief.html) · [两分钟带英文字幕的演示](portfolio/tour.html)。
- [九次实验的汇总证据](portfolio/evidence/case.json) · [CSV](portfolio/evidence/case.csv)。
- [运行说明](docs/RUNNING.md)与[开发/测试说明](docs/DEVELOPMENT.md)分开维护。
- [最新验证记录](validation/2026-10-18-p0.md) · [贡献与上游边界](docs/CONTRIBUTIONS.md)。

展示主案例是固定 1,037 人、三个种子、三个方案、每次十轮迭代的扩网实验。
普通 CBD 快速入口仍为三轮迭代，下面的历史运行记录不与展示案例混用。
本次修复将缺失和非法测量从真实零值中分离，报告各指标有效/缺失/非法数；
没有有效测量时，摘要、比较、网页和导出均明确表示不可用。
当前本地运行 317 项 Python 测试：316 通过、1 项因可选 osmium 未安装跳过。
SQL 分析层和 AI 助手属于后续计划，不作为本版已完成能力。

## 方案影响工作台

第一次使用可先读 [不需要写代码的方案讨论指南](docs/PLANNER_QUICKSTART.zh-CN.md)。

打开已有 IF Line 方案后，可以选择参照方案、早晚高峰或自定义时段、交通方式，并在地图上多选有向路段形成走廊。界面提供配对出行耗时、变快/变慢数量、P95、路段实际通行次数及固定刻度差异图，可定位回 3D，也可下载 HTML 讨论报告和 JSON 核对数据。更改条件后必须重新分析；失败不会保留上次结论冒充成功。打开结果和分析不会启动新仿真。

“成组规划实验”展示固定人口、多个种子的基线／封路／封路加替代道路运行记录，只开放有成功证据的结果；未完成部分明确保留。多种子范围是描述性结果，不是置信区间或收敛证明。

阅读 [工作台用法与指标口径](docs/IMPACT_WORKBENCH.md)、[成组实验协议](docs/PLANNING_CASE.md)。旧图中的相对排名彩虹不再当绝对拥堵显示；步行和传送公交没有路段观测时显示“不可用”，不会填零。

已实际完成一组九次实验：同一批 1,037 个合成代理，三个种子，各运行“基线、封路、封路＋356 m 替代道路”，每次 10 次迭代。汽车平均出行耗时的跨种子平均差分别为 **+7.530 s、+7.628 s**（相对基线）；替代道路相对仅封路为 **+0.098 s**。正数表示更慢。这个案例**不支持该替代道路带来耗时收益**，也不能把很小的差异解释为显著影响。完整数值、配对队列与局限见上述实验协议；原始方案没有为了得到好看的结果而调整。

**地理范围注意：** 9 月 26 日审计发现原小 CBD 流程的路网与完整 SA1 合成人口范围不一致，活动点路网矩形覆盖只有 69.1%。另建的固定人口扩展路网覆盖全部 4,660 个活动点，保持 1,037 人及原计划文件不变；它与旧结果分开保存。矩形覆盖和近路距离仍不等于真实交通校准，详见 [范围修正记录](validation/2026-09-26-domain-expansion.md)。

## 上游项目与本项目的边界

以下目录保存 `matsim-melbourne` 上游项目的代码：

- `vendor/network/`：R 路网生成流程，负责 OSM 获取、裁剪、拓扑处理、简化和 MATSim XML 输出。
- `vendor/demand/`：R 需求生成流程，使用 ABS/VISTA 派生数据生成合成人口、活动和出行计划。
- `vendor/baseline/`：Java/Maven MATSim 基准项目。

本项目增加或调整的部分主要是：

- `docker/`：固定 R、Java、Maven 和 MATSim 运行环境。
- `wrapper/`：Python CLI、FastAPI、任务队列、环境检查、区域匹配、完整流程、分析、运行记录和 3D 场景导出。
- `vendor/demand/R/run_from_env.R` 与 `derive_sa1_subset.R`：容器入口和 SA1 区域筛选入口。
- `vendor/baseline/.../RunPocScenario.java`：不要求 GTFS 运输时刻表的 PoC 入口。
- 上游代码中的少量兼容性修复，包括 Docker/Rosetta 并行进程和 GDAL 临时目录权限。

这不是从零重写 MATSim 或人口模型；简历和项目介绍中应明确区分上游能力与本项目包装、编排和排错工作。

## 固定的完整演示

当前 CBD 入口采用 `cbd_activity_domain_v2`：先生成并固定人口计划，再围绕活动域单独生成路网。旧 `cbd_small_v1` 的运行记录保持不变，不能混称为新版结果。新流程的执行证据与局限单独记录。

| 项目 | 固定值 |
|---|---:|
| 区域 | `data/sample_region.geojson`（墨尔本 CBD 小区域） |
| SA1 选择缓冲 | 原区域周围 500 m，只用于生成需求 |
| 路网范围 | 同一批活动点的原生坐标矩形；网络单独加 500 m，不反过来扩大人口 |
| 范围保护 | CBD 网络提取域上限 25 km²；活动点须全部有效，清理后路网矩形覆盖须为 100%，否则停止 |
| 合成人口抽样比例 | 5% |
| 上游 `numPlans` 参数 | 500（不是最终代理数硬上限；结果会受数据和 SA1 子集影响） |
| 需求随机种子 | 4711 |
| MATSim 随机种子 | 4711 |
| MATSim 配置 | `firstIteration=0`、`lastIteration=2`，即实际记录 3 次迭代 |
| 坐标系 | EPSG:7899 |
| 公共交通 | 固定速度传送模式；不是完整 GTFS 公交仿真 |

运行命令：

```bash
python3 -m wrapper.cli demo
```

该命令会自动使用唯一的新运行 ID，不覆盖旧结果。网络域准备、独立临时目录及覆盖审计也会留下记录。只有范围前置条件通过、路网、人口计划、MATSim 事件、统计文件、图表和 3D 场景都存在，且 MATSim 日志显示正常关闭，运行记录才会标为 `completed`。成功仍仅证明这些执行检查通过，不等于模型校准。

其他五个网页区域仍可试用，但明确标为“实验”；Greater Melbourne 目前只有大路网压力测试结果，不属于完整演示。

## IF Line：自由规划与受控政策分支

网页中的 **IF Line** 把一个已完成、带运行记录的仿真作为基线。用户进入全屏 3D 城市后，可以在真实路网与地形上逐点绘制一条折线路径，自行填写设计速度、每方向车道数、通行能力、单双向以及允许的出行方式。编辑器会把端点吸附到现有 MATSim 节点，显示长度和连接状态，并在满足连接与参数约束后才允许提交。提交后，系统真正向网络 XML 添加节点/link，再运行一个独立 MATSim 分支；它不是预先准备的答案幻灯片。

已有道路仍可直接点击，并创建以下一种实验性变更；二维路网图保留为备用编辑器：

- 自由绘制一条新的双向或单向道路；
- 调整已有道路限速；
- 按基线百分比调整已有道路通行能力；
- 对已有道路的机动车关闭，同时保留原有步行和自行车模式。

每个分支复用基线的合成人口计划、MATSim 随机种子和迭代次数，只生成一份修改后的路网并重新运行仿真。结果页同时显示总体与分方式差异；同一个 3D 沙盘会切换为影响视图，蓝色表示直接干预道路、绿色表示平均 link 延误减少、红色表示延误增加。运行中或失败时界面会明确标注仍在显示提交前基线，不会把旧画面冒充新结果。方案的路网参数前后值、控制条件、日志、产物和成功/失败状态保存在：

```text
output/ifline/<scenario_id>/scenario.json
output/ifline/<scenario_id>/comparison.json
output/<scenario_id>_network/network.xml
output/<scenario_id>_sim/
output/run_records/<scenario_id>/run_manifest.json
```

新版 3D 编辑器支持一个方案内组合 1–12 项修改、撤销/重做、编辑或移除单项，并将草案保存在当前浏览器。移动鼠标即时预览道路，直接拖动蓝点改走向；Shift 临时关闭吸附，选择会随点保存。可一键建议高架过渡段，在纵断面拖点调整相对地面高度；仍是随地形抬高的概念道路，非独立桥面线形。点击检查会自动加入或更新当前画路草案；运行只提交已检查、已确认的方案，不会越过检查直接运行未提交的路线。

“检查当前路线与方案的冲突”在内存中编译整个方案：地面交叉切分机动车 link 并共享节点；高架及匝道中间不误接地面道路。道路两端必须接地。道路占用宽度与现有建筑轮廓相交时，独立显示总数及稳定的“建筑1、建筑2…”编号列表，点击可定位。确认风险后才允许试算；按钮旁会说明未满足的条件，系统**不自动拆楼或削减地块**。任何修改或基线文件变化都会使检查凭据失效。

这是早期交通概念筛选，不是因果推断或施工设计。高度限制和相对地面坡度上限只是演示输入约束，不含真实地形纵坡、净空、桥墩、结构、信号配时和用地验证。没有土地利用反馈、诱发需求或长期城市发展模型。二维备用编辑器保留旧单项流程，不具有新版组合方案的建筑检查。详见 [方案操作与限制](docs/CITY_PLANS.md)。

## 新电脑上的一次性准备

### 1. 软件

- Python 3.10 或更高版本。
- Docker Desktop。小型演示至少需要 8 GB Docker 内存，建议分配 24 GB 以上。

在项目根目录创建独立 Python 环境并安装产品层依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

新版 CBD 路网阶段只使用与源码匹配的本地镜像和 PBF，不会在长任务中悄悄下载或构建。新电脑首次准备或修改 `vendor/network` 后，应显式构建网络镜像（这一步可能联网下载依赖，不是仿真）：

```bash
python3 -c 'from wrapper.runner import build_image; build_image()'
```

需求和 MATSim 镜像仍按现有入口在缺失时构建。Apple Silicon 的 R 镜像使用 `linux/amd64` 环境，可能比原生执行慢。2026 年 10 月已在 Windows/Ubuntu WSL2 新环境构建全部三个镜像，并复用迁移的路网/需求输入完成一次新短仿真；这不代表重新生成全套外部数据或重跑九次完整实验。详见最新验证记录。

### 2. 数据

仓库只跟踪区域 GeoJSON；大型或受分发约束的原始数据不会随 Git 仓库提供。完整演示需要：

- OpenStreetMap Victoria `.osm.pbf`：固定演示要求文件名为 `data/geofabrik_victoria-latest.osm.pbf`，避免上游自动匹配偶尔选中整个澳大利亚。通用 `build` 命令仍可自动下载，但正式演示前应把 Victoria PBF 准备到该路径。
- ABS 2016 / VISTA 2012–18 派生需求数据：按照 `vendor/demand/data/README.md` 和上游 OSF 数据说明放入 `data/`。
- `data/absRegionsReprojected.sqlite`、距离矩阵、SA1 属性/中心点/地址及 `vistaSummaries/` 中的统计文件。
- 3D 展示使用 `data/dem/fabdem_melbourne.tif` 与 `data/landmarks/v2/*.json`（兼容旧版 `data/landmarks/*.json`）。缺少这些文件不应伪装成完整 3D 演示。

人口和活动计划是根据统计分布合成的数据，不包含现实个人轨迹。不要把测试夹具或合成样本描述成完整真实人口数据。

地块缓存准备（需要先取得 Victoria PBF；不运行 MATSim）：

```bash
python3 -m pip install -r requirements-data.txt
python3 scripts/extract_landmarks.py --all
```

新版缓存保留 OSM 多多边形、庭院/岛屿空洞和水域，裁剪跨界面而非整块丢弃。
缓存另存 `data/landmarks/v2/`，不会覆盖旧缓存。普通运行依赖 Shapely；只有提取缓存需要 osmium。
要更新某次**已有结果回放**的地块显示，使用准确的运行目录与区域：

```bash
python3 scripts/refresh_scene_landmarks.py <RUN_sim> --region cbd
```

这只另存 `skyline_scene.landuse-v2.json` / `ifline_scene.landuse-v2.json`，不改原始结果、不重算交通。
网页仅加载与原场景 SHA-256 匹配的更新文件。新仿真直接使用新版缓存；运行记录记录实际选中的缓存路径与校验值。
OSM 面状地物不等于完整城市地籍；未标注土地仍保持中性底色，不能凭空补成建筑。

### 3. 运行前检查

```bash
python3 -m wrapper.cli doctor
```

它只检查 Python、依赖、Docker、Docker 资源、必需数据、区域边界、3D 数据和磁盘空间，不下载数据、不运行仿真。所有阻断项解决后再运行固定演示。

## 输出和运行证据

一次运行 `<run_id>` 会留下：

```text
output/<run_id>_network/             路网、原生 R 日志
output/<run_id>_demand/              合成人口/计划、原生 R 日志
output/process_logs/               外部程序 stdout/stderr（含镜像构建、SA1 筛选）
output/service_logs/web.log         网页服务启动、访问和错误日志（追加保留）
output/<run_id>_sim_config/config.xml 实际使用的 MATSim 配置
output/<run_id>_sim/                 MATSim 事件、计划、统计、图表、摘要和 3D JSON
output/run_records/<run_id>/
  run_manifest.json                  可核对的运行清单
  pipeline.log                       编排阶段和失败记录
```

`run_manifest.json` 记录：Git 基准提交和工作区是否有未提交修改、配置、随机种子、输入文件元数据、依赖锁定文件指纹、Docker 版本/镜像、开始结束时间、各阶段状态、日志位置、结果位置和最终产物核对结果。它不会保存环境变量、主机名、用户名或原始数据内容。

失败运行会保留 `failed` 记录，但不会进入网页的“完成结果”列表。网页只接受与当前任务预期 `run_id` 完全一致的返回结果。

### 已验证的干净重跑

2026-09-09（墨尔本时间）在新输出目录完成了固定演示：

- 运行 ID：`cbd_demo_20260908T205520Z_16879d`
- 路网：684 个节点、2,464 条链接
- 合成代理：1,037；出行：3,623
- MATSim：迭代 0、1、2，共 3 次；日志正常关闭
- 产物核对：要求的 16 项文件均存在且非空
- 总耗时：约 14 分 46 秒，其中包含首次重建 Java/MATSim 镜像和下载 Maven 依赖

证据在 `output/run_records/cbd_demo_20260908T205520Z_16879d/run_manifest.json`。`output/` 不随 Git 分发，因此这是当前机器的运行证据，不是克隆仓库后自动携带的示例结果。

### 已验证的 IF Line 对照

2026-09-10（墨尔本时间）从上述同一基线完成了两条受控分支：link 255
限速从 50 调整为 30 km/h，以及 links 890/2071 双向机动车关闭（保留
bike/walk）。两次均保持 1,037 个合成代理、3,623 次出行、随机种子 4711
和迭代 0–2，并正常关闭。后一个方案在当前模型中得到汽车平均出行时间
`+7.595 s`、全方式加权平均时间 `+1.958 s`；这是实验性差异，不是交通
改善/恶化的真实预测。证据和完整限制见 `validation/2026-09-09-local-tests.md`。

2026-09-10 还完成了一次从 3D 沙盘自由绘制新道路的真实分支：约 800 m
折线、3 个控制点、每方向 2 车道、双向，共写入 4 条有向 link。该分支保持
1,037 个合成代理、3,623 次出行、随机种子 4711 和迭代 0–2，MATSim 正常
关闭；事件流记录到新增 link 共 164 次 `entered link`。这只证明新增网络被
仿真读取并使用，不证明道路方案具有现实效益。详见
`validation/2026-09-10-freeform-road-editor.md`。

## 网页使用

固定小场景的完整运行、单项道路干预、证据导出与限制说明见
[可复现 CBD 对比演示](docs/REPRODUCIBLE_DEMO.md)。

双击 `start.command`。首次启动时，它会创建项目自己的 `.venv` 并安装
`requirements.txt`，避免依赖原开发电脑全局环境中偶然存在的 Python 包。
也可以在已经准备好的 Python 环境中执行：

```bash
python3 -m wrapper.server
```

启动器确认服务已就绪后才打开浏览器，重复启动会复用健康服务。服务与启动终端
分离，关闭终端或浏览器不会中断任务。服务日志追加到 `output/service_logs/web.log`；
路网、人口、区域筛选、MATSim 的外部程序输出按本次输出名称写到
`output/process_logs/<output_name>.log`，失败信息会指出具体文件。目录独立于 R/Java
管理的结果目录，失败和重复尝试不会覆盖旧日志。运行记录中的 `logs` 也包含这些位置。
启动器不会自动重启已有服务、重试失败任务或重新运行仿真。升级代码需要先等所有
任务结束，再停止旧服务并重新启动。开发时仍可直接运行 `uvicorn wrapper.api:app`
（前台进程随终端生命周期结束，不用于长期后台运行）。
外部程序的原始日志可能包含其打印的本机路径或数据；公开分享前仍需检查和脱敏。

然后打开：

- 用户界面：<http://127.0.0.1:8000/>
- API 文档：<http://127.0.0.1:8000/docs>

网页会明确区分：

- **本次新运行**：由当前任务完成，并通过运行 ID 和产物核对。
- **已有结果回放**：读取磁盘中的历史结果，不表示刚刚重新执行了仿真。

后端失败时网页会隐藏先前结果并显示失败；不会用上一次结果替代本次失败运行。

## 测试与验证

执行 Python 测试：

```bash
python3 -m unittest discover -s tests -v
```

保存的本地测试报告位于 `validation/`。测试覆盖 API 输入限制、数据缺失、运行前检查、GDAL 临时目录、后台任务失败、运行 ID 绑定、失败记录过滤、结果读取和部分 3D 数据逻辑。

2026-09-11 最新一次实际执行 67 项 Python 测试，全部通过（包含 17 项地块/回放测试和 16 项建筑/屋顶/回放测试）；建筑浏览器夹具的 21 项检查也通过。报告及执行日志见 `validation/2026-09-11-building-roofs.md`。先前的地块像素、空洞三角化和深度回归记录见 `validation/2026-09-11-land-parcels.md`。既有测试包括 IF Line 路网变更、自由绘制道路、连接失败、模式保留、A/B 汇总与 API 入队约束。上游 `vendor/demand/tests/testthat/` R 测试先前已执行：在显式补入其夹具所需的 EPSG:28355 后，仍有 1 项旧的 `plan.csv` MD5 快照不一致和 4 条绘图警告；没有删除或放宽该失败检查，本次未重跑 R 测试。`vendor/network/` 的单个 R 测试依赖旧的硬编码 city 配置，与当前环境变量入口不兼容，尚未作为独立测试执行；既有端到端演示覆盖了路网生成阶段。

“测试通过”和“仿真成功运行”都不等于模型已校准。当前没有真实交通观测对比、预测精度、性能提升或交通改善证据。

已有结果可单独更新建筑显示：`python3 scripts/refresh_scene_buildings.py <RUN_sim>`。
脚本优先读取匹配的地块更新，另存 `*.buildings-v1.json`，不重跑 MATSim、不改道路/车辆/比较数据。
API 只选用源文件 SHA-256 仍匹配的更新。屋顶沿真实轮廓内收、保留庭院并占用原有高度；
这是受约束的示意造型，不是逐栋建筑复原，暂未完整解析 OSM `building:part` 的层级关系。

## 其他 CLI/API 入口

高级用户仍可分别运行：

```bash
python3 -m wrapper.cli build --city test --region sample_region.geojson --output run1
python3 -m wrapper.cli demand --num-plans 500 --seed 4711
python3 -m wrapper.cli scenario --region sample_region.geojson --output scenario1 --sample-percent 5 --seed 4711
python3 -m wrapper.cli simulate --network-output scenario1_network --demand-output scenario1_demand --output scenario1_sim --iterations 2 --seed 4711
python3 -m wrapper.cli analyze --sim-output scenario1_sim
```

主要 HTTP 入口包括 `/pipeline/run`、`/ifline/baselines`、`/ifline/network/{run_name}`、`/ifline/run`、`/ifline/scenarios`、`/jobs/{job_id}`、`/runs`、`/runs/{run_name}` 和 `/system/status`。耗时任务串行执行，避免多个大型容器同时耗尽内存。

## 已知限制

- 只有 `cbd_small_v1` 被定义为固定完整演示；其他区域不能自动继承其验证结论。
- `scenario` 的覆盖率检查使用路网节点矩形包围盒，不是严格多边形包含验证。
- `pt` 是固定速度传送模式，没有接入完整 GTFS 车辆、站点和时刻表。
- 默认三次实际迭代只用于流程演示，不足以证明行为收敛或研究结论。
- 原始需求数据没有自动下载器；新电脑仍需按说明手动准备。
- 网页是本地 FastAPI/Three.js 原型，不是正式桌面安装程序或生产运维平台。
- 3D 建筑分类、颜色和部分造型用于可读性，不是逐栋摄影测量复原。
- IF Line 目前一次只做一条自由绘制道路或一项已有道路干预，并进行确定性单次对比；几何交叉不会自动创建路口，且尚未提供多随机种子置信区间、多个政策组合、诱发需求或土地利用反馈。

更多项目边界见 `PROJECT_OVERVIEW.md`；安全清理旧输出见 `CLEANUP_GUIDE.md`。
