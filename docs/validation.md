# 0.3.0 验证结果

日期：2026-10-13。目标仅为 GaussDB Kernel **507.0.0 O 模式**，集中式目录值 A，分布式目录值 ORA、2 DN。测试基于已有本地数据库实验环境，另创建独立集中式 TLS 实例；没有云服务或全平台认证含义。

## 回归结果

| 客户端与测试集 | 结果 | 条件 |
| --- | --- | --- |
| Linux aarch64 / Python 3.12，全量 tests | **174 passed in 33.33s**，无失败/跳过 | 单元 + 集中式/分布式集成 + 11 项独立 TLS 测试 |
| Linux amd64 / Python 3.12，unit + integration | **163 passed in 21.63s**，无失败/跳过 | Docker 在 ARM 宿主机上仿真 x86，使用重建驱动和匹配 x86 libpq |
| 0.3.0 wheel 隔离 venv | 集中式、分布式均 PASS | 取消 PYTHONPATH，确认从 venv site-packages 导入；建表/CRUD/事务回滚 |
| 公开驱动源码入口 | PASS | requirements-driver.txt 固定 GitHub 提交，在线构建 driver 与 pool |
| 有界性能与 30 分钟混合读写 | 两种部署均 PASS | 双部署同时运行；无节点故障注入 |

测试覆盖 JSON/数组/Duration、整数越界、日期/时区、聚合/子查询/窗口、并发事务及同键创建、锁竞争、服务端游标生命周期、schema 内省、迁移组合变更、多 app 数据迁移与并发执行器、SQLite 共存、FastAPI、TLS/认证负例、坏连接替换和初始多地址回退。新增用例位于 `tests/integration/test_extended.py`、`tests/transport/test_tls.py` 与 `tests/unit/test_extensions.py`。

实测发现并修复 JSON Unicode 编码、路径键转义、JSON 构造参数类型、迁移改名与改类型顺序、跨应用迁移目标选择、编程/数据异常映射。507 的 SERIALIZABLE 降级和集中式 EXPLAIN JSON 格式问题采用明确拒绝/使用 TEXT 的边界，不伪装成功。

## 复现

1. 取得有授权且匹配平台的 GaussDB libpq，并配置动态库路径。
2. `python -m pip install -r requirements-driver.txt`，再 `python -m pip install '.[test,fastapi]'`。
3. 参考 `.env.example` 设置两套专用测试库的进程环境，凭据不写入源文件。
4. `python -m pytest tests/unit tests/integration --live -q --tb=short`。
5. TLS 另按[扩展验证](extended-validation.md)配置环境；完整 `python -m pytest tests --live -q` 才包含 11 项传输专项。不配置 TLS 会明确 skip，不能算作全部通过。
6. `python scripts/soak.py --seconds 1800` 运行有界负载。测试自行创建/清理随机 schema。

本地镜像使用 Python 3.12、Tortoise ORM 1.1.8、gaussdb/gaussdb-pool 1.0.4、pypika-tortoise 0.6.5、anyio 4.15.1。测试镜像需包含 FastAPI/httpx/asgi-lifespan，TLS 错误 CA 用例需 openssl。驱动及 libpq 细节见[来源文档](DRIVER_PROVENANCE.md)。基础静态检查使用 `ruff check --isolated --select E4,E7,E9,F src tests scripts/soak.py`，另检查 `git diff --check`。

## 尚不能宣称完成的内容

174 个参数化测试不是原计划 88 组子场景的全量覆盖。集中式 TLS 恢复不等于分布式 CN/DN 故障切换；30 分钟正常负载不等于故障注入或生产容量测试。物理 x86、Python 3.10/3.11、Windows/macOS、完整上游套件及全部字段/查询组合仍需独立矩阵。迁移并发已测预建历史表的情况，首次初始化仍应串行。

[88 组清单](COVERAGE_88.md)逐项保留剩余内容；0.2.0 的 67/77 项结果仅为[历史阶段报告](PHASE3_REPORT_20261012.md)。原始日志/私有证书/凭据不随 Git 仓库分发。

## 本地批量测量

下表为每组 3 次的中位耗时（秒），包含事务内增查改删；两种部署同时运行，池最多 10 条连接，不作为生产吞吐承诺。

| 并发 | 每事务行数 | 集中式 | 分布式 |
| --- | --- | --- | --- |
| 1 | 100 | 0.053 | 0.062 |
| 1 | 1000 | 0.499 | 0.566 |
| 10 | 100 | 0.144 | 0.157 |
| 10 | 1000 | 1.697 | 2.010 |
| 50 | 100 | 1.017 | 0.960 |
| 50 | 1000 | 9.162 | 10.344 |

集中式持续 **1800.20 秒**、累计 **79,222** 次事务检查；分布式持续 **1800.03 秒**、累计 **76,002** 次。计数包含前置预热/批量测量与主动回滚事务；正常完成后均断言表中无残留行，删除本次随机 schema。
