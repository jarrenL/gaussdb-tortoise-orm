# 88 组计划覆盖跟踪（2026-10-13）

状态累计至 0.3.0。以下是计划组而非 pytest 参数化条数，不将历史 12 项探针重复算入。PARTIAL 表示已有相关自动化或安装验证，但没有满足该组全部子场景/平台矩阵；NOT_RUN 表示本轮未落地。没有一项据此宣称全平台验收完成。

| 用例组 | 优先级 | 计划内容 | 本轮状态 | 证据/剩余内容 |
| --- | --- | --- | --- | --- |
| ENV-01 | P0 | 干净环境安装 wheel；源码安装；仅按交付清单离线安装 | PARTIAL | 0.3.0 wheel 双部署隔离安装；固定公开提交在线构建驱动通过；完整离线/OS 矩阵待验收 |
| ENV-02 | P0 | 两种部署分别执行版本/模式预检 | PARTIAL | unit/test_client.py 模式/版本负例；实库连接预检 |
| ENV-03 | P0 | 字典配置连接；多个连接别名指向独立测试 schema | PARTIAL | test_multi_alias_independent_rollback：字典配置与第二 alias 独立事务 |
| ENV-04 | P0 | 密码含 `% @ : / #`；schema 含大写/保留字 | NOT_RUN | 待实现或待实库验证 |
| ENV-05 | P0 | 错误口令、用户、数据库、端口；无权限 | PARTIAL | TLS 专项：错误口令/用户/数据库/端口；权限变更待测 |
| ENV-06 | P0 | SSL 证书校验成功；错误 CA/主机名失败 | PARTIAL | verify-full 正例，错误主机名/缺失 CA/有效错误 CA；集中式已测，分布式 TLS 待验收 |
| ENV-07 | P0 | 驱动/libpq 缺失或不匹配 | NOT_RUN | 待实现或待实库验证 |
| ENV-08 | P1 | URL 配置与编码、连接额外参数 | NOT_RUN | 待实现或待实库验证 |
| DDL-01 | P0 | 从空 schema 建表，再执行安全建表；清理后重建 | PARTIAL | test_DDL_01_standard_safe_repeated |
| DDL-02 | P0 | Int/BigInt 自动主键；显式主键；UUID 应用生成主键 | PARTIAL | 插入主键回填；UUID/BigInt 尚未测 |
| DDL-03 | P0 | nullable/default/unique/unique_together/索引 | PARTIAL | 迁移默认/非空/唯一约束与索引；完整组合待验收 |
| DDL-04 | P0 | 自定义表名/列名/schema；关键字、混合大小写、长名称 | PARTIAL | test_DDL_04_quoted_schema；source_field SQL 测试 |
| DDL-05 | P0 | 注释、默认表达式中含单引号/百分号/中文 | PARTIAL | 迁移中文、引号、百分号注释与默认值；默认表达式未穷尽 |
| DDL-06 | P0 | 检查 ORM 生成 DDL 与实库目录；依赖顺序删除 | PARTIAL | inspect_schema 对照表/视图、列、约束、索引与分布；依赖删除完整矩阵待测 |
| DDL-07 | P1 | identity/sequence/RETURNING 候选策略对照 | NOT_RUN | 待实现或待实库验证 |
| DDL-08 | P1 | 分区表、已有表、自定义索引 | NOT_RUN | 待实现或待实库验证 |
| TYPE-01 | P0 | SmallInt/Int/BigInt 的 0、负数、最小最大值及越界 | PARTIAL | SmallInt/BigInt 最小最大值、越界异常及恢复；Int 全边界待测 |
| TYPE-02 | P0 | Decimal 的小数、负数、最大精度/scale、舍入边界 | PARTIAL | test_TYPE_02_decimal：三个精度边界 |
| TYPE-03 | P0 | Float 的正常有限值；极大极小值 | PARTIAL | 负有限 Float；极大/极小值待测 |
| TYPE-04 | P0 | Boolean True/False/None，过滤及聚合相关场景 | PARTIAL | True/False/None 往返；完整聚合组合待测 |
| TYPE-05 | P0 | Char/Text：中文、emoji、单引号、反斜杠、长度边界 | PARTIAL | 中文/emoji/引号/反斜杠、LIKE 转义；长度边界待测 |
| TYPE-06 | P0 | `''`、NULL、空格；nullable 与非空字段；唯一字段 | PARTIAL | test_TYPE_06_empty_string：可空字段；非空历史探针尚未迁入 |
| TYPE-07 | P0 | Date/Datetime/Time；微秒、闰日、UTC/Asia-Shanghai、auto_now | PARTIAL | date/time/datetime 微秒、闰日、UTC/+08:00、提取/截断；auto_now 完整组合待测 |
| TYPE-08 | P0 | Binary 的空 bytes、NUL、0xFF、1 MiB 内容 | PARTIAL | NUL/FF 往返及 test_TYPE_08_binary_megabyte |
| TYPE-09 | P0 | UUID、整数/字符串枚举、自定义字段转换 | PARTIAL | UUID 往返；枚举/自定义字段完整矩阵待测 |
| TYPE-10 | P0 | 所有基础类型的 NULL、默认值、省略字段 | NOT_RUN | 待实现或待实库验证 |
| TYPE-11 | P1 | JSON 对象/数组/标量/JSON null/SQL NULL、路径查询 | PARTIAL | JSON 对象/数组/标量/null/SQL NULL、包含/路径/中文引号键/投影/构造；使用本包字段与表达式 |
| TYPE-12 | P1 | Array、Duration、NaN/Infinity、CHAR 尾空格 | PARTIAL | 整数数组、Duration 正负及运算；其他元素/NaN/Infinity/CHAR 待测 |
| CRUD-01 | P0 | create/save/get/refresh_from_db；显式 PK 与自动 PK | PARTIAL | GaussDBModel 刷新列映射/关系缓存及 CRUD；所有组合未穷尽 |
| CRUD-02 | P0 | get 查无/多行；first/last；exists/count | PARTIAL | test_CRUD_queries_relations：get 负例/count/exists |
| CRUD-03 | P0 | 单对象更新；QuerySet.update；update_fields；F 表达式 | PARTIAL | F 表达式及 QuerySet.update；完整 update_fields 尚未测 |
| CRUD-04 | P0 | 单行/多行删除；无匹配删除 | PARTIAL | 集中式 FK 三种删除行为；分布式物理 FK 明确拒绝 |
| CRUD-05 | P0 | get_or_create/update_or_create；多协程同一唯一键 | PARTIAL | 8 协程同键 get_or_create 仅一个 created；update_or_create |
| QUERY-01 | P0 | exact/in/空 in/range/isnull/比较；Q 的 AND/OR/NOT | PARTIAL | Q OR/空 in；完整 lookup 矩阵尚未测 |
| QUERY-02 | P0 | contains/startswith/endswith/大小写忽略；输入含 `%`、`_` | PARTIAL | contains/iexact/startswith 与 %/_/反斜杠；locale/collation 未穷尽 |
| QUERY-03 | P0 | 排序、limit/offset、切片、空页 | PARTIAL | test_queries 排序、分页、空页，双部署 |
| QUERY-04 | P0 | values/values_list/only、别名、distinct | PARTIAL | values/values_list/distinct；only 完整组合待测 |
| QUERY-05 | P0 | Count/Sum/Avg/Min/Max、group by、having | PARTIAL | Count/Sum/Avg/Min/Max、having；完整表达式组合待测 |
| QUERY-06 | P0 | 原生参数化 SQL、执行器字典结果、查询 SQL 预览 | PARTIAL | 参数化原生 SQL 及字典结果；SQL 预览 |
| QUERY-07 | P1 | 子查询、Case/When、函数表达式、窗口、正则 | PARTIAL | 正则、子查询、Case/When、Upper/Lower/Length、日期、10 类窗口及 ROWS |
| BULK-01 | P0 | bulk_create：0/1/N 条、多批次、显式/自动 PK | PARTIAL | 7 条分批 create；空/超大批次尚未测 |
| BULK-02 | P0 | bulk_update：多字段、不同值、空集合、边界批大小 | PARTIAL | 8 条分批 update；完整错误矩阵尚未测 |
| BULK-03 | P0 | 批量中间行唯一/类型错误；分别在显式事务内外执行 | PARTIAL | 第二批唯一冲突时显式事务整体回滚；无事务错误矩阵待测 |
| BULK-04 | P1 | ignore_conflicts/update_conflicts 等上游提供选项 | PARTIAL | ignore_conflicts 与 MERGE 指定冲突键、唯一索引校验/负例；并发同键 MERGE 待测 |
| REL-01 | P0 | 一对多、反向关系、可空关联、按关联字段过滤 | PARTIAL | 逻辑一对多/反向关系；可空外键尚未测 |
| REL-02 | P0 | 一对一；重复关联写入 | PARTIAL | 一对一新增迁移、重复拒绝及缓存刷新；完整组合待测 |
| REL-03 | P0 | M2M add/remove/clear、重复 add、自定义中间表 | PARTIAL | test_REL_03_m2m：增/重复增/删/清空/预取 |
| REL-04 | P0 | select_related/prefetch_related、多级关联 | PARTIAL | select_related/prefetch_related；多层及查询数尚未测 |
| REL-05 | P0 | 物理 FK 支持探测；显式关闭 db_constraint 的逻辑关系 | PARTIAL | 集中式 FK/非法引用，分布式三种删除行为均拒绝建物理 FK |
| REL-06 | P1 | CASCADE/RESTRICT/SET NULL；孤儿记录；跨分布键关联 | PARTIAL | 集中式 CASCADE/RESTRICT/SET NULL；分布式逻辑关系由应用维护 |
| TX-01 | P0 | in_transaction/atomic 成功提交、异常回滚 | PARTIAL | test_TX_01_02_04；跨 DN 提交/回滚 |
| TX-02 | P0 | 嵌套事务成功/失败；内层回滚后外层继续 | PARTIAL | test_TX_01_02_04：内层保存点回滚、外层提交 |
| TX-03 | P0 | 同时运行多个独立事务，期间查询连接身份 | PARTIAL | 并发独立事务一提交一回滚、读隔离；连接身份完整矩阵待测 |
| TX-04 | P0 | 唯一冲突/SQL 错误后回滚并复用连接 | PARTIAL | 唯一冲突后的事务回滚与连接复用 |
| TX-05 | P0 | 事务中取消协程、查询超时、池等待超时 | PARTIAL | 事务取消回滚、游标取消/早退、池等待超时及复用 |
| TX-06 | P1 | select_for_update；nowait/skip_locked；死锁/锁超时 | PARTIAL | FOR UPDATE/OF/LIMIT、真实锁竞争 NOWAIT/SKIP LOCKED；死锁/锁超时待测 |
| TX-07 | P1 | 默认隔离级别；可配置级别下重复读/并发更新 | PARTIAL | READ COMMITTED/REPEATABLE READ、重复读证据；拒绝降级 SERIALIZABLE |
| DIST-01 | P0 | 指定/缺省分布策略建表、重建、迁移 | PARTIAL | test_DIST_01_explicit_layout；migration SQL 分布策略 |
| DIST-02 | P0 | 主键/唯一键包含分布键与不包含分布键两组 | PARTIAL | unit 分布列/唯一键校验；独立全套 DB 约束组合尚未测 |
| DIST-03 | P0 | 同 DN 与跨 DN 的关联、聚合、排序分页 | PARTIAL | test_DIST_03_04_cross_dn：EXPLAIN All datanodes；跨节点分页尚未测 |
| DIST-04 | P0 | 一事务写入多个分片后提交/回滚 | PARTIAL | 100 行跨分片提交/回滚；其他故障路径尚未测 |
| DIST-05 | P0 | 跨 CN/并发会话插入自动主键及业务唯一键 | NOT_RUN | 待实现或待实库验证 |
| DIST-06 | P0 | 分布式 M2M 中间表、逻辑关系、物理 FK 探测 | PARTIAL | 显式 M2M HASH、逻辑关系、物理 FK 双部署对照 |
| DIST-07 | P1 | 更新分布键、跨节点批量更新/删除 | NOT_RUN | 待实现或待实库验证 |
| DIST-08 | P1 | CN 断连/切换；池中旧连接失效 | PARTIAL | 集中式专用实例坏连接替换、多地址回退；真正 CN 切换未验收 |
| DIST-09 | P1 | DN 故障/恢复时读写、提交响应丢失 | NOT_RUN | 待实现或待实库验证 |
| DIST-10 | P1 | 节点间 DDL 可见性；第二 CN 立即执行迁移后查询 | NOT_RUN | 待实现或待实库验证 |
| MIG-01 | P0 | 原生迁移 init/makemigrations/sqlmigrate/migrate 流程 | PARTIAL | 原生 init/makemigrations + adapter 离线预览/执行/重复执行 |
| MIG-02 | P0 | 新增字段/索引/唯一约束、改名、可支持的类型变更 | PARTIAL | 长度/默认/非空/注释/唯一/索引、同次改名与改类型前进回退；任意类型转换未验收 |
| MIG-03 | P0 | 支持可逆操作的前进/回退；再次执行已完成迁移 | PARTIAL | 前进/回退/重跑；不可逆数据迁移尚未测 |
| MIG-04 | P0 | 中途 DDL 失败、缺权限、约束冲突 | PARTIAL | 失败 DDL 与历史回滚；权限失败专项尚未测 |
| MIG-05 | P0 | 两种部署的关系表/序列/schema/分布属性 | PARTIAL | 分布 HASH/REPLICATION 及 schema；逻辑 FK/M2M 增量迁移双形态本地通过；完整组合尚未验收 |
| MIG-06 | P1 | RunSQL/RunPython、多 app、多数据库 alias、并发迁移 | PARTIAL | 多 app 依赖 RunSQL/RunPython、应用级前进回退、预建历史表后两个并发执行器；首次并发初始化/多库迁移待验收 |
| ERR-01 | P0 | 主键/唯一/非空/检查约束、非法输入、SQL 语法错误 | PARTIAL | 非法函数、非法类型、越界、非空/唯一冲突；完整检查约束矩阵待测 |
| ERR-02 | P0 | 注入字符串、恶意标识符、日志中的敏感参数 | PARTIAL | 参数化注入字符串/标识符；完整日志扫描尚未测 |
| ERR-03 | P0 | SQL 失败后查询；连接失败后重新初始化 | PARTIAL | 事务错误、取消后恢复；预检失败关闭池 |
| ERR-04 | P1 | 只读账号/迁移账号分离；账号权限变更 | NOT_RUN | 待实现或待实库验证 |
| ASYNC-01 | P0 | 慢查询与心跳协程并行运行 | PARTIAL | 慢查询+20次心跳协程 |
| ASYNC-02 | P0 | 并发超过池上限、等待超时、取消等待者 | PARTIAL | 3连接池/20并发写入/池耗尽超时恢复 |
| ASYNC-03 | P0 | 重复初始化/关闭；异常退出；多事件循环测试夹具 | PARTIAL | 重复 fixture 初始化/关闭、流式早退/取消；多事件循环完整矩阵待测 |
| ASYNC-04 | P1 | 空闲连接被服务端关闭；prepare/pipeline 开关对照 | PARTIAL | 服务端终止空闲连接后替换并查询；prepare/pipeline 对照待测 |
| E2E-01 | P0 | 干净环境运行异步示例：建表、增查改删、事务、关系 | PARTIAL | 隔离安装+库操作 smoke；async_crud 示例 |
| E2E-02 | P0 | FastAPI 启停与并发 API 请求 | PARTIAL | FastAPI 生命周期+10并发创建/读取/404/422 |
| E2E-03 | P0 | 两部署运行相同 API/模型；重新部署后使用迁移 | PARTIAL | 相同模型分别运行两种部署；完整升级重部署尚未测 |
| PERF-01 | P1 | 1/10/50 并发，100/1000 条批量，预热后重复 3 次 | PARTIAL | scripts/soak.py：1/10/50 并发 × 100/1000 条、预热与三次测量，见 validation.md |
| PERF-02 | P1 | 至少 30 分钟混合读写及故障后继续运行 | PARTIAL | 双部署至少 30 分钟混合提交/回滚；故障注入后的持续负载未验收 |
| UP-01 | P0 | 移植相关上游后端测试，与本项目差异用例共同执行 | NOT_RUN | 待实现或待实库验证 |
| UP-02 | P1 | 适配包与其他 Tortoise 后端共存、版本升级前后对照 | PARTIAL | SQLite 后端同进程共存及上游 JSON filter 未被全局修改；版本升级对照未验收 |
