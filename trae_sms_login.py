#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trae 短信验证码登录 · 获取 Token  (trae_sms_login.py)
────────────────────────────────────────────────────────────
用「手机号 + 短信验证码」走 Trae 网页端真实登录流程，最终拿到
可直接用于签到 / 积分监控的 accessToken 与 refreshToken。

✨ 特性
  • 零依赖    纯 Python 标准库，无需 pip install
  • 全自动    发码 → 校验 → 换 Token 一条龙
  • 真实还原  复刻网页端 passport SDK：mix_mode 混淆 + 表单编码 + CSRF
  • 可续期    同时输出 refreshToken，配合签到脚本长期免登录
  • 多账号    交互式逐个登录，结果写入 trae_sms_accounts.json

🚀 用法
  1. 直接运行：            python trae_sms_login.py
  2. 按提示输入手机号 → 收到短信后输入验证码
  3. 终端打印 accessToken / refreshToken，并保存到 trae_sms_accounts.json

  （可选）非交互 / 脚本调用：
     python trae_sms_login.py -p 138xxxxxxxx -c 123456
     set TRAE_PHONE=138xxxxxxxx & set TRAE_SMS_CODE=123456 & python trae_sms_login.py
     python trae_sms_login.py --selftest     # 仅离线自检混淆与编码

⚠️ 重要：风控说明
  字节跳动风控会对「机房 / 代理 / VPN IP」强制弹出滑块验证（错误码 1105）。
  本脚本已正确复刻请求，但无法自动过滑块 —— 请在【家庭宽带 / 手机热点】
  等真实网络下运行；若确实被要求滑块，可在真实浏览器过验证后，把返回的
  verify_ticket 与 fp 通过 --ticket / --fp 传入继续登录。

📦 输出字段
  • accessToken  ：JWT，约 8 小时有效，Cloud-IDE-JWT 用
  • refreshToken ：轮换链，签到脚本用它长期续期（务必保存）
  • uid / mobile ：便于区分账号

📌 说明
  • 只与本机及 Trae 官方域名通信，不上传任何数据到第三方。
  • 短信验证码有频率限制，同一号码短时间内不要重复请求。
────────────────────────────────────────────────────────────
"""

import base64, json, os, sys, time, argparse, urllib.parse, urllib.request, urllib.error, http.cookiejar, getpass

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SITE       = "https://www.trae.cn"
API_HOST   = "https://api.trae.cn"
OAUTH_HOST = "https://api.trae.com.cn"
AID        = 711126
SDK_VER    = "3.0.11"
CLIENT_ID  = "en1oxy7wnw8j9n"
APP_KEY    = "834295f004615bbae4c2538cad9a68af"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

EP_SEND_CODE = "/passport/web/send_code/"
EP_SMS_LOGIN = "/passport/web/sms_login/"
EP_USER_TOKEN = "/cloudide/api/v3/common/GetUserToken"
EP_REFRESH    = "/cloudide/api/v3/trae/oauth/GetRefreshToken"
EP_CHECK      = "/cloudide/api/v3/trae/CheckLogin"

def _utf8(s):
    out = []
    for ch in str(s):
        c = ord(ch)
        if c <= 0x7F: out.append(c)
        elif c <= 0x7FF: out += [0xC0 | (c >> 6), 0x80 | (c & 0x3F)]
        else: out += [0xE0 | (c >> 12), 0x80 | ((c >> 6) & 0x3F), 0x80 | (c & 0x3F)]
    return out

def obf(v):
    if v is None: return ""
    return "".join(format(5 ^ b, "x") for b in _utf8(v))

def mix(obj, fields):
    s = dict(obj); s["mix_mode"] = 0
    for f in fields:
        if f in s: s[f] = obf(s[f])
    s["mix_mode"] = 1; s["fixed_mix_mode"] = 1
    return s

def form_encode(d):
    parts = []
    for k, v in d.items():
        if isinstance(v, bool): v = "true" if v else "false"
        parts.append(urllib.parse.quote(str(k), safe="") + "=" + urllib.parse.quote(str(v), safe=""))
    return "&".join(parts)

def jwt_payload(tok):
    try:
        p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return {}

class TraeLogin:
    def __init__(self, debug=False):
        self.debug = debug
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def _req(self, url, method="GET", data=None, headers=None, raw=None, timeout=25):
        h = {"User-Agent": UA, "Accept": "application/json, text/javascript, */*"}
        if headers: h.update(headers)
        body = raw
        if body is None and data is not None:
            body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=h, method=method)
        try:
            with self.opener.open(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)
        except Exception as e:
            return -1, str(e), {}

    def cookie(self, *names):
        for c in self.cj:
            if c.name in names: return c.value
        return ""

    def warmup(self):
        self._req(SITE + "/login")
        return self.cookie("passport_csrf_token", "passport_csrf_token_default")

    def _passport(self, path, body, extra_params=None):
        q = {"aid": AID, "account_sdk_source": "web",
             "passport_jssdk_version": SDK_VER, "passport_jssdk_type": "normal"}
        if extra_params: q.update(extra_params)
        url = SITE + path + "?" + urllib.parse.urlencode(q)
        h = {"Content-Type": "application/x-www-form-urlencoded",
             "Referer": SITE + "/", "Origin": SITE,
             "x-tt-passport-csrf-token": self.cookie("passport_csrf_token", "passport_csrf_token_default")}
        return self._req(url, "POST", raw=form_encode(body).encode("utf-8"), headers=h)

    def send_code(self, mobile, verify_ticket=None, fp=None):
        body = {"mobile": mobile, "type": 24, "is6Digits": True}
        if verify_ticket: body["verify_ticket"] = verify_ticket
        if fp: body["fp"] = fp
        body = mix(body, ["mobile", "type"])
        st, txt, _ = self._passport(EP_SEND_CODE, body)
        return _json(txt)

    def sms_login(self, mobile, code):
        body = mix({"mobile": mobile, "code": code}, ["mobile", "code"])
        st, txt, _ = self._passport(EP_SMS_LOGIN, body)
        return _json(txt)

    def get_user_token(self):
        h = {"Content-Type": "application/json", "Referer": SITE + "/"}
        st, txt, _ = self._req(API_HOST + EP_USER_TOKEN, "POST", data=b"{}", headers=h)
        try: return json.loads(txt)["Result"]["Token"]
        except Exception: return None

    def get_refresh_token(self):
        h = {"Content-Type": "application/json", "Referer": SITE + "/"}
        st, txt, _ = self._req(OAUTH_HOST + EP_REFRESH, "POST", data={"clientID": CLIENT_ID}, headers=h)
        try:
            j = json.loads(txt); r = j.get("Result") or j.get("data") or {}
            return r.get("RefreshToken") or r.get("refreshToken")
        except Exception: return None

    def check_login(self, token):
        h = {"Content-Type": "application/json", "Authorization": "Cloud-IDE-JWT " + token}
        st, txt, _ = self._req(API_HOST + EP_CHECK, "POST",
                               data={"GetNickNameEditStatus": True}, headers=h)
        try:
            r = json.loads(txt)["Result"]
            return {"is_login": r.get("IsLogin"), "user_id": r.get("UserID"),
                    "region": r.get("Region"), "host": r.get("Host")}
        except Exception: return None

def _json(t):
    try: return json.loads(t)
    except Exception: return {"message": "非 JSON 响应", "raw": t[:200]}

def mask(m):
    return m[:3] + "****" + m[-4:] if len(m) >= 7 else m

# ══════════════════ 业务错误码 ══════════════════
ERR_SLIDER   = 1105   # 需要滑动滑块（风控）
ERR_FREQ     = 1204   # 请求过于频繁
ERR_CODE_BAD = 1203   # 验证码错误/过期
ERR_MOBILE   = 1003   # 手机号错误/未注册
ERR_ILLEGAL  = 22     # 非法应用（参数/来源不对）
ERR_SESSION  = 1      # 会话过期


def _desc(resp):
    d = (resp or {}).get("data") or {}
    return d.get("error_code"), d.get("description") or "", d


def send_code_flow(s, mobile, verify_ticket=None, fp=None):
    """返回 (ok, resp, hint)。"""
    r = s.send_code(mobile, verify_ticket=verify_ticket, fp=fp)
    code, desc, d = _desc(r)
    if code in (None, 0):
        return True, r, ""
    if code == ERR_SLIDER:
        return False, r, "风控要求滑动验证（当前出口 IP 被判定为高风险，通常是机房/代理 IP）。"
    if code == ERR_FREQ:
        return False, r, "该号码请求过于频繁，请稍后再试。"
    if code == ERR_MOBILE:
        return False, r, "该手机号未注册 / 填写错误。"
    if code == ERR_ILLEGAL:
        return False, r, "非法应用：请求参数或来源被拒，请更新脚本。"
    return False, r, desc or "发送失败"


def sms_login_flow(s, mobile, code):
    r = s.sms_login(mobile, code)
    c, desc, d = _desc(r)
    if c in (None, 0):
        return True, r, ""
    if c == ERR_CODE_BAD:
        return False, r, "验证码错误或已过期，请重新获取。"
    if c == ERR_SLIDER:
        return False, r, "登录时触发滑块风控。"
    return False, r, desc or "登录失败"


def login_one(mobile=None, code=None, verify_ticket=None, fp=None):
    s = TraeLogin()
    print("🌐 初始化会话 …")
    s.warmup()

    if not mobile:
        mobile = (os.environ.get("TRAE_PHONE") or "").strip()
    if not mobile:
        mobile = input("📱 请输入手机号：").strip()
    if not (mobile.isdigit() and len(mobile) == 11):
        print("❌ 手机号格式不正确（应为 11 位数字）")
        return None

    print(f"📨 正在向 {mask(mobile)} 发送短信验证码 …")
    ok, r, hint = send_code_flow(s, mobile, verify_ticket, fp)
    if not ok:
        print(f"❌ 发送失败：{hint}")
        if hint.startswith("风控"):
            print("   提示：请在【家庭/手机热点等真实网络】下运行本脚本，机房/代理 IP 会被强制滑块。")
        return None
    print("✅ 验证码已发送")

    if not code:
        code = (os.environ.get("TRAE_SMS_CODE") or "").strip()
    if not code:
        code = input("🔑 请输入收到的短信验证码：").strip()

    print("🔐 正在校验验证码 …")
    ok, r, hint = sms_login_flow(s, mobile, code)
    if not ok:
        print(f"❌ 登录失败：{hint}")
        return None
    print("✅ 登录成功")

    print("🎫 正在获取 accessToken …")
    access = s.get_user_token()
    if not access:
        print("❌ 获取 accessToken 失败（会话 Cookie 可能未下发，请重试）")
        return None
    print("🔄 正在获取 refreshToken …")
    refresh = s.get_refresh_token()

    info = s.check_login(access) or {}
    payload = jwt_payload(access)
    uid = str(info.get("user_id") or (payload.get("data") or {}).get("id") or "")

    print("─" * 60)
    print("🎉 登录成功，凭证如下：")
    if uid:
        print(f"   账号 UID : {uid}")
    print(f"   accessToken  = {access}")
    if refresh:
        print(f"   refreshToken = {refresh}")
    else:
        print("   refreshToken = (未取到，可稍后重试)")
    print("─" * 60)
    return {"mobile": mobile, "uid": uid, "accessToken": access, "refreshToken": refresh}


def save(result, path=None):
    path = path or os.environ.get("TRAE_SMS_OUT") or "trae_sms_accounts.json"
    try:
        data = []
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        data = [a for a in data if a.get("uid") != result.get("uid") or not result.get("uid")]
        data.append(result)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"💾 已保存到 {path}")
    except Exception as e:
        print("⚠️  保存失败：", e)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trae 短信验证码登录获取 Token")
    ap.add_argument("-p", "--phone", help="手机号（也可用环境变量 TRAE_PHONE）")
    ap.add_argument("-c", "--code", help="短信验证码（也可用环境变量 TRAE_SMS_CODE）")
    ap.add_argument("--ticket", help="滑块风控的 verify_ticket（可选）")
    ap.add_argument("--fp", help="滑块风控的 fp（可选）")
    ap.add_argument("-o", "--out", help="结果输出文件（默认 trae_sms_accounts.json）")
    ap.add_argument("--selftest", action="store_true", help="仅自检混淆/编码，不联网")
    args = ap.parse_args(argv)

    if args.selftest:
        assert obf("13800138000") == "34363d353534363d353535"
        assert mix({"mobile": "1", "type": 24}, ["mobile", "type"])["mix_mode"] == 1
        assert form_encode({"a": True, "b": 1}) == "a=true&b=1"
        print("✅ 自检通过：混淆 / mix / 表单编码 均与网页端一致")
        return

    print("=" * 60)
    print("  Trae 短信验证码登录 · 获取 Token")
    print("=" * 60)
    while True:
        res = login_one(args.phone, args.code, args.ticket, args.fp)
        if res:
            save(res, args.out)
        if args.phone and args.code:
            break
        again = input("➡️  继续登录下一个账号？(y/N)：").strip().lower()
        if again != "y":
            break
    print("🏁 结束")


if __name__ == "__main__":
    main()
