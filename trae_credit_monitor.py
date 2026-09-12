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
  • 多账号     支持任意数量账号，环境变量 TRAE_REFRESH_TOKEN[_N] 配置
  • 微信推送   已用 / 剩余积分一目了然

📦 环境变量
  TRAE_REFRESH_TOKEN       第 1 个账号的 refreshToken（必填）
  TRAE_REFRESH_TOKEN_2~_N  第 2~N 个账号的 refreshToken（可选）
  WECHAT_WEBHOOK           企业微信机器人 webhook 地址（可选，用于推送）
  TRAE_TOKEN_CACHE         缓存文件路径（可选，默认 /ql/data/config/ 或脚本同目录）
  TRAE_SAVE_DIR            账号 JSON 所在目录（可选，用于回写轮换后的 refreshToken）

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
  1. 脚本放入 /ql/data/scripts/，环境变量填好 TRAE_REFRESH_TOKEN_* 与 WECHAT_WEBHOOK
  2. 定时任务：python /ql/data/scripts/trae_credit_monitor.py   定时 0 * * * *
  3. 默认查询全部账号；设 JOB_INDEX 可只查部分（用法同签到脚本）

📌 特别说明
  • refreshToken 是轮换链：每次续期都会产生新值，脚本会写回缓存与账号文件，
    请勿在多处同时使用同一账号，否则会互相使对方 token 失效。
  • 只有"refreshToken 也续期失败"才算硬失败；网络抖动等软失败会照常推送。
────────────────────────────────────────────────────────────
"""

import base64, datetime, hashlib, json, os, sys, time, urllib.request, urllib.error

UgHost = 'https://api.trae.cn'
OAuthHost = 'https://api.trae.com.cn'
ClientID = 'en1oxy7wnw8j9n'
EP_EXCHANGE = OAuthHost + '/cloudide/api/v3/trae/oauth/ExchangeToken'
EP_ENTITLE = UgHost + '/trae/api/v2/pay/user_current_entitlement_list'
UA = 'Trae/1.0'
AUTH_FAIL_CODES = (1001, 1002)


# ══════════════════ 缓存文件 ══════════════════
def _cache_path():
    p = os.environ.get('TRAE_TOKEN_CACHE', '').strip()
    if p:
        return p
    for cand in ('/ql/data/config/trae_token_cache.json',
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trae_token_cache.json')):
        try:
            d = os.path.dirname(cand)
            if d and os.path.isdir(d):
                return cand
        except Exception:
            pass
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trae_token_cache.json')


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


# ══════════════════ Token 工具 ══════════════════
def refresh(refresh_token):
    body = json.dumps({'ClientID': ClientID, 'RefreshToken': refresh_token, 'ClientSecret': '-', 'UserID': ''})
    status, text = _post(EP_EXCHANGE, {'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': UA}, body)
    if status >= 400 or status < 0:
        return None, None, 'refresh http=%s %s' % (status, text[:200])
    try:
        res = json.loads(text)['Result']
        return res.get('Token'), res.get('RefreshToken'), 'ok'
    except Exception as e:
        return None, None, 'parse refresh: %s %s' % (e, text[:200])


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
    """把续期后的最新 refreshToken 回写到账号 JSON（需设 TRAE_SAVE_DIR）。"""
    d = os.environ.get('TRAE_SAVE_DIR', '').strip()
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


def get_token(idx, rt_env, did_env, cache, force_refresh=False):
    key = str(idx)
    did = did_env or stable_device_id(rt_env)
    ent = cache.get(key) or {}
    at = ent.get('accessToken')
    rt_cache = ent.get('refreshToken')
    exp = ent.get('expiresAt') or 0
    if at and not force_refresh:
        if exp and exp - 60 > time.time():
            return at, did, (rt_cache or rt_env), None
        if token_ok(at, did):
            real_exp = _jwt_exp(at)
            if real_exp and real_exp != exp:
                cache[key] = {'accessToken': at, 'refreshToken': rt_cache or rt_env, 'expiresAt': real_exp, 'updatedAt': int(time.time())}
            return at, did, (rt_cache or rt_env), None
    cands = []
    for c in (rt_cache, rt_env):
        if c and c not in cands:
            cands.append(c)
    last = 'no refreshToken'
    for rt in cands:
        new_at, new_rt, msg = refresh(rt)
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
def selected_indexes():
    raw = os.environ.get('JOB_INDEX', '').strip()
    idxs = []
    if raw:
        for part in raw.replace(',', ' ').split():
            if part.isdigit() and int(part) >= 1:
                idxs.append(int(part))
    if idxs:
        return sorted(set(idxs))
    return []


def iter_accts():
    for i in (selected_indexes() or range(1, 6)):
        t = os.environ.get('TRAE_REFRESH_TOKEN' if i == 1 else 'TRAE_REFRESH_TOKEN_%d' % i, '').strip()
        if not t:
            continue
        yield i, t, os.environ.get('TRAE_DEVICE_ID' if i == 1 else 'TRAE_DEVICE_ID_%d' % i, '').strip()


def main():
    accts = list(iter_accts())
    if not accts:
        print('❌ 未找到 TRAE_REFRESH_TOKEN')
        sys.exit(1)
    webhook = os.environ.get('WECHAT_WEBHOOK', '').strip()
    cache = load_cache()
    ok, fail = [], []
    out = ['📊 Trae 积分监控', '🕒 ' + bj()]
    for i, (idx, rt, did) in enumerate(accts):
        name = 'acct %d' % idx
        token, did, new_rt, err = get_token(idx, rt, did, cache)
        if not token:
            print('❌ [%s] 凭证续期失败: %s' % (name, err))
            fail.append(name + ' 凭证续期失败'); out.append('❌ %s：凭证续期失败' % name); continue
        cs = credits_summary(token, did)
        if cs and cs.get('code') in AUTH_FAIL_CODES:
            token, did, new_rt, err = get_token(idx, rt, did, cache, force_refresh=True)
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
