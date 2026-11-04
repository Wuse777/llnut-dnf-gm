# 自动化测试与验收

## 隔离是硬要求

后端集成夹具会删除重建实验库。实验连接只支持本地 Unix socket，检查 `VERSION()` 为 5.7 且 `@@server_id=57044`；**这个标记不是生产保护的替代品，绝不能在正式实例设置它来跑测试**。夹具只使用合成账号和物品，不包含玩家密码。

在 Linux x86_64 维护电脑（需要 `dpkg-deb`，无需 sudo）可构建固定版本实验室：

```bash
python3.12 tools/bootstrap_lab.py --runtime "$PWD/.runtime"
.runtime/venv/bin/python tools/local_mysql.py init --runtime "$PWD/.runtime"
.runtime/venv/bin/python tools/local_mysql.py start --runtime "$PWD/.runtime"
DNF_GM_M0_SOCKET="$PWD/.runtime/mysql.sock" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .runtime/venv/bin/python -m pytest -q
.runtime/venv/bin/python tools/local_mysql.py stop --runtime "$PWD/.runtime"
```

依赖下载校验见 `tools/runtime-sources.json`；若旧官方档案链接不可用，先验证并更新来源，不跳过哈希检查。MySQL 5.7 是兼容性实验目标，不建议作为新的公网数据库。不设置 socket 时集成用例会 skip，因此不能将全 skip 说成完整通过。

前端：

```bash
cd web
npm ci
npm test
npm run build
```

覆盖目标包括业务规则、SQL 注入 / XSS / CSRF / Host / Origin、最小列权限、幂等、提交未知、原子性、物品动态策略、角色名称、表单就地错误提示、确认对话框和金币附件。

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
