# 安装、升级与回滚

本流程是公开版的通用模板，不读取原部署者的凭据或私有运维仓库。**不要将其直接覆盖到已有安装上**。先在隔离环境演练；安装脚本只控制 `dnf-gm*`，不会重启游戏、Docker、代理或现有网关。

## 1. 前置条件

- Linux + systemd，Python 3.12、venv、curl；现有且已正常运行的 llnut/dnf 容器和 MySQL 5.7。数据库只能通过私有网络访问，不发布数据库公网端口。
- 准备备份并验证恢复。不能停止会删除运行容器的管理单元后再试图导出其中的 MySQL。
- 维护电脑构建前端和 Python wheels，目标 Python / OS / 架构必须匹配。服务器不运行 Node 开发服务。
- 明确容器名、PVF 路径、s6 组件名、网关回环健康地址、数据库 IP / 端口，以及 MySQL 实际看到的宿主机来源地址。模板中的 `172.18.0.2` 只是示例，不保证与你的 Docker 网络相同。

## 2. 在维护电脑构建

```bash
PYTHON_BIN=python3.12 bash tools/build_release.sh /absolute/new/release-directory
# 可选：在本地生成匹配目录。不要提交 PVF 或输出索引到 Git。
PYTHONPATH=src .venv/bin/python tools/build_catalog.py /private/Script.pvf /private/catalog.sqlite --encoding gbk
```

构建脚本复制源码、前端产物、部署文件和 wheels，不打包配置、玩家记录或 PVF。将 release-directory 复制到服务器 `/opt/dnf-gm/releases/<你的版本>/`；如有本地索引，单独交付为该目录的 `catalog.sqlite`，初次也可无索引，以只读账号查询开始。将校验清单与可信的传输前哈希核对。

## 3. 首次创建管理库与凭据

先创建虚拟环境（以下命令均在服务器 root 维护会话执行）：

```bash
python3.12 -m venv /opt/dnf-gm/venv
/opt/dnf-gm/venv/bin/python -m pip install --no-index \
  --find-links /opt/dnf-gm/releases/<版本>/wheels \
  -r /opt/dnf-gm/releases/<版本>/requirements.lock
```

在 root 私有目录复制并编辑 `deploy/config.example.json`，填写真实 `db_host`（数字 IPv4）和端口；暂时保持 `public=false`、`writes=[]`、`test_uids=[-1]`、本地 Origin 不变。不要编辑或提交仓库里的示例文件来保存生产秘密。

```bash
/opt/dnf-gm/venv/bin/python /opt/dnf-gm/releases/<版本>/deploy/provision.py \
  --config /root/private-gm-config-input.json --container <现有容器名> \
  --mysql-port 4000 --db-account-host <MySQL看到的宿主机来源IP>
```

工具交互输入管理员密码（至少 20 字符），自动生成独立数据库密码和应用密钥，创建系统账号 `dnfgm`、管理库 `dnf_gm` 和管理员 `admin`。不打印密码、不修改玩家行；维护授权仅通过容器已有的 `DNF_DB_ROOT_PASSWORD` 使用。运行账号最多 3 连接，只有指定表 / 列权限，没有游戏表 DDL、玩家密码读取、背包修改或授权能力。

最终应用配置为 `/etc/dnf-gm/config.json`（dnfgm 所有，0600）。不要使用此工具升级或重置密码。MySQL DDL 无法整体回滚，失败时保留私密配置并检查部分创建状态，禁止自动反复初始化。

## 4. 配置独立监控并安装

复制 `deploy/monitor.example.json` 为 `/etc/dnf-gm/monitor.json`，root 所有、0644 或更严格；按实际环境配置容器、PVF 和组件。`core_services` 可包含 `mihomo`、`cliproxyapi` 等必须保护的服务。采集器没有原运维仓库依赖，快照不含命令输出、日志正文或凭据。

```bash
bash /opt/dnf-gm/releases/<版本>/deploy/install.sh
```

- 安装只生成数据库目标 IP 的 systemd 访问放行，应用无 Docker socket / 任意命令接口。
- 网页应用与 root 采集进程合计受 `dnf-gm.slice` 的 192 MiB 内存上限、单核 25% CPU 配额限制。
- 采集每 15 秒；保护每 5 秒检测，连续两次低于 256 MiB 可用内存、1536 MiB 空闲 Swap 或核心检查失败，仅停止 GM。不会启动 / 重启核心服务；恢复后需要人工启动 GM。
- 若机器没有 Swap 或不足，监控将阻止启动。请在维护窗口规划 Swap，不为上线而调低保护底线。
- 状态未就绪时安装拒绝启动应用；物品索引缺失可只读运行，但不能发物品。

## 5. 隧道验收与写入激活

```bash
ssh -N -L 8765:127.0.0.1:8765 <SSH用户>@<你的主机>
```

通过 `http://127.0.0.1:8765/dnf-gm/` 登录。先核对只读数据。

在**私密配置**中设置：

- `test_uids` 为专用测试账号的真实 UID（默认 `[-1]` 拒绝所有玩家写入；空数组意味着取消目标限制，需明确决定）。
- `image_digest` 为 `docker inspect -f '{{.Image}}' <容器>` 的完整值，本公开采集器使用不可变 image ID，而不是 tag 或 `RepoDigest`。
- `pvf_sha256` 为服务器 PVF 的 SHA-256；本地索引也必须匹配。
- 在 `writes` 添加经过适配的 `currency`、`mail`、`ban`、`unban`，对应 `write_approvals` 必须显式置 `true`。仅填写指纹不意味着游戏内验收已通过。

仅重启 `dnf-gm.service` 应用配置；更改监控设置需仅重启 `dnf-gm-monitor.service`。先验证测试角色，尤其在线消费交错、邮件领取与封禁后的重新登录。客户端缺失时只能标为接口 / 数据库通过，不能标为游戏内通过。

## 6. 可选 HTTPS

没有自动公网发布脚本。先检查域名 / IP 证书、既有同源页面的脚本安全，再人工将 `deploy/nginx.conf` 内容 include 到现有 HTTPS server 块，保持路径不变。修改后 `nginx -t`，成功才平滑 reload；不要覆盖已有路由。

配置 `origins=["https://你的管理域名"]`、`public=true`；删除或注销旧会话后仅重启 GM。新模式不会接受隧道模式的旧会话。后端仍仅监听回环地址。公共端口只用现有 HTTPS，不能开放 8765 或数据库端口。

同一域名下的其他面板与 GM 共享浏览器源；不同路径不构成安全隔离。有同源注入风险时保留隧道，优先使用独立受控域名。

## 7. 升级与回滚

1. 备份管理库及只读索引，保留之前 release 和 wheels；**不要备份到公开 Git**。
2. 对比迁移与列权限，先在隔离库演练。首次开源版本含迁移 001 / 002；未来升级不能重新运行 provision，不能清空审计或幂等表。
3. 新版本在新 release 目录，运行其 `deploy/install.sh` 切换代码 / 依赖 / 服务文件。目录已有 current 时记录 previous；安装不会自动执行未来数据库迁移，也不会修改 Nginx。
4. 回滚前可人工关闭 GM 的 Nginx include 并验证 reload，然后 `bash /opt/dnf-gm/current/deploy/rollback.sh`。它用 previous 的本地 wheels 重装旧应用，仅控制 GM 服务；目录和旧索引须事先保留兼容性。
5. 回滚不删除审计、不撤回充值 / 已领取邮件，不通过整库恢复纠正单笔发放。出现不确定提交时只按操作编号查询，不盲目重放。

资源上限和 systemd 语法在目标主机需通过 `systemd-analyze verify` 复核。公开化脚本未经其他服务器完整安装验收，不宣称一键通用适配。
