# 阿拉德工作台改版实施与验收

范围：用户要求落实角色工作台、紧凑选物与奖励、统一待办、问题排查、活动上下文、游戏存档一致性恢复点，以及暖白／石墨灰与琥珀金视觉规范。

## 实施清单

- [x] 角色默认工作台与轻量读取；装备、背包、资源、问题和邮件摘要，资料／外观／维护按需展开。
- [x] 桌面紧凑选物、手机首屏列表与筛选抽屉、目标折叠、右侧奖励草稿；手机首屏搜索、首物品和加入按钮已用Chrome几何断言核验。
- [x] 统一待办与异常深链接，批量失败筛选和原编号核对。
- [x] 奖励未到账、卡地图、装备、任务场景及同屏证据；邮件条件检索与领取标记。
- [x] 活动固定奖励、人群、批次、计划、统计与跨批次事务防重；真实MySQL并发、跨登录原编号核对与取消闭环通过。
- [x] 游戏全库一致性备份、独立复制协议与隔离恢复演练，分别展示三个状态与管理库范围；真实Linux／MySQL／age链路通过。
- [x] 主题与业务组件规范、手机壳层、文档与安装／升级路径；迁移授权和回退兼容已在实验室验证。
- [x] 定向／集成／构建／桌面和手机浏览器验证与最终逐项审计。

源码实施不代表生产已经升级；数据库标记不代表游戏客户端已经验收。所有验证结果以完成后的实际命令、测试收据和截图为准。

## 实施范围与核对入口

| 要求 | 实现与可检查证据 |
| --- | --- |
| 默认轻量角色工作台 | [概览读取](../../src/dnfgm/character_overview.py)、[角色工作台](../../web/src/components/CharacterOverview.vue)、[真实MySQL用例](../../tests/app/test_character_overview.py)；不预取仓库与装扮，最近邮件最多200条附件 |
| 紧凑目录与奖励草稿 | [选物组件](../../web/src/components/GmItemPicker.vue)、[奖励页](../../web/src/views/gm/RewardComposerView.vue)、[双栏与手机切换](../../web/src/components/MailWorkbench.vue)；列表56/58px，次要条件与收藏入抽屉 |
| 跨工作流统一待办 | [只读聚合](../../src/dnfgm/workbench.py)、[首页](../../web/src/views/gm/HomeView.vue)、[路由集成测试](../../tests/app/test_workbench_redesign.py)；具体问题／批次／计划／原操作／恢复点深链接 |
| 按玩家问题排查 | [问题详情](../../web/src/components/SupportDesk.vue)、[场景排查](../../web/src/components/PlayerInvestigation.vue)、[奖励证据](../../web/src/components/RewardEvidence.vue)；目标隔离、核对清单草稿与原时间线 |
| 邮件证据查询 | [邮件查询](../../src/dnfgm/mail_center.py)、[邮件界面](../../web/src/components/MailCenter.vue)；北京时间日期范围、原目标名称、物品／礼包与近期200条领取标记，详情完整分页 |
| 活动上下文与防重 | [活动事务](../../src/dnfgm/campaigns.py)、[活动界面](../../web/src/components/Campaigns.vue)、[并发与回滚测试](../../tests/app/test_campaigns.py)；固定礼包／人群条件，账号或角色完整奖励去重 |
| 游戏存档恢复点 | [备份与恢复](../../src/dnfgm/game_backup.py)、[维护执行器](../../deploy/game_backup_worker.py)、[集成测试](../../tests/app/test_game_backup_mysql.py)；全业务表READ锁、固定加密副本与隔离同版本MySQL演练 |
| 视觉与兼容迁移 | [主题变量](../../web/src/styles/gm-theme.css)、[旧默认色迁移](../../web/src/theme/migrate.ts)、[浏览器脚本](../../tools/browser-workspace-redesign.mjs)；用户自定义配色与可访问性偏好保留 |

操作说明见 [工作台使用指南](../UI-WORKSPACE.md)，备份配置和边界见 [游戏恢复点说明](../GAME-BACKUP-DESIGN.md)。源码版本仍为0.6.5，本批记为未发布，不创建发行标签或修改生产环境。

## 已取得的验证证据

- PowerShell 7.6.9／Python3.12：备份、邮件、工作台与回退契约测试合计56通过、4明确跳过。跳过项为真实POSIX接收端／worker，不注入假的`fcntl`；活动和应用测试另外在Linux实验室执行。
- `vp lint`正确在`web`目录执行，修复4处无用数组展开后退出0；最终CI报告508条风格警告、0错误，不将其报告为零警告。
- `compileall`、所有部署／工具Shell语法、17个文档入口与版本一致性检查、Node消息桥5项通过。
- 最终本地前端73文件／474项全部通过（`vitest run --maxWorkers=4`），类型检查、lint与生产构建通过。未限并发的一次运行有单个worker启动超时，降低并发后全量通过；Linux CI默认并发也全部通过。lint仍含风格警告。
- 活动跨登录原编号核对／取消、未知取消保护、活动精确关联导航、同页最新深链接排队和问题工作台跨目标慢请求隔离均有回归用例；迟到响应不能恢复旧目标，未知写入不自动重放。
- 回退保护纯测试20项通过，新增6项真实MySQL最小读取权限用例也已通过；旧版本不能忽略活动绑定或抛下未决游戏备份请求。
- Chrome合成API最终验收覆盖7页面×2设备×2主题、28组页面矩阵，38张截图，210个合成API请求，无页面脚本异常或横向溢出。手机奖励空草稿进入物品页，目标摘要高28px；390×844首屏中搜索框y307–341、首物品y427–485、加入按钮y438–474，均完整可见。已有19金币草稿刷新后继续保留奖励页及自定义原因。

本地产物位于忽略目录`outputs/workspace-redesign-synthetic/`，包含`report.json`、README与PNG。合成截图采用缺失图标文字降级；没有真实玩家信息、生产连接、游戏写入、实际SSH跨主机复制或客户端领取验收。

## Linux集成与最终结论

隔离开发分支为 `development/workspace-redesign-20261109`，完整送测提交为 `0b080143b0fbf9034f318933d226fe956d1661ac`，源码树为 `6479311bd0936ece5f0dc093e642e83b185077d9`。本地119个改动文件与送测快照核对一致；此后只补充验收文档，不改变已测试的应用代码、迁移或测试。

[Actions运行42646356521](https://github.com/Wuse777/llnut-dnf-gm/actions/runs/42646356521)的两个任务均成功：

| 验证 | 实际结果 |
| --- | --- |
| [后端全仓回归](https://github.com/Wuse777/llnut-dnf-gm/actions/runs/42646356521/job/129260542827) | Ubuntu24.04、Python3.12.16、校验摘要固定的MySQL5.7.44 Unix-socket实验室；2324通过、0失败、0跳过，2条弃用警告，730.15秒 |
| [前端完整验证](https://github.com/Wuse777/llnut-dnf-gm/actions/runs/42646356521/job/129260541424) | 73文件／474项通过，lint、类型检查、生产构建及消息桥检查成功；lint含508条警告 |
| [JUnit原始证据](https://github.com/Wuse777/llnut-dnf-gm/actions/runs/42646356521/artifacts/13688302918) | 后端XML已上传，artifact编号13688302918，压缩文件43480字节；实验室MySQL已正常停止 |

全仓零跳过意味着本轮新增的7项真实MySQL备份测试、5项POSIX worker测试、3项POSIX receiver测试、6项最小读取权限回退测试，以及活动并发、同角色跨批次竞争和跨登录恢复用例均实际执行。备份覆盖混合InnoDB／MyISAM READ锁与释放、watchdog中断、受限恢复用户、百分号默认值／注释和库名样式字符串保真，以及实际age加密→接收校验→解密→隔离实库恢复；没有注入假的POSIX模块。

全量回归同时修正了4个既有权限测试的过期前提：等级维护早已按列授权`lev`，因此改为验证基础职业`job`及创建时间`create_time`仍禁止写入，保留资金、密码、审计、删除和DDL负权限检查，没有扩大数据库授权。

上述结果完成的是源码和隔离实验室验收。生产仍需按部署文档配置完整业务库、固定且处于独立故障域的SSH接收端、独立同版本演练实例，并按原维护协议停游戏、核验停写和开启窗口。此轮未执行生产部署、生产备份或真实跨主机复制；客户端领取、实际物品素材及现场故障恢复仍由对应环境验收。版本保持0.6.5未发布，远端main保持`f82a6d0311eaecf108b4df10f1f5e0f5dbb72ea8`。
