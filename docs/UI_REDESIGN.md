# 共序·港乡：直接体验与交互开场

默认入口改为交互开场，不再出现登录注册表单。产品名、页面标题、共享协议单和启动提示统一为「共序·港乡」。按 UI/UX Pro Max 的层级、留白、可读性和减少动态效果建议保持蓝白视觉。

## 开场与产品功能

- 可点击「需求、方案、共识、交付」四个步骤查看说明；不是自动轮播，不阻止进入产品。
- 可先选项目经理、住户、设计师或施工团队；首次选择非经理身份时，后台自动准备同一份四方案例，不要求用户先注册经理账号。
- 点击「进入协作现场」或「跳过开场，直接进入」进入原有产品工作区；四种身份和项目总览、排程、协商、施工照片、成员、记录入口保持可用。
- 刷新沿用已有浏览器的身份与案例；「返回开场」回到身份选择，不删除案例。
- 本地材质图为生成示意，页面标注「非项目现场」，不得作为施工照片证据。
- 两个外部参考站点在当前环境均被网络策略拦截（403）；实现基于用户给出的简洁交互、蓝白材质和保留功能要求，未声称逐项复刻原站。

## Swarm Rebuild

真实使用 `swarm-rebuild@0.2.4` 官方 ESM 构建。仅在用户主动打开协作说明并点击播放后运行，光标限制为单色。动效在独立同源示意页面内运行，不覆盖实际业务页面。关闭或播放完成后销毁；系统要求减少动态效果时只显示静态说明。

代码与 MIT 许可在 `static/vendor/swarm-rebuild/`；来自 https://github.com/MaximeBoulle/Swarm-Rebuild 。下载包已核验 npm SHA-512：

```
sha512-qktBNuvOn3mWNv2ZMwJ4sZe/tfaqFOiCIVYU56VKAu3GRFCfmTud0w2mScjJXF5Ofyj/8oyyQLsgs3diColNKA==
```

只有 `/static/collaboration-scene.html` 允许同源嵌入与引擎所需的内联样式；该示意页禁止网络连接、表单和非同源嵌入，主应用 CSP 保持严格。

## 验证

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
node --check static/motion.js
node --check static/collaboration-scene.js
```

现有业务规则、权限、版本冲突、任务、照片与验收测试保持运行。新增测试覆盖公开直接体验的 HTTPS/域名校验、禁用账号入口及浏览器案例隔离。

实际浏览器回归需要已有 Playwright 和 `/usr/bin/chromium`，必须对临时数据目录运行：

```sh
TASKFLOW_HOST=127.0.0.1 TASKFLOW_PORT=18777 TASKFLOW_DEMO_ACCESS=1 TASKFLOW_KITCHEN_DEMO=1 TASKFLOW_DATA_DIR=/tmp/gangxiang-ui-check .venv/bin/python server.py
```

另一个终端执行：

```sh
python3 tests/ui_smoke.py --app-url http://127.0.0.1:18777 --artifacts-dir /tmp/gangxiang-ui-artifacts
```

覆盖四个开场步骤、无密码表单、住户先进入、四种身份共用一个案例、六个业务页、375/768/1440 宽度、Swarm 加载与关闭、焦点恢复、Escape、减少动态效果、刷新、返回开场及不同浏览器的案例隔离。截图保存在指定目录。脚本会创建合成案例，不要指向实际业务数据。

Windows 启动脚本已检查完整解压的 `requirements.txt`，避免只从 ZIP 内启动而缺少依赖清单。Linux 和容器的真实启动已独立验证；Windows 脚本需在 Windows 上执行。
