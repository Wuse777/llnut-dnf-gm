# 文档中心

[项目首页](../README.md) · [界面导览](SCREENSHOTS.md) · [部署指南](DEPLOYMENT.md) · [版本说明](releases/v0.6.5.md)

先按你的任务选择指南。**首页与本指南描述当前源码；历史报告只证明对应日期和版本的检查，不代表新安装自动具备生产配置。**

## 安装与开始使用

| 文档 | 适合何时阅读 |
| --- | --- |
| [安装、升级与回滚](DEPLOYMENT.md) | 已有游戏服务器，安装或更新 GM |
| [兼容性与配置](COMPATIBILITY.md) | 核对镜像、PVF、MySQL、中文编码与在线行为 |
| [界面导览](SCREENSHOTS.md) | 了解桌面／手机操作及合成截图 |
| [开发指南](DEVELOPMENT.md) | 构建前后端、运行隔离环境、修改代码 |
| [安全策略](../SECURITY.md) | 凭据、最小权限、公网访问与漏洞报告 |

## 玩家与奖励

- [玩家中心／角色详情](PLAYER-CENTER.md)、[账号名单与批量奖励](ACCOUNT-LIST-REWARDS.md)
- [物品展示与策略](ITEM-PRESENTATION.md)、[定时运营](SCHEDULES.md)
- [原生在线监控与控制](NATIVE-MONITOR.md)、[玩家问题工作台](SUPPORT-DESK.md)、[经济与发放统计](ECONOMY.md)
- [定向系统消息桥](PRIVATE-MESSAGE.md)：源码与受控安装流程，本批按用户安排暂不启用

[角色外观与默认站姿](CHARACTER-APPEARANCE.md)说明私有图层配方、默认预览与实际装扮的区别。

## 角色与装备维护

这些指南涉及存档写入；先阅读[网页维护中心](WEB-MAINTENANCE.md)。

- [装备编辑及附魔检索](EQUIPMENT-EDITOR.md)、[存档维护协议](INVENTORY-MAINTENANCE.md)
- [角色疲劳](CHARACTER-MAINTENANCE.md)、[等级／经验](CHARACTER-PROGRESSION.md)、[转职／觉醒](CHARACTER-PROFESSION.md)
- [SP／TP](CHARACTER-SKILLS.md)、[PvE 技能重置](CHARACTER-SKILL-RESET.md)
- [角色改名](CHARACTER-RENAME.md)、[位置救援](CHARACTER-RESCUE.md)、[任务检索与修复](CHARACTER-QUESTS.md)
- [维护中断恢复](MAINTENANCE-RECOVERY.md)、[写入准入](WRITE-ADMISSION.md)

## 运维、安全与素材

- [网页功能开关](CAPABILITIES.md)、[插件证据与边界](PLUGIN-DIAGNOSTICS.md)
- [告警](ALERTS.md)、[管理库备份及恢复证据](BACKUP-HEALTH.md)、[游戏恢复点、异地副本与隔离演练](GAME-BACKUP-DESIGN.md)（当前开发源码，未生产部署）
- [任务健康](TASK-HEALTH.md)、[升级检查](UPGRADE-CHECK.md)、[旧发布目录清理](RELEASE-CLEANUP.md)
- [私有素材提取与图片包](ASSETS.md)：仓库不含游戏图片，缺少素材仍可使用文字／占位视图

## 开发、发布与证据

- [开发](DEVELOPMENT.md)、[测试与验收](TESTING.md)、[贡献](../CONTRIBUTING.md)、[第三方声明](../THIRD_PARTY.md)
- [v0.6.5 发布说明](releases/v0.6.5.md)、[发布流程](RELEASING.md)、[更新记录](../CHANGELOG.md)
- [实施台账](ROADMAP-IMPLEMENTATION.md)、[历史报告](reports/)、[旧部署批次记录](history/DEPLOYMENT-BATCHES-202610-20261106.md)
- [文档维护约定及参考项目](DOCUMENTATION.md)

遇到故障先按[部署排查表](DEPLOYMENT.md#常见问题)查看健康状态；不要通过重复提交奖励、直接改数据库或重启共享 Docker 来试错。

## 新工作台

[工作台与偏好](UI-WORKSPACE.md) · [v0.6.5 发布说明](releases/v0.6.5.md) · [界面偏好接口](UI-PREFERENCES.md)
