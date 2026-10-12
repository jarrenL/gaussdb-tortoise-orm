# 测试说明

## 当前源码回归

2026-10-12 上传前，对当前源码执行完整测试集合：**77 passed in 8.81s**，无失败、跳过或未选择项。

- 服务端：已有本地 GaussDB Kernel 507.0.0 实验实例；集中式 O 模式（目录值 A）与分布式 O 模式（目录值 ORA，2 DN）。
- 客户端：Linux aarch64 / Python 3.12，配套修复版 gaussdb 1.0.4、gaussdb-pool 1.0.4、Tortoise ORM 1.1.8 及匹配的 libpq。
- 测试入口：`python -m pytest tests --live -q --tb=short`。
- 测试内容包括现有单元测试、两种部署上的集成测试、FastAPI、逻辑关系迁移、模型刷新以及定向 upsert 用例。

第一次执行因旧测试镜像缺少 `httpx` 导致两项 FastAPI 用例失败，其余 75 项通过。为临时测试容器安装 `httpx`、`asgi-lifespan`、`fastapi`、`uvicorn` 后重新执行完整集合，得到上述 77 项通过结果；没有通过跳过测试消除失败。

## 复现条件

先取得并校验配套驱动与 libpq，参考 [README](../README.md) 和[驱动说明](DRIVER_PROVENANCE.md)。测试镜像依赖已有的 GaussDB 客户端基础镜像；厂商客户端、驱动 wheel 和本地构建产物不随 Git 仓库上传。

1. 在项目根目录将 `.env.example` 复制为私有 `.env`，填写两套专用测试库的连接信息。
2. 准备 `tortoise-gaussdb-test:cp312-arm64` 镜像，确保 FastAPI 测试依赖齐全。
3. 执行：

```bash
docker run --rm --env-file .env -v "$PWD:/work" -e PYTHONPATH=/work/src \
  tortoise-gaussdb-test:cp312-arm64 python -m pytest tests --live -q --tb=short
```

测试创建并清理自己的随机 schema。不要使用生产数据库；异常退出后的残留对象应在核对创建来源后处理。原始日志、私有连接信息和本地诊断脚本不随仓库上传。

## 验收边界

77 项参数化测试不等于原定 88 组场景全量完成，也不是所有上游 Tortoise API 的兼容认证。TLS 正反例、多 CN、故障切换、持续负载、完整类型/查询组合和其他 Python/操作系统/CPU 平台仍需专项。

现有 `dist/` 0.2.0 快照对应较早的阶段三构建，未因本次源码上传自动重建或发布。当前源码能力与快照区别见 README；历史材料见[阶段三报告](PHASE3_REPORT_20261012.md)及[覆盖清单](COVERAGE_88.md)。
