#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trae 浏览器登录取 Token · trae_browser_login.py
────────────────────────────────────────────────────────────
弹一个真实浏览器让你正常登录（手机号 + 验证码），滑块也能手动过；
脚本在后台监听网络响应，自动把 accessToken / refreshToken 抓出来。

比起纯接口版（trae_sms_login.py），这条路**不怕风控滑块**：
滑块本来就是给人过的，浏览器里你自己划一下就通过。

✨ 特性
  • 不怕风控   真实浏览器登录，滑块手动过，机房/代理 IP 也能用
  • 自动抓取   监听 GetUserToken / GetRefreshToken 响应，登录完自动拿到 token
  • 会话复用   登录态持久化，下次打开无需重新登录
  • 直接出配置  登录成功直接打印可粘贴的账号 JSON

🚀 使用方法
  python trae_browser_login.py
  # 浏览器里：输手机号 → 输验证码 →（有滑块就划一下）→ 回到终端看结果

  # 想换个数码箱目录（避免和其它调试会话互相干扰）
  python trae_browser_login.py --profile "D:/trae-browser-profile"

  # 自动附加到你的 TRAE_ACCOUNTS 片段里，并写进账号目录
  python trae_browser_login.py --save

  # 滑块不弹/登录没反应时，抓日志和截图给作者看
  python trae_browser_login.py --debug

📌 说明
  • 需要 playwright：pip install playwright && python -m playwright install chromium
  • 只在本机开浏览器，凭据不经过任何第三方。
  • 反复登录同一个账号不会互相顶掉（浏览器用的是自己的会话）。
────────────────────────────────────────────────────────────
"""
import argparse
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ 缺少 playwright。先装一下：")
    print("   pip install playwright")
    print("   python -m playwright install chromium")
    sys.exit(1)

LOGIN_URL = "https://www.trae.cn/login"
HOME_URL = "https://www.trae.cn/"
DEFAULT_PROFILE = os.path.join(os.path.expanduser("~"), ".trae-browser-profile")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def pick_channel(pref=""):
    """优先用系统里真实安装的 Chrome / Edge —— 风控对自带 Chromium 识别率更高。"""
    if pref:
        return pref
    cands = [
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    if any(p and os.path.isfile(p) for p in cands):
        return "chrome"
    edges = [
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    if any(p and os.path.isfile(p) for p in edges):
        return "msedge"
    return ""


def jwt_uid(token):
    try:
        import base64
        p = token.split(".")[1]
        pad = "=" * (-len(p) % 4)
        return str(json.loads(base64.urlsafe_b64decode(p + pad)).get("data", {}).get("id", ""))
    except Exception:
        return ""


def make_sniffer(found):
    """监听响应，抓 GetUserToken / GetRefreshToken。"""
    def on_response(resp):
        url = resp.url
        try:
            if "GetUserToken" in url:
                j = resp.json()
                tok = ((j or {}).get("Result") or {}).get("Token")
                if tok:
                    found["accessToken"] = tok
                    print("   ✅ 抓到 accessToken")
            elif "GetRefreshToken" in url:
                j = resp.json() or {}
                r = j.get("Result") or j.get("data") or {}
                rt = r.get("RefreshToken") or r.get("refreshToken")
                if rt:
                    found["refreshToken"] = rt
                    print("   ✅ 抓到 refreshToken")
        except Exception:
            pass
    return on_response


def run(profile, headless, save, timeout, debug=False, channel=""):
    found = {}
    print("=" * 64)
    print("  Trae 浏览器登录 · 取 Token")
    print("=" * 64)
    print("🌐 启动浏览器（会话目录：%s）" % profile)

    dbg_log = []
    shot_dir = None
    if debug:
        shot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trae_browser_shots")
        os.makedirs(shot_dir, exist_ok=True)
        print("🐞 调试模式：日志与截图会存到 %s" % shot_dir)

    with sync_playwright() as pw:
        ch = pick_channel(channel)
        kw = {}
        if ch:
            kw["channel"] = ch
        if ch:
            print("🧭 使用系统安装的浏览器：%s" % ch)
        else:
            print("🧭 使用 Playwright 自带 Chromium（风控识别率较高，建议装个 Chrome）")
        ctx = pw.chromium.launch_persistent_context(
            profile, headless=headless,
            viewport={"width": 1280, "height": 860},
            args=["--disable-blink-features=AutomationControlled"],
            **kw)
        if headless:
            pass
        else:
            try:
                ctx.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                    "window.chrome=window.chrome||{runtime:{}};")
            except Exception:
                pass
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", make_sniffer(found))

        if debug:
            def _log(kind, text):
                line = "[%s] %s" % (kind, text)
                dbg_log.append(line)
            page.on("request", lambda r: _log("req", r.url[:180]))
            page.on("requestfailed", lambda r: _log("FAIL", "%s  %s" % (r.url[:140], str(r.failure)[:80])))
            page.on("response", lambda r: _log("http%d" % r.status, r.url[:180]) if r.status >= 400 else None)
            page.on("console", lambda m: _log("console." + m.type, m.text[:160]))
            page.on("frameattached", lambda f: _log("frame", f.url[:160]))
            page.on("popup", lambda p: _log("popup", p.url[:160]))

        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print("⚠️ 打开登录页超时/失败：%s" % str(e)[:120])
            print("   浏览器已打开，你可以手动访问 https://www.trae.cn/login")

        if not headless:
            print()
            print("👉 现在到浏览器窗口里操作：")
            print("   1) 输入手机号，点发送验证码（有滑块就划一下）")
            print("   2) 输入收到的 6 位验证码，完成登录")
            print("   3) 登录成功后这里会自动抓取 token")
            print()
            print("   （窗口关掉就退出；最多等 %d 秒）" % timeout)

        deadline = time.time() + timeout
        while time.time() < deadline:
            if found.get("accessToken"):
                # 再等一小会儿，通常 refreshToken 紧随其后
                for _ in range(20):
                    if found.get("refreshToken"):
                        break
                    if page.is_closed():
                        break
                    time.sleep(0.5)
                break
            if page.is_closed():
                print("⚠️ 浏览器窗口已关闭")
                break
            if debug and int(time.time() * 2) % 12 == 0:
                try:
                    page.screenshot(path=os.path.join(shot_dir, "shot_%d.png" % int(time.time())))
                except Exception:
                    pass
            time.sleep(0.5)

        # 收尾：抓不到 refreshToken 时补一次接口调用
        if found.get("accessToken") and not found.get("refreshToken"):
            try:
                r = page.evaluate("""async () => {
                    const r = await fetch('https://api.trae.com.cn/cloudide/api/v3/trae/oauth/GetRefreshToken', {
                        method: 'POST', credentials: 'include',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({clientID: 'en1oxy7wnw8j9n'})});
                    return await r.text();
                }""")
                j = json.loads(r or "{}")
                rr = j.get("Result") or j.get("data") or {}
                rt = rr.get("RefreshToken") or rr.get("refreshToken")
                if rt:
                    found["refreshToken"] = rt
                    print("   ✅ 补抓到 refreshToken")
            except Exception as e:
                print("   ⚠️ 补抓 refreshToken 失败：%s" % str(e)[:80])

        if debug:
            try:
                page.screenshot(path=os.path.join(shot_dir, "shot_final.png"))
            except Exception:
                pass
            logp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trae_browser_debug.log")
            try:
                with open(logp, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write("\n".join(dbg_log))
                print("\n🐞 调试日志已写入：%s" % logp)
                print("🐞 截图目录：%s" % shot_dir)
                print("   把日志里 FAIL / console.error / http4xx|5xx 的行发给我即可。")
            except Exception as e:
                print("⚠️ 写日志失败：%s" % e)

        try:
            ctx.close()
        except Exception:
            pass

    at, rt = found.get("accessToken"), found.get("refreshToken")
    if not at:
        print("\n❌ 没抓到 token。可能还没登录成功，或页面变了。")
        return 1

    uid = jwt_uid(at)
    print("\n" + "─" * 60)
    print("🎉 登录成功，凭证如下：")
    if uid:
        print("   账号 UID     : %s" % uid)
    print("   accessToken  = %s" % at)
    if rt:
        print("   refreshToken = %s" % rt)
    else:
        print("   refreshToken = (没抓到，可重跑一次)")
    print("─" * 60)

    entry = {"accessToken": at, "refreshToken": rt or "", "uid": uid or "未命名", "name": uid or "未命名"}
    line = json.dumps([entry], ensure_ascii=False, separators=(",", ":"))
    print("\n📋 可直接粘进 TRAE_ACCOUNTS（记得和已有账号合并成一个数组）：")
    print(line)

    if save:
        out = os.environ.get("TRAE_SMS_OUT") or "trae_sms_accounts.json"
        data = []
        if os.path.isfile(out):
            try:
                data = json.load(open(out, encoding="utf-8"))
            except Exception:
                data = []
        data = [a for a in data if a.get("uid") != uid]
        data.append({"accessToken": at, "refreshToken": rt or "", "uid": uid})
        json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("\n💾 已保存到 %s（共 %d 个账号）" % (out, len(data)))
    return 0


def main():
    ap = argparse.ArgumentParser(description="用真实浏览器登录 Trae 并抓取 Token")
    ap.add_argument("--profile", default=DEFAULT_PROFILE, help="浏览器会话目录（默认 ~/.trae-browser-profile）")
    ap.add_argument("--headless", action="store_true", help="无头模式（滑块过不了，仅调试用）")
    ap.add_argument("--save", "-s", action="store_true", help="把结果写进 trae_sms_accounts.json")
    ap.add_argument("--timeout", type=int, default=600, help="等待登录的秒数（默认 600）")
    ap.add_argument("--debug", action="store_true", help="抓网络日志 + 定时截图，排查滑块不弹等问题")
    ap.add_argument("--browser", default="", help="指定浏览器：chrome / msedge / （留空=自动优先真 Chrome）")
    args = ap.parse_args()
    return run(args.profile, args.headless, args.save, args.timeout, args.debug, args.browser)


if __name__ == "__main__":
    sys.exit(main())
