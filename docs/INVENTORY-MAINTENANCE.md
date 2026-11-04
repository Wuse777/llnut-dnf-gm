# 装备编辑：存档编码与显式维护窗口

状态：**2026-11-05 本地开发基础，未部署；还不是可用的网页装备编辑功能。**

本批提供独立的61字节槽位编辑器、实例乐观校验、历史快照恢复校验和根维护窗口协议。没有新增游戏UPDATE权限、数据库迁移、装备写API或网页按钮。事务快照、权限、服务端预览/确认/审计、物品属性语义和页面仍待后续接入。不得把本批测试结果当作客户端效果或生产维护方案已验收。

## 为什么不只判断离线

数据库登录标记或原生monitor离线响应，不证明游戏缓存已落盘，也不能阻止随后登录/加载。直接写背包可能被游戏的后续存档覆盖。因此拟采用人工安排的明确维护窗口：保留MySQL，停止全部游戏/登录写入组件并禁止其自动拉起，再允许装备事务。

**本工具绝不执行停服、启动、重启或SQL。** 它不能暂停mihomo、cliproxyapi、共享Docker或dnf宿主单元。操作员必须另行安排窗口；不能执行`systemctl stop dnf`来获取窗口，因为可能连MySQL一起移除。

## 1. 存档编码契约

`src/dnfgm/inventory_codec.py`：

- 存档是4字节LE解压长度与单一完整zlib流；严格限制压缩长度、解压长度及61字节对齐，拒绝截断、拼接和尾随数据。损坏不能当空背包。
- 修改选定槽位中的已知字段，保留其他槽位及未知字节。强化低5位可变，重封装高3位保留。
- 支持的底层字段：强化、锻造、耐久、增幅类型/值、附魔ID、装备原始品级、堆叠数量。此处只验证编码，不保证每个字段取值都有合法的PVF/客户端语义；生产服务层必须继续适配。
- **原始品级是普通装备类型1中的大端32位字段，不是0–100%的百分比，也不直接等于“最上级”。** 不提供虚假的百分比转换。
- 数量保持1–2,147,483,647，不恢复PVF堆叠上限，不将未知上限限制为1。
- 回收仅清零所选槽位；锁定物品拒绝直接回收，防止孤立锁记录。宠物等关联记录、未知槽位类型不走普通槽位删除；特殊类型仍需专门适配，不宣称全类型完成。
- 不允许通过该模块改变item_id、锁指针、关联记录ID或任意原始偏移。

`identity()`绑定账号、角色、容器、槽位、**整个压缩存档**、目标槽位以及镜像/PVF/游戏程序指纹。它是HMAC乐观引用，不是已发现了游戏全局物品UUID。其他槽位变化也会使旧引用失效。

`restore()`只在整个当前容器仍等于原操作的after-image时，返回原before-image；否则拒绝覆盖后续进度。更换角色、容器、快照归属和操作权限的校验仍属于尚待实现的事务层。

## 2. 维护窗口生命周期

固定目录`/run/dnf-gm/maintenance`：

- `fence.lock`：root创建一次，不替换；应用只能只读打开并取得共享flock。
- `permit.json`：root签发，随机窗口ID，期限30–3600秒；绑定启动ID、容器ID/启动时间、镜像/PVF/程序/进程策略指纹和完整组件列表。
- `evidence.json`：root重新采集，最长30秒有效；失败会写入无效证据。

根工具`deploy/inventory_window.py`只允许本机root运行，命令如下。**以下是尚待生产验证的工具接口，不是要求现在执行维护：**

```bash
# 安装产物中源码包已能导入dnfgm；本地开发可使用PYTHONPATH=src。
/opt/dnf-gm/venv/bin/python /opt/dnf-gm/current/deploy/inventory_window.py init
/opt/dnf-gm/venv/bin/python /opt/dnf-gm/current/deploy/inventory_window.py issue \
  --reason '已预约的装备维护' --ttl 600 --acknowledge-writers-stopped
/opt/dnf-gm/venv/bin/python /opt/dnf-gm/current/deploy/inventory_window.py status
/opt/dnf-gm/venv/bin/python /opt/dnf-gm/current/deploy/inventory_window.py refresh
/opt/dnf-gm/venv/bin/python /opt/dnf-gm/current/deploy/inventory_window.py close --id <签发的窗口ID>
```

`issue`要求两次稳定探测，中间至少等待2秒；必须有明确操作员声明，但声明本身不能替代探测。未关闭的过期窗口也不能被新窗口静默替换。

`close`取得独占锁后使证据失效、删除许可并同步目录；存在装备事务时返回busy，不会在事务途中撤销。**只有close明确成功后，操作员才能按原维护流程恢复游戏。** 关闭不依赖Docker、MySQL、配置文件或代理仍然可用。

签发响应丢失时先查看状态，不重复签发；程序中断或证据过期会拒绝新事务。有效期与新鲜度同时核对墙上时间和绑定本次启动的单调时钟，系统时间回拨不能延长许可或复活旧证据。close响应丢失可使用原ID重试；若已经没有许可，返回already_closed，不启动任何服务。

应用未来使用方式：

```python
with fence.hold() as lease:
    # 锁定并核对目标容器；在同一MySQL事务写入快照、修改和审计。
    lease.check()  # 必须紧邻commit，重新校验窗口/锁/证据/有效期
    connection.commit()
    # 直到commit成功/失败/不确定得到处理，才释放上下文。
```

窗口协议不是对抗root的安全沙箱。root绕过close直接拉起游戏、外部维护工具写库、其他未声明的外部写入者，不受共享锁保护。部署前必须确认全部实际写入来源并遵守维护流程；有限次进程快照不是形式化的“未来永远没有写入”证明。

## 3. 固定只读探测

`deploy/inventory_probe.py`不会接受网页参数或任意命令。它只运行固定的Docker inspect、Docker内s6状态查询、受保护单元的systemctl is-active，并读取宿主/proc及已配置文件。

- 枚举完整`/run/service`，必须与配置完全一致，未知/新增组件拒绝。
- 除MySQL外，要求s6 `up,wantedup,normallyup,ready,pid`为`false false false true -1`；仅“down”不够。MySQL要求运行、允许正常保持运行，不能误要求它一定实现ready通知。
- 容器必须运行且无OOM、暂停、重启；两次检查的容器和组件状态一致。
- 检查Docker、dnf宿主单元、mihomo、cliproxyapi的`systemctl is-active`，不通过停核心服务绕过检查；实际单元名必须核实。这只是单元状态，不是完整业务健康证明；监控适配同时保留已配置的auxiliary检查，真实核心接口仍需生产验证。
- 以宿主cgroup扫描容器进程，含子cgroup；拒绝嵌套PID命名空间、未知进程、僵尸、异常父子链和PID/参数变化。按人工审核的可执行文件哈希、完整argv、UID、父规则进行精确匹配；不只查`df_`名称，也不自动学习白名单。
- MySQL进程必须存在且与s6的mysql服务进程具有已核对的父子关系。
- 每次采集限20秒、每条命令限5秒、输出限64KiB；进程数和文件读取有界，哈希缓存绑定inode/size/mtime/ctime，失败不返回旧的安全状态。
- 可用内存至少256MiB、Swap剩余至少1536MiB；监控器原有磁盘/资源保护仍然保留。

配置为root-owned且不可组/全局写的`/etc/dnf-gm/inventory-maintenance.json`。`deploy/inventory-maintenance.example.json`故意留空指纹和进程规则，因此不能直接启用。必须在隔离镜像中取得真实执行链和完整服务列表，逐条人工审核后填入，不将游戏二进制、玩家数据、含私密参数的配置放进公开仓库。

进程规则包含`id,role,exe,sha256,argv,uid,parents`；角色仅init/supervisor/logger/mysql，init与mysql各一个规则。该配置是维护者的信任声明，不能靠把未知进程改叫logger来证明安全。

s6字段语义依据官方文档：https://skarnet.org/software/s6/s6-svstat.html 。当前部署镜像是否支持对应版本和输出格式，还没有生产验证；格式不兼容时拒绝窗口，不能降低到简单down检查。

## 4. 与现有监控的关系

`monitor.json`增加`inventory_maintenance_enabled:false`，默认完全不加载新流程；本批没有修改生产配置。

显式开启且存在窗口时，监控器刷新并验证证据。配置必须与普通监控的容器、PVF、组件及核心单元一致，不能漏掉已有受保护单元。验证成功仅允许**保留GM进程运行**，对外`core_ok`仍为false、状态为maintenance；既有充值、邮件、奖励和原生控制不得把维护许可当游戏正常。

验证失败、过期、资源/代理失败仍按原保护规则处理GM；不因维护模式自动恢复GM。窗口结束后须人工恢复游戏并确认正常健康。配额仍是现有192MiB/25% slice，不新增独立常驻进程、Web停服权或Docker socket权限。

## 5. 尚未完成

- 管理库不可变快照、实例编辑/回收/纠正事务与最小列权限。
- 专用预览/确认API、归属/版本/防重/并发和提交不确定恢复。
- 网页物品详情操作、前后差异、操作记录和恢复入口。
- 附魔兼容、品级显示映射、特殊关联类型的完整语义适配。
- 当前生产镜像进程规则、维护探测、资源开销和真实游戏效果验证。

在这些事项完成前，不开放装备写功能、不授予游戏存档UPDATE、不签发生产窗口。完整目标继续，以`ROADMAP-IMPLEMENTATION.md`为准。
