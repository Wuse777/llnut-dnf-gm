<div align="center">

# llnut DNF GM

**为 llnut/dnf 清风 1031 适配的轻量中文 GM 控制台**

SoybeanAdmin 工作台 · 多玩家独立草稿 · 组合选物与对比 · 外观与动作 · 运营与审计

[![Release](https://img.shields.io/github/v/release/Wuse777/llnut-dnf-gm?color=8b8780&style=flat-square)](https://github.com/Wuse777/llnut-dnf-gm/releases)
[![License](https://img.shields.io/badge/license-MIT-8b8780?style=flat-square)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square)
![Vue](https://img.shields.io/badge/Vue-3-42b883?style=flat-square)
![MySQL](https://img.shields.io/badge/MySQL-5.7-4479A1?style=flat-square)

[界面展示](#界面展示) · [功能一览](#功能一览) · [部署指南](docs/DEPLOYMENT.md) · [文档中心](docs/README.md) · [更新记录](CHANGELOG.md)

</div>

![SoybeanAdmin 玩家工作台](docs/images/workbench-v063.jpg)

> **截图说明**：当前源码的真实前端界面，使用本地合成 API、演示角色与虚构物品；不是生产玩家数据，也不是游戏内效果证明。缺图位置如实显示占位，不附带 DNF 游戏素材。[更多界面与截图来源 →](docs/SCREENSHOTS.md)

## 项目简介

把账号查询、奖励发放和受控维护放进一个可追踪的中文工作台：先选定玩家，预览变更，再确认执行；遇到响应中断，按原操作编号查询，而不是重复发放。

- **真实图标选物**：匹配客户端离线解析与 PVF 绑定；已验证样本覆盖 66,450／66,456 项，缺图状态、职业插画出处和鉴权保持明确。游戏素材需部署者自行提供。
- **组合筛选与对比**：部位、PVF 品级、等级、职业适用、武器类别和套装联合查询；常用条件可同步管理库，最多四件装备比较来源明确的基础属性；批量策略沿用同一筛选语义。
- **角色装备与外观**：12 个穿戴槽位、图标与品级边框；透明时装关联、私有部件图集、ANI 时间线与 Canvas 预览。32 个已核实的客户端转职插画映射，独立觉醒插画仍有缺口；未还原的染色／发光层列出原因。
- **面向 GM 的界面**：固定 SoybeanAdmin v2.3.0、浅色蓝紫主题、原创天空城场景、DNF 徽记、多玩家工作页签、独立草稿和角色专页；图标随包离线可用，手机抽屉导航与全页操作，业务页及弹窗按需加载。
- **减少重复等待**：认证请求并行、首页统计去重，后台刷新不锁定全局操作；带内容指纹的公开静态资源使用长期缓存，JS／CSS 支持 gzip。接口与私有素材继续禁止公共缓存。
- **奖励流程完整**：点券／代币券／商城积分、物品与金币邮件、版本化礼包、批量任务、定时运营和投递记录。
- **维护边界明确**：存档类修改通过显式维护窗口；不可变快照、幂等记录与审计保留历史，不把数据库成功写成游戏效果已验收。
- **部署保持克制**：FastAPI 单进程、最多 3 个数据库连接；前端在维护电脑构建，游戏数据库不暴露公网。

> [!IMPORTANT]
> 这是**非官方、特定镜像适配项目**，不是通用 DNF GM，也不是游戏整合包。你需要已有且有权管理的 llnut/dnf 服务端、自行准备的私有配置及匹配 PVF。更换镜像、PVF 或数据库结构必须重新适配。公开仓库不含服务端、客户端、PVF、NPK、真实物品索引、玩家数据或管理员凭据。

## 界面展示

| 手机选物：卡片与固定工作区切换 | 手机角色：主要动作与信息优先 |
| :---: | :---: |
| <img src="docs/images/picker-mobile.jpg" alt="手机选物卡片，使用合成物品数据" width="300"> | <img src="docs/images/character-mobile.jpg" alt="手机角色详情，使用虚构角色数据" width="300"> |
| 名称、编号、状态与加入按钮同时可见 | 余额、奖励直接操作；解锁／封禁收进“更多” |

多玩家奖励草稿绑定 UID／角色；刷新恢复、目标切换与未决操作分别管理。操作前先核对预览，结果未知时按原编号查询。详见[工作台指南](docs/UI-WORKSPACE.md)与[界面导览](docs/SCREENSHOTS.md)。

## 功能一览

| 模块 | 能做什么 | 操作边界／说明 |
| --- | --- | --- |
| 玩家中心 | 账号／角色／在线查询；等级、职业、属性、金币；装备、背包及仓库快照 | 中文编码适配，存档值不等于实时战斗属性；[玩家中心](docs/PLAYER-CENTER.md) |
| 账号货币 | 点券、代币券、商城积分增减及余额预览 | 不混淆角色金币；[奖励与名单](docs/ACCOUNT-LIST-REWARDS.md) |
| 邮件与礼包 | 物品、金币、标题／正文；模板版本、复制与临时调整；领取标记查询 | 金币每次最多 10 亿；物品数量 1–2,147,483,647，不按 PVF 堆叠值限量；特殊物品仍需适配 |
| 批量与定时运营 | 名单导入、筛选、全服／在线目标；进度、暂停、失败项处理；一次／每日／每周计划 | 冻结名单与期次防重；[定时运营](docs/SCHEDULES.md) |
| 在线与解锁 | 原生公告、定向系统消息源码、踢人、封禁／解封；解锁申请及提前设为到期 | 定向消息本批按用户安排暂不启用；发包或设为到期不等于客户端已处理；[在线控制](docs/NATIVE-MONITOR.md) |
| 装备维护 | 强化、锻造、增幅、附魔、品级、耐久、数量；回收、受条件保护的快照恢复 | 需显式维护窗口；[装备编辑器](docs/EQUIPMENT-EDITOR.md) |
| 角色维护 | 改名、位置救援、疲劳、等级／经验、SP／TP、同基础职业转职／觉醒、两套 PvE 技能重置 | 是存档维护，不是在线注入；[角色维护](docs/CHARACTER-MAINTENANCE.md) |
| 任务排查 | 当前任务槽、完成标记、任务名称／前置条件；单任务槽清理 | 不自动代做任务；[任务手册](docs/CHARACTER-QUESTS.md) |
| 运营与运维 | 玩家问题、发放统计、功能开关、资源监控、告警、版本诊断、管理库备份和隔离恢复演练 | 管理库备份不是游戏全服恢复点；[文档中心](docs/README.md) |

### 已知边界

- **源码、素材与服务器分别管理**。`v0.6.3` 修复图标空白、目标卡片排版及重复加载，加入原创生成背景；从 v0.6.2 升级没有数据库迁移。更早版本迁入工作台时涉及管理库迁移 017 和经过核实的 `user_items.ui_id` 只读权限，见[本版说明](docs/releases/v0.6.3.md)。公开下载不带客户端游戏素材。
- **并非每项都完成游戏客户端验收**。以构建和关键场景检查为主，不声称全量 CI 或游戏客户端效果已全部通过；各项边界见[工作台指南](docs/UI-WORKSPACE.md)和[外观指南](docs/CHARACTER-APPEARANCE.md)。
- **图片链路与素材分开**。匹配客户端样本已有 66,450 项可读图标，6 项明确保留缺口。私有部件包支持独立时间线和静态回退，旧图片包仍可使用。
- **外观完整性如实呈现**。透明时装按实例关联解析；未核实的染色混色、特殊发光、光环与职业附加层不猜测，逐项报告未绘制原因；不将基础职业插画作为精确觉醒头像。网页试穿不直接修改角色穿戴。
- 指定角色系统消息已有独立桥接实现，当前按用户安排暂不启用；未来需安装与指纹绑定、在维护窗口加载游戏桥后验收，见[定向消息指南](docs/PRIVATE-MESSAGE.md)。插件证据页不提供“0CD／无敌”等效果开关；没有任意 SQL／Shell 入口，也没有玩家兑换码网站。
- 默认密码登录，不要求 TOTP。运行权限、网页能力开关、索引／程序指纹及维护窗口分别生效，不因显示按钮而绕过校验。

## 开始使用

### 选择你的入口

| 你的情况 | 从哪里开始 |
| --- | --- |
| 已有 llnut/dnf，第一次安装 GM | [部署指南：前置条件 → 本机构建 → 首次安装](docs/DEPLOYMENT.md) |
| 已有 GM，准备升级 | [部署指南：已有实例升级](docs/DEPLOYMENT.md#已有实例升级)；不要重新运行 provision |
| 想了解操作流程 | [界面导览](docs/SCREENSHOTS.md) → [文档中心](docs/README.md) |
| 准备修改代码 | [开发指南](docs/DEVELOPMENT.md) → [贡献说明](CONTRIBUTING.md) |
| 下载发布文件 | [GitHub Releases](https://github.com/Wuse777/llnut-dnf-gm/releases) → [v0.6.3 说明](docs/releases/v0.6.3.md) |

### 从固定版本构建

维护电脑需要 Python 3.12（含 pip／venv）、Node.js 24.15+ 的 24.x、pnpm 12.10.1 和 Git。以下**只构建，不连接生产数据库、不安装服务**：

```bash
git clone --branch v0.6.3 --depth 1 https://github.com/Wuse777/llnut-dnf-gm.git
cd llnut-dnf-gm
PYTHON_BIN=python3.12 bash tools/build_release.sh "$HOME/dnf-gm-build-v0.6.3"
```

输出路径必须尚不存在；wheels 必须与服务器 OS／CPU 架构匹配。完成后继续[安装步骤](docs/DEPLOYMENT.md)，不要直接把源码压缩包交给安装器。

> [!WARNING]
> Release 的 `source.tar.gz` 是源码，`web.tar.gz` 是预构建静态网页；两者都**不是完整离线安装包**。它们不包含平台 wheels、私有配置、索引或游戏资产。下载后先验证 `SHA256SUMS`，不要公开数据库端口，也不要在小内存游戏服务器上运行 Node 开发服务。

## 架构与安全

```text
浏览器 ── SSH 隧道 / HTTPS 反代 ── FastAPI（回环地址，单进程）
                                      ├── dnf_gm：会话 / 操作 / 审计 / 任务
                                      ├── 游戏 MySQL 5.7：按表 / 列授权
                                      └── 私有只读目录：PVF 索引 / 可选图片包
固定监控与维护执行器 ── 脱敏快照 / 显式维护协议
```

- 后端不是 root，没有 Docker socket、任意命令或通用数据库管理权限；特权维护执行器与网页进程分开。
- `dnf-gm.slice` 合计内存硬上限 192 MiB、CPU 配额单核 25%；这是 GM 组件预算，**不是游戏服务器整机推荐配置**。
- 会话 Cookie、CSRF、精确 Origin、重新认证、事务防重与审计；新实例从隧道和受限范围验收开始。
- HTTPS 同 IP 的不同路径不是安全来源隔离。公网开放前检查同源应用与反代边界，优先独立管理域名。

详见[安全说明](SECURITY.md)、[兼容性](docs/COMPATIBILITY.md)和[部署指南](docs/DEPLOYMENT.md)。

## 文档与贡献

[文档中心](docs/README.md)按玩家、奖励、维护、运维和开发分类；历史生产记录集中在 `docs/reports/`，不作为新安装步骤。

欢迎提交可复现问题、文档修正与适配补丁。提交前阅读[贡献说明](CONTRIBUTING.md)；问题中只提供脱敏版本、复现步骤和错误，不上传私钥、配置、玩家备份或游戏文件。安全问题按 [SECURITY.md](SECURITY.md) 私下报告。

<details>
<summary>仓库结构</summary>

```text
src/dnfgm/       API、认证、业务、审计与索引
src/dnfgm_m0/    隔离实验室及兼容性工具
web/            Vue 页面、组件与测试
migrations/     管理库迁移 001–017
fixtures/       合成数据库结构（无真实玩家）
deploy/         安装、授权、监控、维护、回滚
tools/          索引工具、构建与实验室
docs/           指南、截图、功能手册与历史报告
```

</details>

## 许可证与致谢

自有代码采用 [MIT](LICENSE)。SoybeanAdmin v2.3.0 上游与 MIT 许可见 [web/UPSTREAM.json](web/UPSTREAM.json)、[web/SOYBEAN-LICENSE](web/SOYBEAN-LICENSE) 及 [THIRD_PARTY.md](THIRD_PARTY.md)；历史 CPAMC 来源声明继续保留。DNF、游戏程序及第三方素材的权利不随本项目许可证转移。

文档布局参考 [Uptime Kuma](https://github.com/louislam/uptime-kuma) 的截图与安装导航、[Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template) 的开发／部署分层；未复制其代码、截图或文案。更多见[文档维护约定](docs/DOCUMENTATION.md)。
