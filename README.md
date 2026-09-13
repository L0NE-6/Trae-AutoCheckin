# 🤖 Trae AutoCheckin

Trae 每日积分签到，一个脚本搞定：多账号、自动续期、抗 9074 限流、企业微信推送。

> 主脚本是 **`trae_checkin.py`**（青龙 / 本地均可，纯标准库零依赖）。
> 另附三个独立小工具：短信登录、refreshToken 一键提取、积分只读监控。

---

## 🚦 为什么签到老是返回「9074 参与用户太多」

`9074` **不是账号没资格**，而是服务端按**时间窗口**做的排队限流。实测踩过的三个坑：

| 坑 | 说明 | 解法 |
| :--- | :--- | :--- |
| 走代理 | 系统代理 / Clash 让多账号共用同一个出口 IP，最容易触发限流 | 强制直连 `ProxyHandler({})` |
| 双重设备头 | 同时发 `x-device-id` 和 `X-Device-Id`，会被风控判定为异常客户端 | 只发一个小写头 |
| 当场连发重试 | 失败就 sleep 再打，反而**不断延长**自己的惩罚窗口 | 每账号每轮只发 **1 次**，失败交给下一轮 cron |

> 实测：同一批账号，用「当场重试 3~6 次」连续十几轮全部 9074；
> 改成「静默几小时后单次请求 + 账号间隔 25 秒」，一次性全部签到成功。
> 脚本还内置**熔断**：任一账号命中 9074 就收工，避免把剩余账号一起拖进惩罚窗口。

推荐让青龙**高频轻量**地跑，而不是一次跑到底：

```cron
*/30 * * * * trae_checkin.py
```

配合当日状态文件 `.trae_checkin_state.json`，已签成功的账号后续运行**零请求**，
全天多轮下来每个账号都能排到。

---

## 🔁 refreshToken 会轮换，务必缓存

Trae 每次续期都会下发**新的** `refreshToken`。青龙里的环境变量是静态的，
如果不缓存新值，第二三次就会拿旧 token 去续期而彻底失效。
`trae_checkin.py` 会把续期结果写进同目录 `.trae_token_cache.json`，并在下次运行时优先使用它。

⚠️ **该文件含真实凭据，已列入 `.gitignore`，切勿提交或分享。**
⚠️ 青龙容器如果每次重建会丢缓存，请把缓存里的最新值贴回环境变量。

---

## 🧩 trae_checkin.py

### 环境变量

| 变量 | 必填 | 说明 |
| :--- | :---: | :--- |
| `TRAE_REFRESH_TOKEN` | ✅ 二选一 | 账号 1 的 refreshToken（最简单写法） |
| `TRAE_REFRESH_TOKEN_2~_9` | ➖ | 账号 2~9 的 refreshToken |
| `TRAE_ACCOUNTS` | ✅ 二选一 | JSON 数组，适合想显式指定 uid / name 的场景 |
| `TRAE_ONLY` | ➖ | 只跑指定账号：序号(从 1 起) / `uid` / `name` |
| `CLAIM_TRIES` | ➖ | 单账号每轮 claim 次数，默认 **1**（抗限流关键，别调大） |
| `QYWX_TOKEN` | ➖ | 企业微信群机器人 key（`?key=` 后面那段） |
| `PLUSPLUS_TOKEN` | ➖ | PushPlus token |
| `TRAE_ACCOUNT_DIR` | ➖ | 凭据 json 所在目录，续期后回写 |

> 兼容旧部署：`WECHAT_WEBHOOK` 与 `QYWX_TOKEN` 都能识别。
> 不需要 accessToken —— 脚本会用 refreshToken 自动续期换取，
> **不需要 cryptography**（只有直接解密桌面端 storage.json 才需要）。

### 青龙面板

```bash
# 1. 把 trae_checkin.py 放入青龙 scripts 目录
# 2. 环境变量里添加：
#      TRAE_REFRESH_TOKEN  = 你的 refreshToken
#      TRAE_REFRESH_TOKEN_2 = 第 2 个账号（多账号时）
#      QYWX_TOKEN          = 企业微信机器人 key（可选）
# 3. 定时任务（建议高频轻量）：
python /ql/data/scripts/trae_checkin.py     # 定时: */30 * * * *
```

### 本地运行

```bash
export TRAE_REFRESH_TOKEN="你的 refreshToken"
python trae_checkin.py
```

### 📦 依赖

- 用 `refreshToken` / `accessToken` 配置账号（推荐，含青龙）：**零依赖**，纯标准库
- 需要直接解密桌面端 `storage.json` / `icubeAuth` 时：`pip install cryptography`

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

## 📂 项目结构

```text
Trae-AutoCheckin/
├── trae_checkin.py        # 🎯 多账号签到（主脚本，抗 9074 限流）
├── trae_credit_monitor.py # 📊 积分只读监控（可选，不签到）
├── trae_sms_login.py      # 📲 短信验证码登录换 Token
├── trae_get_token.py      # 🔑 refreshToken 一键提取（免抓包）
├── LICENSE                # 📄 MIT
└── README.md              # 📖 本文件
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
