#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Trae SOLO 国内版 每日签到脚本（多账号版 · v2 抗限流优化）

【v2 关键改进（解决 9074 限流）】
  1. 强制直连不走代理 —— 系统代理 / Clash 会让多账号共用出口 IP，最容易触发限流
  2. 单一设备头 x-device-id —— 同时发大小写两个头会被风控判定为异常客户端
  3. 每账号每轮只发 1 次 claim —— 9074 是时间窗口限流，当场连发只会延长惩罚；
     失败直接退出，交给青龙下一轮 cron 补签（实测单次+错峰即可稳定通过）
  4. 当日状态文件 .trae_checkin_state.json —— 已签成功的账号后续运行零请求
  5. Token 缓存 .trae_token_cache.json —— Trae 每次续期都会轮换 refreshToken，
     而环境变量里的值是静态的，必须缓存新值，否则越刷越失效
  6. Token 过期自动续期，code=1001 鉴权失败自动刷新后重试
  7. HTTP 429/5xx 与 code=9074 同等对待；entitlement API 查真实积分余额

【调度建议】青龙 cron 设为每 30~60 分钟一次即可，全天多轮自然会把每个账号都签上：
    */30 * * * * trae_checkin.py
需要当场多重试几次时设 CLAIM_TRIES=2/3；只想跑指定账号设 TRAE_ONLY=1（或填 uid）。

【特性】
- 纯标准库 + cryptography，无需其它依赖
- 自动读取桌面端登录凭据并解密，无需手动抓包
- 多账号支持：从 accounts.json 读取多个账号，逐个签到并汇总
- 每个账号自动生成固定、独立的 16 位模拟设备号（持久化，跨运行不变）
- 自动签到：先查今日是否已签 / 是否开放，未签才领积分并复查确认
- Token 过期自动刷新：用 refreshToken 换新，失败自动重试一次
- 企业微信群机器人 + PushPlus 推送（可选），运行结果自动通知
- 带图标与边框的美观日志输出

【使用方法】
全部通过环境变量配置（无需任何文件）。

1) 多账号（推荐）：TRAE_ACCOUNTS 为 JSON 数组，包含多个账号对象：
   set TRAE_ACCOUNTS=[{"accessToken":"xxxx","refreshToken":"yyyy","uid":"账号1"},{"icubeAuth":"<桌面端凭据base64串>","uid":"账号2"}]
   每个账号对象支持字段：
     accessToken  / refreshToken  明文 token（二选一与 icubeAuth 搭配）
     icubeAuth                  桌面端 storage.json 里的 base64 加密串（自动解密）
     storagePath                storage.json 路径（自动读并解密）
     uid                        账号标识（可选，用于日志）
     deviceId                   16 位模拟设备号（可选，不填则自动生成并持久化）
     name                       备注（可选）
   然后运行：python trae_checkin.py

2) 单账号用环境变量：
   set TRAE_ACCESS_TOKEN=xxxx
   set TRAE_REFRESH_TOKEN=yyyy        (可选)
   set TRAE_ICUBE_AUTH=<base64 串>    (或直接给桌面端凭据串)
   set TRAE_STORAGE_PATH=<storage.json 路径>
   set TRAE_DEVICE_ID=1510001234567890 (可选，不填自动生成)
   python trae_checkin.py

【推送配置（可选，留空则不推送）】
  PLUSPLUS_TOKEN    PushPlus token
  QYWX_TOKEN        企业微信群机器人 Webhook key（机器人地址 ?key= 后面的值）

【关于设备号】
- 签接口按"设备号"维度判断今日是否已签；实测用模拟的 16 位数字即可签到成功，
  服务端不校验设备号是否真实注册。
- 每个账号自动生成一个固定的 16 位数字设备号并存到 .trae_device_ids.json，
  不同账号用不同号、同一账号永远同一号，避免互相干扰，也便于跨日稳定去重。
"""

import base64
import hashlib
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
# cryptography 仅解密桌面端 storage.json(icubeAuth) 时才需要；
# 用 accessToken / refreshToken 的常规部署（含青龙）完全不需要，
# 因此改为惰性导入，保证那种场景下真正零依赖、不会 ImportError。

# ---------- tc 解密常量 ----------
SALT_A = bytes([82,9,106,213,48,54,165,56,191,64,163,158,129,243,215,251,
  124,227,57,130,155,47,255,135,52,142,67,68,196,222,233,203,
  84,123,148,50,166,194,35,61,238,76,149,11,66,250,195,78,
  8,46,161,102,40,217,36,178,118,91,162,73,109,139,209,37])
SALT_B = bytes([31,221,168,51,136,7,199,49,177,18,16,89,39,128,236,95,
  96,81,127,169,25,181,74,13,45,229,122,159,147,201,156,239,
  160,224,59,77,174,42,245,176,200,235,187,60,131,83,153,97,
  23,43,4,126,186,119,214,38,225,105,20,99,85,33,12,125])
SALT_C = bytes([191,192,216,250,122,246,220,97,31,254,98,27,8,72,71,176,
  135,99,96,18,127,101,203,104,211,102,191,125,37,72,150,156,
  51,229,121,35,17,153,141,177,110,131,150,128,172,255,254,6,
  18,140,55,62,236,249,135,64,135,12,117,4,89,149,168,209])
SALT_D = bytes([246,204,26,232,232,70,129,109,223,146,169,242,23,241,105,145,
  50,196,165,42,254,120,3,54,244,207,209,85,53,6,138,106,
  175,148,31,204,186,186,165,182,87,142,49,10,39,110,26,154,
  86,56,173,125,18,64,198,225,99,99,83,82,191,134,76,170])

SALT_AES = bytes(a ^ b for a, b in zip(SALT_A, SALT_B))
SALT_AES_PRIVATE = bytes(a ^ b for a, b in zip(SALT_C, SALT_D))

STORAGE_KEY = "iCubeAuthInfo://icube.cloudide"

# ---------- 签到点 ----------
UgHost     = "https://api.trae.cn"
OAuthHost  = "https://api.trae.com.cn"
ClientID   = "en1oxy7wnw8j9n"
IdeVersion = "1.107.1"
UA         = f"Trae/{IdeVersion}"

EP_STATUS    = UgHost    + "/trae/api/v2/ug/checkin_credits/status"
EP_CLAIM     = UgHost    + "/trae/api/v2/ug/checkin_credits/claim"
EP_EXCHANGE  = OAuthHost + "/cloudide/api/v3/trae/oauth/ExchangeToken"

# ---------- 推送配置 ----------
PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")
# 兼容旧脚本命名：WECHAT_WEBHOOK 与 QYWX_TOKEN 都可
QYWX_TOKEN     = os.getenv("QYWX_TOKEN") or os.getenv("WECHAT_WEBHOOK") or ""

# 设备号持久化文件
DEVICE_ID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".trae_device_ids.json")
# 当日签到状态：已成功的账号当天不再重复请求，避免白烧限流额度
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".trae_checkin_state.json")
# 刷新后的 token 缓存：Trae 每次续期都会轮换 refreshToken，
# 青龙里 TRAE_ACCOUNTS 是静态的，必须靠本文件记住最新的 token 对，否则会越刷越失效。
TOKEN_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".trae_token_cache.json")


# ========================= Token 缓存 =========================
def load_token_cache() -> dict:
    try:
        with open(TOKEN_CACHE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_token_cache(cache: dict) -> None:
    try:
        with open(TOKEN_CACHE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _acct_key(acc: dict) -> str:
    """账号唯一键：uid > _name > name。用于 token 缓存与当日状态，绝不能撞键，
    否则多账号会互相覆盖（曾导致 refreshToken-only 模式 5 个账号共用空键）。"""
    return (str(acc.get("uid") or "").strip()
            or str(acc.get("_name") or "").strip()
            or str(acc.get("name") or "").strip()
            or "default")


def _cache_key(acc: dict) -> str:
    return _acct_key(acc)


def cache_tokens(acc: dict) -> None:
    key = _cache_key(acc)
    if not (key and acc.get("accessToken")):
        return
    cache = load_token_cache()
    cache[key] = {"accessToken": acc["accessToken"],
                  "refreshToken": acc.get("refreshToken", ""),
                  "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    save_token_cache(cache)


def apply_token_cache(accounts: list) -> list:
    """用缓存里更新的 token 覆盖静态环境变量里的旧 token。"""
    cache = load_token_cache()
    if not cache:
        return accounts
    hit = 0
    for a in accounts:
        rec = cache.get(str(a.get("uid") or "").strip()) or cache.get(_cache_key(a))
        if rec and rec.get("accessToken"):
            a["accessToken"] = rec["accessToken"]
            if rec.get("refreshToken"):
                a["refreshToken"] = rec["refreshToken"]
            hit += 1
    if hit:
        print(f"🔁 [缓存] 已用上次续期的 token 覆盖 {hit} 个账号")
    return accounts


# ========================= 当日状态 =========================
def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_state() -> dict:
    """返回 {"date": "YYYY-MM-DD", "done": {uid: {...}}}，跨天自动清空。"""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            st = json.load(fh)
        if st.get("date") != today_str():
            return {"date": today_str(), "done": {}}
        return st
    except Exception:
        return {"date": today_str(), "done": {}}


def mark_done(uid: str, info: dict) -> None:
    st = load_state()
    st["done"][str(uid or info.get("name", "?"))] = info
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(st, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ========================= 日志与图标 =========================
def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_title(total: int) -> None:
    print()
    print("╔" + "═" * 52 + "╗")
    print("║ 🤖 Trae SOLO 每日签到脚本（多账号）            ║")
    print(f"║ 🕒 启动时间: {now_text():<34}║")
    print(f"║ 👥 账号数量: {total:<37}║")
    print("╚" + "═" * 52 + "╝")


def log_box_open(title: str) -> None:
    print()
    print("┌" + "─" * 52 + "┐")
    print(f"│ {title:<48}│")
    print("└" + "─" * 52 + "┘")


# ========================= tc 解密 =========================
def _detect_enc_type(header: bytes) -> str:
    if header[0:6] == bytes([0x74, 0x63, 0x05, 0x10, 0x00, 0x00]):
        return "AES"
    if header[0:6] == bytes([18, 57, 32, 32, 2, 3]):
        return "AES_PRIVATE"
    return "UNKNOWN"


def _derive_key_iv(random_bytes: bytes, enc_type: str):
    salt = SALT_AES_PRIVATE if enc_type == "AES_PRIVATE" else SALT_AES
    hash_of_random = hashlib.sha512(random_bytes).digest()
    final_hash = hashlib.sha512(hash_of_random + salt).digest()
    return final_hash[0:16], final_hash[16:32]


def decrypt_storage_value(base64_value: str) -> str:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        raise SystemExit("❌ 解密 icubeAuth/storage.json 需要 cryptography，"
                         "请 pip install cryptography；"
                         "或改用 accessToken/refreshToken 方式配置账号（零依赖）")
    buf = base64.b64decode(base64_value)
    header = buf[0:6]
    random_bytes = buf[6:38]
    encrypted = buf[38:]
    enc_type = _detect_enc_type(header)
    if enc_type == "UNKNOWN":
        raise ValueError("未知的加密类型 (前 6 字节=%s)" % header.hex())
    key, iv = _derive_key_iv(random_bytes, enc_type)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    dec = cipher.decryptor()
    decrypted = dec.update(encrypted) + dec.finalize()
    stored_hash = decrypted[0:64]
    plaintext = decrypted[64:]
    # 去掉尾部填充字节（零填充等）后再校验与解析
    plaintext = plaintext.rstrip(b"\x00").rstrip()
    if stored_hash != hashlib.sha512(plaintext).digest():
        raise ValueError("SHA-512 校验失败，解密可能不正确")
    return plaintext.decode("utf-8")


def load_from_storage(storage_path: str) -> dict:
    with open(storage_path, "r", encoding="utf-8") as fh:
        storage = json.load(fh)
    enc = storage.get(STORAGE_KEY)
    if not enc:
        raise ValueError("storage.json 里找不到 %s" % STORAGE_KEY)
    enc = enc.strip()
    if enc.startswith("{"):
        return json.loads(enc)
    return json.loads(decrypt_storage_value(enc))


# ========================= 设备号生成/持久化 =========================
def _gen_device_id(seed: str) -> str:
    """由账号特征生成一个固定的 16 位数字设备号（1000000000000000 ~ 9999999999999999）"""
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    num = int.from_bytes(h[:8], "big") % (10**16 - 10**15) + 10**15
    return str(num)


def load_device_ids() -> dict:
    try:
        with open(DEVICE_ID_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_device_ids(ids: dict) -> None:
    try:
        with open(DEVICE_ID_FILE, "w", encoding="utf-8") as fh:
            json.dump(ids, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️  [设备号] 持久化失败: {e}")


def resolve_device_id(account: dict, manual: str) -> str:
    """优先级：手动 deviceId > 已持久化 > 自动生成并持久化。
    种子必须用稳定键(_acct_key)：早先用 accessToken 做种子，而 accessToken
    每次续期都会变，导致设备号每轮都换、凭据文件无限增长 —— 对风控而言
    "设备不停更换"本身就是高危信号。"""
    if manual and manual.isdigit() and len(manual) == 16:
        return manual
    seed = _acct_key(account)
    ids = load_device_ids()
    if seed in ids:
        return ids[seed]
    new_id = _gen_device_id(seed)
    ids[seed] = new_id
    save_device_ids(ids)
    return new_id


# ========================= 凭据获取 =========================
def _pick(d: dict, *candidates) -> str:
    for c in candidates:
        if c in d and d[c]:
            return d[c]
    return ""


def _from_decrypted(d: dict, src: str, name: str = "") -> dict:
    return {
        "accessToken":  _pick(d, "accessToken", "token", "access_token"),
        "refreshToken": _pick(d, "refreshToken", "refresh_token"),
        "deviceId":     _pick(d, "deviceId", "device_id"),
        "uid":          _pick(d, "uid", "userId", "user_id"),
        "_src": src,
        "_name": name,
    }


def _load_one(raw: dict, name: str) -> dict:
    # 1) 明文 token 直给
    if raw.get("accessToken"):
        return _from_decrypted(raw, "accounts.json(明文token)", name or raw.get("uid", name))
    # 2) 直接给桌面端凭据串
    if raw.get("icubeAuth"):
        d = json.loads(decrypt_storage_value(raw["icubeAuth"].strip()))
        return _from_decrypted(d, "accounts.json(icubeAuth)", name)
    # 3) 指定 storage.json 路径
    if raw.get("storagePath"):
        d = load_from_storage(raw["storagePath"])
        return _from_decrypted(d, raw["storagePath"], name)
    raise ValueError("账号 %s 缺少 accessToken / icubeAuth / storagePath" % (name or "(未命名)"))


def load_accounts() -> list:
    # 1) 多账号：TRAE_ACCOUNTS 为 JSON 数组（推荐，全部走环境变量）
    #    例: set TRAE_ACCOUNTS=[{"accessToken":"...","refreshToken":"...","uid":"账号1"},
    #                           {"icubeAuth":"<base64串>","uid":"账号2"}]
    raw_list = os.getenv("TRAE_ACCOUNTS", "").strip()
    if raw_list:
        try:
            data = json.loads(raw_list)
        except Exception as e:
            print(f"❌ [凭据] TRAE_ACCOUNTS 不是合法 JSON: {e}", file=sys.stderr)
            sys.exit(1)
        if isinstance(data, dict):
            data = [data]
        accounts = []
        for i, raw in enumerate(data):
            try:
                acc = _load_one(raw, raw.get("name", f"账号{i+1}"))
                accounts.append(acc)
            except Exception as e:
                print(f"❌ [凭据] 账号{i+1} 加载失败: {e}", file=sys.stderr)
        accounts = apply_token_cache(accounts)

        # TRAE_ONLY 支持按序号(从1开始)、uid 或名字过滤，便于青龙拆分定时任务错峰签到
        only = os.getenv("TRAE_ONLY", "").strip()
        if only:
            picked = []
            for i, a in enumerate(accounts):
                if only == str(i + 1) or only == str(a.get("uid")) or only == a.get("_name"):
                    picked.append(a)
            if picked:
                print(f"🎯 [筛选] TRAE_ONLY={only} -> 仅处理 {len(picked)} 个账号")
                return picked
            print(f"⚠️ [筛选] TRAE_ONLY={only} 未匹配到账号，将处理全部", file=sys.stderr)

        if accounts:
            return accounts
        print("❌ [凭据] TRAE_ACCOUNTS 中没有任何可用账号。", file=sys.stderr)
        sys.exit(1)

    # 2) 兼容旧脚本部署：只给 TRAE_REFRESH_TOKEN（_2.._9 后缀 = 多账号），
    #    accessToken 留空由 process_account 自动续期换取，真正零依赖。
    rts = []
    for name in ["TRAE_REFRESH_TOKEN"] + [f"TRAE_REFRESH_TOKEN_{i}" for i in range(2, 10)]:
        v = os.getenv(name, "").strip()
        if v:
            rts.append((name, v))
    if rts and not os.getenv("TRAE_ACCESS_TOKEN"):
        accs = []
        for name, v in rts:
            idx = "1" if name == "TRAE_REFRESH_TOKEN" else name.split("_")[-1]
            accs.append({
                "accessToken":  os.getenv(f"TRAE_ACCESS_TOKEN_{idx}", "").strip(),
                "refreshToken": v,
                "deviceId":     os.getenv(f"TRAE_DEVICE_ID_{idx}", "").strip(),
                "uid":          os.getenv(f"TRAE_UID_{idx}", "").strip(),
                "name":         os.getenv(f"TRAE_NAME_{idx}", "") or f"账号{idx}",
            })
        accs = apply_token_cache(accs)
        print(f"🔁 [兼容] 从 TRAE_REFRESH_TOKEN* 读到 {len(accs)} 个账号，accessToken 将自动续期换取")
        return accs

    # 3) 单账号：原环境变量用法（兼容）
    if os.getenv("TRAE_ACCESS_TOKEN") or os.getenv("TRAE_ICUBE_AUTH") or os.getenv("TRAE_STORAGE_PATH"):
        if os.getenv("TRAE_ICUBE_AUTH"):
            acc = _from_decrypted(json.loads(decrypt_storage_value(os.getenv("TRAE_ICUBE_AUTH").strip())),
                                  "环境变量 TRAE_ICUBE_AUTH")
            acc["deviceId"] = os.getenv("TRAE_DEVICE_ID", "")
        elif os.getenv("TRAE_STORAGE_PATH"):
            acc = _from_decrypted(load_from_storage(os.getenv("TRAE_STORAGE_PATH")),
                                  os.getenv("TRAE_STORAGE_PATH"))
            acc["deviceId"] = os.getenv("TRAE_DEVICE_ID", "")
        else:
            acc = {
                "accessToken":  os.getenv("TRAE_ACCESS_TOKEN", ""),
                "refreshToken": os.getenv("TRAE_REFRESH_TOKEN", ""),
                "deviceId":     os.getenv("TRAE_DEVICE_ID", ""),
                "uid":          os.getenv("TRAE_UID", ""),
                "name":         os.getenv("TRAE_NAME", "环境变量账号"),
            }
        return [acc]

    print("❌ [凭据] 未找到账号配置。可选写法：TRAE_ACCOUNTS(JSON数组，推荐) / TRAE_REFRESH_TOKEN(_2.._9) / TRAE_ACCESS_TOKEN+TRAE_REFRESH_TOKEN / TRAE_ICUBE_AUTH / TRAE_STORAGE_PATH", file=sys.stderr)
    sys.exit(1)


# ========================= 请求 =========================
def _ug_headers(access_token: str, device_id: str) -> dict:
    # 签接口要求 16 位数字设备号，缺了会返回 9004(参数不正确)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": UA,
        "Authorization": "Cloud-IDE-JWT " + access_token,
        "X-User-Region": "CN",
    }
    if device_id:
        headers["x-device-id"] = device_id
    return headers


# 直连不走代理（关键：系统代理/Clash 会触发限流）
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def _post(url: str, headers: dict, payload: bytes = b"{}", timeout: int = 30):
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def query_points(auth: dict):
    """查询当前积分余额（entitlement API，参考脚本同款）。"""
    host = "https://api.trae.cn"
    path = "/trae/api/v2/pay/user_current_entitlement_list"
    headers = _ug_headers(auth["accessToken"], auth.get("deviceId"))
    status, text = _post(host + path, headers, b'{"require_usage": true}', timeout=15)
    try:
        data = json.loads(text)
        packs = (((data.get("data") or {}).get("user_entitlement_pack_list")) or [])
        total = 0
        found = False
        for p in packs:
            limit = ((((p.get("entitlement_base_info") or {}).get("quota")) or {})
                     .get("credits_limit")) or 0
            used = (((p.get("usage") or {}).get("credits_amount"))) or 0
            if limit > 0:
                found = True
                total += max(limit - used, 0)
        if found:
            return total
    except Exception:
        pass
    return None


def refresh_access_token(auth: dict):
    if not auth.get("refreshToken"):
        return False, "无 refreshToken，无法刷新"
    body = json.dumps({
        "ClientID": ClientID,
        "RefreshToken": auth["refreshToken"],
        "ClientSecret": "-",
        "UserID": "",
    }).encode("utf-8")
    status, text = _post(EP_EXCHANGE, {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": UA,
    }, body)
    if status >= 400:
        return False, f"刷新失败 http={status} {text[:200]}"
    try:
        data = json.loads(text)["Result"]
        auth["accessToken"] = data["Token"]
        if data.get("RefreshToken"):
            auth["refreshToken"] = data["RefreshToken"]
        cache_tokens(auth)
        _save_tokens_to_file(auth)
    except Exception as e:
        return False, f"解析刷新响应失败: {e} body={text[:200]}"
    return True, "已刷新 accessToken"


def _save_tokens_to_file(auth: dict):
    """若本机存有该账号的凭据文件 trae-<uid>*.json，把续期结果写回去。
    目录可用 TRAE_ACCOUNT_DIR 指定，默认取脚本所在目录（青龙下通常没有该文件，
    静默跳过即可，token 仍会保存在 .trae_token_cache.json 里）。"""
    uid = str(auth.get("uid", "") or "").strip()
    if not uid:
        return
    import glob as _g
    here = os.path.dirname(os.path.abspath(__file__))
    dirs = [os.getenv("TRAE_ACCOUNT_DIR", "").strip(), here]
    files = []
    for d in dirs:
        if d and os.path.isdir(d):
            files += _g.glob(os.path.join(d, f"trae-{uid}*.json"))
    if not files:
        return
    fp = files[0]
    try:
        with open(fp, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if "auth" in d:
            d["auth"]["accessToken"] = auth["accessToken"]
            d["auth"]["refreshToken"] = auth["refreshToken"]
        else:
            d["accessToken"] = auth["accessToken"]
            d["refreshToken"] = auth["refreshToken"]
        with open(fp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=2)
        print(f"💾 [持久化] 已更新 {os.path.basename(fp)}")
    except Exception as e:
        print(f"⚠️ [持久化] 写回失败: {e}")


def checkin_status(auth: dict):
    status, text = _post(EP_STATUS, _ug_headers(auth["accessToken"], auth.get("deviceId")))
    if status >= 400:
        return None, None, None, f"http={status} {text[:200]}"
    try:
        d = json.loads(text)
    except Exception:
        return None, None, None, f"解析失败 {text[:200]}"
    return (d.get("checked_in", False), d.get("credits", 0), d.get("enable", False), text)


def checkin_claim(auth: dict):
    """签到领取积分。以业务 code 为准：
       code=0  成功；code=9095 今日已签；code=9074 参与用户太多(可重试)；其它失败。
       遇到 9074 自动退避重试若干次（服务端限流，稍后通常可成）。"""
    import time as _t
    import random as _rand
    last_code, last_msg = "?", ""
    # 9074 属于服务端排队限流，短时间内反复轰会被延长惩罚。
    # 默认只试 1 次，失败交给青龙下一轮 cron（配合当日状态文件，只补失败的账号）。
    # 需要时可设 CLAIM_TRIES=2/3。
    try:
        max_retries = max(1, int(os.getenv("CLAIM_TRIES", "1")))
    except Exception:
        max_retries = 1
    for attempt in range(1, max_retries + 1):
        status, text = _post(EP_CLAIM, _ug_headers(auth["accessToken"], auth.get("deviceId")))
        try:
            body = json.loads(text)
            code = body.get("code", -1)
            msg = body.get("message") or text
        except Exception:
            code = "?"
            msg = text
        last_code, last_msg = code, msg
        if code == 0:
            return True, code, msg
        if code == 9095:
            return False, code, msg
        if code == 1001 and auth.get("refreshToken"):
            print(f"🔑 [claim] 检测到 code=1001，尝试刷新 token ...")
            ok, _ = refresh_access_token(auth)
            if not ok:
                return False, code, msg
            continue  # 刷新后立即重试，不做限流退避
        # 9074=限流 或 HTTP 429/5xx：指数退避+随机抖动
        is_rate = code == 9074 or (status and status in (429, 500, 502, 503, 504))
        if is_rate and attempt < max_retries:
            wait = _rand.randint(4, 9)
            print(f"⏳ [限流] 第{attempt}次被限，{wait}s 后重试（或交给下轮 cron）...")
            _t.sleep(wait)
            continue
        if is_rate:
            print(f"⏳ [限流] 本轮放弃，等下轮 cron 自动补签")
        if not is_rate and code != 9074:
            return False, code, msg
    return False, last_code, last_msg


# ========================= 单个账号处理 =========================
def process_account(auth: dict) -> dict:
    name = (auth.get("_name") or auth.get("name")
            or auth.get("uid") or "(未知)")
    result = {"name": name, "uid": auth.get("uid", "-"), "icon": "✅",
              "status": "失败", "credits": "-", "detail": "", "_claimed": False}

    if not auth.get("accessToken"):
        if auth.get("refreshToken"):
            ok, msg = refresh_access_token(auth)
            if not ok:
                result["status"] = "token失效"; result["detail"] = msg
                return result
        else:
            result["status"] = "无token"; result["detail"] = "解密后无 token"
            return result

    # 解析设备号（自动生成+持久化）
    auth["deviceId"] = resolve_device_id(auth, auth.get("deviceId", ""))
    print(f"📱 [设备号] {name}: {auth['deviceId']}")

    log_box_open(f"📡 {name} 签到状态查询")
    checked_in, credits, enable, raw_text = checkin_status(auth)

    # 检测鉴权失败 (code=1001) 并自动刷新 token 重试
    if raw_text and '"code":1001' in raw_text.replace(" ", ""):
        if auth.get("refreshToken"):
            print(f"🔑 [刷新] 检测到 code=1001 鉴权失败，尝试刷新 token ...")
            ok, msg = refresh_access_token(auth)
            if ok:
                print(f"✅ [刷新] token 已更新")
                checked_in, credits, enable, raw_text = checkin_status(auth)
            else:
                print(f"❌ [刷新] 失败: {msg}")

    print(f"📊 [状态] 今日已签: {checked_in}   积分: {credits}   开放: {enable}")

    if checked_in:
        pts = query_points(auth)
        result["icon"] = "☑️"; result["status"] = "已签到"
        result["credits"] = pts if pts is not None else credits
        result["detail"] = f"今日已签，积分余额 {result['credits']:,.2f}" if pts is not None else f"今日已签，积分 {credits}"
        print(f"☑️  [结果] 今日已签到")
        return result
    # 状态查询拿到的是鉴权失败（刷新后仍 1001）→ 硬失败，绝不浪费 claim 请求
    rt = (raw_text or "").replace(" ", "")
    if '"code":1001' in rt:
        result["icon"] = "🔑"; result["status"] = "鉴权失败"
        result["detail"] = "token 无效且自动续期失败，需重新登录取新 refreshToken"
        print(f"❌ [结果] 鉴权失败（硬失败）")
        return result

    # 状态查询本身不通（HTTP 异常 / 非 JSON）→ 先不发 claim，等下一轮
    if checked_in is None:
        result["icon"] = "⏳"; result["status"] = "待重试"
        result["detail"] = f"状态查询未成功，本轮不发起 claim：{(raw_text or '')[:70]}"
        print(f"⏳ [结果] 状态不可用，跳过 claim")
        return result

    # 服务端明确 enable=false 且鉴权正常 → 该账号确实没开放签到，
    # 继续发 claim 只会白烧限流额度并拖累其它账号，直接判定未开放。
    if enable is False:
        result["icon"] = "🚫"; result["status"] = "未开放"
        result["detail"] = "该账号未开放签到（enable=false），不再重复请求"
        print(f"🚫 [结果] 未开放签到")
        mark_done(str(auth.get("uid") or auth.get("_name") or ""),
                  {"status": "未开放", "credits": "-", "at": now_text()})
        return result

    result["_claimed"] = True          # 只有真正发过 claim 才需要账号间错峰
    claim_ok, claim_code, claim_msg = checkin_claim(auth)
    # 以 claim 业务 code 为准，避免积分未变导致误判
    if claim_ok:
        # 用 entitlement API 查询实际积分余额（比 status 更准确）
        pts = query_points(auth)
        if pts is not None:
            result["status"] = "签到成功"
            result["credits"] = pts
            result["detail"] = f"签到成功（code=0），当前积分余额 {pts:,.2f}"
        else:
            _, credits_after, _, _ = checkin_status(auth)
            result["status"] = "签到成功"
            result["credits"] = credits_after if credits_after is not None else credits
            result["detail"] = f"签到成功（code=0），积分 {credits} → {result['credits']}"
        print(f"🎉 [结果] 签到成功")
    elif claim_code == 9095:
        result["icon"] = "☑️"; result["status"] = "已签到"
        result["credits"] = credits
        result["detail"] = "今日已签到(9095)"
        print(f"☑️  [结果] 今日已签到")
    elif claim_code == 9074:
        result["icon"] = "⏳"; result["status"] = "待重试"
        result["detail"] = "参与用户太多(9074)，本轮未签成，下轮 cron 自动补签"
        print(f"⏳ [结果] {result['detail']}")
    else:
        result["icon"] = "❌"; result["status"] = "失败"
        result["detail"] = f"code={claim_code}: {claim_msg}"
        print(f"❌ [结果] 签到失败: {claim_msg}")
    return result


# ========================= 推送 =========================
def send_qywx(title: str, content: str) -> bool:
    if not QYWX_TOKEN:
        return False
    key = QYWX_TOKEN.split("key=")[-1].strip()
    try:
        text = f"{title}\n{content}"
        if len(text.encode("utf-8")) > 2000:
            text = text.encode("utf-8")[:2000].decode("utf-8", "ignore")
        payload = json.dumps({"msgtype": "text", "text": {"content": text}}).encode("utf-8")
        req = urllib.request.Request(
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=" + key,
            data=payload, headers={"Content-Type": "application/json"})
        res = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
        ok = res.get("errcode") == 0
        print(f"{'✅' if ok else '❌'} [企业微信] 推送{'成功' if ok else '失败'} errcode={res.get('errcode')}")
        return ok
    except Exception as e:
        print(f"❌ [企业微信] 推送异常: {e}")
        return False


def send_pushplus(title: str, content: str) -> None:
    send_qywx(title, content)
    if not PLUSPLUS_TOKEN:
        return
    try:
        req = urllib.request.Request(
            "https://www.pushplus.plus/send",
            data=json.dumps({
                "token": PLUSPLUS_TOKEN, "title": title,
                "content": content, "template": "txt",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10)
        print("✅ [PushPlus] 推送成功")
    except Exception as e:
        print(f"❌ [PushPlus] 推送失败: {e}")


# ========================= 主流程 =========================
def main() -> None:
    accounts = load_accounts()
    log_title(len(accounts))

    results = []
    state = load_state()
    pending = []
    for acc in accounts:
        key = _acct_key(acc)
        rec = (state.get("done") or {}).get(key)
        if rec:
            results.append({"name": (acc.get("_name") or acc.get("name") or key),
                            "uid": acc.get("uid", "-"),
                            "icon": "☑️", "status": "已签到",
                            "credits": rec.get("credits", "-"),
                            "detail": f"今日已完成（{rec.get('at','-')}），跳过请求"})
            print(f"☑️  [{acc.get('_name') or acc.get('name') or key}] 今日已签到，跳过")
        else:
            pending.append(acc)

    if not pending:
        print("✅ 全部账号今日均已完成，无需请求接口")

    import random as _rand
    import time as _t
    prev_claimed = False
    for idx, acc in enumerate(pending):
        # 只有上一次真的发过 claim 才需要错峰；纯只读的 status 查询不必等待，
        # 否则"全部已签到"的巡检也要白等一分多钟。
        if idx > 0 and prev_claimed:
            gap = _rand.randint(12, 25)   # 实测 25s 间隔可让相邻账号连续签到成功
            print(f"\n⏳ [间隔] 等待 {gap} 秒后处理下一个账号...")
            _t.sleep(gap)
        try:
            r = process_account(acc)
            if r["status"] == "待重试":
                # 命中限流说明当前出口 IP 已在惩罚窗口内，
                # 继续打后面的账号只会一起失败并延长窗口 —— 直接收工等下一轮。
                results.append(r)
                rest = len(pending) - idx - 1
                if rest > 0:
                    print(f"⏭  [熔断] 命中限流，跳过剩余 {rest} 个账号，等下一轮 cron")
                break
            if r["status"] in ("签到成功", "已签到"):
                mark_done(_acct_key(acc),
                          {"status": r["status"], "credits": r.get("credits"),
                           "at": now_text()})
            prev_claimed = bool(r.get("_claimed"))
            results.append(r)
        except Exception as e:
            prev_claimed = False
            results.append({"name": acc.get("_name", "?"), "uid": acc.get("uid", "-"),
                            "icon": "❌", "status": "异常", "credits": "-", "detail": str(e)})

    SOFT = ("待重试",)          # 限流类，下一轮 cron 会自动补签，不算失败
    DEAD = ("未开放", "鉴权失败")  # 需要人工处理
    ok_n = sum(1 for r in results if r["status"] == "签到成功")
    already_n = sum(1 for r in results if r["status"] == "已签到")
    soft_n = sum(1 for r in results if r["status"] in SOFT)
    dead_n = sum(1 for r in results if r["status"] in DEAD)
    fail_n = len(results) - ok_n - already_n - soft_n - dead_n

    print()
    print("╔" + "═" * 52 + "╗")
    print(f"║ 🏁 Trae SOLO 签到完成                        ║")
    print(f"║ ✅ 成功 {ok_n:<3} ☑️ 已签 {already_n:<3} ⏳ 待重试 {soft_n:<3} ❌ 失败 {fail_n + dead_n:<3}      ║")
    print(f"║ 🕒 结束时间: {now_text():<34}║")
    print("╚" + "═" * 52 + "╝")

    notify = (
        f"🤖 Trae SOLO 多账号签到\n"
        f"━━━━━━━━━━━━━━\n"
        f"🕒 时间：{now_text()}\n"
        f"✅ 成功 {ok_n}  ☑️ 已签 {already_n}  ⏳ 待重试 {soft_n}  ❌ 失败 {fail_n + dead_n}\n"
        f"━━━━━━━━━━━━━━\n"
    )
    for r in results:
        notify += f"{r['icon']} {r['name']}({r['uid']}): {r['status']} | {r['detail']}\n"

    send_pushplus("🤖 Trae SOLO 签到汇总", notify)


if __name__ == "__main__":
    main()
