# GaussDB 507 Tortoise-ORM 阶段三实现与验证报告

日期：2026-10-12。适配包：tortoise-gaussdb 0.2.0。结论：已补齐主要工程缺口并验证部分新增能力，尚未完成任务书 88 组全量验收。

## 本轮交付

| 原缺口 | 本轮结果 |
| --- | --- |
| distributed.py 未接入建表 | 已接入 schema generator；配置在 credentials.distributions，以真实 schema.table/column 为键；支持 HASH、REPLICATION；M2M 中间表单独配置 |
| 建表依赖默认分布 | 分布式未配置策略默认报错；只有显式 allow_default_distribution=True 才允许默认策略；集中式不生成分布子句 |
| schema 预检限 public/tortoise_% 且手工执行 | 标准 Tortoise.generate_schemas(safe=True) 已可重复执行；安全 DO 块覆盖任意业务 schema；双引号/单引号/空格 schema 有实库测试 |
| 原生迁移未验收 | 原生 init/makemigrations 生成、适配入口离线 sqlmigrate、migrate、加普通字段/改名/回退/重复执行、失败回滚已在两种形态通过 |
| ignore_conflicts 使用 PostgreSQL 语法 | 507 实测拒绝 ON CONFLICT；适配为 ON DUPLICATE KEY UPDATE NOTHING，重复行保持原值、新行写入 |
| targeted upsert 风险 | on_conflict/update_fields 明确抛 OperationalError；未宣称支持指定冲突目标的更新 |
| 测试未落地 | 新建 pytest 套件，本次 67 项通过；其中 27 项单元、20 项集中式、20 项分布式；不等于 88 组计划已完成 |
| 关系/并发覆盖不足 | 增加逻辑一对多、select_related/prefetch_related、多对多增删去重、3 连接池/20 并发、超时恢复、查询取消、心跳、锁 NOWAIT 等验证 |
| 安装未验收 | wheel/sdist 已构建；无系统包继承的新 venv 通过本地 wheelhouse 离线安装；两种实例建表/读写/回滚通过，导入路径确认是 venv 的 site-packages |
| 应用示例 | 新增 async_crud 与 FastAPI 示例；FastAPI 生命周期、10 并发创建与读取、404/422 在两种形态通过 |

补充修复：模式预检同时校验 GaussDB Kernel 507；预检失败关闭连接池；不再记录连接模板/参数值；schema 通过参数化 set_config 配置；日期二进制使用整数微秒，BC 日期拒绝而不静默变成 AD；时间小数解析不经 float。

## 迁移的明确使用契约

1. 使用 Tortoise 原生迁移文件和生成器，但执行、计划和 SQL 预览用 `python -m tortoise_gaussdb.migrations`（或安装后的 gaussdb-tortoise）。1.1.8 的上游 CLI 没有第三方 schema editor 注册接口，直接 `tortoise migrate` 尚不是支持路径。
2. 迁移 recorder 修复了 PostgreSQL `$1` 占位符问题，使用 `%s`；历史表显式 schema 限定。分布式历史表使用 REPLICATION，避免 id 与 app/name 两组唯一键冲突于 HASH 分布要求。
3. 迁移 DDL 与历史更新同事务提交；历史表锁串行化迁移。测试覆盖失败加列回滚且不记成功；尚未进行两个迁移进程争锁专项。
4. 自动生成的 CreateSchema 在回退时保留连接 schema 与历史表，避免 CASCADE 删除无关对象及记录；其他 schema 删除用 RESTRICT。此行为已经写入 README。
5. 仅支持原子迁移，拒绝 fake/non-atomic。新增关系字段迁移明确拒绝；复杂索引、约束、类型、跨应用依赖等尚未完整验收。
6. SQL 预览测试使用无法连接的地址，仍能成功生成 SQL，证明没有访问数据库。

## 实测环境与证据

- 内核：GaussDB Kernel 507.0.0 build d791c80a，last mr 27222。
- 集中式 A 模式；分布式 ORA 模式，经现有 CN 访问。分布式聚合计划包含 All datanodes；100 行跨分片提交/回滚断言通过。
- 客户端：现有 Linux aarch64 容器，CPython 3.12，Tortoise-ORM 1.1.8，gaussdb/gaussdb-pool 1.0.4，pypika-tortoise 0.6.5。
- 底层驱动仍为既有修复 fork，客户端库仍由已有镜像提供；详见 `docs/DRIVER_PROVENANCE.md`。未将 PyPI 同版本包视为等价。

| 证据 | 结果 |
| --- | --- |
| reports/phase3-regression.xml | 67 tests，0 failures，0 errors，0 skipped |
| reports/phase3-cli.xml | 2 个 CLI 链路测试通过，已包含在最终 67 项中，不重复计数 |
| reports/clean-install-central.json | 隔离安装后集中式 smoke PASS |
| reports/clean-install-dist.json | 隔离安装后分布式 smoke PASS |
| tests/unit、tests/integration | 可执行源用例与编号关联 |
| docs/COVERAGE_88.md | 全部 88 组计划逐项跟踪；51 组已有部分覆盖，37 组本轮未覆盖；没有把 PARTIAL 记为全量通过 |
| dist/wheelhouse、dist/requirements-offline.txt | 核心运行依赖离线包及确切版本/哈希；不含 libpq，也不含 FastAPI/test extras |

早期 phase3-first.xml、phase3-migrations.xml 是本轮中间结果，最终以 phase3-regression.xml 为准。

## 剩余工作

- JSON 属性、FOR NO KEY UPDATE、带 LIMIT/ORDER BY 的 UPDATE/DELETE 保持关闭。
- 数组、窗口、复杂子查询、完整查询/类型边界、物理外键/级联与完整关系矩阵尚未验收。
- targeted upsert、增量关系迁移尚不支持，不能作为通过项。
- TLS 证书正反例、错误凭证/权限全集、多 alias、事务内取消、并发事务隔离、迁移竞争、批量异常原子性还需专项。
- HA/CN/DN 切换与 30 分钟性能稳定性未执行；本轮不重启数据库、不改变拓扑。
- Python 3.10/3.11/其他版本、Linux x86_64、Windows/macOS 客户端尚未验证。
- 隔离 venv 安装通过，不等于从全新操作系统安装授权 libpq 的完整验收；历史 fork 驱动源码到 wheel 的可复现构建仍待核验。

本轮交付保留这些限制，不宣称已达到“507 O 模式两种形态全量支持”。下一阶段应按 COVERAGE_88.md 补齐 P0 未覆盖项，再扩展 P1 和平台矩阵。
