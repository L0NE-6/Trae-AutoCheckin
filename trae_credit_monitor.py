#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trae CreditMonitor · Trae 积分余额监控
────────────────────────────────────────────────────────────
只读脚本：查询每个账号的积分「已用 / 剩余」，推送到企业微信机器人。
与 Trae AutoCheckin 共用同一份 token 缓存，绝不触发签到。

✨ 特性
  • 零依赖     仅用 Python 标准库，无需 pip 安装
  • 只读安全   只调用查询接口，不会签到、不会消耗任何积分
  • Token 缓存 与签到脚本共用缓存，复用未过期的 accessToken
  • 链式续期   refreshToken 轮换时自动回写最新值，长期不失效
  • 多账号     与签到脚本共用 TRAE_ACCOUNTS，也兼容 TRAE_REFRESH_TOKEN[_N]
  • 微信推送   已用 / 剩余积分一目了然

📦 环境变量
TRAE_ACCOUNTS            多账号 JSON 数组（推荐，与签到脚本共用同一个变量）
TRAE_REFRESH_TOKEN       旧部署兼容：refreshToken（也支持 _2~_N 后缀多账号）
QYWX_TOKEN               企业微信机器人 key（可选，也兼容 WECHAT_WEBHOOK）
TRAE_TOKEN_CACHE         缓存文件路径（可选，默认 /ql/data/config/ 或脚本同目录）
TRAE_ACCOUNT_DIR         账号 JSON 所在目录（可选，用于回写轮换后的 refreshToken）
TRAE_DEVICE_KEY_PEM      设备 ECDSA 私钥（新版续期必需，trae_get_token.py --export-keys 导出）
TRAE_DEVICE_PUB_PEM      设备 ECDSA 公钥（新版续期必需，同上）
TRAE_MACHINE_ID          设备 machineId（建议一起填）
TRAE_DEVICE_ID           设备号（16 位，与上面三个配套）

🔑 如何获取 refreshToken（新手必看，两步搞定）
  方式一：一键提取（推荐 · 免抓包）
    1) 在本机打开 Trae 客户端并登录你的账号（确保已产生登录凭据）
    2) 运行本仓库的提取脚本：python trae_get_token.py
    3) 终端会打印一行：TRAE_REFRESH_TOKEN = xxxxxx
    4) 复制等号后面的 xxxxxx，粘贴到青龙面板「环境变量」→ 新建变量里
    多账号：在客户端依次登录每个账号，各跑一次提取脚本，得到 _2 / _3 ... 的值
  方式二：手动定位（懂原理的可选）
    Trae 客户端把登录凭据加密存放在（Windows 路径）：
      %APPDATA%/Trae CN/User/globalStorage/storage.json
    其中键名 iCubeAuthInfo://icube.cloudide 对应的值即加密凭据，
    解密算法已内置在 trae_get_token.py 中，直接跑脚本即可自动解密。

🚀 使用方法（青龙面板）
  1. 脚本放入 /ql/data/scripts/，环境变量填好 TRAE_ACCOUNTS 与 QYWX_TOKEN
  2. 定时任务：python /ql/data/scripts/trae_credit_monitor.py   定时 0 * * * *
  3. 默认查询全部账号；设 TRAE_ONLY 可只查部分（用法同签到脚本）

📌 特别说明
  • refreshToken 是轮换链：每次续期都会产生新值，脚本会写回缓存与账号文件，
    请勿在多处同时使用同一账号，否则会互相使对方 token 失效。
  • 只有"refreshToken 也续期失败"才算硬失败；网络抖动等软失败会照常推送。
────────────────────────────────────────────────────────────
"""

import base64, datetime, hashlib, json, os, platform, sys, time, urllib.request, urllib.error

UgHost = 'https://api.trae.cn'
OAuthHost = 'https://api.trae.com.cn'
ClientID = 'en1oxy7wnw8j9n'          # 旧客户端 / 旧 token 用
ClientIDIde = os.getenv('TRAE_CLIENT_ID', '').strip() or 'ono9krqynydwx5'   # 桌面端实测值（新版续期必须）
EP_EXCHANGE = OAuthHost + '/cloudide/api/v3/trae/oauth/ExchangeToken'
EP_EXCHANGE_PROOF = UgHost + '/trae/api/v3/oauth/ExchangeToken'   # 新版：必须带设备证明
EP_ENTITLE = UgHost + '/trae/api/v2/pay/user_current_entitlement_list'
UA = 'Trae/1.0'
IdeVersion = '1.107.1'
AUTH_FAIL_CODES = (1001, 1002)


# ══════════════════ 缓存文件 ══════════════════
def _cache_path():
    p = os.environ.get('TRAE_TOKEN_CACHE', '').strip()
    if p:
        return p
    for cand in ('/ql/data/config/.trae_token_cache.json',
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), '.trae_token_cache.json')):
        try:
            d = os.path.dirname(cand)
            if d and os.path.isdir(d):
                return cand
        except Exception:
            pass
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), '.trae_token_cache.json')


def load_cache():
    try:
        with open(_cache_path(), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache):
    try:
        path = _cache_path()
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print('⚠️  [缓存] 写入失败:', e)


# ══════════════════ HTTP ══════════════════
def _post(url, headers, body=''):
    req = urllib.request.Request(url, data=body.encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')
    except Exception as e:
        return -1, str(e)


def ug_headers(token, device_id):
    return {'Authorization': 'Cloud-IDE-JWT ' + token, 'X-User-Region': 'cn', 'x-device-id': device_id,
            'User-Agent': 'TraeCreditMonitor/1.0', 'Content-Type': 'application/json'}


# ══════════════════ 设备证明（纯标准库 ECDSA P-256） ══════════════════
# Trae 新版 ExchangeToken 要求带设备签名，缺了会返回 20405 Device proof required。
P256_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
P256_A = P256_P - 3
P256_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
P256_GX = 0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296
P256_GY = 0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5


def _der_tlv(buf, i):
    tag = buf[i]; i += 1
    ln = buf[i]; i += 1
    if ln & 0x80:
        n = ln & 0x7f
        ln = int.from_bytes(buf[i:i + n], 'big'); i += n
    return tag, buf[i:i + ln], i + ln


def _pem_der(pem):
    body = ''.join(l.strip() for l in pem.splitlines() if '---' not in l)
    return base64.b64decode(body)


def ec_private_scalar(pem):
    """从 PKCS#8 / SEC1 PEM 里取出 P-256 私钥标量。"""
    der = _pem_der(pem)
    try:
        _, body, _ = _der_tlv(der, 0)
        i = 0
        _, _, i = _der_tlv(body, i)
        _, _, i = _der_tlv(body, i)
        _, octs, i = _der_tlv(body, i)
        _, inner, _ = _der_tlv(octs, 0)
        j = 0
        _, _, j = _der_tlv(inner, j)
        _, d, j = _der_tlv(inner, j)
        return int.from_bytes(d, 'big')
    except Exception:
        _, body, _ = _der_tlv(der, 0)
        i = 0
        _, _, i = _der_tlv(body, i)
        _, d, i = _der_tlv(body, i)
        return int.from_bytes(d, 'big')


def _ec_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P256_P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1 + P256_A) * pow(2 * y1, -1, P256_P) % P256_P
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, P256_P) % P256_P
    x3 = (lam * lam - x1 - x2) % P256_P
    return x3, (lam * (x1 - x3) - y1) % P256_P


def _ec_mul(k, pt):
    r = None
    while k:
        if k & 1:
            r = _ec_add(r, pt)
        pt = _ec_add(pt, pt)
        k >>= 1
    return r


def _der_sig(r, s):
    def enc(x):
        b = x.to_bytes(32, 'big').lstrip(b'\x00') or b'\x00'
        if b[0] & 0x80:
            b = b'\x00' + b
        return b'\x02' + bytes([len(b)]) + b
    body = enc(r) + enc(s)
    return b'\x30' + bytes([len(body)]) + body


def ec_sign(pem, data):
    """ECDSA P-256 / SHA-256 签名，返回 base64(DER)。低 s 归一化，与客户端一致。"""
    d = ec_private_scalar(pem)
    z = int.from_bytes(hashlib.sha256(data).digest(), 'big')
    while True:
        k = int.from_bytes(os.urandom(32), 'big') % (P256_N - 1) + 1
        x1, _ = _ec_mul(k, (P256_GX, P256_GY))
        r = x1 % P256_N
        if r == 0:
            continue
        s = (pow(k, -1, P256_N) * (z + r * d)) % P256_N
        if s == 0:
            continue
        if s > P256_N // 2:
            s = P256_N - s
        return base64.b64encode(_der_sig(r, s)).decode('ascii')


def norm_pem(v):
    """把环境变量里字面量的 \\n 还原成真换行（复制粘贴友好）。"""
    v = (v or '').strip()
    if '\\n' in v and '\n' not in v:
        v = v.replace('\\n', '\n')
    return v


def env_device_keys():
    """从环境变量取设备证明材料（新版续期必需）。"""
    priv = norm_pem(os.getenv('TRAE_DEVICE_KEY_PEM', ''))
    pub = norm_pem(os.getenv('TRAE_DEVICE_PUB_PEM', ''))
    did = os.getenv('TRAE_DEVICE_ID', '').strip()
    mid = os.getenv('TRAE_MACHINE_ID', '').strip()
    if priv and pub and did:
        return {'deviceId': did, 'privateKeyPem': priv, 'publicKeyPem': pub, 'machineId': mid}
    return None


def device_proof(path, refresh_token, keys, client_id=None, platform_code='IDE_PC'):
    """构造 (DeviceProof, DeviceInfo)，供新版 ExchangeToken 使用。"""
    ts = int(time.time())
    nonce = os.urandom(16).hex()
    canonical = '\n'.join(['POST', path, client_id or ClientID, refresh_token, str(ts), nonce])
    proof = {'Timestamp': ts, 'Nonce': nonce,
             'Signature': ec_sign(keys['privateKeyPem'], canonical.encode('utf-8'))}
    info = {'DeviceID': keys.get('deviceId') or '', 'MachineID': keys.get('machineId') or '',
            'PlatformCode': platform_code, 'DeviceType': 'PC',
            'DeviceName': os.getenv('TRAE_DEVICE_NAME', '').strip() or platform.node() or 'PC',
            'DeviceModel': os.getenv('TRAE_DEVICE_MODEL', '').strip(),
            'ClientVersion': IdeVersion, 'DevicePublicKey': keys['publicKeyPem'],
            'DeviceBrand': os.getenv('TRAE_DEVICE_BRAND', '').strip(), 'DeviceCPU': '',
            'OSInfo': platform.system() or 'Windows', 'OSVersion': platform.release() or ''}
    return proof, info


# ══════════════════ Token 工具 ══════════════════
def refresh(refresh_token, keys=None):
    """续期：新版接口要求设备证明，缺了会返回 20405 Device proof required。"""
    if keys and keys.get('privateKeyPem') and keys.get('publicKeyPem'):
        path = '/trae/api/v3/oauth/ExchangeToken'
        last = None
        import json as _json
        # (ClientID, PlatformCode) 组合链：
        #   ① 桌面端实测钥匙 + IDE_PC（TRAE 线）
        #   ② 旧 ClientID + IDE_PC（旧 token 兜底）
        #   ③ SOLO 线：en1oxy7wnw8j9n + SOLO_PC（TRAE SOLO 客户端签发的 token）
        combos = [(ClientIDIde, 'IDE_PC')]
        for pair in ((ClientID, 'IDE_PC'), (ClientID, 'SOLO_PC')):
            if pair not in combos:
                combos.append(pair)
        for cid, pcode in combos:
            try:
                proof, info = device_proof(path, refresh_token, keys, cid, pcode)
            except Exception as e:
                return None, None, '设备签名失败: %s' % e
            body = _json.dumps({'ClientID': cid, 'ClientSecret': '', 'RefreshToken': refresh_token,
                                'DeviceInfo': info, 'DeviceProof': proof, 'IDEVersion': IdeVersion})
            status, text = _post(EP_EXCHANGE_PROOF, {'Content-Type': 'application/json', 'x-cloudide-token': ''}, body)
            if status < 400:
                break
            last = (status, text)
            if '10101' not in text and '20403' not in text:
                break
        else:
            status, text = last or (status, text)
    else:
        body = json.dumps({'ClientID': ClientID, 'RefreshToken': refresh_token, 'ClientSecret': '-', 'UserID': ''})
        status, text = _post(EP_EXCHANGE, {'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': UA}, body)
    if status >= 400 or status < 0:
        return None, None, 'refresh http=%s %s' % (status, explain_refresh_err(text))
    try:
        res = json.loads(text)['Result']
        return res.get('Token'), res.get('RefreshToken'), 'ok'
    except Exception as e:
        return None, None, 'parse refresh: %s %s' % (e, text[:200])


def explain_refresh_err(text):
    """把 Trae 错误码翻译成人话。"""
    try:
        err = (json.loads(text).get('ResponseMetadata') or {}).get('Error') or {}
        code = err.get('Code')
        dirty = ((err.get('Data') or {}).get('__Message.error')) or err.get('Message') or ''
    except Exception:
        return text[:200]
    hint = {20101: 'refreshToken 已失效或被轮换掉了，请重新提取',
            10101: 'refreshToken 与客户端不匹配（可能被别处轮换过、或来自另一条产品线的客户端），请重新提取',
            20405: '需设备证明：请配置 TRAE_DEVICE_KEY_PEM / TRAE_DEVICE_PUB_PEM / TRAE_DEVICE_ID',
            20403: '设备与 token 不匹配：确认设备密钥来自签发该 token 的同一台机器',
            }.get(code, '')
    return 'code=%s %s%s' % (code, dirty, ('（%s）' % hint) if hint else '')


def _jwt_exp(token):
    try:
        parts = token.split('.')
        pad = parts[1] + '=' * (-len(parts[1]) % 4)
        return int(json.loads(base64.urlsafe_b64decode(pad)).get('exp', 0))
    except Exception:
        return 0


def _jwt_uid(token):
    try:
        parts = token.split('.')
        pad = parts[1] + '=' * (-len(parts[1]) % 4)
        return str(json.loads(base64.urlsafe_b64decode(pad)).get('data', {}).get('id', ''))
    except Exception:
        return ''


def stable_device_id(seed):
    h = hashlib.md5(('trae:' + seed).encode('utf-8')).hexdigest()
    return str(int(h[:15], 16))[:16].rjust(16, '0')


def persist_refresh_token(uid, new_rt, seed_rt):
    """把续期后的最新 refreshToken 回写到账号 JSON（需设 TRAE_ACCOUNT_DIR）。"""
    d = os.environ.get('TRAE_ACCOUNT_DIR', '').strip()
    if not d or not os.path.isdir(d):
        return
    for fn in os.listdir(d):
        if not fn.endswith('.json'):
            continue
        p = os.path.join(d, fn)
        try:
            o = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        a = o.get('auth') or {}
        fuid = str((o.get('account') or {}).get('uid') or '')
        hit = (uid and fuid == uid) or ((not uid) and a.get('refreshToken') == seed_rt)
        if hit:
            if a.get('refreshToken') != new_rt:
                a['refreshToken'] = new_rt
                o['auth'] = a
                try:
                    json.dump(o, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
                    print('  💾 [续期] %s 的 refreshToken 已回写' % fn)
                except Exception as e:
                    print('  ⚠️  [续期] 回写失败:', e)
            return


def get_token(idx, rt_env, did_env, cache, force_refresh=False, keys=None, at_env=''):
    key = str(idx)
    did = did_env or stable_device_id(rt_env)
    ent = cache.get(key) or {}
    at = ent.get('accessToken')
    rt_cache = ent.get('refreshToken')
    exp = ent.get('expiresAt') or 0
    # 环境变量里的 token 比缓存新时就先用它（缓存里可能残留旧链里已失效的 token）
    at_use, rt_use, exp_use = at, (rt_cache or rt_env), exp
    if at_env:
        e_env = _jwt_exp(at_env)
        if e_env > exp_use:
            at_use, rt_use, exp_use = at_env, rt_env, e_env
    if at_use and not force_refresh:
        if exp_use and exp_use - 60 > time.time():
            return at_use, did, rt_use, None
        if token_ok(at_use, did):
            real_exp = _jwt_exp(at_use)
            if real_exp and real_exp != exp_use:
                cache[key] = {'accessToken': at_use, 'refreshToken': rt_use, 'expiresAt': real_exp, 'updatedAt': int(time.time())}
            return at_use, did, rt_use, None
    cands = []
    for c in (rt_cache, rt_env):
        if c and c not in cands:
            cands.append(c)
    last = 'no refreshToken'
    keys = keys or env_device_keys()
    for rt in cands:
        new_at, new_rt, msg = refresh(rt, keys)
        if new_at:
            new_rt = new_rt or rt
            cache[key] = {'accessToken': new_at, 'refreshToken': new_rt, 'expiresAt': _jwt_exp(new_at) or 0, 'updatedAt': int(time.time())}
            persist_refresh_token(_jwt_uid(new_at), new_rt, rt)
            return new_at, did, new_rt, None
        last = msg
    return None, did, (rt_cache or rt_env), last


# ══════════════════ 积分接口 ══════════════════
def credits_summary(token, device_id, tries=3):
    for attempt in range(tries):
        status, text = _post(EP_ENTITLE, ug_headers(token, device_id), json.dumps({'require_usage': True, 'full_data': True}))
        if status < 0:
            time.sleep(4 + attempt * 4)
            continue
        try:
            b = json.loads(text)
            s = b.get('usage_summary', {})
            total = s.get('total_amount')
            used = s.get('consumed_amount')
            remain = round(total - used, 2) if (total is not None and used is not None) else None
            return {'total': total, 'used': used, 'remain': remain, 'code': b.get('code', -1)}
        except Exception:
            time.sleep(4 + attempt * 4)
            continue
    return None


def token_ok(token, device_id):
    r = credits_summary(token, device_id, tries=1)
    if r is None:
        return True
    return r.get('code') not in AUTH_FAIL_CODES


# ══════════════════ 推送 ══════════════════
def notify(url, text):
    if not url:
        return None
    try:
        payload = json.dumps({'msgtype': 'text', 'text': {'content': text}}, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except Exception:
        return None


def bj_now():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)


def bj():
    return bj_now().strftime('%Y-%m-%d %H:%M:%S')


# ══════════════════ 账号选择 ══════════════════
def load_accounts():
    """优先读 TRAE_ACCOUNTS（与签到脚本共用同一个变量），否则退回旧变量。"""
    raw = os.environ.get('TRAE_ACCOUNTS', '').strip()
    if raw:
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        only = os.environ.get('TRAE_ONLY', '').strip()
        accounts = []
        for i, a in enumerate(data):
            rt = a.get('refreshToken', '').strip()
            if not rt:
                continue
            idx = i + 1
            label = a.get('name') or a.get('uid') or '账号%d' % idx
            if only and only not in (str(idx), str(a.get('uid', '')), label):
                continue
            # 设备证明材料：优先账号自带的（不同账号可能绑在不同机器上），
            # 拿不到时由 get_token 回落到环境变量里那套通用密钥。
            priv = norm_pem(a.get('deviceKeyPem', ''))
            pub = norm_pem(a.get('devicePubPem', ''))
            did = a.get('deviceId', '').strip()
            keys = None
            if priv and pub and did:
                keys = {'deviceId': did, 'privateKeyPem': priv, 'publicKeyPem': pub,
                        'machineId': (a.get('machineId') or '').strip()}
            accounts.append((idx, rt, did, label, keys, (a.get('accessToken') or '').strip()))
        if accounts:
            return accounts
    only = os.environ.get('TRAE_ONLY', '').strip()
    accounts = []
    for i in range(1, 10):
        name = 'TRAE_REFRESH_TOKEN' if i == 1 else 'TRAE_REFRESH_TOKEN_%d' % i
        rt = os.environ.get(name, '').strip()
        if not rt:
            continue
        did = os.environ.get('TRAE_DEVICE_ID' if i == 1 else 'TRAE_DEVICE_ID_%d' % i, '').strip()
        label = '账号%d' % i
        if only and only not in (str(i), label):
            continue
        accounts.append((i, rt, did, label, None, ''))
    return accounts


def iter_accts():
    for idx, rt, did, label, keys, at_env in load_accounts():
        yield idx, rt, did, label, keys, at_env


def main():
    accts = list(iter_accts())
    if not accts:
        print('❌ 未找到账号配置（TRAE_ACCOUNTS 或 TRAE_REFRESH_TOKEN）')
        sys.exit(1)
    webhook = os.environ.get('QYWX_TOKEN') or os.environ.get('WECHAT_WEBHOOK') or ''
    if webhook and 'key=' in webhook:
        webhook = webhook.split('key=')[-1].strip()
    if webhook:
        webhook = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=' + webhook
    cache = load_cache()
    ok, fail = [], []
    out = ['📊 Trae 积分监控', '🕒 ' + bj()]
    for i, (idx, rt, did, label, keys, at_env) in enumerate(accts):
        name = label if label else '账号%d' % idx
        token, did, new_rt, err = get_token(idx, rt, did, cache, keys=keys, at_env=at_env)
        if not token:
            print('❌ [%s] 凭证续期失败: %s' % (name, err))
            fail.append(name + ' 凭证续期失败'); out.append('❌ %s：凭证续期失败' % name); continue
        cs = credits_summary(token, did)
        if cs and cs.get('code') in AUTH_FAIL_CODES:
            token, did, new_rt, err = get_token(idx, rt, did, cache, force_refresh=True, keys=keys, at_env=at_env)
            cs = credits_summary(token, did) if token else None
        if not cs or cs.get('total') is None:
            print('❌ [%s] 查询失败' % name)
            fail.append(name); out.append('❌ %s：查询失败' % name); continue
        line = '%s：已用 %s · 剩余 %s' % (name, cs.get('used'), cs.get('remain'))
        print('💰 ' + line)
        out.append('💰 ' + line)
        ok.append(name)
        if i < len(accts) - 1:
            time.sleep(3)
    save_cache(cache)
    if webhook and (ok or fail):
        st = notify(webhook, '\n'.join(out))
        print('📤 推送状态:', st)
    hard = [n for n in fail if '凭证续期失败' in n]
    if hard:
        sys.exit(1)
    print('🏁 全部完成')


if __name__ == '__main__':
    main()
