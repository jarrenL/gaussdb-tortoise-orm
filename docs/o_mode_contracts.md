# GaussDB 507 O 模式契约（2026-10-08 历史记录）

> 2026-10-12 更新：本文保留历史探测结论。O2/O5 不代表原生迁移可直接使用；现行实现使用独立迁移 executor/recorder。O6 手工预检已由标准建表路径的安全 DO 块替代。分布配置、当前支持范围以 README 和 PHASE3_REPORT_20261012.md 为准。

日期：2026-10-08
环境：C507-O（gaussdb-507-ha-lab, 55452, datcompatibility=A）
     D507-O（gaussdb-507-cn-lab, 55432 CN + 2 DN + GTM, datcompatibility=ORA）
内核：GaussDB Kernel 507.0.0 build d791c80a, last mr 27222
驱动：gaussdb 1.0.4（本地 fork 构建，非 PyPI 版——见 §6）
ORM：tortoise-orm 1.1.8

本文档每条契约都由探针脚本实测固化，脚本路径标注在每节。契约变化必须重跑对应探针。

## 1. 驱动层（scripts/segv_isolate.sh, date_adapter_probe.py, pool_loader_check.py）

| # | 契约 | 证据 |
|---|---|---|
| D1 | PyPI gaussdb 1.0.4 连接失败路径 SIGSEGV | finish_pgconn 反射读 password→PQpass() 在失败连接上返回 NULL，ctypes 崩溃 |
| D2 | 单独交付的本地 gaussdb-python fork 已修复 | finish_pgconn 显式参数传递；15 文件差异 |
| D3 | gaussdb_pool 的 configure 回调必须是 async | fork 的 pool await 回调返回值；同步回调→"object NoneType can't be used in 'await' expression"，池初始化超时 |
| D4 | date 二进制绑定必须 8 字节微秒（timestamp wire 格式） | int4 days 被拒（Insufficient data left in message）；int8 micros 存出 2024-02-29 |

## 2. 类型与 wire 格式（scripts/ts_vs_date_probe.py, type_bisect.py）

| # | 契约 | 证据 |
|---|---|---|
| T1 | DATE 列返回 OID **1116**（非 PG 的 1082），文本 `YYYY-MM-DD 00:00:00 AD` | 带 AD/BC 纪元后缀是 DATE 列的判别标志 |
| T2 | 真 TIMESTAMP 列 OID 1114，无纪元后缀；TIMESTAMPTZ OID 1184 | — |
| T3 | bigint/numeric/float/bool/text/bytea(1KB)/timestamp 全部正常往返 | type_bisect 9 例中 8 PASS |
| T4 | O 模式空字符串 `''` 归并为 NULL | `SELECT ''::text IS NULL` → true；NOT NULL 列插 '' → NotNullViolation |
| T5 | O 模式 DATE 字面量不吃 ISO | `date '2024-02-29'` 报错 invalid value for "MON"；`cast('29-JAN-2024' as date)` = **2024-01-29**（DD-MON-YYYY，日在前）；`to_date(...,'YYYY-MM-DD')` 正常 |
| T6 | `d::text` 输出 Oracle 风格 `29-FEB-24` | DateStyle=ISO 但 DATE 列文本是 Oracle 形态 |

## 3. DDL 与 schema（drop_semantics.py, 两形态 gsql 实测）

| # | 契约 | 影响形态 | 证据 |
|---|---|---|---|
| S1 | `CREATE SCHEMA IF NOT EXISTS` 语法不支持 | 两者 | syntax error at or near "NOT EXISTS" |
| S2 | `CREATE TABLE IF NOT EXISTS` 支持 | 两者 | CREATE TABLE 成功（分布式附 HINT 建议 DISTRIBUTE BY） |
| S3 | **CN 上非限定 DDL/DML 不走 search_path** | 分布式 | INSERT 报 "does not exist on DN dn2_lab"；DROP IF EXISTS 对存在表报 does not exist。**必须 schema 限定名（Meta.schema）** |
| S4 | **CN 完全不支持 REFERENCES 约束** | 分布式 | FeatureNotSupported: REFERENCES constraint is not yet supported。ORM 关系必须 db_constraint=False（逻辑关系） |
| S5 | 分布式建表需 node group 权限 | 分布式 | GRANT CREATE ON NODE GROUP dual_group + ALTER ROLE ... NODE GROUP |
| S6 | **不含分布键的唯一索引被拒** | 分布式 | Cannot create index whose evaluation cannot be enforced to remote nodes。含分布键的复合唯一索引 OK → 业务唯一键必须包含分布键 |

## 4. 分布式行为（scripts/dist_evidence.py）

| # | 契约 | 证据 |
|---|---|---|
| X1 | ORM 建表默认 HASH 分布、分布列=第一列（attnum=1） | pgxc_class: locator=H, attnum=1 |
| X2 | 查询真实跨 DN | EXPLAIN: Streaming(type: GATHER) Node/s: All datanodes |
| X3 | 20 行实际分布 DN1=9、DN2=11 | DN 直查（55442/55452 端口） |
| X4 | 跨 DN 事务提交/回滚一致 | 提交后10行更新生效；回滚后 doomed=0、总数不变 |
| X5 | CN 建表 DISTRIBUTE BY 可显式指定 | 语法支持（gsql 实测），缺省时用默认 node group 策略 |

## 5. Tortoise-ORM 1.1.8 适配要点

| # | 要点 |
|---|---|
| O1 | engine 模块暴露 `client_class`；连接配置用字典 credentials |
| O2 | capabilities.dialect 必须是 "postgres"（迁移框架 _schema_editor 按 dialect 分发，否则掉进通用 BaseSchemaEditor） |
| O3 | 上游 psycopg 后端顶层 import psycopg，与 gaussdb fork 不共存 → 适配包 client/executor/schema 自包含实现（继承 base_postgres） |
| O4 | 1.1.8 事务 API：`tortoise.transactions.in_transaction("alias")`（Tortoise.in_transaction 已移除） |
| O5 | 迁移框架按 `connection.__class__.__module__` 含 "psycopg" 分发 PsycopgSchemaEditor；tortoise_gaussdb.client 不含 → 依赖 dialect=="postgres" 兜底到 BasePostgresSchemaEditor（已验证此路径可用） |
| O6 | generate_schemas(safe=True) 依赖 CREATE TABLE IF NOT EXISTS（507 支持）+ CREATE SCHEMA IF NOT EXISTS（507 不支持）→ GaussDBSchemaGenerator.probe_existing_schemas() 预检后跳过 |

## 6. 驱动来源与构建（关键供应链事实）

- **PyPI gaussdb==1.0.4 不可直接用于 507**（D1 段错误）。
- 可用驱动：单独交付的本地 `gaussdb-python` fork（本地交付 dist 里已有构建好的 whl，Git 仓库不包含该文件），与 PyPI 版 15 文件差异，全部是 GaussDB 兼容修复。
- 测试镜像 `tortoise-gaussdb-test:cp312-arm64` 基于 psycopg2-gaussdb:cp312-arm64（含 507 配套原厂 libpq at /opt/gaussdb_libpq）+ fork whl。
- 容器内连接宿主机数据库用 `host.docker.internal`（--add-host=host.docker.internal:host-gateway）。

## 7. 环境与账号

- 测试账号 `tortoise_lab`（两实例同密码，存 .env，600 权限）
- C507-O：库 tortoise_central（A 模式，public schema owner 已转给 tortoise_lab）
- D507-O：库 distributed_acceptance 的 schema tortoise_test（tortoise_lab 所有）+ node group 权限
- gsql 密码登录：`gsql -W '<password>'`（PGPASSWORD 环境变量不被 gsql 识别）
