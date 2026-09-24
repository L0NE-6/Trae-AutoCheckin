<div align="center">

# 🤖 Trae AutoCheckin

**Trae 每日自动签到 & 积分监控 · 零依赖 · 多账号 · 企业微信推送**

[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-none-success)](.)
[![Platform](https://img.shields.io/badge/platform-青龙%20%7C%20本地%20%7C%20任意定时-blue)](.)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Stars](https://img.shields.io/github/stars/L0NE-6/Trae-AutoCheckin?style=social)](https://github.com/L0NE-6/Trae-AutoCheckin)

[✨ 特性](#-特性) · [🔑 获取 Token](#-获取-refreshtoken新手必看) · [🚀 快速开始](#-快速开始) · [⚙️ 配置](#️-环境变量) · [🧠 原理](#-工作原理) · [❓ FAQ](#-常见问题)

</div>

---

## 📖 简介

**Trae AutoCheckin** 是一套用于 Trae 的积分自动化工具，包含 4 个独立脚本：

| 脚本 | 作用 |
| :--- | :--- |
| `trae_checkin.py` | 🎯 多账号每日签到，9074 自动换号，自动续期 + 推送 |
| `trae_credit_monitor.py` | 📊 只读查询积分「已用 / 剩余」，绝不签到 |
| `trae_sms_login.py` | 📲 手机号 + 短信验证码登录，直接换取 Token（免客户端） |
| `trae_get_token.py` | 🔑 从 Trae 客户端一键提取 refreshToken / 生成 TRAE_ACCOUNTS（免抓包） |

纯 **Python 标准库**实现，**无需 pip 安装任何依赖**，可直接丢进青龙面板 / 本地 crontab / 任意定时任务运行。

---

## ✨ 特性

- 🪶 **零依赖** — 只用 Python 标准库，开箱即用
- 🛡️ **解 9074** — 命中后自动换新设备号重签（实测立刻成功），与桌面端请求完全对齐
- 🚀 **一轮全签** — 默认每轮把所有未签账号全签掉，9074 自动换号兜底
- 🔐 **Token 缓存** — 复用未过期的 `accessToken`，失效才续期，减少请求
- ⛓️ **链式续期** — 自动处理 `refreshToken` 轮换并回写，长期不失效
- 👥 **多账号** — 支持任意数量账号，环境变量即可配置
- 📅 **当日跳过** — 已签成功的账号后续运行零请求，不重复消耗
- 📱 **稳定设备号** — 优先用客户端真实设备号，拿不到才按账号生成固定 16 位
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

**多账号**：直接运行下面这条，会自动把本机登录态和账号目录里的凭据合成一个 `TRAE_ACCOUNTS` 数组：

```bash
python trae_get_token.py --accounts
```

输出一行 JSON，整行复制到 `TRAE_ACCOUNTS` 环境变量即可（字段说明见下方「[TRAE_ACCOUNTS 怎么填](#-trae_accounts-怎么填新手必看)」）。

也可以沿用旧写法：在客户端依次登录每个账号，各运行一次 `trae_get_token.py`，
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

**① 一键订阅拉取（推荐，自动跟随更新）**

在青龙「定时任务」里新建一条任务，命令填：

```bash
ql repo "https://github.com/L0NE-6/Trae-AutoCheckin.git" "trae_checkin.py|trae_credit_monitor.py" "" "" "main"
```

手动执行一次，脚本就会拉到 `/ql/repo/Trae-AutoCheckin/` 下，之后每次执行都会自动更新到最新版。

**② 手动放置（不想用订阅时）**

```bash
# 把两个脚本放入青龙 scripts 目录
/ql/data/scripts/trae_checkin.py
/ql/data/scripts/trae_credit_monitor.py
```

**③ 添加环境变量**

在「环境变量」里添加 `TRAE_ACCOUNTS` 和 `QYWX_TOKEN`。

**④ 新建签到任务**

```bash
# 订阅方式（路径在 repo 下）
python /ql/repo/Trae-AutoCheckin/trae_checkin.py          # 早窗: 23 0 * * *  补签: 7,37 * * * *
python /ql/repo/Trae-AutoCheckin/trae_credit_monitor.py   # 定时: 0 * * * *

# 手动放置方式（路径在 scripts 下）
python /ql/data/scripts/trae_checkin.py
python /ql/data/scripts/trae_credit_monitor.py
```

### 方式二：本地运行

```bash
export TRAE_ACCOUNTS='[{"accessToken":"...","refreshToken":"...","uid":"账号1"},...]'
export QYWX_TOKEN="你的企业微信机器人 key"  # 可选

python trae_checkin.py          # 签到
python trae_credit_monitor.py   # 查积分
```

### 方式三：GitHub Actions（免费 · 无需服务器）

1. Fork 本仓库（或直接使用你自己的仓库）
2. 打开 **Settings → Secrets and variables → Actions**，添加两个 secret：

   | Secret 名称 | 值 |
   |---|---|
   | `TRAE_ACCOUNTS` | 与青龙相同的 JSON 数组 |
   | `QYWX_TOKEN` | 企业微信机器人 key |

3. 打开 **Actions** 标签页，确认两个工作流已启用（默认自动启用）：
   - **Trae Daily Checkin** — 每天北京时间 00:23 自动签到 + 可手动触发
   - **Trae Credit Monitor** — 每小时自动查积分 + 可手动触发

> 💡 手动测试：进入 Actions → 选一个工作流 → Run workflow → Run，
> 日志里能看到每个号的签到/积分结果。

---

## ⚙️ 环境变量

| 变量 | 必填 | 说明 |
| :--- | :---: | :--- |
| `TRAE_ACCOUNTS` | ✅ | 多账号 JSON 数组（推荐）：每号可给 `accessToken` / `refreshToken` / `icubeAuth` / `storagePath` |
| `TRAE_REFRESH_TOKEN[_N]` | ➖ | 旧部署兼容：refreshToken（无 TRAE_ACCOUNTS 时生效） |
| `TRAE_ACCESS_TOKEN[_N]` | ➖ | 已有 accessToken 时直接给，省一次续期 |
| `TRAE_ICUBE_AUTH` | ➖ | 桌面端加密凭据串，脚本自动解密（需 cryptography） |
| `TRAE_STORAGE_PATH` | ➖ | 直接指向客户端 `storage.json`，自动解密取 token |
| `TRAE_UID[_N]` | ➖ | 账号标识，仅用于日志与缓存键 |
| `TRAE_DEVICE_ID[_N]` | ➖ | 设备号；留空则优先用客户端真实设备号，再回退自动生成 |
| `TRAE_TOKEN_CACHE` | ➖ | token 缓存路径，默认 `/ql/data/config/` 或脚本同目录 |
| `TRAE_ACCOUNT_DIR` | ➖ | 账号 JSON（`trae-<uid>.json`）所在目录：读取与回写都用它 |
| `TRAE_ONLY` | ➖ | 只跑指定账号：序号(从 1 起) / `uid` / `name` |
| `TRAE_BATCH` | ➖ | 每轮签几个账号，默认 **all**（一轮全签）；设 `1` 按小时轮换 |
| `TRAE_JITTER` | ➖ | 启动随机抖 0~20s 避开整点同秒，默认开；设 `0` 关闭 |
| `TRAE_COOLDOWN_MIN` | ➖ | 平时 9074 冷却分钟数，默认 **55**，冷却内零请求 |
| `TRAE_PEAK_HOURS` | ➖ | 早窗小时，默认 **0**；支持 `0` / `0,23` / `0-1`，早窗自动一轮全签 |
| `TRAE_PEAK_COOLDOWN_MIN` | ➖ | 早窗内冷却分钟数，默认 **12**（好让下轮还在窗口里补签） |
| `TRAE_CIRCUIT` | ➖ | 设 `1` 恢复旧熔断：一个账号 9074 就全体收工（默认关） |
| `TRAE_ROTATE` | ➖ | 9074 后自动换新设备号，默认开；设 `0` 关闭 |
| `TRAE_DEVICE_BRAND` | ➖ | 设备品牌请求头（可选，默认不发，与桌面端 `device_model` 对应） |
| `CLAIM_TRIES` | ➖ | 每账号每轮 claim 次数，默认 **1**（换号才是正解，别调大） |
| `QYWX_TOKEN` | ➖ | 企业微信机器人 key（`?key=` 后面那段） |
| `PLUSPLUS_TOKEN` | ➖ | PushPlus token |
| `TRAE_PHONE` | ➖ | 仅 `trae_sms_login.py`：手机号（免交互） |
| `TRAE_SMS_CODE` | ➖ | 仅 `trae_sms_login.py`：短信验证码（免交互） |

> 💡 兼容旧命名：`WECHAT_WEBHOOK` 与 `QYWX_TOKEN` 都能识别。

---

## 📋 TRAE_ACCOUNTS 怎么填（新手必看）

一个 **JSON 数组**，一个元素 = 一个账号。**最省事的是让脚本自动生成**：

```bash
# 自动扫描「本机 Trae 登录态 + 账号目录里的 trae-<uid>.json」，直接打印可用的一行 JSON
python trae_get_token.py --accounts

# 账号文件（trae-<uid>.json）在别的目录时，指定一下
TRAE_ACCOUNT_DIR="/your/accounts/dir" python trae_get_token.py --accounts
```

把打印出来的那一行**整行**复制进 `TRAE_ACCOUNTS` 就行，不用手动拼。

### 字段说明

| 字段 | 必填 | 说明 |
| :--- | :---: | :--- |
| `refreshToken` | ✅ | 账号的 refreshToken。**只给这一个也能跑**，脚本会自动换取 accessToken |
| `accessToken` | ➖ | 有就直接用，省一次续期；没有脚本自动换 |
| `uid` | ➖ | 账号标识，用于日志和缓存键；不填会用 `name` 或序号 |
| `name` | ➖ | 备注名，只影响日志显示 |
| `deviceId` | ➖ | 16 位设备号；不填会自动生成并持久化 |
| `icubeAuth` | ➖ | 桌面端加密凭据串（自动解密，需 cryptography），可替代 refreshToken |
| `storagePath` | ➖ | 直接给 `storage.json` 路径，脚本自己解密取 token |

### 最小可用示例

只有一个 refreshToken 也能直接跑（推荐先这样跑通）：

```json
[{"refreshToken":"第1个账号的refreshToken"},{"refreshToken":"第2个账号的refreshToken"}]
```

### 完整示例

```json
[{"accessToken":"eyJhbGciOi...","refreshToken":"AbCd...=.0123456789abcdef","uid":"账号1","name":"主号"},{"refreshToken":"XyZ...=.fedcba9876543210","uid":"账号2","name":"小号"}]
```

### ⚠️ 三个最容易踩的坑

- 必须是**一行**，中间不能有换行（换行会让 JSON 解析失败）
- 只能用**英文双引号** `"`，中文引号 `“”` 会报错
- 最后一个 `}` 后面**不能有逗号**

> 💡 填完在青龙里点一次「执行」，日志会打印每个账号的状态；有账号报错会单独提示，不影响其它账号。
> 旧写法 `TRAE_REFRESH_TOKEN[_N]` 仍然兼容，两种任选其一，`TRAE_ACCOUNTS` 优先。

---

## 🎛️ 运行模式

| 模式 | 配置 | 行为 |
| :--- | :--- | :--- |
| **全量签到**（默认） | 不设 `TRAE_ONLY` | 一轮把所有未签账号全签掉，9074 自动换号重签 |
| **指定账号** | `TRAE_ONLY=3` | 只跑第 3 个账号，其余跳过 |
| **按 uid 筛选** | `TRAE_ONLY=113185...` | 只跑匹配 uid 的账号 |
| **重试多次** | `CLAIM_TRIES=2` | 单账号 9074 后当场再试（一般不需要，换号已内置） |

> 💡 配合青龙定时 `*/30 * * * *`，加上当日状态文件自动跳过已签账号，
> 9074 的账号会自动换设备号重签，仍不行才冷却等下轮补签。

---

## 🧠 工作原理

```text
        ┌──────────────────────────────────────────────────┐
        │  读取 token 缓存（.trae_token_cache.json）        │
        │  已签到账号 → 跳过（当日状态文件）                 │
        └───────────────────────┬──────────────────────────┘
                                │
              ┌─────────────────┴─────────────────┐
              ▼                                   ▼
      ✅ 有效期内 / 校验通过               ❌ 过期或未认证(code=1001)
              │                                   │
              ▼                                   ▼
       直接复用（不刷新）              用 refreshToken 续期
              │                                   │
              ▼                                   ▼
       查今日是否已签 ──────┬────── 获取新 token + refreshToken
                           │                    │
                ┌──────────┴──────────┐         │
                ▼                     ▼         ▼
         checked_in=true      checked_in=false   写回缓存（链式回写）
              │                     │
              ▼                     ▼
         ☑️ 今日已签到          发送 claim（每账号仅 1 次）
                                   │
                          ┌────────┴────────┐
                          ▼                 ▼
                      code=0 成功       code=9074 设备号被记住
                          │                 │
                          ▼                 ▼
                     🎉 签到成功       🔄 换新设备号重签 → 仍 9074 才冷却
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
<summary><b>9074 到底是什么？</b></summary>

9074 **不是限流** —— 是服务端把这个**设备号**记住了（反复用它请求会越记越死）。
脚本的做法：命中 9074 就**自动换一个全新设备号**重签一次（实测立刻成功），
仍不行才按账号冷却。另外请求体必须带 `{"req_source":1}` 和设备头（与桌面端一致），
空请求体也会被拒成 9074 —— 脚本已内置，不需要手动配。
配合青龙定时高频轻量跑 + 当日状态文件跳过已签账号，全天多轮下来每个号都能签上。
</details>

> 💡 **实测结论（2026-09-14 更正）**：9074 **不是限流** —— 是这个设备号被服务端记住了
> （反复用它请求会越记越死）。换个**全新设备号**立刻就能签成，跟出口 IP、请求头无关。
> 另外请求体必须带 `{"req_source":1}` 和设备头（与桌面端一致），空请求体也会被拒成 9074。

<details>
<summary><b>为什么有两个脚本？</b></summary>

`trae_checkin.py` 负责签到（主脚本），`trae_credit_monitor.py` 负责只读查询积分。
两者共用同一份 token 缓存，互不干扰。
</details>

---

## 📂 项目结构

```text
Trae-AutoCheckin/
├── trae_checkin.py             # 🎯 多账号签到（主脚本，9074 自动换号）
├── trae_credit_monitor.py      # 📊 积分只读监控
├── trae_sms_login.py           # 📲 短信验证码登录换 Token
├── trae_get_token.py           # 🔑 refreshToken 提取 + --accounts 一键生成 TRAE_ACCOUNTS
├── .github/workflows/          # ⚙️ GitHub Actions（每日签到 / 每小时积分）
├── .gitignore                  # 🚫 运行时缓存与账号文件永不入库
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

**遇到问题或想改进？欢迎提 [Issues](https://github.com/L0NE-6/Trae-AutoCheckin/issues) 或发 [Pull Request](https://github.com/L0NE-6/Trae-AutoCheckin/pulls) 🚀**

Made with ❤️ by [L0NE-6](https://github.com/L0NE-6)

</div>
