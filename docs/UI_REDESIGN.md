# 共序·港乡：保留原产品，只增加黑白开场与角色目录

## 本次还原的基准

以仓库 `b6af43d`（新增暖棕/蓝白主题之前）的前端作为原产品基准。两个参考站点在云环境仍返回网络策略 403，因此不声称已逐项查看实时网站。

恢复原版角色页面、组件布局和全部业务表单。默认访问不再强制设置 `state.roadshow=true`，不再把原来的角色产品替换为六个入口的完整工作台。

- 住户：原来的「我的装修」，发起变更、住户确认及原有照片/记录。
- 设计师：原来的「设计确认」与专业确认表单。
- 施工团队：原来的「施工确认」、材料变更和现场照片上传。
- 中介方：原来的成员与邀请页面。
- 原有显式 `?show=1` 路演模式仍按原逻辑提供总览、排程、协商、任务、成员与记录，不改变其跳转方式。

原版 `api`、`post`、`busy`、`setProject`、`field`、`collaborationPage`、`changesPage`、`tasksPage`、`membersPage`、`schedulePage`、`enterDemo`、`bindDemoRoles`、`bind`、`bindSchedule` 和 `boot` 已核对与基准一致（仅产品名统一为「共序·港乡」）。本次没有修改服务器、业务规则或数据库。

## 仅新增的界面层

1. 一个可跳过的黑白开场，目录内选择身份即调用原有角色切换。
2. 页面内紧凑的「目录」替代原身份切换控件的外观；仍调用原来的 `bindDemoRoles` / `enterDemo`。可返回开场，不清空项目和进度。
3. 原版组件 CSS 保留尺寸、排列及断点，仅将颜色改为黑白灰，去除彩色渐变。仅对原成员列表的长 ID 增加换行，防止手机溢出。
4. 开场材质图灰度显示。真实施工照片保留原色，避免改变人工核对的证据。

UI/UX Pro Max 用于检查视觉层级、可读性、键盘操作和减少动态效果；没有用检索建议替换原产品结构。

## Swarm Rebuild

继续使用官方 `swarm-rebuild@0.2.4` ESM 构建及 MIT 许可，位于 `static/vendor/swarm-rebuild/`。仅「播放协作开场」中的主动播放使用动效；单色呈现、不自动滚动、不覆盖业务操作，关闭和完成后销毁。启用减少动态效果时显示静态说明。

npm 包的 SHA-512 已核验：

```
sha512-qktBNuvOn3mWNv2ZMwJ4sZe/tfaqFOiCIVYU56VKAu3GRFCfmTud0w2mScjJXF5Ofyj/8oyyQLsgs3diColNKA==
```

同源示意页的专用 CSP 保留，主应用安全策略不变。

## 验证

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
node --check static/motion.js
node --check static/collaboration-scene.js
```

浏览器回归必须使用临时数据库，会创建合成案例、确认变更并上传测试照片：

```sh
TASKFLOW_HOST=127.0.0.1 TASKFLOW_PORT=18777 TASKFLOW_KITCHEN_DEMO=1 TASKFLOW_DATA_DIR=/tmp/gangxiang-ui-check .venv/bin/python server.py
```

另一终端（需已安装 Playwright 和 `/usr/bin/chromium`）：

```sh
python3 tests/ui_smoke.py --app-url http://127.0.0.1:18777 --artifacts-dir /tmp/gangxiang-ui-artifacts
```

覆盖原版四种角色页面、默认模式没有被强制切换、住户发起变更 → 设计与施工确认 → 住户同意 → 施工方上传照片的实际操作、原显式路演模式的六个页面，以及目录、返回开场、375/768/1440 布局、动效、Escape、焦点恢复和减少动态效果。

下载新版必须先关闭旧启动窗口、完整解压 ZIP，再运行 `start.cmd`，避免继续看到旧进程提供的页面。
