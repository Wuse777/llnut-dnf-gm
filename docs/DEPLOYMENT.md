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
- 采集完成后间隔15秒，失败也退避；保护每5秒读资源。连续两次低于256MiB可用内存、1536MiB空闲Swap、2GiB磁盘余量，或两份新采集的核心故障快照，仅停止GM并要求人工恢复；缓存失败不会重复计数。
- 采集超时立即发布未知快照，阻止游戏写入；至少60秒、至少3次采集持续失败才停止GM。只有本监控进程自身发起的采集失败停止，才可在3份连续健康新快照且跨度至少30秒后自动启动GM。每进程每小时最多3次；启动失败不自动重放，监控重启不接管旧停止，核心服务不会被启动或重启。
- 手动维护应先 `touch /var/lib/dnf-gm/no-auto-recover` 再 `systemctl stop dnf-gm.service`。结束维护时删除标记，核验资源/核心状态后手动启动GM。标记由root目录控制，网页无权操作。普通手动停服不产生恢复资格；已经被监控停下时的重复stop是systemd空操作，必须先设置禁止标记来表达维护意图。
- `/api/v1/health`（带 `/dnf-gm` 前缀）检查管理库；`/api/v1/ready` 另检查新鲜快照、核心和资源，异常返回503。监控外部可用性时应检查ready，不能仅以首页200判正常。
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

### 0.3.1统一数量规则

无需逐项配置数量上限。已知、缺失或为0的PVF堆叠值均只作元数据，不限制邮件和礼包数量；所有物品使用原生数量字段正整数范围1–2,147,483,647。旧`mail_stack_limits`配置作为兼容键保留，但不参与启动校验、物品验证和发放，可从私密配置删除。

从0.3.0升级无需数据库迁移、新增授权或重新生成索引。安装新release，切换`static_dir`到新前端并只重启GM；监控及核心服务可保持原样。旧待确认邮件可能因物品描述变化而需要重新预览，已完成操作的结果与幂等记录不修改。升级后核对`/health`、`/ready`版本0.3.1，以及未知/已知上限条目的`quantity_unlimited=true`。装备类填写多件时后端逐件创建邮件附件及特殊存储记录，耗时和存储随件数增长。

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

### 从0.1.0升级到0.2.0

没有新管理库迁移。原配置的只读/测试目标/写入审批保持；不能重新provision。安装器先核对SHA256SUMS，再禁止自动恢复、停止GM及监控，然后安装离线依赖；current原子切换，等待新监控PID产生健康快照并通过ready后才完成。失败时GM保持停止，检查后人工回退；安装前已有的禁止恢复标记不会被移除。

若需要开启1031装备解锁，先备份管理库、私有配置与授权；在隔离库核对存档格式和事务表引擎，再执行仅追加授权的命令：

```bash
PYTHONPATH=/opt/dnf-gm/current/src /opt/dnf-gm/venv/bin/python \
  /opt/dnf-gm/current/deploy/upgrade-equipment-unlock.py \
  --container <现有容器> --mysql-port 4000 --db-account-host <MySQL看到的来源IP>
```

授权不会激活功能；仍需私有配置同时添加 `writes` 中的 `equipment-unlock` 和相应 `write_approvals=true`，再只重启GM。不适配的服务器保持关闭。10亿金币/新解锁预览可能不被旧代码理解，跨版本回滚前保持GM停止、核对未确认操作，不能直接以旧版重新开放写入。


## 升级至0.3.0：全物品与商城积分

先备份管理库、现有列权限、索引和私有配置，并创建维护禁止恢复标记，停止GM。使用新版本代码在维护窗口执行：

```bash
/opt/dnf-gm/venv/bin/python deploy/upgrade-rewards.py --container YOUR_CONTAINER --mysql-port 4000 --db-account-host YOUR_EXACT_SOURCE_IP
/opt/dnf-gm/venv/bin/python tools/enrich_catalog_creatures.py /private/Script.pvf /var/lib/dnf-gm/catalog.sqlite /private/catalog-rewards.sqlite
```

占位参数须替换为当前部署的值。升级脚本只追加积分、时装和宠物的列级权限，并执行003管理库迁移：首次将既有禁止策略统一开放，再次运行保留此后手动停用。无游戏表DDL，不发放任何奖励。索引工具校验PVF摘要，补充宠物和宠物装备的存储类型；将输出文件以原索引所有者和只读权限安装到配置的catalog_file，再原子切换release并启动GM。全新索引已包含该元数据。

`writes`及`write_approvals`中的`currency`同时控制点券、代币券和积分；`mail`控制所有类型邮件。原有测试UID、PVF及资源门禁继续生效。恢复后先核对健康版本0.3.0、完整索引与可发放总数、账号积分和邮件预览。时装、宠物、积分与大额领取尚需真实客户端验收。

回退应用时同时恢复原索引和catalog_policy_items/catalog_policy_state/schema_versions的管理库备份；保留或按授权备份撤销新增列权限。回退代码不会撤回已经确认的奖励。


## 开发版管理扩展（未发布，不是0.3.1的必需升级）

当前源码在0.3.1之后加入004邮件流水、005物品偏好、006持久奖励任务及仓库只读。发布前先在隔离环境演练并按当前实例逐项核验权限，不可重新运行`provision.py`。在完整备份和升级窗口中，仅停止GM应用，保留游戏、数据库、共享Docker及核心代理服务。

在新的版本目录、root维护身份下依次执行（参数必须替换为已核实的现有容器和数据库用户精确来源）：

```bash
python3 deploy/upgrade-mail-center.py --container <现有容器> --mysql-port <数据库端口> --db-account-host <精确来源IP>
python3 deploy/upgrade-warehouse-read.py --container <现有容器> --mysql-port <数据库端口> --db-account-host <精确来源IP>
python3 deploy/upgrade-item-preferences.py --container <现有容器> --mysql-port <数据库端口> --db-account-host <精确来源IP>
python3 deploy/upgrade-reward-jobs.py --container <现有容器> --mysql-port <数据库端口> --db-account-host <精确来源IP>
```

这些工具只执行管理库DDL或专用账号增量授权，不修改游戏表结构、不发奖励、不重启服务。`health`要求管理库至少版本6；它不替代实际运行账号的列权限核验。安装应用后用管理员认证分别检查角色详情中的两类仓库、物品收藏/最近选择、邮件中心和原业务；历史邮件导入步骤仍见第一批阶段说明。

回滚旧应用时保留004/005/006表、邮件流水、偏好、审计及操作编号，不删除玩家数据或执行降级DDL。新增账号仓库金币只是只读存档，与金币邮件上限无关。


### 组合奖励与批量执行器（开发版，默认关闭）

- 单次组合奖励需在`writes`和`write_approvals`显式激活`reward`；若内容含账号货币还须`currency`，含邮件还须`mail`。既有充值/邮件权限不会自动启用组合奖励。
- 批量发放额外要求`batch-reward`及其显式审批，并设置`batch_worker_enabled: true`；`batch_worker_interval`须为1–60秒整数，默认1秒。启用前确认管理库006、最小权限、镜像/PVF指纹、采集快照、资源和测试UID条件均满足。
- 仅一个应用进程内线程逐目标执行，仍共享最多3条数据库连接，没有新进程、额外数据库端口、Docker socket或命令接口。MySQL具名锁避免重复执行器同时发奖；连接关闭释放锁。时间间隔不是吞吐量保证，大量独立装备投递可能延长单目标事务。
- 全服/在线模式按**角色**固定名单；在线表示登录状态表在线账号名下的匹配角色，不表示这些角色同时在线。没有角色的账号不包含在本轮名单内。全服启动要输入“全服发放”；按角色重复账号货币需单独确认。
- 任务列表与目标分页保留实际状态；关浏览器不停止任务。暂停/取消只影响未开始的目标，不撤销已提交奖励；已开始的事务可能先完成。控制请求超时只查询原任务。
- 单角色的货币、邮件、幂等操作、成功审计、目标完成和去重记录一次提交。**整个批量任务不是跨全服的大事务**；一部分角色成功后，另一角色失败不会撤销前者。界面明确显示逐角色结果。
- 执行前持久记录`executing`。进程中断后先取得目标行锁，核对原操作/审计；不能因为浏览器报错而自动重发。已知未提交标为failed；人工“重新排队”后仍需“继续”。不一致记录隔离为uncertain并暂停该任务，其他任务不被反复核对阻塞。手工核对不能忽略审计冲突。
- 升级/回滚前先在面板暂停任务，记录其编号，再仅停止GM。回滚不删除006表，不将executing/uncertain直接改成pending，不恢复整库撤销单笔奖励。旧版代码不运行执行器；回到新版本后先核对持久任务。
- 数据库完成不证明在线消费、邮件领取或客户端显示正确。本轮网页/API/事务测试不替代游戏客户端验证。

### 私有图片包（开发版，可选）

见[图片包指南](ASSETS.md)。在维护电脑离线生成全新目录，复制至服务器root拥有、dnfgm组只读的私有路径；设置`assets_dir`，仅重启GM。默认空字符串，不要求图片包才可使用原业务。无需新增迁移/数据库权限/解析进程。包、配置及新鲜服务器快照的PVF不符时拒绝图片；缺图/损坏降级到文字，不改变发奖数量或业务预览指纹。回滚只切换完整包路径，不在线覆盖文件。真实素材尚未取得和验收，当前代码未部署。


### 解锁申请中心（开发版）

- `/unlock-requests`按角色编号游标每次扫描至多25个存档，按账号/角色/UID搜索；状态在扫描后过滤，因此空结果页仍可能有下一页。不是无界全库解压。
- 单角色和跨角色处理复用`equipment-unlock`写权限及原有指纹/资源/测试目标审批；没有新增权限开关或迁移。本批单独不增加授权，合并开发版仍需要前述004/005/006与最小权限。
- 列表只读。处理前退出选中账号，确认后下次加载角色由游戏处理。一批1–20个不同角色、明确申请编号、共同原因，所有角色申请修改和审计在同一事务提交，失败全部回滚。
- 预览绑定穿戴、背包、角色仓库和锁记录指纹，确认再次锁定/核验；新代码拒绝旧版缺少容器指纹的待提交预览，请重建。已完成操作保留原编号查询，不重放。
- 结果丢失保存原操作编号，重新打开解锁中心只查询，不自动重发。查询仍为preview不代表可以安全重发未知提交。不要用清除浏览器存储来绕过待确认状态。
- 物品关联按当前二进制已核对的锁字段，不是槽号；重复关联显示候选，缺失/损坏显示不完整。范围仅穿戴、背包和角色仓库；不覆盖独立时装/宠物表或账号仓库。逐角色处理标注从最近20条该账号解锁审计中匹配，未显示标注不证明从未处理。
- 回滚应用保留全部操作/审计；已回拨的申请时间不会因切回版本而恢复。无游戏装备写入、无新维护停机或运行时补丁，不把数据库完成等同于客户端完成。生产正向关联和客户端验证仍未完成。


### 运维诊断（开发版，只读）

- 新监控入口`monitor.py`在`/var/lib/dnf-gm/telemetry.sqlite`持久保存诊断，无需MySQL迁移或新授权。监控所有者写入、应用只读，默认0644；内容只有资源数字、固定事件、脱敏目录标签和发布包名称，禁止复制凭据/原始日志/argv。不要授予应用写此数据库的权限。
- 新配置`telemetry_file`默认上述路径，一般不需写入应用配置；如使用自定义路径，必须是维护人员配置的绝对路径并允许应用只读。旧版应用不认识新增配置键，回滚时恢复与旧版本兼容的配置，不删除诊断或业务审计。监控自定义包装器也须创建Recorder并传给`run(..., telemetry=recorder)`；保留已有auxiliary核心检查，不能直接覆盖生产包装器导致漏检。
- 每分钟保留最差观测，最多10080分钟（7天）；事件最多256条。24小时5分钟聚合、7天30分钟聚合，分别最多约289/337点。CPU为观测峰值、内存/Swap/磁盘为最低可用量；时间缺口不补0，初次部署没有历史可回填。数据库查询有时间/文件大小/返回数量边界。
- 固定目录由root所有且不可被组/其他用户写入的`monitor.json`中`storage_paths`配置，格式见example；最多8个id/label/path项，不接受网页传入路径。单个后台扫描线程每小时一次，GNU du仅统计同文件系统、不跟随符号链接；每目录5秒超时。失败不清空保护状态，扫描不在主监控循环内等待；扫描线程/子进程仍属于原192MiB/25% slice。
- 保留systemd沙箱，不为扫描扩大`ProtectHome`或核心访问权限。示例`/root/.../backups`可能被沙箱阻止，显示不可读/未知，不能当0或自动放宽权限。分类根目录可能嵌套、Docker卷可能与游戏数据重叠，分类量不可直接求和。没有任何删除动作。
- 保护停止事件记录当时的可用资源。过去发生过的“恢复请求成功”不代表当前健康；GM停止时网页可能502，恢复后回看持久历史。诊断SQLite忙碌/损坏/写失败不会绕过、停止或降级原资源保护；旧的仅采集故障自动恢复机制不扩展到资源/核心故障。
- 只读列出至多扫描100个发布目录条目，显式标记列表截断和current/previous保护。目录mtime不是部署时间，其他目录也不是自动清理许可。旧产物清理仍待独立受控流程，当前接口仅GET，无SQL/Shell/重启/删除接口。
- 升级须包含新的`deploy/telemetry.py`，按现有安装流程只更新GM与其监控，不动mihomo/cliproxyapi/Docker。生产上线后验证历史持续增长、超时状态、采集延迟及共享slice资源；本地测试不是这项生产验收。
