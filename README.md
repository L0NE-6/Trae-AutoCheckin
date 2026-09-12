<div align="center">

# 🤖 Trae AutoCheckin

**Trae 每日自动签到 & 积分监控 · 零依赖 · 多账号 · 企业微信推送**

[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-none-success)](.)
[![Platform](https://img.shields.io/badge/platform-青龙%20%7C%20本地%20%7C%20Actions-blue)](.)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Stars](https://img.shields.io/github/stars/L0NE-6/Trae-AutoCheckin?style=social)](https://github.com/L0NE-6/Trae-AutoCheckin)

[✨ 特性](#-特性) · [🔑 获取 Token](#-获取-refreshtoken新手必看) · [🚀 快速开始](#-快速开始) · [⚙️ 配置](#️-环境变量) · [🧠 原理](#-工作原理) · [❓ FAQ](#-常见问题)

</div>

---

## 📖 简介

**Trae AutoCheckin** 是一套用于 Trae 的积分自动化工具，包含 4 个独立脚本：

| 脚本 | 作用 |
| :--- | :--- |
| `trae_auto_checkin.py` | 🎯 每日自动签到，领取签到积分 |
| `trae_credit_monitor.py` | 📊 只读查询积分「已用 / 剩余」，绝不签到 |
| `trae_sms_login.py` | 📲 手机号 + 短信验证码登录，直接换取 Token（免客户端） |
| `trae_get_token.py` | 🔑 从 Trae 客户端一键提取 refreshToken（免抓包） |

纯 **Python 标准库**实现，**无需 pip 安装任何依赖**，可直接丢进青龙面板 / 本地 / GitHub Actions 运行。

---

## ✨ 特性

- 🪶 **零依赖** — 只用 Python 标准库，开箱即用
- 🔐 **Token 缓存** — 复用未过期的 `accessToken`，失效才续期，减少请求
- ⛓️ **链式续期** — 自动处理 `refreshToken` 轮换并回写，长期不失效
- 👥 **多账号** — 支持任意数量账号，环境变量即可配置
- ⏰ **智能轮签** — 每小时只签 1 个账号，5 小时一轮，规避服务端限流
- 📱 **稳定设备号** — 按账号生成固定 16 位设备号，避免随机设备号异常
- 🔁 **失败重试** — 遇限流自动退避重试，网络抖动不影响任务
- 📤 **微信推送** — 签到 / 积分结果推送到企业微信机器人
- 📲 **短信登录** — 无需客户端，手机号 + 验证码直接换 Token
- 🎨 **美观日志** — 带图标与分区的执行日志，状态一目了然

---

## 🔑 获取 refreshToken（新手必看）

> 这是**唯一**需要你手动准备的东西，弄到它就大功告成。

### ✅ 方式一：一键提取（推荐 · 免抓包）

本仓库自带 `trae_get_token.py`，会自动从 Trae 客户端读取并解密登录凭据，**零依赖、不联网、不上传**。

```bash
# 1. 先在电脑上打开 Trae 客户端并登录你的账号
# 2. 运行提取脚本
python trae_get_token.py

# 3. 终端会打印出（直接复制等号后面的那串）：
#    TRAE_REFRESH_TOKEN = AbCdEfGhIjKlMnOpQrStUvWxYz0123456789ABCD=.0000000000000000
```

复制到青龙面板 **环境变量** → 新建变量：

| 变量名 | 值 |
| :--- | :--- |
| `TRAE_REFRESH_TOKEN` | 粘贴上面复制的那串 |

**多账号**：在客户端依次登录每个账号，各运行一次 `trae_get_token.py`，
把得到的值分别填到 `TRAE_REFRESH_TOKEN`、`TRAE_REFRESH_TOKEN_2`、`TRAE_REFRESH_TOKEN_3` …

### 🔍 方式二：手动定位（了解原理可选）

Trae 客户端把登录凭据加密后存在（Windows）：

```text
%APPDATA%/Trae CN/User/globalStorage/storage.json
```

其中键名 `iCubeAuthInfo://icube.cloudide` 的值就是加密凭据。
解密算法（AES-128-CBC + SHA-512 校验）已内置在 `trae_get_token.py` 里，
所以**直接跑脚本即可**，不用自己动手解密。

### 📲 方式三：短信验证码登录（无需客户端）

不想装 Trae 客户端？用本仓库自带的 `trae_sms_login.py`，
直接「手机号 + 短信验证码」走网页端真实登录流程换 Token，**零依赖**。

```bash
# 交互式（按提示输入手机号 → 收到的验证码）
python trae_sms_login.py

# 非交互 / 脚本调用
python trae_sms_login.py -p 138xxxxxxxx -c 123456

# 离线自检（不联网，仅验证混淆与编码）
python trae_sms_login.py --selftest
```

运行后会打印 `accessToken` / `refreshToken`，并保存到 `trae_sms_accounts.json`，
把其中的 `refreshToken` 填到环境变量即可。

> ⚠️ **风控提示**：字节风控会对**机房 / 代理 / VPN IP** 强制弹滑块（错误码 `1105`）。
> 请在**家庭宽带 / 手机热点**等真实网络下运行；脚本无法自动过滑块。
> 若确实被要求滑块，可在真实浏览器过一次，把返回的 `verify_ticket`、`fp`
> 用 `--ticket` / `--fp` 传入继续登录。

---

### ⚠️ 注意事项

- 提取前请确保 **Trae 客户端已登录**，否则读不到凭据。
- 一个账号只在一处刷新（要么青龙，要么其它工具），**别同时挂两处**，否则 token 会互相顶失效。

---

## 🚀 快速开始

### 方式一：青龙面板（推荐）

```bash
# 1. 把两个脚本放入青龙 scripts 目录
/ql/data/scripts/trae_auto_checkin.py
/ql/data/scripts/trae_credit_monitor.py

# 2. 在「环境变量」里添加 TRAE_REFRESH_TOKEN_* 和 WECHAT_WEBHOOK

# 3. 新建定时任务
python /ql/data/scripts/trae_auto_checkin.py     # 定时: 0 * * * *
python /ql/data/scripts/trae_credit_monitor.py   # 定时: 0 * * * *
```

### 方式二：本地运行

```bash
export TRAE_REFRESH_TOKEN="你的 refreshToken"
export TRAE_REFRESH_TOKEN_2="第 2 个账号的 refreshToken"   # 可选
export WECHAT_WEBHOOK="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"  # 可选

python trae_auto_checkin.py      # 签到
python trae_credit_monitor.py    # 查积分
```

### 方式三：GitHub Actions

仓库自带 `.github/workflows/` 配置，把 `TRAE_REFRESH_TOKEN_*` 和 `WECHAT_WEBHOOK`
加进 **Settings → Secrets and variables → Actions** 即可，定时自动运行。

---

## ⚙️ 环境变量

| 变量 | 必填 | 说明 |
| :--- | :---: | :--- |
| `TRAE_REFRESH_TOKEN` | ✅ | 第 1 个账号的 refreshToken |
| `TRAE_REFRESH_TOKEN_2~_N` | ➖ | 第 2~N 个账号的 refreshToken |
| `TRAE_DEVICE_ID[_N]` | ➖ | 设备号，留空自动按账号生成固定值 |
| `WECHAT_WEBHOOK` | ➖ | 企业微信机器人 webhook，用于推送结果 |
| `TRAE_TOKEN_CACHE` | ➖ | 缓存文件路径，默认 `/ql/data/config/` 或脚本同目录 |
| `TRAE_SAVE_DIR` | ➖ | 账号 JSON 目录，用于回写轮换后的 refreshToken |
| `JOB_INDEX` | ➖ | 指定签到的账号下标，如 `3` 或 `1,2,3`；留空则自动轮签 |
| `TRAE_PHONE` | ➖ | 仅 `trae_sms_login.py`：手机号（免交互） |
| `TRAE_SMS_CODE` | ➖ | 仅 `trae_sms_login.py`：短信验证码（免交互） |

---

## 🎛️ 运行模式

| 模式 | 配置 | 行为 |
| :--- | :--- | :--- |
| **自动轮签**（默认） | 不设 `JOB_INDEX` | 按「北京时间小时 % 5 + 1」决定本次签哪个账号 |
| **手动指定** | `JOB_INDEX=3` | 只签第 3 个账号 |
| **一次全签** | `JOB_INDEX=1,2,3,4,5` | 一次性签完所有账号 |

---

## 🧠 工作原理

```text
        ┌──────────────────────────────────────────────────┐
        │  读取缓存 accessToken                             │
        └───────────────────────┬──────────────────────────┘
                                │
              ┌─────────────────┴─────────────────┐
              ▼                                   ▼
      ✅ 有效期内 / 校验通过               ❌ 过期或未认证(code=1001)
              │                                   │
              ▼                                   ▼
       直接复用（不刷新）              用 refreshToken 续期
                                              │
                                              ▼
                                 拿到新 accessToken + refreshToken
                                              │
                                              ▼
                                  写回缓存 & 账号文件（链式回写）
```

> 💡 **关于 refreshToken**
> Trae 的 `refreshToken` 是**轮换链**：每次续期都会产生一个新值，旧值随即失效。
> 因此本脚本会把最新值**回写到缓存与账号文件**，避免链停在旧节点导致 401。
> ⚠️ 请勿在多处同时使用同一账号刷新，否则会互相使对方 token 失效。

---

## ❓ 常见问题

<details>
<summary><b>怎么获取 refreshToken？</b></summary>

**推荐用本仓库自带的一键提取工具**：先在电脑上登录 Trae 客户端，然后运行

```bash
python trae_get_token.py
```

终端会直接打印出 `TRAE_REFRESH_TOKEN = xxx`，复制到青龙环境变量即可。
该脚本会自动定位并解密客户端凭据，免抓包、零依赖。
详见 [🔑 获取 refreshToken](#-获取-refreshtoken新手必看)。
</details>

<details>
<summary><b>提示「凭证续期失败 / 401」怎么办？</b></summary>

说明该账号的 refreshToken 链已被推进到失效节点，需要**重新登录 Trae 客户端并导出新的 refreshToken**。
</details>

<details>
<summary><b>会不会被限流？</b></summary>

默认每小时只签 1 个账号，5 小时一轮，已大幅降低限流概率；
脚本还内置了退避重试。若仍遇限流，会照常推送结果并稍后自动恢复。
</details>

<details>
<summary><b>为什么有两个脚本？</b></summary>

`trae_auto_checkin.py` 负责签到，`trae_credit_monitor.py` 负责只读查询积分。
两者共用同一份 token 缓存，互不干扰。
</details>

---

## 📂 项目结构

```text
Trae-AutoCheckin/
├── trae_auto_checkin.py        # 🎯 每日自动签到
├── trae_credit_monitor.py      # 📊 积分只读监控
├── trae_sms_login.py           # 📲 短信验证码登录换 Token
├── trae_get_token.py           # 🔑 refreshToken 一键提取（免抓包）
├── .github/workflows/          # ⚙️ GitHub Actions 定时任务
├── LICENSE                     # 📄 MIT
└── README.md                   # 📖 本文件
```

---

## ⚠️ 免责声明

本项目仅供**个人学习与研究**使用，请遵守 Trae 的服务条款。
使用本工具产生的一切后果由使用者自行承担，作者不对任何账号风险负责。

---

<div align="center">

**如果这个项目对你有帮助，欢迎点个 ⭐ Star 支持一下！**

Made with ❤️ by [L0NE-6](https://github.com/L0NE-6)

</div>
