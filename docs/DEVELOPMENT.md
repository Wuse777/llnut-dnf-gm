# 开发指南

[首页](../README.md) · [文档中心](README.md) · [部署](DEPLOYMENT.md)

开发环境和真实游戏环境分开。不要从公开例子猜生产凭据，不要用游戏 root 账号运行网页或测试。

## 依赖与构建

Python 3.12（含 pip／venv），Node.js 24.15+ 的 24.x，npm：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
npm --prefix web ci
npm --prefix web run build
```

前端 `web/dist/` 由后端 `static_dir` 配置提供，浏览器基路径 `/dnf-gm/`，API `/dnf-gm/api/v1`。

## 独立配置与启动

在 Git 目录外准备权限0600的配置。`deploy/config.example.json` 是占位模板，不能直接登录真实数据库。数据库、管理库、管理员和测试数据须通过隔离环境另行准备。

```bash
DNFGM_CONFIG=/absolute/private/lab-config.json PYTHONPATH=src \
  .venv/bin/python -m uvicorn dnfgm.app:create_app --factory \
  --host 127.0.0.1 --port 8765
```

Vite 开发服务只绑定回环：`npm --prefix web run dev`，已有 `/dnf-gm/api` 代理配置；必须在私有实验配置中加入精确开发 Origin，不允许任意跨域。浏览器访问 Vite 实际输出的 `/dnf-gm/` 地址。

## 测试策略

按改动选相关文件，不要求每次全量回归。后端数据库测试必须使用独立 socket-only MySQL **5.7.44**，准备方法见 [TESTING.md](TESTING.md)；不要将测试连接指向生产库。

```bash
npm --prefix web test -- src/components/MailWorkbench.test.ts
# 后端示例：仅在已启动的独立实验库环境执行
DNF_GM_M0_SOCKET=/absolute/lab/mysql.sock PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .venv/bin/python -m pytest -q tests/app/test_readiness.py
```

CI 全量测试是独立工作流；Release 类型检查与构建不代表重新完成全量测试或客户端验收。截图只用合成对象，见 [截图约定](images/README.md)。

## 贡献重点

- 业务变更配定向测试，记录接口、权限、迁移和维护影响。
- 公开示例必须脱敏，禁止 PVF、NPK、私有索引及玩家记录。
- UI优化保留错误可见性、键盘焦点与操作防重；不为简化流程取消审计。
- 代码规范与问题报告见 [CONTRIBUTING.md](../CONTRIBUTING.md)；发布见 [RELEASING.md](RELEASING.md)。
