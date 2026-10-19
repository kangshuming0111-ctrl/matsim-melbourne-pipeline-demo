# MATSim 墨尔本交通仿真平台：完整成果总览

## 1. 这个项目是什么

这是一个把墨尔本交通数据准备、MATSim 仿真、结果分析和交互式 3D 城市展示连接在一起的本地软件原型。它当前的产品方向是 **IF Line 城市交通政策实验室**：规划人员从一个已完成且可审计的基线出发，自由绘制一条新道路或改变一项既有道路条件，重新运行 MATSim，并直接比较方案与基线的差异。

使用者不需要理解 R、Java、MATSim 配置文件或 Docker 命令。双击 `start.command` 就能打开网页并查看已有结果；当 Docker Desktop 已启动且原始数据准备完整时，还可以选择区域并生成新仿真。

完整流程是：

```text
选择墨尔本区域
  → 生成真实 OSM 路网
  → 按相同区域生成人口和出行需求
  → 运行 MATSim 多方式交通仿真
  → 自动统计结果
  → 在 3D 墨尔本场景中回放真实车辆轨迹
```

政策实验流程是：

```text
选择有运行记录的基线
  → 在 3D 城市中自由画一条道路，或选择一条既有道路
  → 设置走向、单双向、车道、限速、容量、允许方式或封路方案
  → 校验端点连接、长度、边界和网络参数
  → 固定同一份需求、随机种子和迭代次数
  → 运行独立的方案分支
  → 对比总体与分方式指标
  → 在 3D 城市中查看延误增加、减少及直接干预道路
  → 保存参数、日志、产物和成功/失败记录
```

## 2. 已经实现的内容

### 数据与输入

- 使用真实 OpenStreetMap 路网，并缓存 Victoria `.osm.pbf` 数据。
- 使用 ABS 2016 SA1 人口普查区域及墨尔本合成人口数据。
- 使用 VISTA 2012–18 出行调查生成日常活动链。
- 自动从用户选择的地理边界推导相交的 SA1，避免路网与人口范围不一致。
- 使用 FABDEM 裸地高程建立真实起伏地形。
- 从 OSM 提取真实建筑轮廓、公园、图书馆、电车线路及商业区域。

### 仿真

- 生成 MATSim `network.xml` 路网文件。
- 生成 MATSim `plan.xml` 人口与活动计划文件。
- 自动生成并运行 MATSim 配置。
- 支持 car、walk、bike 和简化的 pt 出行。
- 修复了上游老代码在新环境中的 R 包、并行进程、容器权限、Apple Silicon 和 MATSim 模式配置问题。
- API 任务串行排队，避免多个大型 Docker 任务同时耗尽内存。

### 分析

- 自动输出人数、出行数、方式占比、平均时间、平均距离和迭代范围。
- 保留 MATSim 原生 events、plans、scores、mode statistics 等结果。
- 自动生成适合非专业用户阅读的摘要和图表。

### 交互式 3D 城市展示

- 蓝天、真实高程地形和可旋转、缩放、WASD/方向键移动的自由视角。
- 道路采用路缘、沥青路面、车道线和独立交通色带四层结构，表达从畅通到严重拥堵的变化。
- 建筑使用真实 OSM 轮廓和高度；颜色按住宅、办公、商业、公共建筑和工业用途表达。
- 对 OSM 未注明用途的建筑进行确定性的视觉分类；这只影响展示，不改动原始地理数据。
- 建筑包含分类窗格、坡屋顶、商业雨棚、公共建筑穹顶、分层塔冠和高层尖顶，不再只是统一的“火柴盒”。
- Melbourne Central、Eureka Tower、Rialto 和 101 Collins 使用克制的专属轮廓/材质，并与 State Library、Parliament House、Queen Victoria Market 等地标一起标注。
- 显示真实公园、低多边形树木、图书馆、街灯和墨尔本电车线路。
- 小汽车按 MATSim 真实车辆事件和仿真时间沿路网移动。
- 默认从本次仿真的车辆活动峰值开始；提供播放/暂停、活动车辆数、时间轴、三级速度、城市视角和交通俯视。
- 六个网页预设区域都有独立的 OSM 建筑与地标缓存，不再只有 CBD 有城市模型。

### 产品化与可靠性

- 网页启动前检查 Docker、资源、原始数据、3D 数据和磁盘空间。
- `python3 -m wrapper.cli doctor` 可执行同一套终端自检。
- 历史结果浏览器可以直接重新打开已有仿真，不必重复计算。
- 最近任务状态持久保存，刷新或重启后仍能解释任务结果。
- API 对输出名、输入文件名和数值范围做校验。
- 切换历史 3D 场景时主动释放旧动画循环、事件监听器和 WebGL 资源。
- Three.js 文件保存在项目内，3D 页面不依赖外部 CDN。
- 自动化测试覆盖环境检查、结果发现、任务历史和 API 输入保护。

### IF Line 受控方案对比

- 只允许从已完成、带审计记录且仍保有路网与需求文件的运行建立分支。
- 3D 编辑器允许逐点绘制折线道路，自行设置单双向、车道、限速、容量和 car/bike/walk 方式；端点吸附到真实 MATSim 节点，中间点可写成新节点。
- 可在网页简化路网中选择真实 MATSim link，并查看道路类型、长度、限速、容量、车道及基线进入次数。
- 支持调整限速、按比例调整容量，以及仅移除 `car` 模式的道路关闭；步行和自行车模式不会被一并删除。
- 分支复用基线需求计划、MATSim 随机种子和迭代次数，降低无关输入差异对 A/B 结果的干扰。
- 输出总体平均出行时间、距离、得分与分方式占比/时间差异，并生成以蓝、绿、灰、红表达干预与 link 延误变化的 3D 差异场景。
- 每个方案保留独立路网、仿真输出、`scenario.json`、`comparison.json` 和运行清单；失败方案同样留档，且不能在网页中冒充成功结果。

## 3. 使用入口

### 最简单：双击启动

1. 双击项目根目录中的 `start.command`。
2. 浏览器自动访问 <http://127.0.0.1:8000>。
3. 查看已有结果可以直接进行；生成新仿真时先打开 Docker Desktop，并在网页点“重新检查”。
4. 选择区域，点击“生成交通仿真”。

### 命令行

```bash
# 生成路网
python3 -m wrapper.cli build --city test --region sample_region.geojson --output run1

# 生成人口需求
python3 -m wrapper.cli demand --num-plans 5000

# 生成同一区域的路网和需求
python3 -m wrapper.cli scenario --region sample_region.geojson --output scenario1

# 运行 MATSim
python3 -m wrapper.cli simulate --network-output scenario1_network --demand-output scenario1_demand --output scenario1_sim

# 生成摘要
python3 -m wrapper.cli analyze --sim-output scenario1_sim

# 重新导出 3D 场景
python3 -m wrapper.cli skyline --sim-output scenario1_sim
```

### HTTP API

服务启动后可访问 <http://127.0.0.1:8000/docs>，主要接口包括：

- `POST /network`
- `POST /demand`
- `POST /scenario`
- `POST /simulate`
- `POST /analyze`
- `POST /pipeline/run`
- `GET /ifline/baselines`
- `GET /ifline/network/{run_name}`
- `POST /ifline/run`
- `GET /ifline/scenarios`
- `GET /jobs/{job_id}`
- `GET /pipeline/regions`
- `GET /system/status`
- `GET /runs`
- `GET /runs/{run_name}`
- `GET /jobs`

## 4. 当前区域

网页目前提供六个已定义区域：

- 墨尔本市中心 CBD
- 内城北区
- 内城东区
- 内城南区
- 内城东北区
- 内城东南区

`data/region_greater_melbourne.geojson` 是从 ABS GCCSA 数据提取的真实 Greater Melbourne 边界，目前作为大规模压力测试输入保留，没有放进网页的一键区域列表。

## 5. 项目结构

```text
wrapper/                 产品层
  api.py                 FastAPI 和网页/API 路由
  cli.py                 命令行入口
  pipeline.py            一键完整流程
  runner.py              路网 Docker 调用
  demand_runner.py       人口需求 Docker 调用
  baseline_runner.py     MATSim Docker 调用
  scenario.py            路网与人口区域匹配
  analyze.py             结果摘要
  skyline.py             3D 场景数据生成
  static/index.html      网页和 Three.js 3D 客户端

docker/                  三个可复现运行环境
vendor/network/          上游路网生成 R 项目及必要修复
vendor/demand/           上游需求生成 R 项目及必要修复
vendor/baseline/         上游 MATSim Java 项目及入口
scripts/                 一次性数据预处理工具
tests/                   自动化测试
data/                    本机原始数据、边界、DEM、OSM 和地标缓存
output/                  每次运行产生的结果，不属于源代码
```

## 6. 数据真实性与表达边界

- 路网、地形、建筑轮廓、公园、图书馆和电车线路来自真实地理数据。
- 人口与活动链是依据人口统计和调查分布生成的合成数据，不是现实中某个具体人的轨迹。
- 车辆动画来自本次 MATSim 仿真的事件，不是装饰性随机动画。
- 建筑用途色、未分类建筑的视觉推断和部分顶部造型是为了增强城市建造游戏式的可读性，不应当被解释为逐栋建筑的精确摄影测量复原。
- 当前公交 `pt` 为简化的传送方式；尚未接入完整 GTFS 车辆、站点和时刻表仿真。

## 7. 当前阶段

现在已经不是单独的脚本，而是一个可运行的软件原型：数据处理、仿真、分析、API、网页、3D 回放、自由绘制道路和受控方案分支已经贯通。当前 IF Line 一次只能添加一条折线道路或修改一项既有道路；几何交叉不会自动切分成路口，结果属于固定模型假设下的实验性反事实，不是已校准的因果预测。下一阶段最有价值的工作不是继续堆装饰性功能，而是：

1. 增加多随机种子重复实验、置信区间和基线校准状态，让规划人员看到结果的不确定性。
2. 支持多道路组合、几何交叉自动切分成路口，以及更完整的网络连通性与工程约束校验。
3. 增加分区可达性、不同群体影响和公平性指标，而不只看全市平均值。
4. 如需讨论多年城市发展，接入独立的土地利用/需求反馈模型；不能由当前 MATSim 单独推断。
5. 把原始大数据做成可安装的数据包或下载器，并继续推进桌面安装包。
6. 接入完整 GTFS 公交仿真并提高 3D 差异视图性能。
