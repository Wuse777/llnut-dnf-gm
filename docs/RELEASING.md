# GitHub Release 发布流程

[文档中心](README.md) · [部署指南](DEPLOYMENT.md)

发布操作生成源码与预构建网页，不安装服务、不迁移数据库、不访问私人服务器。服务器部署是独立维护任务。

## 发布前

1. 统一 `pyproject.toml`、`src/dnfgm/__init__.py`、`web/package.json` 版本；就绪接口从同一Python版本常量返回。前端固定 pnpm 12.10.1 与 `pnpm-lock.yaml`；pnpm锁文件不包含应用根版本，依赖一致性由冻结安装核验。
2. 准备 `docs/releases/vX.Y.Z.md`、CHANGELOG及受影响手册，标明新功能、迁移、已知缺口和本轮真实验证范围。
3. 执行 `python3 tools/check_documentation.py`、类型检查、生产构建及与变更相关的关键场景检查；全量 Linux 后端（隔离 MySQL）与前端 CI 独立运行，按实际结果报告。本次按部署者要求不将长时间全量回归设为发布前置，不能将构建成功表述为全量 CI 通过。
4. 核对Git变更及截图不含凭据、生产地址、玩家数据、PVF／NPK／索引。只标记已经审查的固定提交，不覆盖旧标签。

## 常规发布

推送版本提交到main后，为该**精确提交**创建 `vX.Y.Z` 标签并推送。`.github/workflows/release.yml` 在标签推送时运行，也可在Actions页面手动选择一个已有标签触发。

发布工作流：

1. 检出标签，核对干净状态、版本和文档引用；不读取生产Secrets。
2. 使用Node24、Python3.12、pnpm12.10.1冻结安装，显式执行前端类型检查，再执行Vite+生产构建；不自动运行全量测试。
3. `git archive`生成源码包；另打包同版`web/dist/`和`SOURCE_REVISION`，生成`SHA256SUMS`。
4. 创建草稿Release，上传两个附件和校验清单，全部成功才公开并标为latest。没有写权限时停止，不索要生产凭据。

也可在干净的标签检出环境设置GitHub CLI的`GH_TOKEN`及`GITHUB_REPOSITORY`，执行：

```bash
bash tools/publish_github_release.sh v0.6.3
```

Token仅需要目标仓库Release写权限；不写入源码或配置。脚本拒绝修改已有Release，避免覆盖下载物。若上传中断留下草稿，先在GitHub检查已上传附件与哈希，由维护者完成或删除该草稿后再明确重试；不能盲目自动覆盖。

## 发布后

- 核实标签commit、Release非草稿、名称和说明、三个附件及大小／digest。
- 重新下载两个附件与SHA256SUMS并验证；检查源码路径、版本及静态网页`SOURCE_REVISION`。
- 若使用一次性源码同步工作流，清理临时工作流和公开传输包并核对404；不把传输包当Release附件。
- 对外说明是否部署服务器、是否完成全新安装／客户端验证，不能用发布成功替代这些结论。

## 包的边界

源码包通过Git标签归档，不带wheels／私有配置／游戏索引。网页包也不是完整安装包。平台匹配的离线安装目录仍由`tools/build_release.sh`在维护电脑生成，详见部署指南。
