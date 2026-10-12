# GaussDB Tortoise ORM 适配

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](pyproject.toml)
[![Tortoise ORM: 1.1.8](https://img.shields.io/badge/Tortoise_ORM-1.1.8-008080.svg)](pyproject.toml)

本项目为 **GaussDB Kernel 507 的 O（Oracle）兼容模式**提供 Tortoise ORM 异步数据库后端，通过配套 `gaussdb` 驱动、连接池和 GaussDB libpq 接入**集中式与分布式**数据库。适合需要在 Python 异步应用或 FastAPI 服务中使用 GaussDB 的开发者。

本项目是**独立适配项目**，Python 包名为 `tortoise-gaussdb`，当前声明版本为 `0.2.0`；源码托管于 GitHub，尚未发布到 PyPI，也未作为华为云或 Tortoise ORM 官方组件发布。适配范围仅限 507 O 模式，不包含其他兼容模式。示例用于集成验证，完整 88 组验收仍在进行。

## 目录

- [架构与能力](#架构与能力)
- [前置条件](#前置条件)
- [快速开始](#快速开始)
- [使用与验证](#使用与验证)
- [已验证范围](#已验证范围)
- [兼容边界](#兼容边界)
- [云服务与费用](#云服务与费用)
- [清理资源](#清理资源)
- [详细文档与依赖](#详细文档与依赖)
- [常见问题](#常见问题)
- [贡献与安全](#贡献与安全)
- [许可证](#许可证)
- [维护者与反馈](#维护者与反馈)

## 架构与能力

```text
Python / FastAPI / Tortoise Model、QuerySet、事务与迁移文件
                         ↓
      tortoise_gaussdb：客户端、执行器、建表与迁移适配
                         ↓
           gaussdb 异步驱动 + gaussdb-pool
                         ↓
                  GaussDB libpq
                         ↓
      GaussDB 507 O 模式：集中式 A / 分布式 ORA
```

通过 Tortoise 的后端模块配置 `engine="tortoise_gaussdb"` 接入，不全局修改上游包。连接预检读取数据库版本与实际兼容模式；本地集中式和分布式 O 模式实例分别返回 `A` 和 `ORA`。

已覆盖的场景包括异步连接和连接池、参数化查询、基础建表、CRUD 与自增主键回填、部分类型往返、逻辑关系、批量操作、事务与保存点、迁移前进和回退。分布式建表支持按表配置 HASH 或 REPLICATION，M2M 中间表也使用显式分布配置。具体测试范围和未完成项目见下文。

## 前置条件

1. Python **3.10+**；目前实测客户端为 **Linux aarch64 / Python 3.12**。依赖固定为 `tortoise-orm==1.1.8`、`gaussdb==1.0.4` 和 `gaussdb-pool==1.0.4`，以 [pyproject.toml](pyproject.toml) 为准。声明支持的 Python 版本不等于全部已验收。
2. **配套修复版 gaussdb 驱动**和与操作系统、CPU 架构及 GaussDB 507 匹配的 libpq。驱动 wheel 不随 Git 仓库上传；取得配套文件后放到 `docker/gaussdb-1.0.4-py3-none-any.whl`。它与 PyPI 同版本原包内容不同，不能直接替换。来源与校验值见[驱动说明](docs/DRIVER_PROVENANCE.md)。
3. 可访问的 GaussDB 507 O 模式数据库、账号和业务 schema。分布式连接 CN；建表和迁移需要相应 DDL 权限，只读连接验证不需要建表权限。
4. libpq 由使用者从有授权的 GaussDB 客户端渠道取得并安装，适配包和离线 wheelhouse 均不包含它。Linux 环境按实际位置配置 `GAUSSDB_LIBPQ_PATH` 与动态库搜索路径 `LD_LIBRARY_PATH`。

## 快速开始

以下命令从**本项目根目录**执行。包尚未发布到 PyPI，先单独取得并核对配套驱动 wheel，按上文路径放置，再安装当前源码：

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install ./docker/gaussdb-1.0.4-py3-none-any.whl
python -m pip install .
```

本地交付若附带 `dist/wheelhouse`，可用于离线安装其对应的交付快照；Git 仓库不包含 `dist/`：

```bash
python -m pip install --no-index --find-links dist/wheelhouse \
  --require-hashes -r dist/requirements-offline.txt
```

**源码与归档包边界：**当前 `dist/` 中的 0.2.0 包是阶段三构建产物；后续源码中的关系迁移、模型刷新和定向 upsert 补充不能视为已包含在该 wheel 中。使用这些补充时按上面的源码安装方式操作。离线包不包含可选 FastAPI 和测试工具，libpq 也需单独准备。

在进程环境中设置以下示例参数；凭据由私有环境配置注入，不要提交到代码仓库。示例不会自动读取项目 `.env` 文件，该文件用于 Docker 测试环境。

| 变量 | 用途 |
| --- | --- |
| `GAUSS_HOST`、`GAUSS_PORT` | 数据库地址与端口；分布式使用 CN 地址 |
| `GAUSS_DATABASE`、`GAUSS_USER`、`GAUSS_PASSWORD` | 数据库、用户名与密码 |
| `GAUSS_DEPLOYMENT` | 集中式填 `centralized`，分布式填 `distributed` |
| `GAUSS_SCHEMA` | 专用示例 schema，默认 `gaussdb_demo` |

[examples/config.py](examples/config.py) 提供完整字典配置。接入自己的应用时，配置后端、模型模块和迁移模块；连接参数示例如下：

```python
import os

schema = os.getenv("GAUSS_SCHEMA", "gaussdb_demo")
connection = {
    "engine": "tortoise_gaussdb",
    "credentials": {
        "host": os.environ["GAUSS_HOST"],
        "port": int(os.environ["GAUSS_PORT"]),
        "database": os.environ["GAUSS_DATABASE"],
        "user": os.environ["GAUSS_USER"],
        "password": os.environ["GAUSS_PASSWORD"],
        "deployment": os.environ["GAUSS_DEPLOYMENT"],
        "schema": schema,
        "distributions": {
            f"{schema}.orders": {"type": "HASH", "field": "id"},
        },
        "minsize": 1,
        "maxsize": 5,
    },
}
```

将 `connection` 放入 Tortoise 配置的 `connections`，并在模型 `Meta.schema` 中设置相同 schema。分布策略的键使用真实的 `schema.table`，`field` 使用数据库列名；M2M 中间表单独配置。集中式忽略共享配置中的分布布局。

## 使用与验证

### 只读连接验证

设置好上述环境变量后，在项目根目录执行：

```bash
python - <<'PY'
import asyncio
from tortoise import Tortoise
from examples.config import CONFIG

async def main():
    try:
        await Tortoise.init(config=CONFIG)
        db = Tortoise.get_connection("default")
        rows = await db.execute_query_dict("SELECT version() AS version")
        print(rows[0]["version"])
    finally:
        await Tortoise.close_connections()

asyncio.run(main())
PY
```

预期输出包含 GaussDB Kernel 507 版本；连接失败或版本、模式不匹配时抛出异常。该命令不创建业务表。

### CRUD 与 FastAPI 示例

[examples/models.py](examples/models.py) 定义订单模型，[异步示例](examples/async_crud.py) 完成建表、事务插入、读取和删除演示记录：

```bash
python -m examples.async_crud
# 预期输出订单 id、customer 和 amount；示例表和 schema 会保留。

python -m pip install '.[fastapi]'
uvicorn examples.fastapi_app:app
```

异步示例会调用 `Tortoise.generate_schemas(safe=True)`，应使用专用演示 schema。FastAPI 默认不建表，先执行下面的迁移；专用演示环境也可设置 `GAUSS_DEMO_CREATE_SCHEMA=1`。

### 建表与迁移

标准 `await Tortoise.generate_schemas(safe=True)` 已接入业务 schema 创建及分布策略，不需要手动 schema 预检。已有表的结构升级使用迁移。

使用 Tortoise 原生迁移文件和变更生成器，**执行迁移、计划及 SQL 预览使用适配包入口**：

```bash
tortoise -c examples.config.CONFIG init
tortoise -c examples.config.CONFIG makemigrations
python -m tortoise_gaussdb.migrations plan -c examples.config:CONFIG
python -m tortoise_gaussdb.migrations sqlmigrate -c examples.config:CONFIG --app models --name 0001
python -m tortoise_gaussdb.migrations migrate -c examples.config:CONFIG
```

`sqlmigrate` 的名称以生成的迁移为准。Tortoise 1.1.8 的原生 `tortoise migrate` 会选择 PostgreSQL editor/recorder，不是本后端支持的执行入口。

迁移历史保存在连接 schema，分布式历史表采用 REPLICATION。一次 `migrate` 的迁移 DDL 与历史更新在同一事务内完成；失败回滚本次待应用迁移，首次创建的空 schema 或历史表可能保留。已补充逻辑 FK、一对一和 M2M 新增字段迁移；`db_constraint=False` 不生成物理外键，M2M 复用建表分布策略。

### 运行回归

先安装配套驱动与 libpq，再安装测试依赖并执行不连接数据库的测试：

```bash
python -m pip install '.[test,fastapi]'
python -m pytest tests/unit
```

真实数据库测试需要**专用测试库**以及已准备好的本地测试镜像：

```bash
# 先复制 .env.example 为私有 .env，并设置两套测试库的实际连接信息。
docker run --rm --env-file .env -v "$PWD:/work" -e PYTHONPATH=/work/src \
  tortoise-gaussdb-test:cp312-arm64 python -m pytest tests --live -q
```

镜像需要配套驱动、libpq 以及 FastAPI 等测试依赖，不能只使用公共 Python 镜像运行。测试配置见 [.env.example](.env.example)：需要 `CENTRAL_PORT/DB/USER/PASSWORD` 与 `DIST_PORT/DB/USER`；`DIST_PASSWORD` 未设置时沿用集中式密码。主机默认 `host.docker.internal`，可用 `TEST_HOST` 覆盖。测试会在两种部署创建并清理自己的随机 schema。

## 已验证范围

2026-10-12 的本地回归使用 GaussDB Kernel **507.0.0**，客户端为 **Linux aarch64 / Python 3.12**。这里的结果来自已有本地实验环境，不代表公有云或所有客户端平台认证。

| 验证对象 | 已有证据 | 边界 |
| --- | --- | --- |
| 集中式 O 模式（目录值 A） | 连接、基础 CRUD/类型、逻辑关系、事务、迁移、FastAPI 回归 | 完整物理外键、级联及 HA 未验收 |
| 分布式 O 模式（目录值 ORA，2 DN） | 同一套基础回归，另含显式分布建表与跨 DN 提交/回滚 | 多 CN、节点切换及故障恢复未验收 |
| 阶段三构建包 | 67 项通过：27 项单元、20 项集中式、20 项分布式；两套隔离 venv 安装验证通过 | 对应现有 dist 快照 |
| 当前源码全量回归 | 上传前重新执行，**77 项通过，0 失败、0 跳过**；包含 FastAPI、关系/刷新与定向 upsert 补充 | 仅代表现有测试集合，完整并发与平台矩阵仍待验收 |

上述测试项与原计划的 **88 组场景**不是同一统计口径，不能按数量相加推断全部验收完成。当前验证结果及复现条件见[测试说明](docs/validation.md)，历史交付结果见[阶段三报告](docs/PHASE3_REPORT_20261012.md)。详细缺口见[覆盖清单](docs/COVERAGE_88.md)；历史报告和清单尚未全部同步后续专项结果。原始本地运行报告不随 Git 仓库上传。

## 兼容边界

- **O 模式语义：**已测字符字段的空字符串 `''` 按 `NULL` 返回，应用校验、过滤和非空约束需要考虑这一差异。日期 wire 适配已覆盖部分边界，不代表所有时区、特殊日期及类型组合均已验收。
- **分布布局：**分布式缺失策略默认报错，只有显式 `allow_default_distribution=True` 才允许数据库默认策略。当前 HASH 校验要求主键、唯一键包含分布列；REPLICATION 可用于适合复制的小表。不能将集中式模型的独立唯一键直接套用到任意 HASH 布局。
- **关系约束：**当前适配器拒绝分布式物理外键，逻辑关联需显式 `db_constraint=False`，由应用维护引用完整性及删除行为。集中式物理外键、级联和完整关系迁移组合仍需专项验收。
- **冲突处理：**`bulk_create(ignore_conflicts=True)` 使用 `ON DUPLICATE KEY UPDATE NOTHING`。当前源码已增加指定 `on_conflict` / `update_fields` 的 MERGE 路径，要求冲突列匹配实际存在的无条件唯一索引；不支持条件/CTE、MERGE RETURNING、更新冲突键等组合。完整并发与原子性矩阵尚未验收，跨多个批次或混合主键形式的整体原子性需显式 `in_transaction()`。
- **查询与迁移：**JSON 属性查询、`FOR NO KEY UPDATE`、带 LIMIT/ORDER BY 的 UPDATE/DELETE 仍关闭。迁移只支持原子执行，拒绝 fake 和非原子迁移；复杂类型变更、约束、多应用及并发迁移尚未完整验收。
- **模型刷新：**Tortoise 1.1.8 的 `refresh_from_db()` 在自定义 `source_field` 场景存在属性映射问题。当前源码提供可选基类 `from tortoise_gaussdb.models import GaussDBModel`，模型继承它可获得刷新映射及 FK/一对一缓存清理修复；直接继承上游 `Model` 不会自动获得修复。
- **标识符与 TLS：**模型数据库列名包含双引号/NUL 时明确拒绝。TLS 使用 libpq 的 `sslmode`、`sslrootcert` 等参数（放入连接 `server_settings`），不接受 Python `SSLContext`；证书校验正反例尚未验收，连通不等于服务器身份校验通过。
- **运行保障：**不自动重放故障写事务。HA/CN/DN 切换、持续压力、完整平台矩阵及干净操作系统上的客户端安装仍待验收；隔离 venv 安装通过不等于完成上述验证。

## 云服务与费用

本包安装、示例和测试命令不创建 GaussDB、EIP、ECS 或安全组。若自行使用云数据库，资源费用按所选服务与配置计算；关闭 Python 程序或卸载本包不会释放云资源。

## 清理资源

不再使用时，在应用对应的虚拟环境执行 `python -m pip uninstall tortoise-gaussdb`，并移除应用中添加的连接配置及环境变量。卸载不会删除数据库中的表、迁移历史或业务数据。

CRUD 示例会删除自身插入的演示记录，保留表和 schema。测试会尝试清理自己创建的随机 schema；异常退出后，需先核对测试日志、创建来源及对象内容再处理残留。迁移回退会保留连接 schema 和历史表，不通过 CASCADE 删除整个业务命名空间。

自行创建的云实例及网络资源由使用者按实际资源 ID 释放，并确认删除结果。

## 详细文档与依赖

- [测试说明](docs/validation.md)：上传前完整回归结果、复现条件与验收边界。
- [阶段三交付报告](docs/PHASE3_REPORT_20261012.md)：构建包、隔离安装及当时的 67 项回归记录；其中部分限制已被后续源码补充。
- [88 组覆盖清单](docs/COVERAGE_88.md)：验收计划与覆盖缺口，PARTIAL 不代表该组全部通过。
- [驱动来源与交付边界](docs/DRIVER_PROVENANCE.md)：配套驱动的哈希、来源及 libpq 边界。
- [O 模式早期探针记录](docs/o_mode_contracts.md)：历史协议与 SQL 行为；使用时留意文首的后续修正说明。
- [pyproject.toml](pyproject.toml)：Python 版本、固定运行依赖、测试与 FastAPI 可选依赖。
- [示例配置](examples/config.py)、[异步示例](examples/async_crud.py)、[FastAPI 示例](examples/fastapi_app.py)：集成入口。

Tortoise ORM、gaussdb 驱动、gaussdb-pool 和 GaussDB libpq 分别提供 ORM、驱动、连接池和客户端协议能力。本适配包提供 GaussDB 后端代码；单独提供的依赖仍受各自许可证和分发条件约束。

## 常见问题

**为什么同样安装 gaussdb 1.0.4 仍然失败？** 版本号相同不代表包内容相同。本项目验证使用修复版 wheel，先核对[驱动来源与哈希](docs/DRIVER_PROVENANCE.md)，再确认 libpq 和动态库搜索路径。

**O 模式为什么出现 A 和 ORA？** 这是本地两种部署在数据库目录中的实际标记。应用通过 `deployment=centralized/distributed` 声明部署形态，适配器读取实际数据库模式进行预检；不要关闭检查来绕过错误模式。

**为什么分布式建表失败？** 核对 schema、真实表名/列名、M2M 中间表分布配置、主键/唯一键与分布列的关系，以及账号 DDL 权限。

**为什么不能直接执行 tortoise migrate？** 当前固定的上游版本不会自动选中本包迁移 editor/recorder。使用 `python -m tortoise_gaussdb.migrations migrate`。

**为什么源码中的新能力在 wheel 安装后不可用？** 现有 dist 包早于后续源码补充，且声明版本尚未更新。按“快速开始”安装当前源码，不能仅凭 `0.2.0` 版本号判断是否包含补充。

## 贡献与安全

源码仓库为 [jarrenL/gaussdb-tortoise-orm](https://github.com/jarrenL/gaussdb-tortoise-orm)，问题与改进可通过 [Issues](https://github.com/jarrenL/gaussdb-tortoise-orm/issues) 反馈；私有仓库需要访问权限。提交改动时附上适用部署形态、复现步骤、依赖版本及对应测试；涉及 ORM 语义或分布式 SQL 的改动应分别验证集中式和分布式 O 模式。

反馈中不要包含密码、私钥、客户数据或完整私有连接信息。厂商客户端二进制与驱动的公开分发需遵循其许可；安全问题通过交付方提供的私有渠道反馈。

## 许可证

本适配包源码按 [Apache License 2.0](LICENSE) 授权，上游代码归属见 [NOTICE](NOTICE)。Tortoise ORM、gaussdb 驱动、连接池及 GaussDB libpq 各自遵循其许可证；本包许可证不改变这些依赖的授权与分发条件。

## 维护者与反馈

维护者：[jarrenL](https://github.com/jarrenL)。包元数据中的维护方为 **GaussDB Tortoise Adapter Project**。源码、反馈和发行信息以本项目 GitHub 仓库为准；配套驱动和 libpq 由交付方另行提供。
