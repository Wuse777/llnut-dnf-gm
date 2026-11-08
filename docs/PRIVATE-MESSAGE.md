# 指定玩家系统消息

2026-11-09已实现源码、网页/API、审计与防重发送链。生产游戏插件尚未激活，客户端显示未验收；网页据实际开关与握手显示就绪状态。`implemented=true`表示本版本包含完整实现，`ready=true`还要求显式启用、当前核心/资源/镜像/monitor指纹通过、root中继和游戏桥接握手成功。开启网页权限本身不会装插件。

## 定向入口与边界

已按上游`llnut/dnf`的`ffa59f2c597978d77aa1ba379f7d17913d298c20`核对`build/dnf_data/home/template/init/frida.js`，其`api_CUser_SendNotiPacketMessage`通过`Memory.allocUtf8String`调用单个CUser的系统通知函数。新增桥接仅使用这一独立系统入口，固定通知类型2，没有发送方玩家或可选报文/代码输入。游戏二进制固定SHA-256为`8859c99d8290dc5fb58151444138cf2697b2bfff12d47d6159596a03f20b5261`；其他镜像须重新适配，不能照搬地址。

网页请求含账号UID、所属未删除角色编号、消息及必填原因。消息最多254个UTF-8字节，拒绝控制/格式字符；这里采用原始函数封装的UTF-8方式，客户端中文字形及颜色需单独验收。预览冻结账号、角色编号和角色名，确认重新核对，执行时还在游戏主线程重新查CUser、UID、在线状态及当前角色。切角色、离线、队列过期均不调用消息函数；不保留跨线程用户指针。

复用原生控制已有的5分钟预览、会话、同源/CSRF、重新认证、写门、资源保护、事务审计与持久发送占位。确认提交后释放DB连接，再通过固定Unix socket发送一次；root中继另有仅追加的持久操作编号占位。结果丢失、异常或重启不重放任何占位。`sent`仅表示已调用通知函数，`effect_status`始终`unknown`，不宣称客户端已显示。

## 三层结构

- 应用仅访问`/run/dnf-gm-message/relay.sock`，不读取游戏目录或桥接令牌。中继socket为root:dnfgm 0660，并以SO_PEERCRED核对调用者UID。
- root中继仅转发固定status/send结构。私有配置`/etc/dnf-gm/private-message.json`为root0600，固定游戏脚本哈希；连接游戏socket后再验证对端root身份和`/proc/PID/exe`的真实运行二进制哈希。单元保留CAP_SYS_PTRACE用于内核对跨容器`/proc/PID/exe`读取的权限检查；代码没有ptrace调用或进程附加入口。SQLite占位库位于私有状态目录，先提交后发送，不删除历史占位。
- 游戏桥接监听容器内`/data/.dnfgm-private-message.sock`（宿主`/var/lib/dnf/data/`），root0600，另需私有令牌。没有TCP监听、eval、任意文件/命令/报文接口。脚本定义本身没有副作用，仅显式start后才启动监听。

API统一前缀`/dnf-gm/api/v1`：`GET /native-controls/status`只读握手；`POST /native-controls/preview`新增`action:"native-message"`、`uid`、`charac_no`、`message`、`reason`；其余确认/取消/历史沿用原生控制接口。测试账号范围同样生效。定时任务仍只允许原有全服公告，不新增定时私信。

## 维护窗口激活步骤

当前Gadget使用`/data/frida.js`脚本模式并配置`on_change:reload`，没有独立外部RPC监听。原脚本`rpc.exports.init`的late/hotreload分支会直接调用`start()`；`start()`会安装玩法hook、初始化DB并安排怪物攻城，`dispose()`仅卸载DB连接。把桥接追加到正在运行的脚本会触发这些已有初始化，不能声称它是无副作用热安装。本版本未提供未经验证的运行时注入或重载捷径。

以下是维护者明确安排游戏停服窗口后的安装流程。普通应用升级不会自动执行这些步骤，也不会重启DNF。

1. 私下备份当前游戏脚本，核对游戏二进制和原脚本摘要。用root0700候选目录、root0600原脚本副本运行`deploy/prepare_private_message.py --source <私有副本绝对路径> --source-sha256 <已核对原脚本SHA256> --output <新候选脚本绝对路径> --config-output <新候选中继配置绝对路径>`。工具独占创建两个600文件、随机生成独立令牌，只打印候选脚本摘要，不改活动脚本。复跑时换新候选路径，勿覆盖证据。
2. 私下审阅候选差异并用`node --check`核对语法。工具只在原start之后启动新模块，并在原dispose之前停止它。候选脚本/配置包含令牌及原游戏脚本内容，禁止提交Git或附加Release。若当前脚本入口已变化，先人工适配，不跳过原摘要核验。
3. 在明确停服的维护窗口安装候选脚本到原活动位置，保持原权限和私有备份；安装新root0600中继配置。仅在确认游戏进程已退出后清除旧桥接socket。按既有方式启动游戏，使原初始化只运行一次。首次启动应验证现有Gadget版本支持Socket/NativeFunction API及main-thread调度器，失败保持消息能力关闭。
4. 单独安装`deploy/dnf-gm-private-message.service`并启动中继；单元在原`dnf-gm.slice`预算内运行，固定Unix地址、32MiB/10%上限，不改变任何其他服务。确认实际slice剩余资源可容纳；安装器和普通发布不启用该单元。维护者保留配置、候选摘要及原脚本备份；systemd StateDirectory为root0700。
5. 启用`native-message`及其显式激活记录，并保留原生monitor和绑定配置。GET status必须返回`bridge_state:"ready"`才允许预览。先对明确的测试账号/角色验证中文、长度、离线、角色切换、两次确认、刷新/重启不重发，并观察真实客户端；验收前不要记录client级证明或宣称送达。

回退时先关闭`native-message`并停止中继。在下次明确停服窗口恢复旧脚本，保留全部审计、原操作编号、中继占位库和私有证据；不通过在线热改、删除占位或重置幂等键来重发。原角色/邮件/公告功能不依赖桥接单元。

## 验证

`node --test tests/private_message_bridge.test.cjs`覆盖无副作用定义、主线程执行、二次身份核对、过期/停止、严格输入、原生异常与重复操作。Python纯测试覆盖字节约束、固定握手、共用单执行槽、模糊结果不重试和root持久占位；隔离MySQL API测试覆盖预览确认、归属/删除/改名/权限/桥接变化、历史与双阶段审计。合成测试不能替代实际Gadget运行和客户端验收。
