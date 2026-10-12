# 驱动交付边界

核对日期：2026-10-12。

- 当前验证使用既有 `docker/gaussdb-1.0.4-py3-none-any.whl`，SHA-256：`ef893d7e705ab29502aa79397fb70e028d3e06c5a59846a4369b52b4d4c1fddf`。
- 它是本地 fork 构建的 gaussdb 1.0.4，不是 PyPI 同版本原包；历史来源记录见 `o_mode_contracts.md` 第 6 节。
- 本轮未修改底层驱动，也未将“同版本号”当作相同内容。离线 wheelhouse 仅放入这一份 gaussdb wheel。
- 本轮核实的是包内容校验值及隔离安装结果；从历史源码提交重新构建同一 wheel 的可复现性未验收，不能据此宣称已完成官方驱动发行。
- libpq 来自已有测试镜像内 `/opt/gaussdb_libpq`，不放进适配包，不宣称纯 Python wheel 自带数据库客户端。
- ORM 适配层沿用 Apache-2.0；GaussDB 驱动及客户端仍遵守各自许可，不能被适配层许可证替代。
