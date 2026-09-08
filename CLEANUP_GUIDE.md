# 项目空间与清理说明

当前项目约 3GB，其中 `output/` 约 2GB、`data/` 约 957MB。源代码本身不到几十 MB；主要空间来自测试运行结果和本机数据。

## 绝对不要随意删除

- `wrapper/`：Python、API、网页和 3D 展示核心。
- `vendor/`：三个上游项目及兼容性修复。
- `docker/`：运行环境定义。
- `data/absRegionsReprojected.sqlite`：ABS 区域几何。
- `data/distanceMatrix.rds`：需求模型距离矩阵。
- `data/geofabrik_victoria-latest.osm.pbf`：Victoria OSM 缓存。
- `data/dem/fabdem_melbourne.tif`：地形高程。
- `data/landmarks/*.json`：六个预设区域的 OSM 建筑与地标缓存。
- VISTA、人口和地址等需求生成原始数据。

## 可以重新生成

- `output/demo_*`：网页测试产生的临时完整运行。
- `output/*_sim_config`：仿真配置中间目录。
- `output/*/ITERS` 和 `output/*/tmp`：MATSim 每轮及临时结果。
- Docker 镜像：删掉后可重建，但首次运行会耗时且可能需要联网。

## 建议保留的基准结果

- `output/scenario1_network`
- `output/scenario1_demand`
- `output/scenario1_sim`
- 至少一个最新、确认可正常显示 3D 建筑与车辆动画的 `demo_*_sim`，以及与它同名的 `_network`、`_demand`。

## 推荐清理原则

不要按单个文件随意删除一套运行。网页完整运行使用同一个前缀产生：

```text
demo_时间戳_network
demo_时间戳_demand
demo_时间戳_sim_config
demo_时间戳_sim
```

清理时应以相同时间戳为一组。先确认要保留哪一组，再删除其余旧组。删除前建议把必要结果压缩备份。

本说明只完成分类，没有自动删除任何文件。
