# 开发指南

[首页](../README.md) · [文档中心](README.md) · [部署](DEPLOYMENT.md)

开发环境和真实游戏环境分开。不要从公开例子猜生产凭据，不要用游戏 root 账号运行网页或测试。

## 依赖与构建

Python 3.12（含 pip／venv），Node.js 24.15+ 的 24.x，pnpm **12.10.1**：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
pnpm --dir web install --frozen-lockfile
pnpm --dir web typecheck
pnpm --dir web build
```

前端 `web/dist/` 由后端 `static_dir` 配置提供，浏览器基路径 `/dnf-gm/`，API `/dnf-gm/api/v1`。

## 独立配置与启动

在 Git 目录外准备权限0600的配置。`deploy/config.example.json` 是占位模板，不能直接登录真实数据库。数据库、管理库、管理员和测试数据须通过隔离环境另行准备。

```bash
DNFGM_CONFIG=/absolute/private/lab-config.json PYTHONPATH=src \
  .venv/bin/python -m uvicorn dnfgm.app:create_app --factory \
  --host 127.0.0.1 --port 8765
```

Vite+ 开发服务只绑定回环：`pnpm --dir web dev`，已有 `/dnf-gm/api` 代理配置；必须在私有实验配置中加入精确开发 Origin，不允许任意跨域。浏览器访问实际输出的 `/dnf-gm/` 地址。

前端完整迁入固定版本 SoybeanAdmin 的 pnpm workspace、Naive UI、路由、布局、主题和 UnoCSS 构建体系。保留 `pnpm-lock.yaml`，不要再生成 npm 锁文件，也不要在发布时更新 catalog 中的依赖。`pnpm build` 只执行 Vite+ 构建，类型检查须单独执行。请求适配仍使用同源 Cookie 与 CSRF，不使用模板演示 token 刷新后重放原请求的行为。

## 测试策略

按改动选相关文件，不要求每次全量回归。后端数据库测试必须使用独立 socket-only MySQL **5.7.44**，准备方法见 [TESTING.md](TESTING.md)；不要将测试连接指向生产库。

```bash
pnpm --dir web test -- src/components/CatalogFilters.test.ts
# 后端示例：仅在已启动的独立实验库环境执行
DNF_GM_M0_SOCKET=/absolute/lab/mysql.sock PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .venv/bin/python -m pytest -q tests/app/test_readiness.py
```

CI 全量测试是独立工作流；Release 类型检查与构建不代表重新完成全量测试或客户端验收。截图只用合成对象，见 [截图约定](images/README.md)。

管理库当前迁移到 **017**。版本化筛选、外观和布局偏好只写管理库，按当前 PVF 隔离，使用乐观版本；见 [界面偏好接口](UI-PREFERENCES.md)。添加筛选时同时维护 `CatalogFilters`、`catalog_filters.predicates`、搜索接口和离线索引补全，不能让批量策略预览忽略目录中已选的条件。

## 贡献重点

- 业务变更配定向测试，记录接口、权限、迁移和维护影响。
- 公开示例必须脱敏，禁止 PVF、NPK、私有索引及玩家记录。
- UI优化保留错误可见性、键盘焦点与操作防重；不为简化流程取消审计。
- 代码规范与问题报告见 [CONTRIBUTING.md](../CONTRIBUTING.md)；发布见 [RELEASING.md](RELEASING.md)。
