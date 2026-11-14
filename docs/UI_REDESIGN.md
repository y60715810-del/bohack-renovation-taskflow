# 蓝白界面与协作演示

本次按 UI/UX Pro Max 的信息层级、留白、可读性和减少动态效果建议统一界面。用户指定蓝白配色；不采用检索结果中默认的暖灰金配色或滚动叙事效果。Lusano 首页在当前环境被网络白名单拦截（403），因此没有声称逐项复刻其实际页面。

## 设计约束

- 白色入口、深蓝文字、雾蓝辅助色；无背景网格、漂浮装饰、渐变卡片。
- 首页标题与材质图形成视觉焦点，登录注册入口直接可见。工作区保持原有路由、权限、表单和业务入口，统一阅读间距及控件状态。
- `static/images/material-study.webp` 是生成的材质示意图（浅蓝陶砖、洞石、木纹），不是项目施工证据；页面有明确标注。图片与字体均无需外部服务。
- `static/design.css` 是统一视觉层，`static/app.css` 保留基础布局与业务组件样式，已删除原先重复的主题覆盖层。

## Swarm Rebuild

真实接入 `swarm-rebuild@0.2.4` 的官方 ESM 构建，零运行时依赖。代码与 MIT 许可保存在 `static/vendor/swarm-rebuild/`。npm 下载包的 SHA-512 已按 registry integrity 核验：

```
sha512-qktBNuvOn3mWNv2ZMwJ4sZe/tfaqFOiCIVYU56VKAu3GRFCfmTud0w2mScjJXF5Ofyj/8oyyQLsgs3diColNKA==
```

来源：https://github.com/MaximeBoulle/Swarm-Rebuild

入口「了解四方如何协作」先显示静态、可阅读的流程；用户主动点击「播放协作构建」才运行重建动画。彩色光标被限制为单色，关闭或完成后销毁动效；不自动滚动、不覆盖实际登录或审批页面。系统启用 `prefers-reduced-motion` 时不显示播放入口。关闭弹窗会释放 iframe 并将焦点还给入口。

动效运行在同源的独立示意页面。只有 `/static/collaboration-scene.html` 使用 `SAMEORIGIN` 与 `frame-ancestors 'self'`；此页禁用网络连接与表单提交，为动效引擎的样式注入允许内联样式。主应用继续禁止嵌入，且未放宽其 CSP。

## 验证

自动测试：

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
node --check static/motion.js
node --check static/collaboration-scene.js
```

29 项测试，包括原有 28 项业务/权限测试和新增的动效页面安全头隔离测试。

浏览器回归脚本使用 Playwright 和系统 Chromium。**只能对临时测试数据库运行**：脚本会注册合成账号、创建项目及邀请码，另会创建独立演示案例。不要指向实际项目数据库。

两个独立终端分别启动普通测试服务和演示测试服务（两者均使用临时目录）：

```sh
TASKFLOW_HOST=127.0.0.1 TASKFLOW_PORT=18774 TASKFLOW_DATA_DIR=/tmp/taskflow-ui-normal .venv/bin/python server.py
```

```sh
TASKFLOW_HOST=127.0.0.1 TASKFLOW_PORT=18775 TASKFLOW_DATA_DIR=/tmp/taskflow-ui-demo TASKFLOW_DEMO_ACCESS=1 TASKFLOW_KITCHEN_DEMO=1 .venv/bin/python server.py
```

再运行（运行环境的 Python 需要已有 Playwright，Chromium 路径为 `/usr/bin/chromium`）：

```sh
python3 tests/ui_smoke.py --app-url http://127.0.0.1:18774 --demo-url http://127.0.0.1:18775 --artifacts-dir /tmp/taskflow-ui-artifacts
```

覆盖登录/注册切换、实际注册、创建项目、生成邀请、退出与重新登录、四种身份与六个工作区页面、375/768/1440 像素布局、Swarm 真实加载、播放中关闭、焦点恢复、Escape 和减少动态效果。测试同时收集前端异常，截图写入指定目录。

此外，修复了已有前端的模板字符串语法错误、`isApproved` 缺失、邀请下拉框未闭合、排程表单多余闭合标签，以及无待上传任务时访问不存在属性的问题。业务审批规则与后端功能保持原样。
