# 更新日志

## v1.0.8（2026-10-27）

- 修复：**`TRAE_BATCH=<数字>` 必崩** —— `pick_batch()` 在非早窗时段取用了从未定义的 `size`，只要把 `TRAE_BATCH` 设成 `1` / `2` / 任意数字，且当前不在早窗时段，整轮签到直接 `NameError` 退出。
  - 默认 `all` 与早窗全签两条路径提前 return，所以默认配置下从未暴露；
  - 该行是「早窗全签」快路径重构时被误删的，`git log -S size` 可追到 `4ca5697` 的原始实现；
  - 现按原实现恢复 `size = max(1, int(raw))`，并对非法值（如 `TRAE_BATCH=abc`）降级为 1，不再抛错打断整轮签到。
- 测试：新增 8 项 `pick_batch` 离线回归测试（数量截断、超量收敛、非法值降级、`all` 全签、早窗全签、北京时间轮换、空列表），全部通过；`py_compile` 与 `ruff --select F821` 无告警。
- 说明：本轮未使用真实账号，未发送真实签到请求。

## v1.0.7（2026-10-27）

- 修复：签到领取接口的 `9004` 与 `9095` 都表示「本设备今日已签到」，现在统一按已签成功处理，不再把 `9004` 误判为失败。
  - 覆盖 `claim_with_retry` 与 `checkin_account` 两处分类；
  - 新增 4 项离线回归测试，分别验证 9004 / 9095 在领取与账号结果中的分类。
- 增强：积分监控新增只读接口 `POST /trae/api/v2/pay/ide_user_ent_usage`（请求体 `{"require_usage":true}`）。
  - 解析 `user_entitlement_pack_list[]` 的 `expire_time`、`quota.credits_limit`、`usage.credits_amount`；
  - 自动跳过已耗尽积分包，按到期时间排序并显示「最早到期包」；
  - 查询失败时不影响原有余额/已用查询，签到主流程完全不受影响。
- 测试：新增 8 项离线回归测试，全部通过；`compileall` 与 `git diff --check` 通过。
- 说明：本轮未使用真实账号，未发送真实签到请求。

## v1.0.6（2026-10-21）

- 新增：GitHub Actions 工作流 `.github/workflows/daily.yml`（默认只开手动触发，schedule 需 fork 后自行取消注释）；
  - 用 Actions Cache 持久化 `.trae_token_cache.json` / `.trae_device_ids.json` / `.trae_checkin_state.json`；
  - 缓存内容用 `TRAE_CACHE_KEY` 加密，避免轮换后的 refreshToken 以明文进入 Cache；
  - 解决 Actions 每次全新环境导致 refreshToken 轮换后下一次运行失效的问题。
- 兼容：PushPlus token 继续优先识别 `PLUSPLUS_TOKEN`，同时支持 `PLUSHPLUS_TOKEN` / `PUSHPLUS_TOKEN` 别名；
- 文档：README 补充 Actions 部署步骤、Secrets 清单与 `TRAE_CACHE_KEY` 说明。


## v1.0.5（2026-10-16）

- 修复：**中国版账号的令牌到期读不出来**（与上游 issue #263 同款问题）。
  - 中国版 JWT 把到期写在自定义声明 `TokenExpireAt`（且可能是**字符串**），旧的只认标准 `exp`，读出来是 0 —— 缓存里的有效期与自动续期节奏一起坏，且不报任何错；
  - 现在按 `exp` → `TokenExpireAt` → `tokenExpireAt` 顺序读取，数字 / 字符串都认，秒 / 毫秒按量级归一；
  - `trae_checkin.py` 与 `trae_credit_monitor.py` 两处同步修正。

## v1.0.4（2026-10-13）

- 修复：签到结束后**逐账号明细也打印到终端**（此前只进推送，没配推送时终端只有「失败 1」这种计数，看不出原因）。排障请直接看这几行。

## v1.0.3（2026-10-13）

- 新增：**领取后同设备号回查确认** —— claim 返回 `code:0` 不再直接判成功（当日已签过的账号对任何 device_id 都回 0，属于假成功）。现在以同设备号回查 `checked_in` 是否翻转为准，未确认就不报成功、交给下一轮 cron，避免亮绿灯但实际没到账。
- 新增开关 `TRAE_VERIFY_CLAIM`（默认 `1`），设 `0` 可关闭该回查。

## v1.0.2（2026-10-09）

- 修正对 9074（「当前参与用户太多」）的理解与处理：它绝大多数不是限流，而是**设备号不对**。
  实测同账号同时刻对照：脚本自动生成的设备号 → `9074`，客户端真实注册号 → 通过设备检查。
- `x-device-id` 一律优先使用客户端真实注册过的设备号（storage.json 里
  `iCubeAuthInfo://icube-dc:<数字>` 键名中的那串数字）。
- 设备号长度校验放宽为 12~20 位十进制：15 位的真实号不再被丢弃（16 位只是观察，不是规则）。
- 命中 9074 后不再生成假号重试，只在**真实设备号之间**切换；换不到就冷却等下轮 cron。
- `trae_get_token.py --accounts` 现在会给每个账号自动带上 `realDeviceId`。
- `trae_credit_monitor.py` 同样优先使用客户端真实设备号。

## v1.0.1（2026-10-09）

- 启动即拦截 token 错配（accessToken / refreshToken 填成同一个值或填反）。
- TRAE_ACCOUNTS JSON 解析失败时给出更友好的格式示例。
- README 补充「鉴权失败（硬失败）」排查说明。

## v1.0.0（2026-10-04）

- 首个公开版本：多账号每日签到、token 自动续期、9074 处理、企业微信 / PushPlus 推送。
