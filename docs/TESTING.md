# 自动化测试与验收

## 隔离是硬要求

后端集成夹具会删除重建实验库。实验连接只支持本地 Unix socket，检查 `VERSION()` 为 5.7 且 `@@server_id=57044`；**这个标记不是生产保护的替代品，绝不能在正式实例设置它来跑测试**。夹具只使用合成账号和物品，不包含玩家密码。

在 Linux x86_64 维护电脑（需要 `dpkg-deb`、含 `ensurepip` 的 Python 3.12，无需 sudo）可构建固定版本实验室：

```bash
python3.12 tools/bootstrap_lab.py --runtime "$PWD/.runtime"
.runtime/venv/bin/python tools/local_mysql.py init --runtime "$PWD/.runtime"
.runtime/venv/bin/python tools/local_mysql.py start --runtime "$PWD/.runtime"
DNF_GM_M0_SOCKET="$PWD/.runtime/mysql.sock" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .runtime/venv/bin/python -m pytest -q
.runtime/venv/bin/python tools/local_mysql.py stop --runtime "$PWD/.runtime"
```

依赖下载校验见 `tools/runtime-sources.json`；若旧官方档案链接不可用，先验证并更新来源，不跳过哈希检查。新下载在校验后才进入缓存，已有缓存也会重新核对。pip 由 Python 自带的 `ensurepip` 在实验室 venv 内初始化，再安装 `requirements.lock` 的固定依赖；不再下载内容会变化的 `pip.pyz`，不修改全局包。MySQL 5.7 是兼容性实验目标，不建议作为新的公网数据库。不设置 socket 时集成用例会 skip，因此不能将全 skip 说成完整通过。

前端：

```bash
cd web
pnpm install --frozen-lockfile
pnpm lint:check
pnpm typecheck
pnpm test
pnpm build
```

覆盖目标包括业务规则、SQL 注入 / XSS / CSRF / Host / Origin、最小列权限、幂等、提交未知、原子性、物品动态策略、角色名称、表单就地错误提示、确认对话框和金币附件。

前端 CI 使用固定 pnpm 12.10.1 与 Vite+，冻结锁文件安装，并单独执行类型检查。管理库迁移017新增的 `tests/app/test_ui_preferences.py` 覆盖偏好版本冲突、删除后重建、防止旧版本覆盖、PVF隔离、数量上限、并发及最小管理库权限；同时验证试衣预览和图集接口的认证边界与无游戏写入。`test_catalog_filters_api.py` 核对职业、武器类别、套装筛选与批量策略目标一致。没有设置隔离socket时这些用例会skip，不能计作已通过。

## 必须另做的真实环境验收

- 测试账号在线刷新余额，交错消费与增减，换频道 / 重登不回退；不能拿 SQL 成功代替。
- 普通装备 / 材料 / 消耗品与纯金币 / 混合金币邮件的可见、领取、堆叠和重登；邮箱 / 背包满时不得丢失或重复。
- 封禁后重新登录拒绝、解封恢复；不要求立刻下线。
- 生产只做低强度测试；监控不触发核心服务重启，无新增 OOM。
- SSH 隧道、HTTPS 路由、Cookie、相邻页面同源风险与回滚演练。

公开导出不包含原服务器的历史验收报告、截图、玩家名单或私有操作收据。公开副本测试结果见 `docs/RELEASE-CHECK.md`，没有完成的项目须明确记录。


## 开发版第二批覆盖

`tests/app/test_character_detail.py`覆盖角色/账号仓库归属、跨角色共享、缺失/损坏/空容器、独立金币、未知索引以及无游戏写入；`test_actual_runtime_grants`在实际MySQL5.7专用用户下检查只读可用且写仓库、读取无关blob被拒绝。

`tests/app/test_item_preferences.py`覆盖按PVF隔离、分页、停用/缺失物品、去收藏、幂等收藏、收藏与选择并发、认证/CSRF/Origin、迁移重复执行、服务对象重建后持久存在，以及修改收藏不影响既有奖励预览或发放数量。前端覆盖收藏按钮、最近选择失败时保留草稿、仓库页和弹窗提示遮挡回归。

浏览器检查使用合成API验证桌面和390px手机点击，不等价于生产已部署或客户端物品效果验收。具体本轮结果见`reports/MANAGEMENT-EXPANSION-02.md`。


## 开发版受控发布包清理

`tests/test_release_cleanup_files.py`只删除pytest临时目录内的合成发布包，检查当前/回滚/最新两个版本、签名、目录指纹、链接/挂载点拒绝、资源门槛、逐目录收据、中断不重放，以及安装器父子进程维护锁。不会调用真实安装、启用或生产清理脚本。

`tests/app/test_release_cleanup.py`在隔离MySQL5.7核验认证/CSRF/Origin/重新认证、预览、同连接审计入队、最小权限、并发、锁/查询超时、审计失败、COMMIT响应丢失、只读查询、原编号投递和原子取消未入队预览。请求使用合成票据，不触发root执行器。前端`ReleaseCleanup.test.ts`核验就近错误、确认、未知结果、取消、只读恢复和隐藏/卸载时停止轮询。

可选浏览器测试`tools/browser-cleanup.mjs`要求Playwright与浏览器已在开发环境安装；不会增加应用运行依赖。先本地构建，并用Vite preview或等价静态服务器仅监听127.0.0.1:8766，提供`/dnf-gm/`。然后在仓库根运行：

```bash
node tools/browser-cleanup.mjs
```

工具只接受回环HTTP地址，阻止外部请求；API全用合成拦截，不连接生产。可通过`PLAYWRIGHT_MODULE`指定开发环境模块路径，`CHROME_EXECUTABLE`指定浏览器；仅在必须的隔离开发环境才设置`DNF_GM_BROWSER_NO_SANDBOX=1`。输出桌面/手机截图到Git忽略的`outputs/`。`DNF_GM_E2E_BASE`可更改本地静态端口，不能设为公网。

以上测试不替代生产systemd权限/资源验证，不证明已经释放生产磁盘空间。


## 装备编码与维护窗口基础测试

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .runtime/venv/bin/python -m pytest -q \
  tests/test_inventory_codec.py tests/test_inventory_fence.py \
  tests/test_inventory_probe.py tests/test_monitor.py
```

使用合成61字节槽位、临时文件、模拟/proc和固定命令返回值；仅探测执行器的超时/输出边界使用本机测试Python子进程，不连接生产Docker或游戏。测试包括未知字节保持、数量范围、品级字节序、关联类型拒绝、历史恢复冲突、共享/独占文件锁、文件替换、许可生命周期、时钟回拨/过期、未知进程/组件、父子链、核心保护及默认关闭。真实游戏进程白名单、已知属性的游戏语义、事务API和页面仍需后续验证；不能用底层测试替代装备功能验收。
