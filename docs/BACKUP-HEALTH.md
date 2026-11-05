# 管理库备份、隔离恢复与健康证据

状态：2026-11-05已完成生产管理库备份及本机隔离恢复，并接通公网健康证据。33张表、200行、190224字节；表定义、全部字段值摘要及行数一致。此功能不等于全服备份。

本次私有备份目录 `/var/backups/dnf-gm/verified-management-20261105-184753`；公开健康报告仅包含摘要，不暴露备份内容。该次为一次性备份/演练，尚未配置定时备份；24小时未重新核对文件时仍显示证据过期。下文“生产准备”为再次备份的操作说明，不表示本次尚未执行。

## 范围

仅备份`dnf_gm`管理库，包括管理员密码哈希、会话、防重/操作流水、审计、礼包、任务、问题记录等。文件包含敏感信息，始终按私有文件管理，禁止提交Git、作为网页下载或粘贴到聊天。

**不覆盖**游戏存档/游戏数据库、MySQL实例配置、应用私有密钥、PVF和图片素材。管理库恢复通过不代表游戏数据可恢复，不可用它撤销已经发放的金币或装备。游戏库备份仍需另外安排原有一致性备份和恢复验证，不能用本工具在网页执行整库覆盖。

## 证据链

1. `backup`在同一MySQL连接的Repeatable Read一致性只读事务中导出全部可见管理表，按主键每页8行，保留定义及字段类型；开始/结束核对完整表清单与定义。
2. 每表有精确行数和主键顺序下全部字段值的SHA-256；整个私有NDJSON文件另有SHA-256。不是仅比较`COUNT(*)`，也不是只检查文件存在。
3. `restore-check`必须连接隔离本机Unix socket，核对MySQL5.7、server_id57044、skip_networking=1和维护者明确给出的datadir。**不支持生产恢复。**
4. 隔离root只创建/清理随机临时库与临时用户。备份中的DDL和行数据使用仅获临时库SELECT/INSERT/CREATE的用户执行，无其他库权限、FILE、TRIGGER、GRANT或全局权限，不以root执行备份SQL。
5. 实际恢复后逐表核对定义、完整字段值摘要、精确行数、文件哈希；临时库和用户清理完成后才返回成功收据。失败不出成功收据。
6. `publish-health`重新校验所选文件并关联收据，输出小型脱敏报告。另一份备份的成功恢复仅显示历史记录，不能证明当前备份可恢复。证据文件不是独立的数字签名证明，它依赖维护者可信工具、私有文件权限和受控保存。

## 类型、性能与失败边界

- 保留二进制BLOB、BIT、无符号大整数、Decimal、日期、微秒时间、空字符串和NULL。二进制走HEX，TIME走原始文本，避免驱动或CASE表达式改变值；BIT按整数插入后按原字节复核。
- 只支持1–64张InnoDB管理表，必须有主键；拒绝视图、触发器、存储过程/函数、事件和生成列。外键依赖等新结构须重新适配和实测，不承诺任意MySQL库的通用迁移。
- 单行原始字段字节总计上限512KiB、NDJSON单行上限2MiB、文件上限1GiB、默认900秒操作预算。超过上限会失败并保留`.partial`，绝不静默跳过记录。上限是备份资源边界，不改变道具发放数量。
- 输出600、独占创建、同步落盘，成功文件通过不覆盖的原子发布产生。失败保留私有partial供排查，不自动删除旧备份。不要无限保留partial占用磁盘，维护者核对后处理。
- 文件校验固定读取已打开的普通文件，拒绝符号链接/公开权限，并核对读取前后身份；读取期间替换路径也会失败。
- 生产备份工具要求GM已由维护者停止、自动恢复抑制文件已存在、维护锁可用，并在既有`dnf-gm.slice`资源预算内运行。工具自身不停止/启动任何服务，游戏、mihomo、cliproxyapi和Docker保持不动。这样备份维护连接不会叠加于运行中的GM三连接池。

## 本地隔离操作

使用已准备好的socket-only实验室和项目Python环境；所有输出放私有目录，以下为占位路径：

```bash
PYTHONPATH=src python tools/management_backup.py backup \
  --lab-socket /absolute/lab/mysql.sock --lab-datadir /absolute/lab/data \
  --output /absolute/private/gm.ndjson --receipt /absolute/private/gm-backup.json

PYTHONPATH=src python tools/management_backup.py restore-check \
  --artifact /absolute/private/gm.ndjson --sha256 <备份收据中的64位SHA256> \
  --lab-socket /absolute/lab/mysql.sock --lab-datadir /absolute/lab/data \
  --receipt /absolute/private/gm-restore.json

PYTHONPATH=src python tools/management_backup.py publish-health \
  --artifact /absolute/private/gm.ndjson \
  --backup-receipt /absolute/private/gm-backup.json \
  --restore-receipt /absolute/private/gm-restore.json \
  --output /absolute/private/backup-health.json
```

每次备份与恢复使用新文件名，收据不覆盖。`publish-health`可刷新既有同格式健康报告，但拒绝覆盖原备份、收据、符号链接或不相关文件。退出码非零不能算成功；可能已有私有备份或partial，先核对，不盲目重跑同名命令。

## 生产准备（另行安排GM维护，不是自动部署脚本）

1. 准备root所有、600的私有维护连接JSON，仅含`host`、`port`、`user`（root）和`password`，不复用网页上传、环境输出或命令行密码。使用维护权限是为了完整观察schema特性；不会给运行账号新增权限。
2. 在预定窗口中人工设置原有`no-auto-recover`抑制标记并停止**GM自身**，不要停止游戏容器或共享Docker。记录标记是否本次创建，事后只处理本次拥有的标记。
3. 通过`systemd-run --scope --slice=dnf-gm.slice`运行已发布版本的Python和`management_backup.py backup --connection-file <私有连接文件> ...`。保持192MiB/25%原有整体限额，不临时扩容。备份脚本检查停止状态，但不能防止另一位root越过维护锁手工启动服务；维护期间不得并行启服/迁移。
4. 将私有备份安全复制到维护电脑，使用隔离实验室恢复并返回脱敏收据。恢复工具不接受TCP目标；不用生产实例做演练。
5. 在维护者选择的受限执行环境中重新核对并发布`/var/lib/dnf-gm/backup-health.json`，root所有、644。网页配置默认只读取这个报告，不读取私有备份或连接文件。
6. 按原部署健康流程恢复GM，核对保护状态；不自动清除其他原因留下的恢复抑制。

2026-11-05已执行一次上述范围的生产备份、隔离恢复与证据发布。为避免额外维护连接，备份时仅停止GM应用；持有共享维护锁且运行于既有资源slice，完成后恢复应用。没有核验游戏库备份；管理库结果不能推广为全服恢复保证。

## 网页与可选告警

“运维诊断→备份与恢复健康”显示：最后文件核对时间、备份完成时间/规模、SHA-256、隔离恢复完成时间、是否匹配当前备份，以及明确的覆盖范围。

- 报告超过24小时未重新核对文件：显示“证据过期”，不沿用旧正常状态。
- 备份超过24小时：提示超过建议周期；匹配恢复超过30天：提示重新演练。此为健康提示，不阻止原有GM发放。
- 另一份备份的演练：显示实际历史时间，但当前文件仍未通过恢复证明。
- 文件或收据校验失败/缺失：显示未知或校验失败，不暴露路径、凭据、SQL或异常正文。

可在独立告警配置`/etc/dnf-gm-alerts.json`中显式设置`backup_health_enabled: true`。观察器读取固定公共证据文件，无数据库连接或文件全量哈希成本。备份证据过期/失败及当前备份缺少有效恢复核验会进入原有去重通知流程。默认false；不得仅打开此开关就声称已有备份。新版本首次观察会为旧六规则状态补上两项，不重置原有防重历史。

## 回滚

停止使用新维护工具即可；保留备份、收据和健康报告。回滚旧版应用若不识别`backup_health_file`需移除此配置键；回滚旧版告警观察器前移除`backup_health_enabled`，并保留新版私有状态副本，不能把不识别的新规则状态静默清空。管理库不新增迁移；回滚代码不回滚任何玩家进度。
