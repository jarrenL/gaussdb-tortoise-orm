# 0.3.0 扩展能力与复现

目标保持 **GaussDB Kernel 507 O 模式，集中式 A / 分布式 ORA**。Django 的管理后台、表单、Session 等属于 Web 框架功能，不是 Tortoise 数据库后端的缺口；本轮补充其数据库后端对应的字段、表达式、事务、内省、迁移、连接和交付能力。

## 新增使用入口

### JSON、Duration、数组

```python
from tortoise_gaussdb.fields import JSONField, DurationField
from tortoise.contrib.postgres.fields import ArrayField
from tortoise_gaussdb.functions import JSONExtract, JSONObject, JSONF
from tortoise.expressions import F

# 模型字段：payload = JSONField(null=True)
# duration = DurationField(null=True)  # bigint 微秒，Python timedelta
# numbers = ArrayField(null=True)
await Event.filter(payload__filter={"user__age__gte": 18})
await Event.annotate(age=JSONExtract("payload", "user", "age")).values("age")
await Event.annotate(age=JSONF("payload__user__age")).values("age")
await Event.annotate(item=JSONObject(id=F("id"), active=True)).values("item")
```

这些表达式绑定 JSON 路径参数，包含引号和中文的键名不会拼入 SQL。`JSONExtract(..., text=False)` 保留 JSON 类型。`JSONF` 与上游 `F` 相同接口，但修正 JSON 路径渲染；普通字段仍可使用上游 `F`。上游 `F("payload__key")` 的 JSON 路径渲染没有全局修改，`support_json_attributes` 因而保留关闭。含 `__` 的实际键名使用 `JSONExtract` 的独立路径参数。

请使用本包 `JSONField`：它将已序列化 JSON 和 Python 对象规范化为未转义的 Unicode 文本，兼容分布式 SQL_ASCII 库对 JSONB Unicode 转义的限制。不会把字符串 JSON 的 SQL NULL 与 JSON null 混为同一个输入。数组为 PostgreSQL 原生数组映射，已测整数数组，不声称所有元素类型均验收。Duration 使用微秒整数，`F("duration") + 2` 表示加 2 微秒；并非数据库 interval 类型。

### 日期与窗口

```python
from tortoise_gaussdb.functions import Extract, DateTrunc, Window

rows = await Event.annotate(
    hour=Extract("created_at", "hour", "Asia/Shanghai"),
    day=DateTrunc("created_at", "day", "Asia/Shanghai"),
    sequence=Window("row_number", partition_by=("category",), order_by=("id",)),
    running=Window("sum", "amount", order_by=("id",), rows=(None, 0)),
).values("hour", "day", "sequence", "running")
```

支持 row_number、rank、dense_rank、sum、avg、min、max、count、lag、lead。必须显式排序；以 `-field` 表示降序。聚合窗口支持 ROWS 边界，负数/正数分别为 PRECEDING/FOLLOWING，0 为 CURRENT ROW，None 为对应方向的 UNBOUNDED。未提供 RANGE、FILTER、自定义 offset/default、命名窗口接口。

### 服务端游标与内省

```python
async with db.stream_query("SELECT id FROM events WHERE id > %s", [0], batch_size=1000) as rows:
    async for row in rows:
        consume(row)

catalog = await db.inspect_schema("business")
```

流式接口每次 fetchmany，使用服务端命名游标；调用方必须使用 `async with`，即使提前退出、取消或失败也释放游标和连接。独立调用开启事务，已有事务内使用保存点，事务完成前占用一条连接。返回字典行，保留底层驱动异常；不是自动转换 ORM Model 的 QuerySet.iterator。内省返回 relations、columns、constraints、indexes、distribution，包含表/视图、列类型/默认值/注释、约束/索引定义及分布键；不自动反向生成模型。

### 隔离级别、锁与恢复

连接 credentials 可填 `isolation_level="READ COMMITTED"`（默认）或 `"REPEATABLE READ"`，在每条新池连接设置。507 实测将 SERIALIZABLE 降为 REPEATABLE READ，因此本包明确拒绝 SERIALIZABLE；不提供虚假的可串行化保证。

已测 FOR UPDATE、OF、NOWAIT、SKIP LOCKED、基本 LIMIT 组合；NOWAIT 与 SKIP LOCKED 同时设置会报错。连接池借出前检查连接，服务端关闭的空闲连接会被替换。libpq 多地址连接可在初始连接失败时尝试后续地址；这不等于 CN/DN 故障切换认证，不会重放正在执行的写事务。

### 迁移与 EXPLAIN

补充长度、默认值、非空、注释、唯一约束，以及“同一次改列名和类型”的迁移前进/回退验证。同时补充跨应用依赖的应用级 `__first__`/`__latest__` 计划修正、RunSQL/RunPython 数据迁移和预建历史表后的并发执行。首次创建迁移历史表仍应串行部署。集中式物理外键 CASCADE / RESTRICT / SET NULL 验证通过；分布式仍明确拒绝物理外键，应使用逻辑关系。

`await QuerySet.explain()` 默认 TEXT，可指定 analyze/verbose/costs/buffers/timing。集中式 507 的 FORMAT JSON 输出实测存在格式问题，因此显式请求非 TEXT 会报不支持。`analyze=True` 实际执行查询，请按业务自行选择。

## TLS 专项

测试需要专用、要求 TLS 的 507 集中式实例和匹配证书，服务器证书 SAN 包含连接主机名。连接使用 `server_settings={"sslmode": "verify-full", "sslrootcert": "/path/ca.crt"}`；GaussDB 客户端/服务器均可能要求证书文件 mode 0600。

设置 TLS_TEST_HOST、TLS_TEST_PORT、TLS_TEST_DATABASE、TLS_TEST_USER、TLS_TEST_PASSWORD_FILE（密码文件路径）、TLS_TEST_CA_FILE 后执行：

```bash
python -m pytest tests/transport --live -q
```

测试覆盖正确 CA/主机名、错误主机名、缺失 CA、有效但不受信任 CA、错误口令/用户/数据库/端口、拒绝明文连接、空闲连接终止后恢复、多地址初始连接回退。错误 CA 用例使用本地 openssl 生成独立自签证书。未配置 TLS 环境会明确跳过，不计为通过。

## 有界并发测试

```bash
python scripts/soak.py --seconds 1800
```

使用与 `.env.example` 相同的进程环境变量，不自动读取 .env。分别在两套库的随机 schema 执行：1/10/50 并发 × 100/1000 条批量，每组预热后测 3 次；然后 10 并发、每次 10 行的混合增查改删、提交/主动回滚持续至少 30 分钟。池上限 10、等待超时 120 秒，循环间隔 0.2 秒。输出计数和耗时，最终确认无残留行并删除自身 schema。这是本地有界稳定性验证，不是生产容量或故障注入基准。

## 仍需单独验收

- 多 CN、DN 停机/恢复、提交响应丢失、实际主备切换；当前 TLS 与连接恢复证据不能替代它们。
- Python 3.10/3.11、Windows/macOS 原生客户端、物理 x86 服务器；当前 x86 为 Linux amd64 容器仿真。
- 全量上游测试移植、完整 88 组子场景及所有组合；见覆盖清单，不以 pytest 数量替代场景覆盖率。
- 分布式物理外键、SERIALIZABLE、FOR NO KEY UPDATE、LIMIT/ORDER BY UPDATE/DELETE 等引擎或后端边界不能通过增加测试自动变为支持。
