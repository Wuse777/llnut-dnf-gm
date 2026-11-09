# 安装、升级与回滚

[项目首页](../README.md) · [文档中心](README.md) · [开发指南](DEVELOPMENT.md) · [发布说明](releases/v0.6.2.md)

适用：**已有 llnut/dnf 清风 1031 + MySQL 5.7 的 Linux 服务器**。GM 以 systemd 服务运行在宿主机，通过私有 Docker 网络连接已有游戏数据库；不是另一套游戏服务端，也没有“通用 Docker 一键安装”承诺。

> [!WARNING]
> 先在隔离环境核对兼容性并准备恢复能力。部署只操作 GM 自身组件；不重启共享 Docker、mihomo、cliproxyapi 或游戏服务。**已有实例走升级，不要重复执行 provision，不要覆盖私有配置。**

本版含管理库迁移 **017**，增加版本化界面偏好；时装透明关联读取需最小 `user_items.ui_id` SELECT 权限。升级工具迁移管理库，不增加游戏表写权限。目录职业／武器／套装元数据和部件动画包需离线更新，旧包保持兼容。

## 部署路线

```text
准备备份及版本信息 → 维护电脑构建 → 传输并核验
           ├─ 首次：创建管理库／专用账号 → 配置监控 → 安装
           └─ 升级：确认维护空闲 → 停止 GM 工作者 → 迁移／授权 → 安装
回环健康检查 → SSH 隧道 → 测试范围验收 → 按需配置 HTTPS
```

## 环境与准备清单

| 位置 | 要求 |
| --- | --- |
| 维护电脑 | Git、Bash、Python **3.12**（pip／venv）、Node.js **24.15+ 的 24.x**、pnpm 12.10.1；可下载锁定依赖 |
| 游戏服务器 | Linux + systemd、Python 3.12／venv、curl；已有可用游戏容器及 MySQL 5.7 |
| 数据库 | 私有网络可达，精确来源 IP，专用用户；不发布公网数据库端口 |
| 版本信息 | 镜像 digest、PVF SHA-256、容器名、容器内 MySQL 端口、实际 s6 组件名、网关健康地址 |
| 备份 | 私有管理库备份、配置／索引备份，以及独立核验的游戏恢复方案；管理库备份不包含游戏进度 |
| 资源 | GM 组件合计 `MemoryMax=192M`、`CPUQuota=25%`；健康门槛包括可用内存≥256 MiB、Swap 剩余≥1536 MiB、磁盘剩余≥2 GiB；不是整机容量保证 |

配置里的示例地址 `172.18.0.2`、容器名和端口不能原样照搬。构建 wheels 的 OS／架构必须匹配目标服务器，macOS／Windows／ARM 构建物不能冒充 Linux x86_64 安装包。其他镜像先阅读[兼容性说明](COMPATIBILITY.md)。

## 1. 在维护电脑构建

```bash
git clone --branch v0.6.2 --depth 1 https://github.com/Wuse777/llnut-dnf-gm.git
cd llnut-dnf-gm
# 输出目录必须是新的绝对路径；默认只做类型检查／构建，不跑全量测试。
PYTHON_BIN=python3.12 bash tools/build_release.sh "$HOME/dnf-gm-build-v0.6.2"
```

完整本机构建目录包含 `src/`、`deploy/`、`migrations/`、`web/dist/`、锁定 wheels、源码版本、构建记录和 `SHA256SUMS`。不包含生产配置、物品库或游戏素材。将整个目录交付服务器，例如：

```bash
# 替换实际 SSH 地址；远端使用新目录，不能覆盖 current 指向的版本。
ssh YOUR_SSH_USER@YOUR_SERVER 'sudo mkdir -p /opt/dnf-gm/releases/v0.6.2'
# 上传到维护账号可写目录，再由维护者移入上面的 root 发布目录。
scp -r "$HOME/dnf-gm-build-v0.6.2" YOUR_SSH_USER@YOUR_SERVER:~/
# 以下在服务器 root 会话中执行，按实际上传目录替换。
cp -a /home/YOUR_SSH_USER/dnf-gm-build-v0.6.2/. /opt/dnf-gm/releases/v0.6.2/
cd /opt/dnf-gm/releases/v0.6.2
sha256sum --check --strict SHA256SUMS
```

传输前后对比可信哈希；同包提供的校验文件用于完整性检查，不独立证明来源可信。新目录必须无旧索引、配置和多余文件。

### Release 下载文件是什么

| 文件 | 内容 | 能否直接 `install.sh` |
| --- | --- | --- |
| `llnut-dnf-gm-0.6.2-source.tar.gz` | 对应标签的 Git 源码与文档 | 否，先本机构建 |
| `llnut-dnf-gm-0.6.2-web.tar.gz` | `web/dist/` 静态前端与 `SOURCE_REVISION` | 否，仅供同版后端配套使用 |
| `SHA256SUMS` | 上述附件 SHA-256 | 用于 `sha256sum -c SHA256SUMS` |

预构建网页不是单独可连接数据库的管理面板；不要与旧后端混用。GitHub 自动生成的 Source code 压缩包也不是含 wheels 的安装目录。

## 2. 首次安装

以下命令在**服务器 root 维护会话**执行。若已安装，请跳到[已有实例升级](#已有实例升级)。

### 2.1 初始化环境和私有配置

```bash
RELEASE=/opt/dnf-gm/releases/v0.6.2
python3.12 -m venv /opt/dnf-gm/venv
/opt/dnf-gm/venv/bin/python -m pip install --no-index \
  --find-links "$RELEASE/wheels" -r "$RELEASE/requirements.lock"
install -d -m 700 /root/dnf-gm-private
install -m 600 "$RELEASE/deploy/config.example.json" /root/dnf-gm-private/config-input.json
```

编辑私有副本，不把秘密填回 Git 示例：

- 填真实 `db_host`（数字 IPv4）和 `db_port`；来源 IP 是 **MySQL 看到的宿主机地址**。
- 起步保留 `public=false`、`origins=["http://127.0.0.1:8765"]`、`writes=[]`、`test_uids=[-1]`；不要全域 CORS。
- 数据库密码和应用密钥由 provision 生成；不把玩家账号、游戏 root 密码或网关 AES 密钥拿来当管理密码。
- 物品目录默认 `/var/lib/dnf-gm/catalog.sqlite`；没有匹配索引也可先做只读账号查询。

```bash
/opt/dnf-gm/venv/bin/python "$RELEASE/deploy/provision.py" \
  --config /root/dnf-gm-private/config-input.json \
  --container YOUR_GAME_CONTAINER --mysql-port YOUR_MYSQL_PORT \
  --db-account-host YOUR_EXACT_SOURCE_IP
```

工具交互读取至少 20 字符管理员密码，生成 `dnfgm` 系统用户、`dnf_gm` 库、专用数据库账号、管理员 `admin` 和 `/etc/dnf-gm/config.json`。MySQL 维护权限使用容器已有 `DNF_DB_ROOT_PASSWORD`；不打印密码，不写玩家行。数据库 DDL 不是整体原子操作，失败后检查部分创建状态，**不要自动重复初始化**。

当前源码管理库迁移为 **001–017**。运行账号最多 3 个连接，只获必要表／列权限。能力开关与实际可执行性分开，初始私有配置不能替代镜像指纹、索引、准入与维护验证。

### 2.2 配置监控并安装

```bash
install -m 644 "$RELEASE/deploy/monitor.example.json" /etc/dnf-gm/monitor.json
# 编辑真实容器、PVF、数据路径、健康地址和 s6 组件名。
# core_services 中加入本机必须保护的实际服务，例如 mihomo、cliproxyapi。
bash "$RELEASE/deploy/install.sh"
```

监控配置 root 所有、0644 或更严格。安装器核验校验清单／维护空闲、安装 GM 单元、原子切换 `current`，先启动监控，健康后才启动后端。它可能重启 `dnf-gm*`，**不会修改 Nginx，也不部署或重启游戏**。

安装器会把应用配置收紧为 root 所有、dnfgm 组可读的 0640；不要为了消除权限报错改成 0777。维护及在线备份还需对应私有执行配置，详见[维护中心](WEB-MAINTENANCE.md)、[备份说明](BACKUP-HEALTH.md)，不要填假指纹来绕过保护。

## 3. 回环检查与 SSH 隧道

```bash
systemctl status dnf-gm.service dnf-gm-monitor.service --no-pager
# Host 必须与 origins 中的主机和端口一致。
curl --fail -H 'Host: 127.0.0.1:8765' http://127.0.0.1:8765/dnf-gm/api/v1/health
curl --fail -H 'Host: 127.0.0.1:8765' http://127.0.0.1:8765/dnf-gm/api/v1/ready
```

`health` 核对数据库及版本结构；`ready` 还检查实时监控／资源。`health=200` 不代表游戏功能完成验收。采集未知或过期必须处理，不能替换为伪正常快照。

维护电脑执行：

```bash
ssh -N -L 8765:127.0.0.1:8765 YOUR_SSH_USER@YOUR_SERVER
```

访问 `http://127.0.0.1:8765/dnf-gm/`，使用独立管理员密码。若更换本地端口，要同步精确 Origin／Host 配置；不要以允许所有 Origin 解决登录问题。先核对账号、中文角色、余额、在线统计，再在专用测试对象上验收已启用写操作。

## 4. 私有索引与可选图片

PVF 在维护电脑离线解析，不在网页上传、不在小内存服务器在线处理：

```bash
# 先按开发指南准备 .venv；输入和输出都位于 Git 之外。
PYTHONPATH=src .venv/bin/python tools/build_catalog.py \
  /private/Script.pvf /private/catalog.sqlite --encoding gbk
```

将索引单独安装为 `/var/lib/dnf-gm/catalog.sqlite`，只读可访问；PVF SHA-256 必须匹配。成长、技能、任务等索引增强按相应功能手册生成，不用一份空索引假装完整适配。图片是可选私有包，见[素材指南](ASSETS.md)；没有素材时保留文字和占位图。

## 已有实例升级

> 不重复 provision，不重置管理员，不清空功能策略、审计、快照或幂等记录。先读[版本说明](releases/v0.6.2.md)及[升级检查](UPGRADE-CHECK.md)。

1. 保留可恢复的私有管理库备份，以及配置、权限、外部索引／图片版本；确认没有未决维护、批量发放或提交结果待核查的操作。
2. 新目录构建、传输并核验。**不能把旧发布目录里的过期 `catalog.sqlite` 复制进新包**：安装器会覆盖外部索引；先检查新包无内嵌旧索引。
3. 确认维护窗口已正常关闭／恢复游戏，再用同版检查器核对维护空闲。停止 GM 工作者，不停止 DNF 容器：

```bash
RELEASE=/opt/dnf-gm/releases/v0.6.2
/opt/dnf-gm/venv/bin/python "$RELEASE/deploy/check_maintenance_idle.py"
touch /var/lib/dnf-gm/no-auto-recover
# 仅对已安装的 GM 单元执行；停定时器以免备份／清理同时启动。
for unit in dnf-gm-alert.timer dnf-gm-cleanup.timer dnf-gm-maintenance.service dnf-gm-monitor.service dnf-gm.service; do
  if systemctl cat "$unit" >/dev/null 2>&1; then systemctl stop "$unit"; fi
done
/opt/dnf-gm/venv/bin/python "$RELEASE/deploy/upgrade-release.py" \
  --container YOUR_GAME_CONTAINER --mysql-port YOUR_MYSQL_PORT \
  --db-account-host YOUR_EXACT_SOURCE_IP --backup /root/private-management-backup.sql
bash "$RELEASE/deploy/install.sh"
```

备份必须已存在、非空、root 所有且仅 root 可读。当前统一升级器核对来源迁移、补齐001–017及精确列授权，不修改游戏行；来源版本不支持或 DDL 中断时停下排查，不能删表重来。**新功能开关及授权需复核**：升级器初始化尚缺失的能力，不以旧截图或旧默认值推断现有策略。

4. 核对 `current`、`previous`、构建记录、`health`、`ready` 和已知账号只读数据。安装失败时禁止自动恢复，保留日志和原目录。
5. 本流程手动创建的 `no-auto-recover` 由维护者在确认健康后移除；原先已存在的标记不要擅自删除。按原配置恢复之前启用的告警／清理定时器。不要启用以前不存在的功能。

`upgrade-release.py` 在进程停止后持有固定维护锁；不要手工 SQL 拼迁移。它不是通用任意版本数据库升级器；配置兼容性、索引和维护协议也要核对。

## 可选：HTTPS 公网访问

完成隧道验收后再做，优先独立管理域名与有效证书：

1. 私有配置设 `public=true`，`origins` 只填写实际 HTTPS Origin（不含路径）；切换模式时注销旧会话。
2. 在现有 HTTPS `server` 内审查并引入 [deploy/nginx.conf](../deploy/nginx.conf)。保留 `/dnf-gm/` 前缀，后端仍监听 `127.0.0.1:8765`。
3. 执行 `nginx -t` 成功后再平滑 reload；保留原游戏网关和其他服务路由。
4. 外部检查后端端口不可直连、`/dnf-gm/api/v1/internal/` 返回404、登录／CSRF／Cookie 正常；再次检查同源其他页面。

不同 URL 路径不等于安全隔离。没有专属域名或存在相邻应用脚本风险时，保留 SSH 隧道，不强行公网开放。不要在文档或 Release 粘贴自己的生产地址和管理员密码。

## 回滚与恢复

```bash
# 在当前发布目录中执行；需已存在可用 previous。
bash /opt/dnf-gm/current/deploy/rollback.sh
```

回滚器核对维护空闲、阻止自动恢复、停止 GM 后检查旧版本兼容性，必要时拒绝回退。配置键不兼容时恢复对应私有配置；数据库保留向前兼容表、审计、防重及快照，不做破坏性降级迁移。Nginx 路由由维护者单独核验。

**应用回滚不会撤回已充值货币或已领取物品。** 不用整库恢复取消一笔奖励；先核查原编号，再做新的纠正操作。游戏恢复和管理库恢复分别处理；禁止先停止会移除容器的 `dnf.service` 再尝试从中备份 MySQL。

## 常见问题

| 现象 | 优先检查 |
| --- | --- |
| 安装器拒绝、GM没有启动 | 新目录校验、维护是否空闲、`journalctl -u dnf-gm.service -u dnf-gm-monitor.service -n 80`；先脱敏再共享日志 |
| health 正常但 ready 失败 | 实时组件、快照时间、内存／Swap／磁盘阈值；不要伪造状态或关闭监控 |
| 登录失败／Origin 拒绝 | 精确协议、主机、端口、代理 Host、Cookie、公网模式；不是开放 CORS |
| 搜索角色中文乱码 | 当前镜像字符编码适配；不要直接批量修改玩家名称 |
| 能查询但不能发放 | 能力策略、私有配置、指纹、测试范围、索引版本、监控准入，存档类还要维护窗口 |
| 不显示图标 | 是否安装有权使用的匹配私有图片包；仓库不会自动附带客户端素材 |
| 请求超时，不知道是否成功 | 保留原操作编号查询，不刷新页面后再执行一次 |

历史开发批次已移入[旧部署记录](history/DEPLOYMENT-BATCHES-202610-20261106.md)，其中的默认值和未部署结论不作为本版安装步骤。

