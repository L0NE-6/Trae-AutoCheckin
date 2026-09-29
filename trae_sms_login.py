#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trae 网页登录取凭据（OAuth 版） · trae_sms_login.py
────────────────────────────────────────────────────────────
用 Trae 官网的**真实网页登录流程**换取 refreshToken。脚本只做三件事：
  ① 生成带 PKCE 的授权 URL，并打开你的默认浏览器；
  ② 在本机 127.0.0.1:17388 接住官网跳回来的回调（AuthCode）；
  ③ 用 AuthCode 调 ExchangeToken 换取新凭据并打印。

✨ 为什么换成这条路（改造说明）
  • 登录 / 短信验证码 / 滑块全部发生在**官网页面**里，脚本不碰风控接口 ——
    机房 IP、代理 IP 不再是障碍（旧纯接口版会被 1105 滑块直接拦死）。
  • AuthCode 兑换**不需要设备私钥**，只要本机客户端设备身份里的公钥，链路更短。
  • 旧接口版（passport 发码 + mix_mode 混淆）已删除，本文件即换代后的实现。

✨ 特性
  • 零依赖      纯标准库（手写 PKCE / 回调解析 / 本地回调服务器）
  • 免短信接口  不发码、不校验码，短信与滑块交给浏览器里的官网
  • 双产品线    默认 Trae(IDE) 线；--solo 切 SOLO 线
  • 强制续期项  AuthCode 兑换必须同时拿到 RefreshToken，缺了直接报错不落库

🚀 使用方法
  1. 本机装有 Trae 客户端并**登录过一次**（脚本要从它的 storage.json 取设备身份）
  2. 运行：python trae_sms_login.py
  3. 在弹出的浏览器里完成登录 → 终端打印 refreshToken / accessToken
  4. 把终端给出的 JSON 条目加进 TRAE_ACCOUNTS / 青龙环境变量

  python trae_sms_login.py --solo         # SOLO 产品线（TRAE SOLO 客户端）
  python trae_sms_login.py --no-open      # 只打印授权 URL，自己手动打开
  python trae_sms_login.py --timeout 600  # 等回调的秒数（默认 300）
  python trae_sms_login.py --selftest     # 离线自检（不联网、不占端口）

⚠️ 注意
  • 回调端口**固定 17388**：官网靠探测这个端口判断「客户端在线」，
    换端口或端口被占都会导致页面卡在「认证中」——被占时先退出 Trae 客户端。
  • 回调只绑 127.0.0.1，不对外网开放；结果保存到 trae_sms_accounts.json。
────────────────────────────────────────────────────────────
"""
import argparse
import base64
import hashlib
import http.server
import json
import os
import platform
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ══════════════════ 协议常量（2026-09 抓包固化，勿按语义改写） ══════════════════
CONSOLE_BASE = "https://www.trae.cn"        # 授权页域（国内）
ACCOUNT_BASE = "https://api.trae.cn"        # 兑换端点兜底 host（回调未回传 host 时用）
ICUBE_BASE = "https://api.trae.com.cn"      # 旧端点域
AUTHORIZE_PATH = "/authorization"
CALLBACK_PATH = "/authorize"
CALLBACK_PORT = 17388                        # ★ 必须固定，见文件头说明
EXCHANGE_PATH = "/trae/api/v3/oauth/ExchangeToken"
LEGACY_EXCHANGE_PATH = "/cloudide/api/v3/trae/oauth/ExchangeToken"
OAUTH_APP_ID = "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"
DEF_APP_VERSION = "3.3.100"                  # 客户端版本兜底（可用 TRAE_APP_VERSION 覆盖）
DEF_PLUGIN_VERSION = "2.3.83560"             # 插件/构建版本兜底（可用 TRAE_PLUGIN_VERSION 覆盖）
LOGIN_TIMEOUT = 300                          # 等回调默认超时（秒）

# 产品线配置：授权 URL 与兑换请求**必须**用同一份，保证「同一把钥匙」
LINES = {
    "trae": {"auth_from": "trae", "client_id": "ono9krqynydwx5",
             "platform": "IDE_PC", "hide_saas": False, "label": "Trae (IDE)"},
    "solo": {"auth_from": "solo", "client_id": "en1oxy7wnw8j9n",
             "platform": "SOLO_PC", "hide_saas": True, "label": "SOLO"},
}

# 回调里出现任一参数 ⇒ 是真回调；一个都没有 ⇒ 只是官网的在线探测
CRED_MARKERS = ("authCodeInfo", "code", "accessToken", "access_token",
                "refreshToken", "refresh_token")

ACCESS_TOKEN_KEYS = ("AccessToken", "access_token", "token", "Jwt", "JWT")
REFRESH_TOKEN_KEYS = ("RefreshToken", "refresh_token")

# 当前兑换用的产品线（exchange_auth_code 里按所选产品线覆盖）
LINES_CURRENT = {"platform": "IDE_PC"}

# ══════════════════ 客户端 storage.json 解密（与 trae_get_token.py 同源实现） ══════════════════
SALT_A = bytes([82, 9, 106, 213, 48, 54, 165, 56, 191, 64, 163, 158, 129, 243, 215, 251, 124, 227, 57, 130, 155, 47, 255, 135, 52, 142, 67, 68, 196, 222, 233, 203, 84, 123, 148, 50, 166, 194, 35, 61, 238, 76, 149, 11, 66, 250, 195, 78, 8, 46, 161, 102, 40, 217, 36, 178, 118, 91, 162, 73, 109, 139, 209, 37])
SALT_B = bytes([31, 221, 168, 51, 136, 7, 199, 49, 177, 18, 16, 89, 39, 128, 236, 95, 96, 81, 127, 169, 25, 181, 74, 13, 45, 229, 122, 159, 147, 201, 156, 239, 160, 224, 59, 77, 174, 42, 245, 176, 200, 235, 187, 60, 131, 83, 153, 97, 23, 43, 4, 126, 186, 119, 214, 38, 225, 105, 20, 99, 85, 33, 12, 125])
SALT_AES = bytes(a ^ b for a, b in zip(SALT_A, SALT_B))


def _gmul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def _build_sbox():
    inv = [0] * 256
    for i in range(1, 256):
        for j in range(1, 256):
            if _gmul(i, j) == 1:
                inv[i] = j
                break
    sb = [0] * 256
    for i in range(256):
        x = inv[i] if i else 0
        s = x
        for _ in range(4):
            x = ((x << 1) | (x >> 7)) & 0xFF
            s ^= x
        sb[i] = s ^ 0x63
    return sb


SBOX = _build_sbox()
INV = [0] * 256
for _i, _v in enumerate(SBOX):
    INV[_v] = _i
RC = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _expand(key):
    w = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = w[i - 1][:]
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= RC[i // 4 - 1]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return w


def _rk(w, r):
    ws = w[r * 4:r * 4 + 4]
    return [ws[c][k] for c in range(4) for k in range(4)]


def _addrk(s, k):
    return [s[i] ^ k[i] for i in range(16)]


def _isub(s):
    return [INV[b] for b in s]


def _ishift(s):
    return [s[0], s[13], s[10], s[7], s[4], s[1], s[14], s[11], s[8], s[5], s[2], s[15], s[12], s[9], s[6], s[3]]


def _imix(s):
    o = []
    for c in range(4):
        a = s[c * 4:c * 4 + 4]
        o += [_gmul(a[0], 14) ^ _gmul(a[1], 11) ^ _gmul(a[2], 13) ^ _gmul(a[3], 9),
              _gmul(a[0], 9) ^ _gmul(a[1], 14) ^ _gmul(a[2], 11) ^ _gmul(a[3], 13),
              _gmul(a[0], 13) ^ _gmul(a[1], 9) ^ _gmul(a[2], 14) ^ _gmul(a[3], 11),
              _gmul(a[0], 11) ^ _gmul(a[1], 13) ^ _gmul(a[2], 9) ^ _gmul(a[3], 14)]
    return o


def aes128_cbc_decrypt(key, iv, data):
    w = _expand(key)
    out = b""
    prev = list(iv)
    for off in range(0, len(data), 16):
        blk = list(data[off:off + 16])
        s = _addrk(blk, _rk(w, 10))
        for r in range(9, 0, -1):
            s = _ishift(s)
            s = _isub(s)
            s = _addrk(s, _rk(w, r))
            s = _imix(s)
        s = _ishift(s)
        s = _isub(s)
        s = _addrk(s, _rk(w, 0))
        out += bytes(a ^ b for a, b in zip(s, prev))
        prev = blk
    return out


def decrypt_storage_value(b64):
    buf = base64.b64decode(b64)
    rb, enc = buf[6:38], buf[38:]
    h = hashlib.sha512(rb).digest()
    fh = hashlib.sha512(h + SALT_AES).digest()
    pt = aes128_cbc_decrypt(fh[:16], fh[16:32], enc)[64:]
    pad = pt[-1] if pt else 0
    if 1 <= pad <= 16:
        return pt[:-pad]
    return pt.rstrip(b"\x00").rstrip()


def candidate_paths():
    home = os.path.expanduser("~")
    names = ("Trae CN", "TRAE SOLO CN", "TRAE SOLO", "Trae")
    sub = ("User", "globalStorage", "storage.json")
    ad = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    for n in names:
        p = os.path.join(ad, n, *sub)
        if os.path.isfile(p):
            yield p
    lib = os.path.join(home, "Library", "Application Support")
    for n in names:
        p = os.path.join(lib, n, *sub)
        if os.path.isfile(p):
            yield p
    for base in (home, os.path.join(home, ".config")):
        for n in (".trae-cn", ".trae", "Trae CN", "TRAE SOLO CN"):
            p = os.path.join(base, n, *sub)
            if os.path.isfile(p):
                yield p


def load_device_identity(storage_path=None):
    """取设备身份：device_id / 公钥 / machineId。

    优先级：环境变量（TRAE_DEVICE_ID + TRAE_DEVICE_PUB_PEM） > storage.json。
    授权 URL 的 device_id 与兑换请求体必须同源，所以这里只返回一份。
    """
    env_id = (os.environ.get("TRAE_DEVICE_ID") or "").strip()
    env_pub = (os.environ.get("TRAE_DEVICE_PUB_PEM") or "").replace("\\n", "\n").strip()
    env_mid = (os.environ.get("TRAE_MACHINE_ID") or "").strip()
    if env_id and env_pub:
        return {"device_id": env_id, "public_key": env_pub,
                "machine_id": env_mid, "from": "env"}
    paths = [storage_path] if storage_path else list(candidate_paths())
    for p in paths:
        try:
            s = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        did = ""
        for k in s:
            if k.startswith("iCubeAuthInfo://icube-dc:"):
                d = k.split(":")[-1]
                if d.isdigit():
                    did = d
                    break
        if not did:
            continue
        enc = s.get("iCubeAuthInfo://icube-dc:%s" % did)
        if not enc:
            continue
        try:
            dev = json.loads(decrypt_storage_value(enc.strip()).decode("utf-8", "replace"))
        except Exception:
            continue
        pub = (dev.get("publicKeyPEM") or "").strip()
        if pub:
            return {"device_id": did, "public_key": pub,
                    "machine_id": (s.get("telemetry.machineId") or "").strip(), "from": p}
    return None


# ══════════════════ 客户端侧事实（URL 与请求体共用同一份） ══════════════════
def system_facts():
    return {
        "os_name": platform.system() or "Windows",
        "os_version": platform.release() or "",
        "device_model": (os.environ.get("TRAE_DEVICE_MODEL") or "").strip(),
        "device_manufacturer": (os.environ.get("TRAE_DEVICE_BRAND") or "").strip(),
        "cpu_brand": (os.environ.get("TRAE_DEVICE_CPU") or "").strip() or (platform.processor() or ""),
        "device_name": (os.environ.get("TRAE_DEVICE_NAME") or "").strip() or platform.node() or "",
    }


def machine_id_of(dev):
    """machineId 缺失时的兜底：由 device_id 派生一个稳定值（URL 与请求体同源）。"""
    mid = (dev.get("machine_id") or "").strip()
    if mid:
        return mid
    return hashlib.sha256(("trae-oauth-machine:" + dev["device_id"]).encode()).hexdigest()[:32]


def app_versions():
    return ((os.environ.get("TRAE_APP_VERSION") or "").strip() or DEF_APP_VERSION,
            (os.environ.get("TRAE_PLUGIN_VERSION") or "").strip() or DEF_PLUGIN_VERSION)


# ══════════════════ PKCE / 授权 URL ══════════════════
def pkce_pair():
    verifier = secrets.token_hex(32)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(line, dev, sysf, port, trace_id, code_challenge):
    cfg = LINES[line]
    app_version, plugin_version = app_versions()
    callback = "http://127.0.0.1:%d%s" % (port, CALLBACK_PATH)
    params = [
        ("login_version", "1"),
        ("auth_from", cfg["auth_from"]),
        ("login_channel", "native_ide"),
        ("plugin_version", plugin_version),
        ("auth_type", "local"),
        ("client_id", cfg["client_id"]),
        ("redirect", "0"),
        ("login_trace_id", trace_id),
        ("auth_callback_url", callback),
        ("machine_id", machine_id_of(dev)),
        ("device_id", dev["device_id"]),
        ("x_device_id", dev["device_id"]),
        ("x_machine_id", machine_id_of(dev)),
        ("x_device_brand", sysf["device_model"]),
        ("x_device_type", sysf["os_name"]),
        ("x_os_version", sysf["os_version"]),
        ("x_env", ""),
        ("x_app_version", app_version),
        ("x_app_type", "stable"),
        ("code_challenge", code_challenge),
        ("code_challenge_method", "S256"),
        ("channel_name", "common"),
    ]
    if cfg["hide_saas"]:
        params.append(("hide_saas_login", "true"))
    return CONSOLE_BASE + AUTHORIZE_PATH + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


# ══════════════════ 回调解析 ══════════════════
def parse_query(raw):
    """回调查询串解析：先按 & 切分（原串），再对每段反复解码（≤3 次），最后切 =。

    这样处理官方对 auth_callback_url 的二次编码（值里现成的 %26 不会被误切）。
    """
    out = {}
    for pair in raw.split("&"):
        if not pair:
            continue
        s = pair
        for _ in range(3):
            n = urllib.parse.unquote_plus(s)
            if n == s:
                break
            s = n
        k, _, v = s.partition("=")
        out[k] = v
    return out


def has_credential_marker(params):
    return any(k in params for k in CRED_MARKERS)


def _param(params, keys):
    for k in keys:
        v = (params.get(k) or "").strip()
        if v:
            return v
    return ""


def parse_callback(params):
    """解析回调参数 → dict。authCodeInfo 解析失败必须报错（不吞异常）。"""
    info = {"auth_code": "", "refresh_token": "",
            "host": _param(params, ("host",)),
            "user_region": _param(params, ("userRegion", "user_region")),
            "trace": _param(params, ("loginTraceID", "login_trace_id")),
            "uid": "", "name": "", "avatar": ""}
    raw = params.get("authCodeInfo")
    if raw and raw.strip():
        data = json.loads(raw)          # 抛错由上层兜住并提示「回调格式异常」
        ac = str(data.get("AuthCode") or "").strip()
        if ac:
            info["auth_code"] = ac
    if not info["auth_code"]:
        info["auth_code"] = _param(params, ("code",))
    for k in ("refreshToken", "refresh_token", "RefreshToken"):
        v = (params.get(k) or "").strip().strip('"').strip()
        if v:
            info["refresh_token"] = v
            break
    user_info = {}
    raw_ui = params.get("userInfo") or params.get("user_info") or params.get("UserInfo")
    if raw_ui:
        try:
            user_info = json.loads(raw_ui)
        except Exception:
            user_info = {}
    if isinstance(user_info, dict):
        info["uid"] = str(user_info.get("UserID") or user_info.get("userId")
                         or _param(params, ("UserID", "userId", "user_id")) or "")
        for k in ("ScreenName", "NickName", "nickname", "nickName", "name", "userName", "email"):
            v = str(user_info.get(k) or "").strip()
            if v:
                info["name"] = v
                break
        if not info["name"]:
            info["name"] = _param(params, ("userName", "user_name", "nickname"))
        info["avatar"] = str(user_info.get("AvatarUrl") or _param(params, ("avatar",)))
    return info


# ══════════════════ AuthCode → Token 兑换 ══════════════════
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _post_json(url, headers, payload, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, "请求异常: %s" % e


def build_main_payload(client_id, auth_code, verifier, dev, sysf):
    app_version, _ = app_versions()
    return {
        "ClientID": client_id,
        "AuthCode": auth_code,
        "CodeVerifier": verifier,
        "DeviceInfo": {
            "DeviceID": dev["device_id"],
            "MachineID": machine_id_of(dev),
            "PlatformCode": LINES_CURRENT["platform"],
            "DeviceType": "PC",
            "DeviceName": sysf["device_name"],
            "DeviceModel": sysf["device_model"],
            "ClientVersion": app_version,
            "DevicePublicKey": dev["public_key"],
            "DeviceBrand": sysf["device_manufacturer"],
            "DeviceCPU": sysf["cpu_brand"],
            "OSInfo": sysf["os_name"],
            "OSVersion": sysf["os_version"],
        },
        "IDEVersion": app_version,
    }


def build_legacy_payload(client_id, auth_code, verifier, dev, code_key):
    return {
        "ClientID": client_id,
        code_key: auth_code,
        "CodeVerifier": verifier,
        "DeviceID": dev["device_id"],
        "PlatformCode": LINES_CURRENT["platform"],
    }


def _search_tokens(node, keys):
    if isinstance(node, dict):
        for k in keys:
            v = node.get(k)
            if isinstance(v, str) and v:
                return v
        for k, v in node.items():
            if any(k.lower() == kk.lower() for kk in keys) and isinstance(v, str) and v:
                return v
        for v in node.values():
            r = _search_tokens(v, keys)
            if r:
                return r
    elif isinstance(node, list):
        for item in node:
            r = _search_tokens(item, keys)
            if r:
                return r
    return None


def find_token(body, keys):
    for c in ("Result", "data", "Data"):
        c2 = body.get(c)
        if c2 is not None:
            r = _search_tokens(c2, keys)
            if r:
                return r
    return _search_tokens(body, keys)


def _dig(body, path):
    node = body
    for key in path:
        if not isinstance(node, dict):
            return ""
        node = node.get(key)
    return str(node or "")


def try_exchange_variant(tag, url, payload, dev, platform, with_cloudide_token):
    """单个兑换变体；返回 (tokens|None, 错误文本)。"""
    app_version, _ = app_versions()
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "User-Agent": "Trae/%s" % app_version,
        "x-device-id": dev["device_id"],
        "x-app-id": OAUTH_APP_ID,
        "x-platform-code": platform,
    }
    if with_cloudide_token:
        headers["x-cloudide-token"] = ""      # 必须存在且为空串（缺了报 20403）
    status, text = _post_json(url, headers, payload)
    if status == -1:
        return None, "%s: %s" % (tag, text)
    try:
        body = json.loads(text)
    except Exception:
        return None, "%s: 非 JSON 响应（HTTP %s）: %s" % (tag, status, text[:180])
    code = _dig(body, ("ResponseMetadata", "Error", "Code"))
    if code and code != "0":
        msg = _dig(body, ("ResponseMetadata", "Error", "Message"))
        std = _dig(body, ("ResponseMetadata", "Error", "StandardCode"))
        return None, "%s: code=%s/%s %s" % (tag, code, std, msg)
    top = body.get("code")
    if isinstance(top, int) and top != 0:
        return None, "%s: code=%s %s" % (tag, top, body.get("message") or "")
    access = find_token(body, ACCESS_TOKEN_KEYS)
    refresh = find_token(body, REFRESH_TOKEN_KEYS)
    if access and refresh:
        return {"accessToken": access, "refreshToken": refresh}, None
    if access and not refresh:
        return None, "%s: 响应缺少 RefreshToken（无法续期，已拒绝）" % tag
    return None, "%s: 响应中未找到 Token（键：%s）" % (tag, " | ".join(sorted(body.keys()))[:160])


def exchange_auth_code(line, host, auth_code, verifier, dev, sysf):
    """三段兑换链（都不需要设备私钥）：主端点 DeviceInfo → 旧端点 AuthCode → 旧端点 Code。"""
    cfg = LINES[line]
    LINES_CURRENT["platform"] = cfg["platform"]
    main_url = (host or ACCOUNT_BASE).rstrip("/") + EXCHANGE_PATH
    legacy_url = ICUBE_BASE + LEGACY_EXCHANGE_PATH
    variants = [
        ("ExchangeToken/DeviceInfo", main_url,
         build_main_payload(cfg["client_id"], auth_code, verifier, dev, sysf), cfg["platform"], True),
        ("ExchangeToken/AuthCode", legacy_url,
         build_legacy_payload(cfg["client_id"], auth_code, verifier, dev, "AuthCode"), cfg["platform"], False),
        ("ExchangeToken/Code", legacy_url,
         build_legacy_payload(cfg["client_id"], auth_code, verifier, dev, "Code"), cfg["platform"], False),
    ]
    errors = []
    for tag, url, payload, platform, with_ct in variants:
        tokens, err = try_exchange_variant(tag, url, payload, dev, platform, with_ct)
        if tokens:
            return tokens, None
        errors.append(err)
    return None, "全部兑换变体失败 → " + " | ".join(errors)


# ══════════════════ 本地回调服务器（127.0.0.1:17388） ══════════════════
def _html_page(ok, title, lines):
    color = "#12b76a" if ok else "#f04438"
    icon = "✅" if ok else "❌"
    body = "".join("<p>%s</p>" % _esc(x) for x in lines)
    return ("<!doctype html><html><head><meta charset=\"utf-8\"><title>%s</title>"
            "<style>body{margin:0;font-family:system-ui,'Microsoft YaHei',sans-serif;background:#0b1220;"
            "color:#e5e7eb;display:flex;min-height:100vh;align-items:center;justify-content:center}"
            ".card{background:#111a2e;border:1px solid #1f2a44;border-radius:14px;padding:32px 40px;"
            "max-width:560px;box-shadow:0 10px 40px rgba(0,0,0,.4)}h1{font-size:20px;margin:0 0 12px;color:%s}"
            "p{margin:6px 0;color:#cbd5e1;line-height:1.6;font-size:14px}</style></head><body><div class=\"card\">"
            "<h1>%s %s</h1>%s</div></body></html>") % (_esc(title), color, icon, _esc(title), body)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def serve_until_callback(port, timeout, process):
    """监听回调；process(params) → ('probe',) 或 ('result', ok, title, lines)。"""
    state = {"done": False}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype):
            raw = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if raw:
                self.wfile.write(raw)

        def do_OPTIONS(self):
            self._send(204, "", "text/plain; charset=utf-8")

        def do_HEAD(self):
            self._send(200, "", "text/plain; charset=utf-8")

        def do_GET(self):
            self._handle()

        def do_POST(self):
            self._handle()

        def _handle(self):
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = parse_query(query)
            verdict = process(params)
            if verdict[0] == "probe":
                self._send(200, "ok", "text/plain; charset=utf-8")
                return
            _, ok, title, lines = verdict
            self._send(200, _html_page(ok, title, lines), "text/html; charset=utf-8")
            state["done"] = True

    try:
        httpd = http.server.HTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        return "端口 %d 被占用（%s）。\n   多半是 Trae 客户端正在运行 —— 先退出客户端再试。" % (port, e)
    httpd.timeout = 1.0
    deadline = time.monotonic() + timeout
    try:
        while not state["done"] and time.monotonic() < deadline:
            httpd.handle_request()
    finally:
        httpd.server_close()
    return None if state["done"] else "TIMEOUT"


# ══════════════════ 单次登录完整流程 ══════════════════
def jwt_uid(token):
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        return str(json.loads(base64.urlsafe_b64decode(p)).get("data", {}).get("id", ""))
    except Exception:
        return ""


def run_login(line, dev, sysf, args):
    cfg = LINES[line]
    trace_id = secrets.token_hex(16)
    verifier, challenge = pkce_pair()
    url = build_authorize_url(line, dev, sysf, CALLBACK_PORT, trace_id, challenge)

    print("╔" + "═" * 58 + "╗")
    print("║ 🤖 Trae 网页登录（OAuth） · %-30s║" % (cfg["label"],))
    print("╚" + "═" * 58 + "╝")
    print("📱 设备身份: %s（来源: %s）" % (dev["device_id"], str(dev.get("from"))[:52]))
    print("🌐 授权 URL 已生成：")
    print("   " + url)
    print()

    outcome = {"tokens": None, "error": None, "info": None}

    def process(params):
        if "error" in params and str(params.get("error") or "").strip():
            outcome["error"] = "授权被拒绝: %s" % params["error"]
            return ("result", False, "已取消授权", ["你在授权页拒绝了本次登录，可以关闭本页。"])
        if not has_credential_marker(params):
            return ("probe",)                       # 官网在线探测：回 ok 继续等
        lt = params.get("loginTraceID") or params.get("login_trace_id") or ""
        if lt and lt != trace_id:
            outcome["error"] = "回调 loginTraceID 校验失败（可能的 CSRF）"
            return ("result", False, "登录失败", ["登录校验失败，请重新发起登录。"])
        try:
            cb = parse_callback(params)
        except Exception as e:
            outcome["error"] = "authCodeInfo 解析失败: %s" % e
            return ("result", False, "登录失败", ["登录信息不完整，请重新授权。"])
        if not cb["auth_code"] and not cb["refresh_token"]:
            outcome["error"] = "回调带凭据参数，但既无 AuthCode 也无 refreshToken"
            return ("result", False, "登录失败", ["登录信息不完整，请重新授权。"])
        print("📨 收到回调：uid=%s name=%s host=%s" % (cb["uid"] or "-", cb["name"] or "-", cb["host"] or "-"))
        if cb["auth_code"]:
            print("🔐 AuthCode 已到手，正在兑换 Token …")
            tokens, err = exchange_auth_code(line, cb["host"], cb["auth_code"], verifier, dev, sysf)
        else:
            print("🔐 回调直接带回 refreshToken，跳过兑换")
            tokens, err = ({"accessToken": "", "refreshToken": cb["refresh_token"]}, None)
        if not tokens:
            outcome["error"] = err
            return ("result", False, "登录失败", ["Token 兑换失败：", err, "请重新发起登录。"])
        outcome["tokens"] = tokens
        outcome["info"] = cb
        shown = cb["name"] or cb["uid"] or "-"
        return ("result", True, "登录成功",
                ["账号 %s 的凭据已获取，可以关闭本页（浏览器）。" % shown,
                 "回到终端查看 refreshToken / accessToken。"])

    print("🕓 等待浏览器回调（最长 %d 秒）…" % args.timeout)
    if not args.no_open:
        try:
            webbrowser.open(url)
            print("🚀 已尝试打开默认浏览器；没弹出就手动复制上面的 URL。")
        except Exception:
            print("⚠️ 打不开浏览器，请手动复制上面的 URL。")
    err = serve_until_callback(CALLBACK_PORT, args.timeout, process)
    if err == "TIMEOUT":
        print("⏰ 等待超时（%d 秒）未收到回调。可加大 --timeout 或重试。" % args.timeout)
        return None
    if err:
        print("❌ " + err)
        return None
    if outcome["error"]:
        print("❌ 登录失败：" + outcome["error"])
        return None

    tokens = outcome["tokens"]
    cb = outcome["info"]
    uid = cb["uid"] or jwt_uid(tokens["accessToken"])
    name = cb["name"] or ("用户%s" % uid[-10:] if uid else "新账号")
    print()
    print("─" * 60)
    print("🎉 登录成功，凭证如下：")
    print("   账号 UID : %s" % (uid or "-"))
    print("   昵称     : %s" % (name or "-"))
    if tokens["accessToken"]:
        print("   accessToken  = %s" % tokens["accessToken"])
    print("   refreshToken = %s" % tokens["refreshToken"])
    print("─" * 60)
    entry = {"accessToken": tokens["accessToken"], "refreshToken": tokens["refreshToken"],
             "uid": uid, "name": name}
    print("📋 可直接放进 TRAE_ACCOUNTS 的条目（把长 token 原样保留）：")
    print(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    return {"uid": uid, "name": name, "accessToken": tokens["accessToken"],
            "refreshToken": tokens["refreshToken"]}


def save(result, path=None):
    path = path or os.environ.get("TRAE_SMS_OUT") or "trae_sms_accounts.json"
    try:
        data = []
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        data = [a for a in data if not (a.get("uid") and a.get("uid") == result.get("uid"))]
        data.append(result)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("💾 已保存到 %s" % path)
    except Exception as e:
        print("⚠️ 保存失败：%s" % e)


# ══════════════════ 入口 ══════════════════
def selftest():
    v, c = pkce_pair()
    assert len(v) == 64 and all(ch in "0123456789abcdef" for ch in v), "verifier 形状不对"
    assert len(c) == 43 and "=" not in c, "challenge 形状不对"
    q = parse_query("authCodeInfo=%7B%22AuthCode%22%3A%22abc%22%7D&host=https%3A%2F%2Fapi.trae.cn"
                    "&loginTraceID=deadbeef&userInfo=%7B%22UserID%22%3A%22123%22%7D")
    assert q["host"] == "https://api.trae.cn", "二次解码失败"
    cb = parse_callback(q)
    assert cb["auth_code"] == "abc" and cb["uid"] == "123" and cb["trace"] == "deadbeef", "回调解析失败"
    assert has_credential_marker(q) and not has_credential_marker(parse_query("")), "探测判别失败"
    dev = {"device_id": "1234567890123456", "machine_id": "abcd", "public_key": "K"}
    sysf = system_facts()
    u1 = build_authorize_url("trae", dev, sysf, CALLBACK_PORT, "t", "c")
    u2 = build_authorize_url("solo", dev, sysf, CALLBACK_PORT, "t", "c")
    for token in ("login_channel=native_ide", "auth_from=trae", "client_id=ono9krqynydwx5",
                  "code_challenge_method=S256", "auth_callback_url=http%3A%2F%2F127.0.0.1%3A17388%2Fauthorize",
                  "channel_name=common"):
        assert token in u1, "授权 URL 缺参数: %s" % token
    assert "hide_saas_login=true" in u2 and "auth_from=solo" in u2, "SOLO 参数不对"
    assert "hide_saas_login" not in u1, "TRAE 线不该有 hide_saas_login"
    print("✅ 自检通过：PKCE / 回调解析 / 授权 URL（TRAE 22 参 + SOLO 23 参）全部正常")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trae 网页登录（OAuth）获取 Token")
    ap.add_argument("--solo", action="store_true", help="走 SOLO 产品线（默认 Trae/IDE 线）")
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器，只打印授权 URL")
    ap.add_argument("--timeout", type=int, default=LOGIN_TIMEOUT, help="等待回调的秒数（默认 300）")
    ap.add_argument("--storage", help="指定客户端 storage.json 路径（默认自动探测）")
    ap.add_argument("-o", "--out", help="结果保存文件（默认 trae_sms_accounts.json）")
    ap.add_argument("--selftest", action="store_true", help="离线自检，不联网、不占用端口")
    args = ap.parse_args(argv)

    if args.selftest:
        selftest()
        return 0

    line = "solo" if args.solo else "trae"
    dev = load_device_identity(args.storage)
    if not dev:
        print("❌ 没找到设备身份（客户端 storage.json 里的 icube-dc 设备密钥）。")
        print("   → 请先安装并登录一次 Trae 客户端；")
        print("   → 或手动指定：TRAE_DEVICE_ID=… TRAE_DEVICE_PUB_PEM=… TRAE_MACHINE_ID=… 再运行。")
        return 1
    sysf = system_facts()

    while True:
        result = run_login(line, dev, sysf, args)
        if result:
            save(result, args.out)
        try:
            again = input("➡️  继续登录下一个账号？(y/N)：").strip().lower()
        except EOFError:
            again = "n"
        if again != "y":
            break
    print("🏁 结束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
