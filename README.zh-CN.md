# MATSim Melbourne unified framework

一个范围有限但证据清楚的本地技术原型：为同一个墨尔本区域生成路网和合成出行需求，运行 MATSim，生成统计，并在网页中查看该次运行的结果与 3D 回放。

本项目不声称已经校准墨尔本交通模型，也不把合成代理称为真实用户。当前优先目标是让一个小场景能够重复运行、留下可核对记录，并让非专业用户能够分辨“新运行”和“已有结果回放”。

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

唯一作为可重复演示目标的配置是 `cbd_small_v1`：

| 项目 | 固定值 |
|---|---:|
| 区域 | `data/sample_region.geojson`（墨尔本 CBD 小区域） |
| 路网及 SA1 缓冲 | 500 m |
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

该命令会自动使用唯一的新运行 ID，不覆盖旧结果。只有路网、人口计划、MATSim 事件、统计文件、图表和 3D 场景都存在，且 MATSim 日志显示正常关闭，运行记录才会标为 `completed`。

其他五个网页区域仍可试用，但明确标为“实验”；Greater Melbourne 目前只有大路网压力测试结果，不属于完整演示。

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

三个 Docker 镜像会在第一次使用时构建。Apple Silicon 使用固定的 `linux/amd64` R 镜像，因此会比原生架构慢。

### 2. 数据

仓库只跟踪区域 GeoJSON；大型或受分发约束的原始数据不会随 Git 仓库提供。完整演示需要：

- OpenStreetMap Victoria `.osm.pbf`：固定演示要求文件名为 `data/geofabrik_victoria-latest.osm.pbf`，避免上游自动匹配偶尔选中整个澳大利亚。通用 `build` 命令仍可自动下载，但正式演示前应把 Victoria PBF 准备到该路径。
- ABS 2016 / VISTA 2012–18 派生需求数据：按照 `vendor/demand/data/README.md` 和上游 OSF 数据说明放入 `data/`。
- `data/absRegionsReprojected.sqlite`、距离矩阵、SA1 属性/中心点/地址及 `vistaSummaries/` 中的统计文件。
- 3D 展示使用 `data/dem/fabdem_melbourne.tif` 与 `data/landmarks/*.json`。缺少这些文件不应伪装成完整 3D 演示。

人口和活动计划是根据统计分布合成的数据，不包含现实个人轨迹。不要把测试夹具或合成样本描述成完整真实人口数据。

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

## 网页使用

双击 `start.command`。首次启动时，它会创建项目自己的 `.venv` 并安装
`requirements.txt`，避免依赖原开发电脑全局环境中偶然存在的 Python 包。
也可以在已经准备好的 Python 环境中执行：

```bash
python3 -m uvicorn wrapper.api:app
```

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

最终 Python 本地测试结果为 22/22 通过。上游 `vendor/demand/tests/testthat/` R 测试也已执行：在显式补入其夹具所需的 EPSG:28355 后，仍有 1 项旧的 `plan.csv` MD5 快照不一致和 4 条绘图警告；没有删除或放宽该失败检查。`vendor/network/` 的单个 R 测试依赖旧的硬编码 city 配置，与当前环境变量入口不兼容，尚未作为独立测试执行；本次端到端演示实际覆盖了路网生成阶段。详见验证报告。

“测试通过”和“仿真成功运行”都不等于模型已校准。当前没有真实交通观测对比、预测精度、性能提升或交通改善证据。

## 其他 CLI/API 入口

高级用户仍可分别运行：

```bash
python3 -m wrapper.cli build --city test --region sample_region.geojson --output run1
python3 -m wrapper.cli demand --num-plans 500 --seed 4711
python3 -m wrapper.cli scenario --region sample_region.geojson --output scenario1 --sample-percent 5 --seed 4711
python3 -m wrapper.cli simulate --network-output scenario1_network --demand-output scenario1_demand --output scenario1_sim --iterations 2 --seed 4711
python3 -m wrapper.cli analyze --sim-output scenario1_sim
```

主要 HTTP 入口包括 `/pipeline/run`、`/jobs/{job_id}`、`/runs`、`/runs/{run_name}` 和 `/system/status`。耗时任务串行执行，避免多个大型容器同时耗尽内存。

## 已知限制

- 只有 `cbd_small_v1` 被定义为固定完整演示；其他区域不能自动继承其验证结论。
- `scenario` 的覆盖率检查使用路网节点矩形包围盒，不是严格多边形包含验证。
- `pt` 是固定速度传送模式，没有接入完整 GTFS 车辆、站点和时刻表。
- 默认三次实际迭代只用于流程演示，不足以证明行为收敛或研究结论。
- 原始需求数据没有自动下载器；新电脑仍需按说明手动准备。
- 网页是本地 FastAPI/Three.js 原型，不是正式桌面安装程序或生产运维平台。
- 3D 建筑分类、颜色和部分造型用于可读性，不是逐栋摄影测量复原。

更多项目边界见 `PROJECT_OVERVIEW.md`；安全清理旧输出见 `CLEANUP_GUIDE.md`。
