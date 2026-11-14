# 完整在线预览部署

本项目是 Flask + Waitress + SQLite 应用，需要运行后端服务；GitHub Pages 不能承载完整的登录、协作与数据库功能。

## 容器方式

仓库提供 Dockerfile，默认使用 8774 端口，并以非 root 用户运行：

```sh
docker build -t taskflow .
docker volume create taskflow-data
docker run --name taskflow --restart unless-stopped \
  -p 127.0.0.1:8774:8774 \
  -v taskflow-data:/data \
  -e TASKFLOW_SECURE_COOKIE=1 \
  -e TASKFLOW_TRUST_PROXY=1 \
  -e TASKFLOW_PUBLIC_PREVIEW=1 \
  -e TASKFLOW_PREVIEW_HOST=your-domain.example \
  -d taskflow
```

将 `your-domain.example` 替换为实际域名，并将 HTTPS 反向代理指向服务器本地 8774 端口。公网地址由实际部署平台或域名产生；未部署时，不应将 localhost 或预设域名当作在线地址。

当前默认提供交互开场和免注册的独立案例体验。持久化 `/data` 以保留账号、项目、会话与附件。停止服务后备份数据卷；不要将实际数据库、账号密码或模型密钥提交到 GitHub。

## Render GitHub 自动部署

已提供 `render.yaml` Blueprint，选择免费预览 Web Service，并监听 Git 提交自动部署。

从 [Render 部署入口](https://render.com/deploy?repo=https://github.com/y60715810-del/bohack-renovation-taskflow) 登录并确认创建服务。创建成功后，Render 控制台显示真实网页地址。

**免费预览仅适用于合成数据：数据库位于容器本地，重部署后会重置。不要上传真实项目资料。** 正式使用如需持久化磁盘，应由用户另行选择相应服务套餐并挂载 `/data`。

手动配置服务时：

1. 连接此 GitHub 仓库的 `main` 分支，新建 Docker Web Service。
2. 按 Dockerfile 运行，将服务端口配置为 8774。
3. 若需要跨重启保留数据，挂载持久化磁盘到 `/data`；具体套餐与费用由用户确认。没有持久化磁盘的临时预览可能在重新部署后丢失数据。
4. HTTPS 入口设置 `TASKFLOW_SECURE_COOKIE=1`；健康检查路径为 `/api/health`。
5. 首次部署成功后，访问平台实际生成的 HTTPS 地址，验证开场、四种身份、排程、照片和任务流程，再开启 `main` 分支的自动部署。

无需模型密钥即可使用规则模式；可选模型变量应通过部署平台的安全设置配置。

GitHub Actions 会检查 Python 测试和前端语法。Actions 状态、部署成功及生成的域名必须实际确认；推送代码本身不等于部署成功。

在带 HTTPS 检查代理的构建环境中，可用 BuildKit 的 `--secret id=pip_ca,src=/etc/ssl/certs/ca-certificates.crt` 临时提供可信 CA。证书只用于构建，不写入镜像，也不关闭 TLS 验证；普通 Render 构建不需要该参数。

Render 的 HTTPS 反向代理需要 `TASKFLOW_TRUST_PROXY=1`，Blueprint 已设置。该选项只用于流量经过可信反向代理的服务；普通本机运行保持关闭。它使 HTTPS 来源检查及安全 Cookie 正常工作，不启用快捷演示登录。


## 当前的直接体验入口

默认本机启动使用 `127.0.0.1:8774`，并开启浏览器独立的案例体验。Windows 的 `start.cmd` 已设置厨房案例及本地数据目录，开场后可选择任意身份，无需账号注册。

Render Blueprint 已设置 `TASKFLOW_PUBLIC_PREVIEW=1`、`TASKFLOW_DEMO_ACCESS=1`、`TASKFLOW_KITCHEN_DEMO=1`。服务读取 Render 自动注入的 `RENDER_EXTERNAL_HOSTNAME` 校验访问域名与 HTTPS；没有有效域名时会拒绝启动公开预览。原有 `TASKFLOW_PUBLIC_DEMO_HOST` 的本机代理模式继续保留。

公开体验沿用浏览器案例隔离与四方角色权限，不开放注册、账号登录或公开项目邀请接口。每位访客选择身份后，仅访问自己浏览器创建的合成案例；原有账号接口及权限测试仍保留。
