# 驱动来源与交付边界

核对日期：2026-10-13。

当前使用修复版 gaussdb 1.0.4 与 gaussdb-pool 1.0.4。公开源码：[jarrenL/gaussdb-python 固定提交](https://github.com/jarrenL/gaussdb-python/commit/6d857f8ad4e1c7276395e7f0471295baab01c52f)。项目根目录 `requirements-driver.txt` 固定两个子目录到该提交，可以独立获取和构建，不再依赖私下传递历史 wheel。

```bash
python -m pip install -r requirements-driver.txt
python -m pip install .
# 或仅构建到自有 wheelhouse
python -m pip wheel --no-deps -r requirements-driver.txt -w wheelhouse
```

源码安装需要 Git、网络及 Python 构建工具。本项目未发布到 PyPI；PyPI 的 gaussdb 同名同版本原包不能代替这个修复提交。pip 中版本相同不代表内容相同，已有错误版本时先卸载再按固定源码安装。

本轮从该不可变提交导出 gaussdb、gaussdb_pool 子目录，重新构建并用于 x86 测试/隔离安装。原配套 driver wheel 与该提交的 **80 个 Python 源文件内容一致**。另已按 `requirements-driver.txt` 从 GitHub 在线拉取两个子目录并成功构建，验证公开安装入口。构建系统 Git 需已安装；运行时 libpq 的 LD_LIBRARY_PATH 若覆盖系统 libstdc++，安装系统工具时应临时取消该变量。

这验证源码对应关系，不承诺 wheel 压缩文件逐字节可复现（构建时间与工具版本会影响归档）。

| 本轮重新构建产物 | SHA-256 |
| --- | --- |
| gaussdb-1.0.4-py3-none-any.whl | `9687625038155820d6c0fad53c84df39863c1a8a12411a6686b3acd1bdc458f4` |
| gaussdb_pool-1.0.4-py3-none-any.whl | `55e664a01dc96567612ebeb7b6d0d59b4629918f6c487fdf6d6f42df47152dfa` |

历史 `docker/gaussdb-1.0.4-py3-none-any.whl` SHA-256 为 `ef893d7e705ab29502aa79397fb70e028d3e06c5a59846a4369b52b4d4c1fddf`，它与新归档哈希不同，不应混淆。

libpq 需由使用者从有授权的 GaussDB 客户端渠道取得，匹配操作系统、CPU 架构与服务端。测试客户端镜像使用 `/opt/gaussdb_libpq`；本项目不上传、捆绑或提供下载该厂商二进制。ORM 适配层的 Apache-2.0 许可证不改变驱动、池与 libpq 各自的许可。公开源码构建通过不代表华为云官方认证或发行。
