#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trae 手机号探测器 · trae_sms_probe.py
────────────────────────────────────────────────────────────
批量探测一批手机号「有没有注册 Trae」，用来在多账号场景下
认出某个 UID 对应的是哪个手机号（登录前先筛一遍，少收几条短信）。

✨ 特性
  • 批量探测   一行一个手机号，或命令行直接跟号码
  • 只发码不登录 只调「发送验证码」接口，不登录、不拿 token
  • 限速保护   默认每个号间隔 6 秒，避免触发风控
  • 结果分类   已注册 / 未注册 / 触发滑块 / 太频繁，一眼看清

🚀 使用方法
  # 直接跟号码
  python trae_sms_probe.py 13800138000 13900139000

  # 从文件读（一行一个，# 开头是注释）
  python trae_sms_probe.py --file phones.txt

  # 调整间隔（默认 6 秒）
  python trae_sms_probe.py --file phones.txt --gap 10

📌 说明
  • 判定依据是发码接口的返回：未注册的号会返回 1003。
  • ⚠️ 已注册的号**会真的收到一条验证码短信**，请只探测你自己的号码。
  • 建议在家庭宽带 / 手机热点下跑；机房或代理 IP 会直接被要求滑块（1105）。
  • 探测结果只是「注册了 Trae」，具体是哪个 UID 还得登录一次看脚本输出的 UID。
────────────────────────────────────────────────────────────
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from trae_sms_login import TraeLogin, ERR_SLIDER, ERR_FREQ, ERR_MOBILE, ERR_ILLEGAL, _desc
except ImportError:
    print("❌ 找不到 trae_sms_login.py，请把本脚本和它放在同一个目录。")
    sys.exit(1)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OK, NOT_REG, SLIDER, FREQ, OTHER = "已注册", "未注册", "触发滑块", "太频繁", "未知"


def probe_one(session, mobile):
    """发一次验证码，按返回判定状态。返回 (状态, 说明)。"""
    r = session.send_code(mobile)
    code, desc, _ = _desc(r)
    if code in (None, 0):
        return OK, "验证码已发出"
    if code == ERR_MOBILE:
        return NOT_REG, "该号码未注册 Trae"
    if code == ERR_SLIDER:
        return SLIDER, "IP 被判定高风险，需要滑块"
    if code == ERR_FREQ:
        return FREQ, "请求过于频繁"
    if code == ERR_ILLEGAL:
        return OTHER, "参数/来源被拒（接口可能变了）"
    return OTHER, desc or ("error_code=%s" % code)


def load_phones(args):
    out = []
    for p in args.phones or []:
        out.append(p.strip())
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.split("#")[0].strip()
                if line:
                    out.append(line)
    seen, uniq = set(), []
    for p in out:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def main():
    ap = argparse.ArgumentParser(description="批量探测手机号是否注册 Trae")
    ap.add_argument("phones", nargs="*", help="手机号，可跟多个")
    ap.add_argument("--file", "-f", help="号码文件，一行一个")
    ap.add_argument("--gap", type=float, default=6, help="每个号之间的间隔秒数（默认 6）")
    ap.add_argument("--yes", "-y", action="store_true", help="跳过确认直接开始")
    args = ap.parse_args()

    phones = load_phones(args)
    if not phones:
        print("❌ 没给号码。用法：python trae_sms_probe.py 13800138000 13900139000")
        print("        或：python trae_sms_probe.py --file phones.txt")
        return 1

    bad = [p for p in phones if not (len(p) == 11 and p.isdigit() and p[0] == "1")]
    if bad:
        print("❌ 这些不是 11 位手机号，已剔除：%s" % ", ".join(bad))
        phones = [p for p in phones if p not in bad]
    if not phones:
        return 1

    print("将要探测 %d 个号码：" % len(phones))
    for p in phones:
        print("   %s" % p)
    print("\n⚠️ 已注册的号会真的收到一条验证码短信（只探测你自己的号码）。")
    if not args.yes:
        try:
            ans = input("继续？(y/N) ").strip().lower()
        except EOFError:
            ans = "n"
        if ans != "y":
            print("已取消。")
            return 0

    # 先看看出口 IP —— 机房/代理 IP 会被风控直接要求滑块，白跑一轮
    ip = ""
    try:
        import urllib.request as _u
        with _u.urlopen("https://api.ipify.org?format=json", timeout=10) as x:
            ip = json.loads(x.read().decode()).get("ip", "")
    except Exception:
        pass
    if ip:
        print("\n🌍 当前出口 IP：%s" % ip)
        print("   （如果是机房/代理 IP，Trae 会一律要求滑块 —— 建议先在 Clash/代理里把")
        print("     *.trae.cn 设为 DIRECT，或临时关掉 TUN/系统代理再跑）")

    print("\n🌐 初始化会话 …")
    s = TraeLogin()
    s.warmup()

    result = {}
    for i, p in enumerate(phones, 1):
        state, note = probe_one(s, p)
        result[p] = state
        icon = {"已注册": "✅", "未注册": "➖", "触发滑块": "🛡️", "太频繁": "⏳"}.get(state, "❓")
        print("  [%d/%d] %s %s  %s" % (i, len(phones), icon, p, note))
        if state == SLIDER:
            print("\n🛡️ 出口 IP 被风控要求滑块，继续探测只会白跑。")
            print("   处理办法：① Clash 里把 *.trae.cn 走 DIRECT；② 临时关掉 TUN/系统代理；")
            print("            ③ 换家庭宽带或手机热点。滑块是浏览器行为，脚本过不了。")
            break
        if i < len(phones):
            time.sleep(args.gap)

    reg = [p for p, v in result.items() if v == OK]
    nreg = [p for p, v in result.items() if v == NOT_REG]
    print("\n" + "=" * 56)
    print("已注册 %d 个：" % len(reg))
    for p in reg:
        print("   ✅ %s   ← 这些号可以跑 trae_sms_login.py 认 UID" % p)
    if nreg:
        print("未注册 %d 个：%s" % (len(nreg), ", ".join(nreg)))
    print("=" * 56)
    print("下一步：对上面 ✅ 的号码逐个跑 python trae_sms_login.py，")
    print("        看输出的「账号 UID」，找到你要的那个即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
