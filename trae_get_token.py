#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trae Token 提取器 · trae_get_token.py
────────────────────────────────────────────────────────────
一键从 Trae 官方客户端本地数据里解出 refreshToken / accessToken，
免抓包、免装依赖（纯 Python 标准库，自己实现 AES-128-CBC）。

✨ 特性
  • 零依赖     纯标准库，无需 pip install
  • 免抓包     直接读客户端 storage.json 并自动解密
  • 一键输出   直接打印 refreshToken，复制进青龙环境变量即可
  • 自动找路径 自动探测 Trae CN / TRAE SOLO 等常见目录

🚀 使用方法
  1. 打开 Trae 客户端并登录一次（确保已产生凭据）
  2. 运行：python trae_get_token.py
  3. 复制输出的 TRAE_REFRESH_TOKEN 值，填入青龙面板环境变量

📌 说明
  • 只读取本机自己的客户端凭据，不联网、不上传，安全无风险。
  • 多账号：在客户端依次登录每个账号并各运行一次本脚本即可。
────────────────────────────────────────────────────────────
"""
import base64, hashlib, json, os, sys, re

# ── 让 Windows 控制台也能正常打印 emoji ──
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SALT_A = bytes([82,9,106,213,48,54,165,56,191,64,163,158,129,243,215,251,124,227,57,130,155,47,255,135,52,142,67,68,196,222,233,203,84,123,148,50,166,194,35,61,238,76,149,11,66,250,195,78,8,46,161,102,40,217,36,178,118,91,162,73,109,139,209,37])
SALT_B = bytes([31,221,168,51,136,7,199,49,177,18,16,89,39,128,236,95,96,81,127,169,25,181,74,13,45,229,122,159,147,201,156,239,160,224,59,77,174,42,245,176,200,235,187,60,131,83,153,97,23,43,4,126,186,119,214,38,225,105,20,99,85,33,12,125])
SALT_AES = bytes(a ^ b for a, b in zip(SALT_A, SALT_B))
STORAGE_KEY = "iCubeAuthInfo://icube.cloudide"

# ══════════ 纯标准库 AES-128-CBC 解密 ══════════
def _gmul(a, b):
    p = 0
    for _ in range(8):
        if b & 1: p ^= a
        hi = a & 0x80; a = (a << 1) & 0xFF
        if hi: a ^= 0x1B
        b >>= 1
    return p

def _build_sbox():
    inv = [0] * 256
    for i in range(1, 256):
        for j in range(1, 256):
            if _gmul(i, j) == 1:
                inv[i] = j; break
    sb = [0] * 256
    for i in range(256):
        x = inv[i] if i else 0; s = x
        for _ in range(4):
            x = ((x << 1) | (x >> 7)) & 0xFF; s ^= x
        sb[i] = s ^ 0x63
    return sb

SBOX = _build_sbox()
INV = [0] * 256
for _i, _v in enumerate(SBOX): INV[_v] = _i
RC = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1B,0x36]

def _expand(key):
    w = [list(key[i*4:i*4+4]) for i in range(4)]
    for i in range(4, 44):
        t = w[i-1][:]
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= RC[i//4-1]
        w.append([w[i-4][j] ^ t[j] for j in range(4)])
    return w

def _rk(w, r):
    ws = w[r*4:r*4+4]
    return [ws[c][k] for c in range(4) for k in range(4)]

def _addrk(s, k): return [s[i] ^ k[i] for i in range(16)]
def _isub(s): return [INV[b] for b in s]
def _ishift(s): return [s[0],s[13],s[10],s[7], s[4],s[1],s[14],s[11], s[8],s[5],s[2],s[15], s[12],s[9],s[6],s[3]]

def _imix(s):
    o = []
    for c in range(4):
        a = s[c*4:c*4+4]
        o += [_gmul(a[0],14)^_gmul(a[1],11)^_gmul(a[2],13)^_gmul(a[3],9),
              _gmul(a[0],9)^_gmul(a[1],14)^_gmul(a[2],11)^_gmul(a[3],13),
              _gmul(a[0],13)^_gmul(a[1],9)^_gmul(a[2],14)^_gmul(a[3],11),
              _gmul(a[0],11)^_gmul(a[1],13)^_gmul(a[2],9)^_gmul(a[3],14)]
    return o

def aes128_cbc_decrypt(key, iv, data):
    w = _expand(key); out = b""; prev = list(iv)
    for off in range(0, len(data), 16):
        blk = list(data[off:off+16]); s = _addrk(blk, _rk(w, 10))
        for r in range(9, 0, -1):
            s = _ishift(s); s = _isub(s); s = _addrk(s, _rk(w, r)); s = _imix(s)
        s = _ishift(s); s = _isub(s); s = _addrk(s, _rk(w, 0))
        out += bytes(a ^ b for a, b in zip(s, prev)); prev = blk
    return out

# ══════════ 解密 storage.json 里的凭据 ══════════
def decrypt_storage_value(b64):
    buf = base64.b64decode(b64)
    rb, enc = buf[6:38], buf[38:]
    h = hashlib.sha512(rb).digest()
    fh = hashlib.sha512(h + SALT_AES).digest()
    pt = aes128_cbc_decrypt(fh[:16], fh[16:32], enc)[64:]
    return pt.rstrip(b"\x00").rstrip()

def candidate_paths():
    ad = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    for n in ("Trae CN", "TRAE SOLO CN", "TRAE SOLO"):
        p = os.path.join(ad, n, "User", "globalStorage", "storage.json")
        if os.path.isfile(p): yield p
    for n in (".trae-cn", ".trae"):
        p = os.path.join(os.path.expanduser("~"), n, "User", "globalStorage", "storage.json")
        if os.path.isfile(p): yield p

def extract(path):
    s = json.load(open(path, encoding="utf-8"))
    enc = s.get(STORAGE_KEY)
    if not enc: return None
    txt = decrypt_storage_value(enc).decode("utf-8", "replace")
    rt = re.search(r'"refreshToken"\s*:\s*"([^"]+)"', txt)
    at = re.search(r'"token"\s*:\s*"([^"]+)"', txt)
    uid = re.search(r'"userId"\s*:\s*"(\d+)"', txt)
    nick = re.search(r'"username"\s*:\s*"([^"]*)"', txt)
    return {"refreshToken": rt.group(1) if rt else None,
            "accessToken": at.group(1) if at else None,
            "uid": uid.group(1) if uid else None,
            "nickname": nick.group(1) if nick else None}

def main():
    found = False
    for p in candidate_paths():
        try:
            r = extract(p)
        except Exception as e:
            print("[!] 解析失败 %s: %s" % (p, e)); continue
        if not r or not r.get("refreshToken"): continue
        found = True
        print("=" * 64)
        print("[来源] %s" % p)
        if r.get("uid"):
            print("[账号] %s (UID %s)" % (r.get("nickname") or "-", r["uid"]))
        print("-" * 64)
        print("TRAE_REFRESH_TOKEN = %s" % r["refreshToken"])
        print("=" * 64)
    if not found:
        print("[X] 没找到可用的 refreshToken。")
        print("    请先打开 Trae 客户端并登录一次，再运行本脚本。")

if __name__ == "__main__":
    main()
