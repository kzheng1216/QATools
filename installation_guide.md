# QATools 安装与环境搭建指南

本文档描述如何从零搭建一套完整可运行的 **QATools (Zen)** 环境，包括 Python 后端、
Node.js + React 前端、配置文件初始化、启动/停止/排错，以及远程部署。

> **约定**：下文用 `$QATOOLS` 表示 QATools 项目根目录。
> 在 Roku 的 dev container 里通常是 `/workspaces/automation-ide/mycode/QATools`。

---

## 目录

1. [架构与端口总览](#1-架构与端口总览)
2. [环境依赖速查](#2-环境依赖速查)
3. [获取代码](#3-获取代码)
4. [方式 A：Dev Container 安装（推荐）](#4-方式-adev-container-安装推荐)
5. [方式 B：本机 / 裸机安装](#5-方式-b本机--裸机安装)
6. [Python 后端环境](#6-python-后端环境)
7. [Node.js + React 前端环境](#7-nodejs--react-前端环境)
8. [配置文件初始化](#8-配置文件初始化)
9. [启动、停止与状态检查](#9-启动停止与状态检查)
10. [安装验证 Checklist](#10-安装验证-checklist)
11. [远程部署](#11-远程部署)
12. [常见问题排查](#12-常见问题排查)
13. [附录：目录结构与配置文件速查](#13-附录目录结构与配置文件速查)

---

## 1. 架构与端口总览

```
┌─────────────────────────────┐        /api/*  (Vite 代理)
│  浏览器                      │ ───────────────────────────┐
│  http://<host>:9898         │                            │
└─────────────────────────────┘                            ▼
            ▲                                  ┌────────────────────────┐
            │ 静态资源 / HMR                     │  后端 FastAPI + uvicorn │
┌───────────┴─────────────────┐                │  0.0.0.0:9888          │
│  前端 Vite Dev Server        │                │  backend/app.py        │
│  React 18 + antd 5 + TS     │                └───────────┬────────────┘
│  0.0.0.0:9898               │                            │
└─────────────────────────────┘                            ▼
                                        ┌──────────────────────────────────┐
                                        │ QA Hub / TestRail / JIRA /       │
                                        │ Jenkins / AI Gateway / 测试设备    │
                                        └──────────────────────────────────┘
```

| 服务 | 端口 | 进程 | 配置位置 |
|------|------|------|----------|
| 后端 API | `9888` | `uvicorn app:app` | `backend/conf/config.yml` → `server_config` |
| 前端 Dev Server | `9898` | `npm run dev` (Vite) | `frontend/conf/config.yml` → `server` |
| File Transfer HTTP | `9000` | `python -m http.server`（按需手动启停） | `backend/conf/file_transfer_data.yml` |

> 前端通过 Vite 的 `/api` 代理转发到后端，**浏览器只需访问 9898**。
> 代理目标在 `frontend/vite.config.ts` 中默认是 `127.0.0.1:9888`。

---

## 2. 环境依赖速查

| 组件 | 最低版本 | 验证命令 | 备注 |
|------|---------|---------|------|
| Python | **3.10+**（推荐 3.13） | `python3 -V` | 代码用到 `datetime.UTC`（3.11+）、`X \| None` 类型语法 |
| pip | 23+ | `pip3 -V` | |
| Node.js | **20.19+ / 22.12+** | `node -v` | Vite 8 的硬性要求 |
| npm | 9+ | `npm -v` | 也可用 yarn |
| git | 2.x | `git --version` | |
| Linux 工具 | — | `which ssh scp sshpass rsync` | `sshpass`/`scp` 供 File Transfer 的 SCP 上传用 |

> ⚠️ **Python 3.10 注意**：`backend/controllers/activate_controller.py` 等用了
> `from datetime import UTC`（Python 3.11 新增）。在 3.10 上会 `ImportError`。
> **生产环境请使用 Python 3.11+，推荐 3.13**。

---

## 3. 获取代码

部分功能（Run-in-local 本地跑例）还需要 `automated_tests` 仓库，默认在
QATools 的上两级目录（由 `config/env.py` 的 `AUTOMATED_TESTS_RELATIVE_DIR =
"../../automated_tests"` 指定）：

---

## 4. 方式 A：Dev Container 安装（推荐）

Roku 的 `roku-automation-framework` 镜像已经内置 Python 3.13、Node.js 20、
`roku_api` 等内部包，是最省事的方式。

### 4.1 前置

- Docker Desktop / Docker Engine
- VS Code 或 Cursor + **Dev Containers** 扩展
- 已登录 Roku 的 Artifactory（能 pull 内部镜像）

### 4.2 配置 `.devcontainer.json`

在 `automation-ide` 工作区根目录（QATools 的上两级）放置 `.devcontainer.json`：

### 4.3 打开容器

VS Code / Cursor → `F1` → **Dev Containers: Reopen in Container**。

### 4.4 容器内首次安装

```bash
cd /workspaces/automation-ide/mycode/QATools

# Python 依赖（见第 6 章）
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt

# 前端依赖（见第 7 章）
cd frontend && npm install && cd ..

# 配置文件（见第 8 章）
cp config/env.py.example config/env.py
vi config/env.py        # 填入 token

# 启动
bash startup_qatools.sh
```

浏览器打开 <http://localhost:9898>。

---

## 5. 方式 B：本机 / 裸机安装

适用于 Ubuntu 22.04 / WSL2 / 实验室服务器。

### 5.1 系统包

```bash
sudo apt update
sudo apt install -y \
    python3 python3-venv python3-pip \
    git curl rsync \
    openssh-client sshpass        # File Transfer 的 SCP 上传需要
```

### 5.2 Python 3.13（若系统自带 < 3.11）

```bash
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.13 python3.13-venv python3.13-dev
python3.13 -V        # 应输出 Python 3.13.x
```

### 5.3 Node.js 20 LTS

推荐用 **nvm**，避免污染系统 Node：

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc

nvm install 20
nvm use 20
nvm alias default 20

node -v      # v20.19+
npm -v       # 9+
```

或用 NodeSource APT 源：

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

> ❗ Ubuntu 自带的 `apt install nodejs` 往往是 v12/v18，**不满足 Vite 8 的
> Node ≥ 20.19 要求**，启动时会报 `crypto.hash is not a function` 之类的错误。

### 5.4 `roku_api`（可选）

`5_activate/*.py` 的设备激活功能会 `import_module("roku_api.roku")`。
这是 Roku 内部包，**不在 PyPI 上**，只随 `roku-automation-framework` 镜像提供
（`/root/roku_automation`）。裸机环境若需要该功能：

```bash
# 把 roku_automation 仓库加入 PYTHONPATH
export PYTHONPATH="$PYTHONPATH:/path/to/roku_automation"
```

不需要激活功能的话可以忽略——其余模块不受影响。

---

## 6. Python 后端环境

### 6.1 创建虚拟环境

```bash
cd $QATOOLS

python3.13 -m venv backend/.venv       # 或 python3 -m venv backend/.venv
backend/.venv/bin/python -V
```

> 启动脚本 `backend/startup.sh` 会按以下顺序自动寻找带 uvicorn 的解释器：
> 1. `backend/.venv/bin/python`
> 2. `/root/.virtualenvs/docker-ra/bin/python`
> 3. `/home/qauser/bot_env/bin/python`
> 4. `python3` / `python`
>
> 所以把 venv 建在 `backend/.venv` 是最省心的做法。

### 6.2 安装依赖

```bash
backend/.venv/bin/pip install --upgrade pip
backend/.venv/bin/pip install -r backend/requirements.txt
```

`backend/requirements.txt` 覆盖了全仓（backend / config / 1_create_test_plan /
4_runcase / 5_activate）的所有第三方依赖：

| 分组 | 包 |
|------|-----|
| Web 框架 / ASGI | `fastapi==0.70.0`、`starlette==0.16.0`、`uvicorn==0.15.0`、`click`、`h11` |
| 数据模型 | `pydantic~=1.9`、`typing_extensions` |
| HTTP 客户端 | `httpx`、`httpcore`、`anyio`、`sniffio`、`certifi`、`requests`、`urllib3`、`idna`、`charset-normalizer` |
| 配置文件 | `pyyaml~=6.0` |
| 认证 | `bcrypt~=4.0` |

### 6.3 验证

```bash
backend/.venv/bin/python - <<'EOF'
import sys; sys.path[:0] = ["backend", "."]
import app
print("OK, routes =", len(app.app.routes))
EOF
```

期望输出类似 `OK, routes = 169`。

---

## 7. Node.js + React 前端环境

### 7.1 技术栈

| 库 | 版本 | 用途 |
|----|------|------|
| React | 18.3 | UI 框架 |
| antd | 5.29 | 组件库（CSS-in-JS，**无需** import css） |
| Vite | 8.3 | 构建 / Dev Server（要求 Node ≥ 20.19） |
| TypeScript | 5.5 | 类型 |
| @uiw/react-codemirror + @codemirror/* | 6.x | JSON/YAML 编辑器 |
| react-markdown + remark-gfm | — | AI 分析结果渲染 |

### 7.2 安装依赖

```bash
cd $QATOOLS/frontend
npm install            # 按 package-lock.json 精确安装
```

CI / 可复现构建建议用：

```bash
npm ci
```

> 也可以用 yarn（仓库里有 `yarn.lock`）：`npm i -g yarn && yarn install`。
> **不要混用** npm 和 yarn，否则两份 lock 文件会打架。

### 7.3 开发模式

```bash
npm run dev            # 等价于 vite，监听 0.0.0.0:9898
```

### 7.4 生产构建（可选）

```bash
npm run build          # tsc 类型检查 + vite build → dist/
npm run preview        # 本地预览产物
```

产物在 `frontend/dist/`，可以交给 nginx 之类的静态服务器托管
（此时需要自行配置 `/api` 反向代理到 9888）。

### 7.5 修改端口

编辑 `frontend/conf/config.yml`：

```yaml
server:
  host: "0.0.0.0"
  port: 9898        # 前端端口
backend:
  host: "127.0.0.1"
  port: 9888        # 代理目标（后端）
```

`vite.config.ts` 在启动时读取该文件，无需改代码。

---

## 8. 配置文件初始化

### 8.1 `config/env.py`（必须，含密钥，已 gitignore）

```bash
cd $QATOOLS
cp config/env.py.example config/env.py
```

编辑 `config/env.py` 填入：

| 变量 | 说明 | 获取方式 |
|------|------|---------|
| `QAHUB_TOKEN` | QA Hub API Token | QA Hub 个人设置页 |
| `EMAIL` | TestRail 登录邮箱 | 你的 Roku 邮箱 |
| `TESTRAIL_API_KEY` | TestRail API Key | TestRail → My Settings → API Keys |
| `JIRA_TOKEN` | JIRA API Token | Atlassian 账号设置 |

同时确认这两项目录配置（一般保持默认）：

```python
DATA_BASE_DIR = "data"                                # 生成数据的根目录
AUTOMATED_TESTS_RELATIVE_DIR = "../../automated_tests"  # automated_tests 仓库位置
```

> 🔒 `config/env.py` 已在 `.gitignore` 中，**绝不要提交**。
> 后端的 *Settings → Account Settings* 页面会原地改写这个文件里的赋值语句。

### 8.2 `backend/conf/` 下的数据文件

这些文件由后端通过 `backend/services/data_service.py` 读写。首次部署时
**仓库里已带有可用的默认版本**，一般无需手工创建。

| 文件 | 内容 | 说明 |
|------|------|------|
| `config.yml` | `server_config` + `data_files` | **引导文件**：定义后端监听地址，以及其余数据文件的文件名映射 |
| `tabs_data.yml` | `tabs` | 左侧导航各 Tab 的显示/隐藏与顺序 |
| `agent_data.yml` | `agent_config`、`agent_model` | AI 网关地址/密钥、可选模型列表 |
| `analyze_data.yml` | `analyze_config` | 日志分析的默认语言 + Prompt 模板 |
| `file_transfer_data.yml` | `file_transfer` | 共享目录、HTTP 端口、SCP 目标缓存、脚本运行历史 |
| `runcase_data.yml` | `runcase_user_query_list`、`roku_test_cache_data` | 用户名查询历史、Run-in-local 的输入历史 |
| `ref.yml` | `ref`、`docs` | Reference 页的链接与文档列表 |
| `testrail.yml` | `testrail.plan` | TestRail 计划列表 |
| `user.yml` | `users` | 用户清单 |

`config.yml` 示例：

```yaml
server_config:
  host: 0.0.0.0
  port: 9888
# 数据文件名映射；改名只需改这里，代码不用动
data_files:
  tabs: tabs_data.yml
  agent: agent_data.yml
  analyze: analyze_data.yml
  file_transfer: file_transfer_data.yml
  runcase: runcase_data.yml
  ref: ref.yml
  testrail: testrail.yml
  user: user.yml
```

> ⚠️ `data_files` 的 8 个键**缺一不可**，缺失会在启动时直接抛
> `DataServiceError`（刻意的硬失败，避免静默用错文件）。

### 8.3 AI 网关配置

编辑 `backend/conf/agent_data.yml`，或启动后在 *Settings → AI Model* 页面改：

```yaml
agent_config:
  base_url: https://ai-hub-lite.msc.rokulabs.net/v1
  api_key: sk-xxxxxxxx
  key_id: xxxxxxxx
  key_alias: <your-alias>
  model: claude-haiku-5-5
  timeout_sec: 300.0
  max_tokens: 128000
  temperature: 1.0
```

### 8.4 环境变量覆盖（可选）

`backend/conf/config.py` 支持用环境变量覆盖 yaml 值，便于容器化部署：

| 环境变量 | 覆盖项 |
|---------|-------|
| `QATOOLS_SERVER_HOST` / `QATOOLS_SERVER_PORT` | `server_config.*` |
| `QATOOLS_AGENT_BASE_URL` | `agent_config.base_url` |
| `QATOOLS_AGENT_API_KEY` | `agent_config.api_key` |
| `QATOOLS_AGENT_KEY_ID` / `QATOOLS_AGENT_KEY_ALIAS` | `agent_config.*` |
| `QATOOLS_AGENT_MODEL` | `agent_config.model` |
| `QATOOLS_AGENT_TIMEOUT_SEC` / `_MAX_TOKENS` / `_TEMPERATURE` | `agent_config.*` |
| `QATOOLS_AGENT_CONFIG_PATH` | 指向另一个 `config.yml`（同目录下找其余数据文件） |

### 8.5 设备与 Profile 配置

| 路径 | 用途 |
|------|------|
| `config/device_conf/*.json` | 被测设备定义（IP、序列号、电源、HDMI 等）。`d_*.json` 已 gitignore |
| `config/activate_account.yml` | 国家码 → 激活账号邮箱映射 |
| `4_runcase/profiles/*.json` | 跑例 Profile（`p*.json` / `kz*.json` / `opm*.json` 已 gitignore） |

### 8.6 数据目录

首次启动会按需自动创建 `data/` 下的子目录，无需手工建：

```
data/
├── agent_session/      AI 会话
├── analyzer_history/   日志分析历史
├── cmd/                Run Script 的脚本
├── device_info/        设备信息缓存
├── docs/               Reference 上传的 Markdown
├── file_transfer/      文件传输共享根目录
├── roku_test_log/      Run-in-local 日志
├── runcase_report/     跑例报告与缓存
├── skill_data/         AI Skill
└── testrail_data/      TestRail 缓存
```

---

## 9. 启动、停止与状态检查

### 9.1 一键启停（推荐）

```bash
cd $QATOOLS

bash startup_qatools.sh     # 启动前后端
bash shutdown_qatools.sh    # 停止前后端
bash restart_qatools.sh     # 重启
```

### 9.2 单独控制

```bash
# 后端
cd $QATOOLS/backend
./startup.sh      # nohup uvicorn app:app --host 0.0.0.0 --port 9888
./shutdown.sh     # 最多重试 3 次 kill -9
./restart.sh
./status.sh       # 查看 uvicorn 进程与 PID

# 前端
cd $QATOOLS/frontend
./startup.sh      # 首次会自动 npm install，然后 nohup npm run dev
./shutdown.sh
./restart.sh
./status.sh
```

> 后端也可以在 *Settings → 页面底部* 点 **Restart Backend** 按钮重启
> （内部调用 `backend/restart.sh`，以 detached 方式执行，HTTP 响应能先返回）。

### 9.3 日志

| 服务 | 日志 | 轮转策略 |
|------|------|---------|
| 后端 | `backend/logs/backend.log` | `TimedRotatingFileHandler`，按天切为 `backend.log.<date>`，保留 7 天 |
| 前端 | `frontend/logs/frontend.<YYYY-MM-DD>.log` | `startup.sh` 自己清理，保留最近 7 个 |
| 跑例 | `4_runcase/logs/`、`4_runcase/profile_logs/` | — |

```bash
tail -f $QATOOLS/backend/logs/backend.log
tail -f $QATOOLS/frontend/logs/frontend.$(date +%F).log
```

---

## 10. 安装验证 Checklist

逐条执行，全部通过即表示环境就绪。

```bash
cd $QATOOLS

# 1) 版本
python3 -V                       # ≥ 3.11（推荐 3.13）
node -v                          # ≥ v20.19
npm -v

# 2) Python 依赖齐备
backend/.venv/bin/python -c "import fastapi, uvicorn, pydantic, httpx, yaml, requests, bcrypt; print('deps OK')"

# 3) 配置可加载
backend/.venv/bin/python -c "
import sys; sys.path[:0]=['backend','.']
from conf.config import config
print('config OK:', config.host, config.port, config.model)"

# 4) 应用可导入
backend/.venv/bin/python -c "
import sys; sys.path[:0]=['backend','.']
import app; print('app OK, routes =', len(app.app.routes))"

# 5) 前端依赖
ls frontend/node_modules >/dev/null && echo "node_modules OK"

# 6) 启动
bash startup_qatools.sh
sleep 8

# 7) 进程
backend/status.sh
frontend/status.sh

# 8) 后端接口
curl -s -o /dev/null -w "tabs       %{http_code}\n" localhost:9888/v1/config/tabs/list
curl -s -o /dev/null -w "models     %{http_code}\n" localhost:9888/v1/agent/models
curl -s -o /dev/null -w "reference  %{http_code}\n" localhost:9888/v1/reference/list
curl -s -o /dev/null -w "testrail   %{http_code}\n" localhost:9888/v1/testrail/plan/list
curl -s -o /dev/null -w "dashboard  %{http_code}\n" localhost:9888/v1/dashboard/summary
curl -s -o /dev/null -w "openapi    %{http_code}\n" localhost:9888/openapi.json

# 9) 前端
curl -s -o /dev/null -w "frontend   %{http_code}\n" localhost:9898
```

全部返回 `200` 后，浏览器打开：

- 前端 UI：<http://localhost:9898>
- 后端 Swagger：<http://localhost:9888/docs>
- 后端 ReDoc：<http://localhost:9888/redoc>

默认管理员账号（用于 Settings 页面解锁）：

| 用户名 | 密码 |
|--------|------|
| `admin` | `Zaq1@wsx` |

> 口令以 bcrypt 哈希形式存在 `config/env.py` 的 `ADMIN_HASHED_PASSWORD`。
> **生产环境请务必修改**：用 `bcrypt.hashpw(b"<new>", ADMIN_AUTH_SALT)` 生成新哈希替换。

---

## 11. 远程部署

`remote_deploy.sh` 用 rsync over ssh 把整个 QATools 同步到远端，并自动重启服务。

### 11.1 部署到主机目录

```bash
cd $QATOOLS
./remote_deploy.sh qauser@10.64.16.16 /home/qauser/QATools
# 带密码（否则走 ssh key / agent / 交互输入）
./remote_deploy.sh qauser@10.64.16.16 /home/qauser/QATools '<password>'
```

### 11.2 部署到远端容器内

```bash
# 按容器名
./remote_deploy.sh -c automation-ide \
    qauser@10.64.16.16 /workspaces/automation-ide/mycode/QATools '<password>'

# 按镜像引用（自动解析为运行中的容器）
./remote_deploy.sh -c eswat-docker-dev-local.artifactory.tools.roku.com/roku-automation-framework:latest \
    qauser@10.64.16.16 /workspaces/automation-ide/mycode/QATools '<password>'
```

容器模式下 `<remote_root_dir>` 是**容器内**的路径。若该路径来自 bind mount，
文件会直接 rsync 到宿主机侧（快，无需 `docker cp`）；否则先暂存到宿主 `/tmp`
再 `docker cp` 进去。

仓库里另有两个固化目标的便捷脚本：`remote_deploy_qabot1616.sh`、
`remote_deploy_qabot26234.sh`。

> 📌 部署会跳过 VCS/构建/运行时产物（`.git`、`node_modules`、`.venv`、`__pycache__`、
> `logs` 等）。**远端首次部署后仍需手工建 venv、`npm install` 并准备 `config/env.py`。**

---

## 12. 常见问题排查

### 12.1 后端起不来

**`ERROR: no Python with uvicorn found`**
`startup.sh` 没找到装了 uvicorn 的解释器。确认 venv 建在 `backend/.venv`
且已装依赖：
```bash
backend/.venv/bin/pip install -r backend/requirements.txt
```

**`ImportError: cannot import name 'UTC' from 'datetime'`**
Python < 3.11。升级到 3.11+（见 5.2）。

**`DataServiceError: ... 'data_files' is missing a file name for: xxx`**
`backend/conf/config.yml` 的 `data_files` 缺键。按 8.2 的示例补齐 8 个键。

**`ConfigError: configuration is incomplete`**
`agent_data.yml` 的 `agent_config` 缺必填项（`base_url` / `api_key` / `key_id` /
`key_alias` / `model` / `timeout_sec` / `max_tokens` / `temperature`）。
补齐，或用 8.4 的环境变量提供。

**端口 9888 被占用**
```bash
ss -lptn 'sport = :9888'     # 或 lsof -i:9888
backend/shutdown.sh          # 先正常停
```

### 12.2 前端起不来

**`crypto.hash is not a function` / Vite 报 Node 版本错**
Node 版本太低。Vite 8 需要 Node ≥ 20.19 或 ≥ 22.12：
```bash
nvm install 20 && nvm use 20
```

**`npm install` 依赖冲突**
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
# 仍失败可临时：
npm install --legacy-peer-deps
```

**日志出现 `Port 9898 is in use, trying another one...`**
Vite 发现端口被占用会**自动顺延到 9899/9900...**，此时浏览器要访问新端口。
先看日志确认实际端口：
```bash
tail -5 frontend/logs/frontend.$(date +%F).log
```
常见占用者是 VS Code / Cursor 的**端口转发进程**（远程开发时会主动监听
`127.0.0.1:9898`），以及上一次没退干净的 Vite：
```bash
ss -lptn 'sport = :9898'     # 看谁占着
frontend/shutdown.sh         # 先正常停
```
若想固定端口，改 `frontend/conf/config.yml` 的 `server.port` 换一个没人用的。

**页面空白 / 接口 404**
确认后端在跑、且 `frontend/conf/config.yml` 的 `backend.host/port` 指向正确。
前端所有请求走 `/api` 前缀，由 Vite 代理 rewrite 掉前缀后转给后端。

**antd 样式不生效**
antd v5 是 CSS-in-JS，**不需要** `import 'antd/dist/antd.css'`；写了反而冲突。

### 12.3 功能相关

**Settings 页面打不开**
需要先用 admin 账号登录（见第 10 章）。

**File Transfer 的 SCP 上传失败**
远端/本地缺 `sshpass` 或 `scp`：
```bash
sudo apt install -y sshpass openssh-client
```

**设备激活功能报 `ModuleNotFoundError: roku_api`**
`roku_api` 是 Roku 内部包，只在 dev container 镜像里。见 5.4。

**Run-in-local 找不到测试代码**
检查 `config/env.py` 的 `AUTOMATED_TESTS_RELATIVE_DIR` 是否指向真实的
`automated_tests` 仓库（相对于 `$QATOOLS`）。

### 12.4 配置文件权限

在 dev container 内，后端以 root 运行并会改写 `config/env.py`、
`backend/conf/*.yml`。若你在容器**外**（如 WSL 宿主）以普通用户编辑这些文件，
可能遇到 `Permission denied`：

```bash
sudo chown -R $(id -u):$(id -g) config/env.py backend/conf/
# 或直接在容器内编辑
docker exec -it <container> bash
```

---

## 13. 附录：目录结构与配置文件速查

### 13.1 目录结构

```
QATools/
├── backend/                    FastAPI 后端
│   ├── app.py                  应用入口（CORS + 路由注册）
│   ├── requirements.txt        Python 依赖（覆盖全仓）
│   ├── startup.sh / shutdown.sh / restart.sh / status.sh
│   ├── conf/                   配置与数据文件
│   │   ├── config.py           配置加载（yaml + 环境变量）
│   │   ├── config.yml          引导文件：server_config + data_files
│   │   └── *_data.yml, ref.yml, testrail.yml, user.yml
│   ├── controllers/            各 Tab 对应的 REST 控制器
│   ├── services/
│   │   ├── data_service.py     数据访问层（基类 / YAML 实现 / DB 实现占位）
│   │   └── agent_service.py    AI 会话服务
│   ├── aiutil/                 AI 网关与 JIRA 客户端
│   └── logs/                   后端日志
├── frontend/                   React + Vite 前端
│   ├── package.json
│   ├── vite.config.ts          读 conf/config.yml 决定端口与 /api 代理
│   ├── conf/config.yml         前端端口 + 后端代理目标
│   ├── src/
│   │   ├── api/client.ts       所有后端接口的 TS 封装
│   │   └── pages/              各 Tab 页面
│   └── logs/
├── config/                     全局配置
│   ├── env.py                  ⚠️ 密钥与路径（gitignore，从 .example 复制）
│   ├── env.py.example
│   ├── log.py                  日志工具
│   ├── activate_account.yml    国家码 → 激活账号
│   └── device_conf/*.json      设备定义
├── data/                       运行期生成的数据（自动创建）
├── 1_create_test_plan/         TestRail 批量加例脚本
├── 4_runcase/                  QA Hub 跑例引擎 + profiles
├── 5_activate/                 设备恢复出厂 + 账号激活
├── 80_tools/                   杂项工具
├── docs/                       用户手册 / 功能文档
├── startup_qatools.sh / shutdown_qatools.sh / restart_qatools.sh
└── remote_deploy*.sh           远程部署
```

### 13.2 关键文件一览

| 文件 | 要不要手工建 | 说明 |
|------|------------|------|
| `config/env.py` | ✅ **必须**（从 `.example` 复制） | 密钥、目录配置。gitignore |
| `backend/conf/config.yml` | ❌ 仓库自带 | 引导文件，含 `data_files` 映射 |
| `backend/conf/*_data.yml` | ❌ 仓库自带 | 各 Tab 的数据，UI 可改 |
| `frontend/conf/config.yml` | ❌ 仓库自带 | 前端端口 + 代理目标 |
| `backend/.venv/` | ✅ **必须** | `python3 -m venv backend/.venv` |
| `frontend/node_modules/` | ✅ **必须** | `npm install` |
| `data/**` | ❌ 自动创建 | 运行期数据 |
| `config/device_conf/d_*.json` | 按需 | 设备定义，gitignore |
| `4_runcase/profiles/p*.json` | 按需 | 跑例 Profile，gitignore |

### 13.3 极简安装（TL;DR）

```bash
git clone git@gitlab.eng.roku.com:yuzheng/qatools.git QATools && cd QATools

python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt

cd frontend && npm install && cd ..

cp config/env.py.example config/env.py && vi config/env.py   # 填 token

bash startup_qatools.sh
# → http://localhost:9898
```