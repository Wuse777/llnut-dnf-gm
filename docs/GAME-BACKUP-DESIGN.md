# 游戏存档恢复点、加密副本与隔离演练

2026-11-09：本轮已在源码接通完整游戏业务库恢复点、固定异地加密传输协议、同版本隔离恢复演练和网页请求接口。**尚未安装到生产，也未在本机运行真实 MySQL 测试**：维护电脑没有 Linux/WSL 发行版或 Docker。代码完成、完整备份、异地接收和恢复通过是四种不同事实；未取得对应收据时不能标为已验证。

2026-11-06的只读适配观察为 MySQL 5.7.44-log、18个业务库、620表（432张 InnoDB、188张 MyISAM），表及索引估计约102MiB。它只是当时的结构证据。执行时重新核对完整库表清单，不能把这个历史数字当作当前实例保证。

## 范围和三个状态

- **完整备份**：除 `mysql`、`sys`、`information_schema`、`performance_schema`、`dnf_gm` 外的全部已安装业务库。库名必须与执行时完整可见清单一致；库、表、引擎或结构变化会拒绝备份。管理库仍使用原有独立自动备份。
- **异地副本**：以 `age` 公钥加密后，通过固定 SSH 目标发送；远端重新计算密文 SHA-256 和字节数并返回收据。目标必须有显式机器身份，且不同于源主机。成功复制只证明密文已接收并校验，不证明远端已经恢复。
- **恢复演练**：在明确配置的 socket-only、同一精确 MySQL 5.7 版本实例中恢复，核对表结构、全部存储值、行数和安装固定的跨表关系检查。演练不会把数据覆盖回生产。

三个状态按同一个明文 `artifact_sha256` 绑定。新备份没有独立复制/演练证据时不继承旧备份状态。新一次失败也不会抹掉同一文件先前成功的证据；界面同时显示最近一次尝试与最近一次匹配的成功记录。

文件不包括 PVF、程序、图片、MySQL实例配置、私有密钥或管理库。清单保存源码、镜像、PVF和程序摘要，用于恢复时匹配版本。运维者仍需另外保留相应程序、素材与私有配置。记录 binlog 坐标不等于具备连续归档或时间点恢复（PITR）。

## 一致性和资源边界

游戏存档包含 MyISAM，不能用单一事务快照宣称全库一致。执行器复用现有串行 maintenance worker、全局维护锁和库存排他屏障，不新增常驻服务或调度器。

1. 管理员先按既有协议主动开启维护窗口。必须是原维护会话、写入入口已冻结、全部业务写入组件已退出、MySQL保留运行；仅“无人在线”不满足条件。
2. 请求绑定原窗口、数据库身份、镜像、PVF和程序。执行器在锁内每5秒通过现有主机探针重新核验许可和停写证据，同时发布不依赖数据库的心跳。普通维护监视器和关窗操作被同一屏障串行化，不等待被锁的业务表更新心跳。
3. 专用单连接用一条 `LOCK TABLES ... READ` 同时锁定全部业务表。InnoDB设置 `autocommit=0`、`innodb_table_locks=1`；MyISAM不用允许并发插入的 `READ LOCAL`。不使用会阻塞管理库心跳/请求的实例全局读锁。
4. 在同一持锁连接上流式导出全部表，记录 binlog 坐标；完成前重新核对库表清单、每表DDL、窗口和停写证据。管理库连接已先释放，导出锁连接关闭后才写回管理结果，生产连接总预算保持网页2＋worker1。
5. 独立 watchdog 到期直接关闭当前 PyMySQL socket，打断取锁/查询并释放该连接持有的锁，不额外建立第4个 `KILL` 连接，不杀其他事务。备份预算最多540秒且不超过原许可剩余时间减5秒；过期或证据变化即失败，不自动停游戏、续开窗口或恢复服务。

支持1–64个业务库、1–2048张表、累计8MiB结构元数据；单表最多256列，单行原始字段最多1MiB，NDJSON记录最多4MiB，明文文件最多8GiB、密文最多9GiB。超过预算留下失败证据，不能静默跳过。文本/BLOB以HEX保留原始字节；BIT按无符号整数传输，日期/TIME以文本保留零日期。无主键表用与顺序无关的SHA-256多重集摘要，重复行仍计入次数。

当前**明确拒绝**视图、InnoDB/MyISAM以外引擎、生成列、触发器、存储过程/函数及事件；它们需要单独适配和真实恢复测试。新增对象不会被悄悄漏备。跨表检查使用安装时固定的账号→角色、角色→背包、角色→统计关系（存在相应表时加入），备份记录孤儿行数量，演练必须保持一致；不会擅自修复已有孤儿数据。

## 一次性安装与配置

管理库需迁移001–020；本功能的019创建控制行和请求表，018为活动表，020为工作台索引。`deploy/grants.py`与`deploy/upgrade-release.py`已包含对应精确授权。网页账号只读控制行，并对请求表作固定列写入；没有游戏库整表、`LOCK TABLES`、`FILE`或root授权。

`deploy/install.sh`调用 `deploy/configure_game_backup.py`，创建固定私有目录 `/var/backups/dnf-gm/game`。默认从既有root私有管理库备份配置 `/etc/dnf-gm/backup.json`只读发现完整业务清单，写入 `/etc/dnf-gm/game-backup.json`（root、600）。发现不支持的对象或无法核验时，这个可选功能保持未配置，不阻断GM其余安装；已有或显式提供的无效配置仍严格拒绝。单独运行管理库升级脚本后，也需运行这个配置步骤。源发现不锁表、不停服务、不写游戏数据。

异地和演练目标默认都是 `null`，不猜测地址。完整设置结构如下，密码和地址只能在root私有文件中填写，不要提交仓库或发到聊天：

```json
{
  "version": 1,
  "connection": {"host": "<已安装数据库地址>", "port": 4000, "user": "root", "password": "<私有维护密码>"},
  "schemas": ["<完整业务库清单>"],
  "relations": [],
  "copy": {
    "age_recipient": "<age-keygen生成的接收公钥>",
    "ssh_config": "/etc/dnf-gm/game-backup-ssh.conf",
    "ssh_host": "dnf-offsite",
    "remote_machine_sha256": "<远端/etc/machine-id去除空白后的SHA256>"
  },
  "lab": {"socket": "/run/dnf-gm-lab/mysql.sock", "datadir": "/var/lib/dnf-gm-lab"}
}
```

实际配置应保留自动发现的完整 `schemas` 和固定 `relations`，不能直接用上面的占位清单。源的host/port必须精确匹配已安装应用实例。首次提供审查好的完整root私有600文件时使用：

```bash
/opt/dnf-gm/venv/bin/python /opt/dnf-gm/current/deploy/configure_game_backup.py \
  --settings-file /absolute/root-private/game-backup-settings.json
```

已有配置不会被这个命令覆盖。维护者可在私有目录审查并原子替换固定配置后，重跑无参数配置检查。网页日常备份/复制/演练无需每次SSH授权。

## 异地接收机

源主机安装 `age` 和 OpenSSH 客户端；只保存接收公钥，解密私钥另行离线保管。接收机使用单独账号，创建该账号所有、700的固定 `/var/backups/dnf-gm-offsite`，把 `deploy/game_backup_receive.py`作为root所有且该账号不可修改的 `/usr/local/bin/dnf-gm-game-backup-receive`安装。

专用公钥的 `authorized_keys` 限制为：

```text
restrict,command="/usr/local/bin/dnf-gm-game-backup-receive" <源主机专用SSH公钥>
```

root私有SSH配置固定 `Host dnf-offsite`、HostName、User、IdentityFile和UserKnownHostsFile；提前核对并固定主机公钥。程序强制 `BatchMode`、`StrictHostKeyChecking`、`IdentitiesOnly`、关闭转发及agent转发。浏览器不接受主机、路径或命令。强制接收命令只接受恢复点ID、密文摘要和长度，拒绝任意命令、明文和超预算内容；同ID重放必须是完全相同密文，绝不覆盖已有副本。独立接收程序不依赖GM应用包。

机器身份不同只能证明不同安装身份；“异地”还需运维者确认目标确实在独立故障域、存储和账户下，不能把同一物理机克隆出的不同machine-id当成灾备隔离。当前实现不自动删除异地或游戏备份，不执行未经核对的清理。

## 隔离演练和离线使用

一次性准备独立MySQL5.7实验室：Unix socket、`skip_networking=1`、`server_id=57044`、准确的datadir、与备份源完全一致的 `SELECT VERSION()`；不挂载生产游戏数据。连接使用该隔离实例的本地root，无浏览器数据库连接输入。运行worker带 `PrivateTmp`，socket建议放 `/run`下的明确目录。

root只创建随机 `gb_restore_*` 库、临时 `gbr_*` 用户、授予临时库内 `SELECT,INSERT,CREATE,REFERENCES`以及最终清理。备份DDL由这个无全局权限、无生产库权限的临时用户执行；禁用 `local_infile`。核验完成或普通失败后清理本次随机库和用户。机器断电等硬中断仍需维护者检查遗留随机对象；不会自动扫描删除未知库。

演练核对精确MySQL版本、每表DDL、所有存储值的多重集摘要、行数、业务关系数量和明文文件SHA-256。网页演练读取服务器原始私有备份；异地密文恢复需先用离线私钥解密到**新的私有文件**，再运行：

```bash
umask 077
age -d -i /offline/private.agekey -o /absolute/private/new-game.ndjson /absolute/private/game.ndjson.age
/opt/dnf-gm/venv/bin/python /opt/dnf-gm/current/tools/game_backup.py restore-check \
  --artifact /absolute/private/new-game.ndjson \
  --sha256 <原备份明文SHA256> \
  --lab-socket /run/dnf-gm-lab/mysql.sock --lab-datadir /var/lib/dnf-gm-lab \
  --receipt /absolute/private/new-restore-receipt.json
```

没有网页在线整库覆盖、自动停服或生产恢复命令。单笔金币/装备问题仍通过对应事务和审计排查，不能用整库回档纠正。

## 文件、失败与请求追踪

每个恢复点位于root私有700目录 `/var/backups/dnf-gm/game/game-<backup_id>/`，包含 `game.ndjson`、`manifest.json`，以及生成后的密文、密文绑定和独立复制/演练收据。文件600、独占创建、fsync并以不覆盖方式发布。完整清单保留库表、版本、关系和binlog等恢复证据；公开结果只返回摘要、计数、时间和核验项，不含路径、表名、SQL或凭据。

任务区分 `preview/queued/running/succeeded/failed/needs_review`。原编号防重；预览5分钟内确认，执行仍核验原维护窗口。网络响应丢失后查原编号，不重新创建同一操作。

worker重启遇到 `running` 只读取并核对已持久化的原收据、完整文件摘要、原窗口/版本绑定和请求指纹：完整证据一致时补记成功并标记 `evidence_reconciled`；无完整收据则进入 `needs_review`，绝不自动重做导出、发送或恢复。`.partial`、没有完整manifest的文件、失败收据不能使状态变绿；保留私有现场供核对。维护者应自行检查剩余磁盘和遗留partial，当前没有未经确认的自动清理策略。

API前缀 `/dnf-gm/api/v1`：`GET /game-backups`、`GET /game-backups/{run_id}`、`POST /game-backups/preview`、`POST /game-backups/{run_id}/confirm`、`POST /game-backups/{backup_id}/copy`、`POST /game-backups/{backup_id}/rehearse`。写接口保留同源/CSRF和近期密码认证。列表的 `latest_backup`独立于分页；详情的 `original_backup`、`related_runs`和 `evidence`支持按原恢复点完整追踪。`verified_run`必须与当前明文摘要匹配，不由当前页猜测。

## 本轮验证范围

Windows PowerShell7.6.9／Python3.12：`PYTHONPATH=src .runtime/backend-tests/Scripts/python.exe -m pytest -q tests/test_game_backup.py tests/test_game_backup_requests.py tests/test_game_backup_transport.py tests/test_game_backup_worker.py`，27项通过，4项明确跳过（3项真实POSIX接收权限用例和1个真实POSIX维护屏障测试模块）。覆盖备份协议、完整范围拒绝、legacy字节、重复无主键行、异常连接释放、socket watchdog、请求证据分页、错误artifact绑定、固定传输收据、实际子进程超时/输出上限、硬链接发布后的文件身份和DDL库名重写保留默认值/注释。不使用伪造的 `fcntl`；这些纯逻辑结果不能代替Linux屏障和实库验证。

`tests/app/test_game_backup_mysql.py`另备有Linux MySQL5.7实库测试：混合引擎完整恢复、真实写锁阻塞/释放、锁等待watchdog、错误实例/文件/实验室拒绝、受限DDL权限，以及实际 `age`加密→接收文件校验→解密→隔离实库恢复链。设置既有 `DNF_GM_M0_SOCKET`并安装 `age`后运行。该测试用本机不同私有目录测试传输协议，不等于真实异地主机验证。未在当前电脑执行这些实库测试，也未运行生产备份、复制或演练。
