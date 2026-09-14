#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trae AutoCheckin · Trae 每日自动签到（抗 9074 限流版）
────────────────────────────────────────────────────────────
一个零依赖的 Trae 积分签到脚本：缓存 token、自动续期、多账号轮签、
当日去重、限流熔断，签到结果推送到企业微信 / PushPlus。

✨ 特性
  • 零依赖     仅用 Python 标准库，无需 pip 安装（解密桌面端凭据时才需 cryptography）
  • Token 缓存 复用未过期的 accessToken，失效才用 refreshToken 续期
  • 链式续期   refreshToken 会轮换，脚本自动回写最新值，长期不失效
  • 多账号     TRAE_ACCOUNTS(JSON) / TRAE_REFRESH_TOKEN[_N] / 桌面端凭据 三种配法均可
  • 自动解密   直接读 Trae 客户端 storage.json，免抓包免手抄 token
  • 稳定设备   按账号生成固定 16 位设备号并持久化，跨运行不漂移
  • 智能轮签   默认每轮只签 1 个账号、按小时轮换，从源头避开 9074 排队限流
  • 抗 9074    请求体带 req_source + 设备头（与客户端同款，缺了会被拒成 9074）
  • 失败让路   本轮没签成的交给下一轮 cron 补签，不硬轰、不拖其它账号下水
  • 积分余额   签到后用 entitlement 接口查真实余额，推送里直接给数字
  • 微信推送   企业微信群机器人 / PushPlus，多账号结果一目了然

🛡 抗 9074 限流要点
  • 强制直连，不走系统代理 / Clash —— 多账号共用一个出口 IP 最容易触发限流
  • 只发一个小写 x-device-id —— 同时发大小写两个头会被风控判为异常客户端
  • 每账号每轮只发 1 次 claim —— 9074 是按时间窗口排队，当场连发反而延长惩罚窗口
  • 不再连坐：某个账号 9074 只给自己记冷却，其余账号继续签
    （想恢复旧行为一个被限就全体收工，设 TRAE_CIRCUIT=1）
  • 当日状态文件 .trae_checkin_state.json —— 已签成功的账号后续运行零请求
  • HTTP 429/5xx 与 code=9074 同等对待；账号间真发过 claim 才错峰 12~25s
  • 9074 反复出现 = 设备号被服务端记住，自动换新设备号立刻重签（实测有效）
  • 换号后仍 9074 才按账号记冷却（早窗 12 分钟 / 平时 55 分钟），冷却内零请求
  • 早窗(TRAE_PEAK_HOURS，默认 0 点)自动一轮全签，其余时段每小时轮 1 个
  • 实测结论：换设备号 / 换出口 IP / 换请求头 都绕不开 9074（服务端按"当前
    参与用户太多"做容量门），凌晨 0 点前后最容易签成，所以 cron 建议放在 00:23
  • 实测 00:00~00:10 是全天最高峰（整点所有人一起签），cron 别用 0 分；
    本脚本启动后再随机抖 0~20s，避免同一定时任务的多个部署互相撞车
  • 设备号优先用客户端真实号（storage.json 的 iCubeAuthInfo://icube-dc 键），拿不到才生成

📦 环境变量
  TRAE_ACCOUNTS            多账号 JSON 数组（推荐），字段见下
  TRAE_REFRESH_TOKEN       第 1 个账号的 refreshToken（兼容旧部署，accessToken 自动换取）
  TRAE_REFRESH_TOKEN_2~_9  第 2~9 个账号的 refreshToken（可选）
  TRAE_ACCESS_TOKEN        单账号 accessToken（可选）
  TRAE_ICUBE_AUTH          桌面端加密凭据串（可选，自动解密）
  TRAE_STORAGE_PATH        storage.json 路径（可选，自动读取并解密）
  TRAE_DEVICE_ID[_N]       设备号（可选；留空则优先用客户端真实设备号，再回退生成）
  TRAE_BATCH               每轮签几个账号（可选，默认 1 按小时轮换；all = 一轮全签）
  TRAE_JITTER              启动随机抖动（可选，默认开；设 0 关闭 0~20s 错峰等待）
  TRAE_COOLDOWN_MIN        平时 9074 冷却分钟数（可选，默认 55）
  TRAE_PEAK_HOURS          早窗小时（可选，默认 0；支持 0 / 0,23 / 0-1）
  TRAE_PEAK_COOLDOWN_MIN   早窗内冷却分钟数（可选，默认 12）
  TRAE_CIRCUIT             设 1 恢复旧熔断：一个账号 9074 就全体收工（默认关）
  TRAE_ROTATE              9074 后自动换新设备号（可选，默认开；设 0 关闭）
  TRAE_DEVICE_BRAND        设备品牌请求头（可选，默认不发，对应桌面端 device_model）
  TRAE_UID[_N]             账号标识（可选，仅用于日志）
  TRAE_ONLY                只跑指定账号：序号 / uid / 名字（可选）
  CLAIM_TRIES              单轮 claim 重试次数（可选，默认 1，调大反而更容易被限）
  TRAE_TOKEN_CACHE         token 缓存文件路径（可选，默认 /ql/data/config/ 或脚本同目录）
  TRAE_ACCOUNT_DIR         账号 JSON 所在目录（可选，用于回写轮换后的 refreshToken）
  QYWX_TOKEN               企业微信群机器人 Webhook key（可选，也兼容 WECHAT_WEBHOOK）
  PLUSPLUS_TOKEN           PushPlus token（可选）

  TRAE_ACCOUNTS 每个账号对象支持的字段：
    accessToken / refreshToken  明文 token（可只给 refreshToken，脚本自动换取）
    icubeAuth                  桌面端 storage.json 里的加密串（自动解密）
    storagePath                storage.json 路径（自动读取并解密）
    uid                        账号标识（用于缓存键与日志）
    deviceId                   16 位设备号（可选，不填自动生成并持久化）
    name                       备注（可选）

🚀 使用方法（青龙面板）
  1. 脚本放入 /ql/data/scripts/，环境变量填好 TRAE_ACCOUNTS 与 QYWX_TOKEN
  2. 定时任务：python /ql/data/scripts/trae_checkin.py
     早窗主力：  23 0 * * *     ← 实测 00:15~00:45 连续签成，早窗自动一轮全签
     其余补签：  7,37 * * * *   ← 冷却 12 分钟到点就补，签成了就不再请求
  3. 想一轮全签（多账号少、能接受慢一点）设 TRAE_BATCH=all，靠熔断+错峰兜底；
     积分查询另用 trae_credit_monitor.py

🎛 运行模式
  每小时轮签（默认） 每轮只签 1 个账号，按北京时间小时轮换，全天自然轮完全部
  一轮多签          TRAE_BATCH=2 每轮签 2 个；TRAE_BATCH=all 一轮签完（靠错峰兜底）
  手动指定           TRAE_ONLY=3 只签第 3 个；也可填 uid 或 name
  当日去重           已签成功的账号当天不再请求接口，重复触发定时任务不浪费额度

📌 特别说明
  • 签接口按"设备号"维度判断今日是否已签；实测用模拟的 16 位数字即可签到成功，
    服务端不校验设备号是否真实注册。
  • refreshToken 是轮换链：每次续期都会产生新值，脚本会写回缓存与账号文件，
    请勿在多处同时使用同一账号，否则会互相使对方 token 失效。
  • 只有"refreshToken 也续期失败"才算硬失败；限流等软失败会照常推送结果。
────────────────────────────────────────────────────────────
"""

import base64, glob, hashlib, json, os, platform, random, sys, time, urllib.request, urllib.error

UgHost = 'https://api.trae.cn'
OAuthHost = 'https://api.trae.com.cn'
ClientID = 'en1oxy7wnw8j9n'
IdeVersion = '1.107.1'
UA = 'Trae/%s' % IdeVersion
EP_STATUS = UgHost + '/trae/api/v2/ug/checkin_credits/status'
EP_CLAIM = UgHost + '/trae/api/v2/ug/checkin_credits/claim'
EP_EXCHANGE = OAuthHost + '/cloudide/api/v3/trae/oauth/ExchangeToken'
EP_ENTITLE = UgHost + '/trae/api/v2/pay/user_current_entitlement_list'
AUTH_FAIL_CODES = (1001, 1002, 401, 403)    # 未认证 / token 失效 / 鉴权类 HTTP
RATE_HTTP_CODES = (429, 500, 502, 503, 504)
RATE_CODE = 9074                            # 参与用户太多（排队限流，可重试）
REQ_SOURCE = 1                              # 客户端签到请求体固定带 {"req_source":1}
REQ_BODY = '{"req_source": %d}' % REQ_SOURCE
ALREADY_CODE = 9095                         # 今日已签
QYWX_URL = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key='
PUSHPLUS_URL = 'https://www.pushplus.plus/send'

# 企业微信 / PushPlus 推送配置（留空则不推送）
PLUSPLUS_TOKEN = os.getenv('PLUSPLUS_TOKEN', '')
QYWX_TOKEN = os.getenv('QYWX_TOKEN') or os.getenv('WECHAT_WEBHOOK') or ''

HERE = os.path.dirname(os.path.abspath(__file__))
DEVICE_ID_FILE = os.path.join(HERE, '.trae_device_ids.json')
STATE_FILE = os.path.join(HERE, '.trae_checkin_state.json')
# 刷新后的 token 缓存：Trae 每次续期都会轮换 refreshToken，青龙里
# TRAE_ACCOUNTS 是静态的，必须靠本文件记住最新的 token 对，否则会越刷越失效。
TOKEN_CACHE_FILE = os.path.join(HERE, '.trae_token_cache.json')


# ══════════════════ tc 解密（仅读桌面端凭据时用得到） ══════════════════
SALT_A = bytes([82, 9, 106, 213, 48, 54, 165, 56, 191, 64, 163, 158, 129, 243, 215, 251,
                124, 227, 57, 130, 155, 47, 255, 135, 52, 142, 67, 68, 196, 222, 233, 203,
                84, 123, 148, 50, 166, 194, 35, 61, 238, 76, 149, 11, 66, 250, 195, 78,
                8, 46, 161, 102, 40, 217, 36, 178, 118, 91, 162, 73, 109, 139, 209, 37])
SALT_B = bytes([31, 221, 168, 51, 136, 7, 199, 49, 177, 18, 16, 89, 39, 128, 236, 95,
                96, 81, 127, 169, 25, 181, 74, 13, 45, 229, 122, 159, 147, 201, 156, 239,
                160, 224, 59, 77, 174, 42, 245, 176, 200, 235, 187, 60, 131, 83, 153, 97,
                23, 43, 4, 126, 186, 119, 214, 38, 225, 105, 20, 99, 85, 33, 12, 125])
SALT_C = bytes([191, 192, 216, 250, 122, 246, 220, 97, 31, 254, 98, 27, 8, 72, 71, 176,
                135, 99, 96, 18, 127, 101, 203, 104, 211, 102, 191, 125, 37, 72, 150, 156,
                51, 229, 121, 35, 17, 153, 141, 177, 110, 131, 150, 128, 172, 255, 254, 6,
                18, 140, 55, 62, 236, 249, 135, 64, 135, 12, 117, 4, 89, 149, 168, 209])
SALT_D = bytes([246, 204, 26, 232, 232, 70, 129, 109, 223, 146, 169, 242, 23, 241, 105, 145,
                50, 196, 165, 42, 254, 120, 3, 54, 244, 207, 209, 85, 53, 6, 138, 106,
                175, 148, 31, 204, 186, 186, 165, 182, 87, 142, 49, 10, 39, 110, 26, 154,
                86, 56, 173, 125, 18, 64, 198, 225, 99, 99, 83, 82, 191, 134, 76, 170])
SALT_AES = bytes(a ^ b for a, b in zip(SALT_A, SALT_B))
SALT_AES_PRIVATE = bytes(a ^ b for a, b in zip(SALT_C, SALT_D))
STORAGE_KEY = 'iCubeAuthInfo://icube.cloudide'


def enc_type_of(header):
    if header[0:6] == bytes([0x74, 0x63, 0x05, 0x10, 0x00, 0x00]):
        return 'AES'
    if header[0:6] == bytes([18, 57, 32, 32, 2, 3]):
        return 'AES_PRIVATE'
    return 'UNKNOWN'


def key_iv_of(random_bytes, enc_type):
    salt = SALT_AES_PRIVATE if enc_type == 'AES_PRIVATE' else SALT_AES
    final_hash = hashlib.sha512(hashlib.sha512(random_bytes).digest() + salt).digest()
    return final_hash[0:16], final_hash[16:32]


def decrypt_storage_value(base64_value):
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        raise SystemExit('❌ 解密 icubeAuth/storage.json 需要 cryptography，'
                         '请 pip install cryptography；'
                         '或改用 accessToken/refreshToken 方式配置账号（零依赖）')
    buf = base64.b64decode(base64_value)
    enc_type = enc_type_of(buf[0:6])
    if enc_type == 'UNKNOWN':
        raise ValueError('未知的加密类型 (前 6 字节=%s)' % buf[0:6].hex())
    key, iv = key_iv_of(buf[6:38], enc_type)
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    decrypted = dec.update(buf[38:]) + dec.finalize()
    stored_hash, plaintext = decrypted[0:64], decrypted[64:]
    # 桌面端写盘用 PKCS7 填充，去掉填充后再校验与解析（旧的非零填充一并兼容）
    pad = plaintext[-1] if plaintext else 0
    if 1 <= pad <= 16:
        plaintext = plaintext[:-pad]
    else:
        plaintext = plaintext.rstrip(b'\x00').rstrip()
    if stored_hash != hashlib.sha512(plaintext).digest():
        raise ValueError('SHA-512 校验失败，解密可能不正确')
    return plaintext.decode('utf-8')


def dc_device_id(storage):
    """取客户端真实设备号：storage.json 里 iCubeAuthInfo://icube-dc:<numeric> 键。
    真机设备号比脚本生成的号更像正常客户端，拿不到时才回退生成号。"""
    for k in storage:
        if k.startswith('iCubeAuthInfo://icube-dc:'):
            d = k.split(':')[-1]
            if d.isdigit():
                return d
    return ''


def load_from_storage(storage_path):
    """返回 (解密后的登录凭据, 客户端真实设备号)。"""
    with open(storage_path, 'r', encoding='utf-8') as fh:
        storage = json.load(fh)
    enc = (storage.get(STORAGE_KEY) or '').strip()
    if not enc:
        raise ValueError('storage.json 里找不到 %s' % STORAGE_KEY)
    if enc.startswith('{'):
        return json.loads(enc), dc_device_id(storage)
    return json.loads(decrypt_storage_value(enc)), dc_device_id(storage)


# ══════════════════ 缓存文件 ══════════════════
def _cache_path():
    p = os.environ.get('TRAE_TOKEN_CACHE', '').strip()
    if p:
        return p
    for cand in ('/ql/data/config/.trae_token_cache.json', TOKEN_CACHE_FILE):
        d = os.path.dirname(cand)
        if d and os.path.isdir(d):
            return cand
    return TOKEN_CACHE_FILE


def load_cache():
    try:
        with open(_cache_path(), 'r', encoding='utf-8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_cache(cache):
    try:
        path = _cache_path()
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print('⚠️  [缓存] 写入失败:', e)


def put_cache(cache, acc):
    """把（续期后的）token 对写进缓存，并立即落盘——轮换链断不得。"""
    key = _acct_key(acc)
    if not (key and acc.get('accessToken')):
        return
    cache[key] = {'accessToken': acc['accessToken'],
                  'refreshToken': acc.get('refreshToken', ''),
                  'expiresAt': _jwt_exp(acc['accessToken']),
                  'updatedAt': int(time.time())}
    save_cache(cache)


def apply_cache(accounts, cache=None):
    """用缓存里更新的 token 覆盖静态环境变量里的旧 token。"""
    cache = load_cache() if cache is None else cache
    if not cache:
        return accounts
    hit = 0
    for a in accounts:
        rec = cache.get(_acct_key(a)) or {}
        if rec.get('accessToken'):
            a['accessToken'] = rec['accessToken']
            if rec.get('refreshToken'):
                a['refreshToken'] = rec['refreshToken']
            hit += 1
    if hit:
        print('🔁 [缓存] 已用上次续期的 token 覆盖 %d 个账号' % hit)
    return accounts


# ══════════════════ 时间与当日状态 ══════════════════
def bj_now():
    return time.gmtime(time.time() + 8 * 3600)


def bj():
    return time.strftime('%Y-%m-%d %H:%M:%S', bj_now())


def today_str():
    return time.strftime('%Y-%m-%d', bj_now())


def load_state():
    """返回 {'date': 'YYYY-MM-DD', 'done': {key: {...}}, 'cooldown': {key: 'YYYY-MM-DD HH:MM'}}。
    跨天自动清空。"""
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as fh:
            st = json.load(fh)
    except Exception:
        st = {}
    if st.get('date') != today_str():
        st = {'date': today_str(), 'done': {}, 'cooldown': {}}
    st.setdefault('done', {})
    st.setdefault('cooldown', {})
    return st


def mark_done(key, info):
    st = load_state()
    st['done'][str(key)] = info
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as fh:
            json.dump(st, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        print('⚠️  [状态] 写入失败:', e)


def cooldown_minutes():
    """9074 后冷却多久：早窗短冷却（默认 12 分钟），平时长冷却（默认 55 分钟）。"""
    env = 'TRAE_PEAK_COOLDOWN_MIN' if in_peak_hour() else 'TRAE_COOLDOWN_MIN'
    try:
        return max(1, int(os.getenv(env, str(PEAK_COOLDOWN_MIN if in_peak_hour() else COOLDOWN_MIN))))
    except Exception:
        return PEAK_COOLDOWN_MIN if in_peak_hour() else COOLDOWN_MIN


def set_cooldown(key, minutes):
    """9074 后给该账号记一个冷却时间：反正换设备号/换出口 IP 都没用（实测），
    短时间反复戳只会刷屏，冷却到点再由 cron 补签。"""
    st = load_state()
    st['cooldown'][str(key)] = time.strftime('%Y-%m-%d %H:%M', time.localtime(time.time() + minutes * 60))
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as fh:
            json.dump(st, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        print('⚠️  [冷却] 写入失败: %s' % e)


def cooldown_left(key, state=None):
    """返回该账号还剩多少秒冷却；没在冷却返回 0。"""
    st = state if state is not None else load_state()
    until = (st.get('cooldown') or {}).get(str(key)) or ''
    try:
        ts = time.mktime(time.strptime(until, '%Y-%m-%d %H:%M'))
    except Exception:
        return 0
    return max(0, int(ts - time.time()))


def _acct_key(acc):
    """账号唯一键：uid > _name > name。用于 token 缓存与当日状态，绝不能撞键，
    否则多账号会互相覆盖（曾导致 refreshToken-only 模式 5 个账号共用空键）。"""
    return (str(acc.get('uid') or '').strip()
            or str(acc.get('_name') or '').strip()
            or str(acc.get('name') or '').strip()
            or 'default')


# ══════════════════ 日志与图标 ══════════════════
BOX = 52


def _wlen(s):
    """按显示宽度计数：中文/emoji 占 2 列，方框才对得齐。"""
    n = 0
    for ch in s:
        o = ord(ch)
        n += 2 if (0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF or 0xAC00 <= o <= 0xD7A3
                   or 0xF900 <= o <= 0xFAFF or 0xFE30 <= o <= 0xFE6F or 0xFF00 <= o <= 0xFF60
                   or 0x1F300 <= o <= 0x1FAFF) else 1
    return n


def log_cell(s):
    body = ' ' + s
    print('║' + body + ' ' * max(0, BOX - _wlen(body)) + '║')


def log_box(lines, top=''):
    print()
    print('╔' + '═' * BOX + '╗')
    for s in ([top] if top else []) + list(lines):
        log_cell(s)
    print('╚' + '═' * BOX + '╝')


def log_title(total):
    log_box(['🕒 启动时间: ' + bj(), '👥 账号数量: %s' % total],
            '🤖 Trae SOLO 每日签到脚本（多账号）')


def log_head(title):
    body = ' ' + title
    print()
    print('┌' + '─' * BOX + '┐')
    print('│' + body + ' ' * max(0, BOX - _wlen(body)) + '│')
    print('└' + '─' * BOX + '┘')


# ══════════════════ HTTP（强制直连，不走系统代理） ══════════════════
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _post(url, headers, body='{}', timeout=30):
    req = urllib.request.Request(url, data=(body.encode('utf-8') if isinstance(body, str) else body),
                                 headers=headers, method='POST')
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')
    except Exception as e:
        return -1, str(e)


def ug_headers(token, device_id):
    # 与桌面端 _applyUgDeviceHeaders 对齐：缺这些设备头会被服务端拒成 9074
    headers = {'Authorization': 'Cloud-IDE-JWT ' + token, 'X-User-Region': 'CN',
               'User-Agent': UA, 'Content-Type': 'application/json'}
    if device_id:
        headers['x-device-id'] = device_id
    headers['x-device-type'] = platform.system() or 'Windows'
    headers['x-os-version'] = platform.version() or '10.0.19045'
    headers['x-app-version'] = IdeVersion
    brand = os.getenv('TRAE_DEVICE_BRAND', '').strip()
    if brand:
        headers['x-device-brand'] = brand
    return headers


# ══════════════════ Token 工具 ══════════════════
def refresh(refresh_token):
    """用 refreshToken 换新 accessToken；Trae 会同时轮换 refreshToken。"""
    body = json.dumps({'ClientID': ClientID, 'RefreshToken': refresh_token,
                       'ClientSecret': '-', 'UserID': ''})
    status, text = _post(EP_EXCHANGE, {'Content-Type': 'application/json',
                                       'Accept': 'application/json', 'User-Agent': UA}, body)
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


def ensure_token(acc, cache):
    """accessToken 缺失时直接续期；返回 (ok, msg)。续期成功即回写缓存与账号文件。"""
    if not acc.get('refreshToken'):
        return False, '无 refreshToken，无法刷新'
    new_at, new_rt, msg = refresh(acc['refreshToken'])
    if not new_at:
        return False, msg
    acc['accessToken'] = new_at
    if new_rt:
        acc['refreshToken'] = new_rt
    put_cache(cache, acc)
    persist_tokens(acc)
    return True, '已刷新 accessToken'


def persist_tokens(acc):
    """若本机存有该账号的凭据文件 trae-<uid>*.json，把续期结果写回去。
    目录可用 TRAE_ACCOUNT_DIR 指定，默认取脚本所在目录（青龙下通常没有该文件，
    静默跳过即可，token 仍会保存在 .trae_token_cache.json 里）。"""
    uid = str(acc.get('uid', '') or '').strip()
    if not uid:
        return
    files = []
    for d in [os.getenv('TRAE_ACCOUNT_DIR', '').strip(), HERE]:
        if d and os.path.isdir(d):
            files += glob.glob(os.path.join(d, 'trae-%s*.json' % uid))
    if not files:
        return
    fp = files[0]
    try:
        with open(fp, 'r', encoding='utf-8') as fh:
            d = json.load(fh)
        node = d['auth'] if 'auth' in d else d
        node['accessToken'] = acc['accessToken']
        node['refreshToken'] = acc.get('refreshToken', '')
        with open(fp, 'w', encoding='utf-8') as fh:
            json.dump(d, fh, ensure_ascii=False, indent=2)
        print('💾 [持久化] 已更新 %s' % os.path.basename(fp))
    except Exception as e:
        print('⚠️ [持久化] 写回失败: %s' % e)


# ══════════════════ 设备号 ══════════════════
def stable_device_id(seed):
    """由账号特征生成一个固定的 16 位数字设备号（1000000000000000 ~ 9999999999999999）。
    种子用稳定账号键，绝不能用 accessToken —— 它每次续期都会变。"""
    h = hashlib.sha256(seed.encode('utf-8')).digest()
    return str(int.from_bytes(h[:8], 'big') % (10 ** 16 - 10 ** 15) + 10 ** 15)


def load_device_ids():
    try:
        with open(DEVICE_ID_FILE, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_device_ids(ids):
    try:
        with open(DEVICE_ID_FILE, 'w', encoding='utf-8') as fh:
            json.dump(ids, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        print('⚠️  [设备号] 持久化失败: %s' % e)


def rotate_device_id(acc):
    """9074 反复出现时换一个全新设备号：旧号会被服务端记住（越戳越黑），
    实测换个新号立刻就能签成。新号按时间生成，保证与旧号不同并写回设备号文件。"""
    key = _acct_key(acc)
    ids = load_device_ids()
    new_id = stable_device_id('%s:rotate:%d' % (key, int(time.time())))
    ids[key] = new_id
    save_device_ids(ids)
    acc['deviceId'] = new_id
    print('🔄 [设备号] %s 换新设备号 %s（旧号已被服务端记住）'
          % (acc.get('_name') or acc.get('name') or key, new_id))
    return new_id


def device_id_for(acc, manual=''):
    """优先级：手动 deviceId > 客户端真实设备号 > 已持久化 > 自动生成并持久化。
    种子必须用稳定键(_acct_key)：早先用 accessToken 做种子，而 accessToken
    每次续期都会变，导致设备号每轮都换、凭据文件无限增长 —— 对风控而言
    "设备不停更换"本身就是高危信号。"""
    if manual and manual.isdigit() and len(manual) == 16:
        return manual
    real = str(acc.get('_realDid') or '').strip()
    if real.isdigit() and len(real) == 16:
        return real
    seed = _acct_key(acc)
    ids = load_device_ids()
    if seed in ids:
        return ids[seed]
    new_id = stable_device_id(seed)
    ids[seed] = new_id
    save_device_ids(ids)
    return new_id


# ══════════════════ 账号读取 ══════════════════
def parse_hours(spec):
    """把 '0' / '0,23' / '0-1' 解析成小时集合，解析不了就返回空集合。"""
    hours = set()
    for part in (spec or '').replace('，', ',').split(','):
        part = part.strip()
        if '-' in part:
            a, _, b = part.partition('-')
            if a.strip().isdigit() and b.strip().isdigit():
                hours |= {h % 24 for h in range(int(a), int(b) + 1)}
        elif part.isdigit():
            hours.add(int(part) % 24)
    return hours


def in_peak_hour(now=None):
    """是否处于早窗（TRAE_PEAK_HOURS，默认 0 点）——实测 00:15~00:45 最容易签成。"""
    return (now or bj_now()).tm_hour in parse_hours(os.getenv('TRAE_PEAK_HOURS', '0'))


def pick_batch(pending):
    """每轮默认只签 1 个账号，按北京时间小时轮换 —— 9074 是服务端按出口 IP 的
    排队限流，一轮只打一个号最稳；配上每小时一跑，全天自然把每个号都轮一遍。
    TRAE_BATCH=all 一轮全签（靠账号间错峰 + 熔断兜底），TRAE_BATCH=2 一轮签 2 个。"""
    raw = os.getenv('TRAE_BATCH', '').strip().lower()
    if raw in ('all', '0'):
        return pending
    try:
        size = max(1, int(raw)) if raw else 1
    except Exception:
        size = 1
    if pending and in_peak_hour():
        return pending        # 早窗容量最松，一轮把剩下的全签掉（账号间照常错峰）
    start = bj_now().tm_hour % max(1, len(pending))
    return (pending[start:] + pending[:start])[:size]


def pick(d, *candidates):
    for c in candidates:
        if c in d and d[c]:
            return d[c]
    return ''


def normalize(d, src, name='', real=''):
    return {'accessToken': pick(d, 'accessToken', 'token', 'access_token'),
            'refreshToken': pick(d, 'refreshToken', 'refresh_token'),
            'deviceId': pick(d, 'deviceId', 'device_id'),
            'uid': str(pick(d, 'uid', 'userId', 'user_id')),
            '_src': src, '_name': name, '_realDid': real}


def build_account(raw, name):
    # 1) 明文 token 直给  2) 桌面端加密凭据串  3) 指定 storage.json 路径（带真实设备号）
    if raw.get('accessToken'):
        return normalize(raw, 'accounts.json(明文token)', name or raw.get('uid', name),
                         str(raw.get('realDeviceId') or ''))
    if raw.get('icubeAuth'):
        return normalize(json.loads(decrypt_storage_value(raw['icubeAuth'].strip())),
                         'accounts.json(icubeAuth)', name)
    if raw.get('storagePath'):
        d, real = load_from_storage(raw['storagePath'])
        return normalize(d, raw['storagePath'], name, real)
    raise ValueError('账号 %s 缺少 accessToken / icubeAuth / storagePath' % (name or '(未命名)'))


def from_env_only():
    """兼容旧脚本部署：只给 TRAE_REFRESH_TOKEN（_2.._9 后缀 = 多账号），
    accessToken 留空由后续流程自动续期换取，真正零依赖。"""
    rts = []
    for i in range(1, 10):
        name = 'TRAE_REFRESH_TOKEN' if i == 1 else 'TRAE_REFRESH_TOKEN_%d' % i
        v = os.getenv(name, '').strip()
        if v:
            rts.append((i, v))
    if not rts or os.getenv('TRAE_ACCESS_TOKEN'):
        return []
    accs = []
    for i, rt in rts:
        idx = '' if i == 1 else '_%d' % i
        accs.append({'accessToken': os.getenv('TRAE_ACCESS_TOKEN%s' % idx, '').strip(),
                     'refreshToken': rt,
                     'deviceId': os.getenv('TRAE_DEVICE_ID%s' % idx, '').strip(),
                     'uid': os.getenv('TRAE_UID%s' % idx, '').strip(),
                     'name': os.getenv('TRAE_NAME%s' % idx, '') or '账号%d' % i})
    print('🔁 [兼容] 从 TRAE_REFRESH_TOKEN* 读到 %d 个账号，accessToken 将自动续期换取' % len(accs))
    return accs


def filter_only(accounts):
    """TRAE_ONLY 支持按序号(从1开始)、uid 或名字过滤，便于青龙拆分定时任务错峰签到。"""
    only = os.getenv('TRAE_ONLY', '').strip()
    if not only:
        return accounts
    picked = [a for i, a in enumerate(accounts)
              if only in (str(i + 1), str(a.get('uid')), a.get('_name') or a.get('name') or '')]
    if picked:
        print('🎯 [筛选] TRAE_ONLY=%s -> 仅处理 %d 个账号' % (only, len(picked)))
        return picked
    print('⚠️ [筛选] TRAE_ONLY=%s 未匹配到账号，将处理全部' % only, file=sys.stderr)
    return accounts


def load_accounts():
    # 1) 多账号：TRAE_ACCOUNTS 为 JSON 数组（推荐，全部走环境变量）
    raw_list = os.getenv('TRAE_ACCOUNTS', '').strip()
    if raw_list:
        try:
            data = json.loads(raw_list)
        except Exception as e:
            print('❌ [凭据] TRAE_ACCOUNTS 不是合法 JSON: %s' % e, file=sys.stderr)
            sys.exit(1)
        data = [data] if isinstance(data, dict) else data
        accounts = []
        for i, raw in enumerate(data):
            try:
                accounts.append(build_account(raw, raw.get('name', '账号%d' % (i + 1))))
            except Exception as e:
                print('❌ [凭据] 账号%d 加载失败: %s' % (i + 1, e), file=sys.stderr)
        accounts = filter_only(apply_cache(accounts))
        if accounts:
            return accounts
        print('❌ [凭据] TRAE_ACCOUNTS 中没有任何可用账号。', file=sys.stderr)
        sys.exit(1)

    # 2) 兼容旧部署：TRAE_REFRESH_TOKEN[_N]
    accs = from_env_only()
    if accs:
        return filter_only(apply_cache(accs))

    # 3) 单账号：环境变量直给
    if os.getenv('TRAE_ACCESS_TOKEN') or os.getenv('TRAE_ICUBE_AUTH') or os.getenv('TRAE_STORAGE_PATH'):
        if os.getenv('TRAE_ICUBE_AUTH'):
            acc = normalize(json.loads(decrypt_storage_value(os.getenv('TRAE_ICUBE_AUTH').strip())),
                            '环境变量 TRAE_ICUBE_AUTH')
        elif os.getenv('TRAE_STORAGE_PATH'):
            d, real = load_from_storage(os.getenv('TRAE_STORAGE_PATH'))
            acc = normalize(d, os.getenv('TRAE_STORAGE_PATH'), '', real)
        else:
            acc = {'accessToken': os.getenv('TRAE_ACCESS_TOKEN', ''),
                   'refreshToken': os.getenv('TRAE_REFRESH_TOKEN', ''),
                   'deviceId': os.getenv('TRAE_DEVICE_ID', ''),
                   'uid': os.getenv('TRAE_UID', ''),
                   'name': os.getenv('TRAE_NAME', '环境变量账号')}
        acc['deviceId'] = os.getenv('TRAE_DEVICE_ID', '')
        acc['_name'] = acc.get('name', '') or acc.get('uid', '')
        return [acc]

    print('❌ [凭据] 未找到账号配置。可选写法：TRAE_ACCOUNTS(JSON数组，推荐) / '
          'TRAE_REFRESH_TOKEN(_2.._9) / TRAE_ACCESS_TOKEN+TRAE_REFRESH_TOKEN / '
          'TRAE_ICUBE_AUTH / TRAE_STORAGE_PATH', file=sys.stderr)
    sys.exit(1)


# ══════════════════ 签到接口 ══════════════════
def status_of(token, device_id):
    """返回 (checked_in, credits, enable, code, raw)；查询不通时前三项为 None。
    请求体必须带 req_source（客户端同款），空体会被服务端拒成 9074。"""
    status, text = _post(EP_STATUS, ug_headers(token, device_id), REQ_BODY)
    try:
        d = json.loads(text)
    except Exception:
        return None, None, None, -1, text
    code = d.get('code', -1)
    if status >= 400:
        return None, None, None, code, text
    return (bool(d.get('checked_in', False)), d.get('credits', 0), d.get('enable', False), code, text)


def claim(token, device_id):
    """签到领取积分一次，以业务 code 为准：0 成功 / 9095 今日已签 / 9074 限流可重试。
    返回 (http, code, message, 本次积分)。"""
    status, text = _post(EP_CLAIM, ug_headers(token, device_id), REQ_BODY)
    try:
        body = json.loads(text)
    except Exception:
        return status, '?', text, None
    points = ((body.get('data') or {}).get('points')) if isinstance(body.get('data'), dict) else None
    return status, body.get('code', -1), body.get('message') or text[:120], points


def is_rate(code, status):
    return code == RATE_CODE or status in RATE_HTTP_CODES


def claim_with_retry(acc, cache):
    """每账号每轮只发 1 次 claim（CLAIM_TRIES 可调大，但一般没必要）。
    9074 属服务端排队限流，短时间内反复轰会被延长惩罚，失败即收工交给下轮 cron；
    code=1001 时先续期 token 再立即重试（不占退避）。返回 (ok, code, msg, 本次积分)。"""
    try:
        tries = max(1, int(os.getenv('CLAIM_TRIES', '1')))
    except Exception:
        tries = 1
    last = ('?', '')
    for attempt in range(1, tries + 1):
        status, code, msg, points = claim(acc['accessToken'], acc.get('deviceId'))
        last = (code, msg)
        if code == 0:
            return True, code, msg, points
        if code == ALREADY_CODE:
            return False, code, msg, None
        if code in AUTH_FAIL_CODES and acc.get('refreshToken'):
            print('🔑 [claim] 检测到 code=%s，尝试刷新 token ...' % code)
            ok, rmsg = ensure_token(acc, cache)
            if not ok:
                return False, code, rmsg, None
            continue
        if not is_rate(code, status):
            return False, code, msg
        if attempt < tries:
            wait = random.randint(4, 9)
            print('⏳ [限流] 第%d次被限，%ds 后重试（或交给下轮 cron）...' % (attempt, wait))
            time.sleep(wait)
            continue
        print('⏳ [限流] 本轮放弃，等下轮 cron 自动补签')
    return False, last[0], last[1], None


def credits_summary(acc):
    """查询当前积分余额：优先用 usage_summary（总额-已用），再按 entitlement
    包求和兜底。实测该接口把 pack_list 放在根级（逆向资料里是 data 包装），两种都认。
    查不到返回 None。"""
    status, text = _post(EP_ENTITLE, ug_headers(acc['accessToken'], acc.get('deviceId')),
                         '{"require_usage": true}', 15)
    try:
        d = json.loads(text)
    except Exception:
        return None
    root = d.get('data') or d
    us = root.get('usage_summary') or {}
    try:
        total_amount, consumed = float(us.get('total_amount') or 0), float(us.get('consumed_amount') or 0)
        if total_amount > 0:
            return total_amount - consumed
    except Exception:
        pass
    try:
        packs = root.get('user_entitlement_pack_list') or []
        total, found = 0, False
        for p in packs:
            limit = ((p.get('entitlement_base_info') or {}).get('quota') or {}).get('credits_limit') or 0
            used = (p.get('usage') or {}).get('credits_amount') or 0
            if limit > 0:
                found = True
                total += max(limit - used, 0)
        return total if found else None
    except Exception:
        return None


# ══════════════════ 推送 ══════════════════
def notify_key():
    return QYWX_TOKEN.split('key=')[-1].strip()


def notify(text, title=''):
    """企业微信群机器人，纯文本；返回是否发送。"""
    key = notify_key()
    if not key:
        return False
    try:
        body = ('%s\n%s' % (title, text)) if title else text
        raw = body.encode('utf-8')
        if len(raw) > 2000:
            body = raw[:2000].decode('utf-8', 'ignore')
        req = urllib.request.Request(QYWX_URL + key,
                                    data=json.dumps({'msgtype': 'text',
                                                     'text': {'content': body}}).encode('utf-8'),
                                    headers={'Content-Type': 'application/json'})
        res = json.loads(urllib.request.urlopen(req, timeout=10).read().decode('utf-8'))
        ok = res.get('errcode') == 0
        print('%s [企业微信] 推送%s errcode=%s' % ('✅' if ok else '❌', '成功' if ok else '失败', res.get('errcode')))
        return ok
    except Exception as e:
        print('❌ [企业微信] 推送异常: %s' % e)
        return False


def notify_pushplus(title, content):
    if not PLUSPLUS_TOKEN:
        return
    try:
        req = urllib.request.Request(PUSHPLUS_URL,
                                    data=json.dumps({'token': PLUSPLUS_TOKEN, 'title': title,
                                                     'content': content, 'template': 'txt'}).encode('utf-8'),
                                    headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=10)
        print('✅ [PushPlus] 推送成功')
    except Exception as e:
        print('❌ [PushPlus] 推送失败: %s' % e)


def push(title, text):
    notify(text, title)
    notify_pushplus(title, text)


# ══════════════════ 单个账号处理 ══════════════════
def checkin_account(acc, cache):
    name = acc.get('_name') or acc.get('name') or acc.get('uid') or '(未知)'
    result = {'name': name, 'uid': acc.get('uid', '-'), 'icon': '✅',
              'status': '失败', 'credits': '-', 'detail': '', '_claimed': False}

    if not acc.get('accessToken'):
        ok, msg = ensure_token(acc, cache) if acc.get('refreshToken') else (False, '解密后无 token')
        if not ok:
            result['status'] = 'token失效' if acc.get('refreshToken') else '无token'
            result['detail'] = msg
            return result

    acc['deviceId'] = device_id_for(acc, acc.get('deviceId', ''))
    print('📱 [设备号] %s: %s' % (name, acc['deviceId']))
    log_head('📡 %s 签到状态查询' % name)

    checked_in, credits, enable, code, raw = status_of(acc['accessToken'], acc['deviceId'])
    if code in AUTH_FAIL_CODES and acc.get('refreshToken'):
        print('🔑 [刷新] 检测到 code=%s 鉴权失败，尝试刷新 token ...' % code)
        ok, msg = ensure_token(acc, cache)
        if ok:
            print('✅ [刷新] token 已更新')
            checked_in, credits, enable, code, raw = status_of(acc['accessToken'], acc['deviceId'])
        else:
            print('❌ [刷新] 失败: %s' % msg)
    print('📊 [状态] 今日已签: %s   积分: %s   开放: %s' % (checked_in, credits, enable))

    if checked_in:
        pts = credits_summary(acc)
        result['icon'] = '☑️'
        result['status'] = '已签到'
        result['credits'] = pts if pts is not None else credits
        result['detail'] = ('今日已签，积分余额 %s' % _fmt(result['credits'])) if pts is not None \
            else '今日已签，积分 %s' % credits
        print('☑️  [结果] 今日已签到')
        return result
    # 状态查询拿到鉴权失败（刷新后仍 1001）→ 硬失败，绝不浪费 claim 请求
    if code in AUTH_FAIL_CODES:
        result['icon'] = '🔑'
        result['status'] = '鉴权失败'
        result['detail'] = 'token 无效且自动续期失败，需重新登录取新 refreshToken'
        print('❌ [结果] 鉴权失败（硬失败）')
        return result
    # 状态查询本身不通（HTTP 异常 / 非 JSON）→ 先不发 claim，等下一轮
    if checked_in is None:
        result['icon'] = '⏳'
        result['status'] = '待重试'
        result['detail'] = '状态查询未成功，本轮不发起 claim：%s' % (raw or '')[:70]
        print('⏳ [结果] 状态不可用，跳过 claim')
        return result
    # 服务端明确 enable=false 且鉴权正常 → 该账号确实没开放签到，
    # 继续发 claim 只会白烧限流额度并拖累其它账号，直接判定未开放。
    if enable is False:
        result['icon'] = '🚫'
        result['status'] = '未开放'
        result['detail'] = '该账号未开放签到（enable=false），不再重复请求'
        print('🚫 [结果] 未开放签到')
        mark_done(_acct_key(acc), {'status': '未开放', 'credits': '-', 'at': bj()})
        return result

    result['_claimed'] = True          # 只有真正发过 claim 才需要账号间错峰
    ok, code, msg, gained = claim_with_retry(acc, cache)
    if code == RATE_CODE and os.getenv('TRAE_ROTATE', '1').strip() != '0':
        # 9074 不是限流，是这个设备号被服务端记住了 —— 换个新号立刻能签（实测）
        rotate_device_id(acc)
        ok, code, msg, gained = claim_with_retry(acc, cache)
    if code == RATE_CODE:
        set_cooldown(_acct_key(acc), cooldown_minutes())
    if ok:
        pts = credits_summary(acc)
        result['status'] = '签到成功'
        gain = ('，本次 +%s 积分' % _fmt(gained)) if gained else ''
        if pts is not None:
            result['credits'] = pts
            result['detail'] = '签到成功%s，当前余额 %s' % (gain, _fmt(pts))
        else:
            _, credits_after, _, _, _ = status_of(acc['accessToken'], acc['deviceId'])
            result['credits'] = credits_after if credits_after is not None else credits
            result['detail'] = '签到成功（code=0），积分 %s → %s' % (credits, _fmt(result['credits']))
        print('🎉 [结果] 签到成功')
    elif code == ALREADY_CODE:
        result['icon'] = '☑️'
        result['status'] = '已签到'
        result['credits'] = credits
        result['detail'] = '今日已签到(9095)'
        print('☑️  [结果] 今日已签到')
    elif code == RATE_CODE:
        result['icon'] = '⏳'
        result['status'] = '待重试'
        result['detail'] = '参与用户太多(9074)，本轮未签成，下轮 cron 自动补签'
        print('⏳ [结果] %s' % result['detail'])
    else:
        result['icon'] = '❌'
        result['status'] = '失败'
        result['detail'] = 'code=%s: %s' % (code, msg)
        print('❌ [结果] 签到失败: %s' % msg)
    return result


def _fmt(v):
    try:
        return '{:,.2f}'.format(float(v))
    except Exception:
        return str(v)


# ══════════════════ 主流程 ══════════════════
SOFT = ('待重试',)               # 限流类，冷却到点由 cron 补签，不算失败
DEAD = ('未开放', '鉴权失败')      # 需要人工处理
COOLDOWN_MIN = 55                # 平时 9074 冷却分钟数（实测 8 小时后仍未解除，一小时一试）
PEAK_COOLDOWN_MIN = 12           # 早窗内的短冷却，好让下一轮还在窗口里补签
GAP_MIN, GAP_MAX = 12, 25        # 实测 25s 间隔可让相邻账号连续签到成功


def main():
    accounts = load_accounts()
    cache = load_cache()
    log_title(len(accounts))

    results, pending = [], []
    state = load_state()
    for acc in accounts:
        key = _acct_key(acc)
        rec = (state.get('done') or {}).get(key)
        if rec:
            results.append({'name': acc.get('_name') or acc.get('name') or key,
                            'uid': acc.get('uid', '-'), 'icon': '☑️', 'status': '已签到',
                            'credits': rec.get('credits', '-'),
                            'detail': '今日已完成（%s），跳过请求' % rec.get('at', '-')})
            print('☑️  [%s] 今日已签到，跳过' % (acc.get('_name') or acc.get('name') or key))
        else:
            left = cooldown_left(key)
            if left > 0:
                print('⏳ [冷却] %s 9074 冷却中，还剩 %d 分钟，本轮跳过'
                      % (acc.get('_name') or acc.get('name') or key, (left + 59) // 60))
            else:
                pending.append(acc)
    if not pending:
        if any(cooldown_left(_acct_key(a)) > 0 for a in accounts):
            print('⏳ 全部待签账号都在冷却中，等冷却到点由 cron 补签')
        else:
            print('✅ 全部账号今日均已完成，无需请求接口')

    batch = pick_batch(pending)
    if len(batch) < len(pending):
        names = '、'.join(a.get('_name') or a.get('name') or _acct_key(a) for a in batch)
        print('🎚  [轮签] 本轮只签 %s（其余交给后续 cron，避开整点排队限流）' % names)
    if batch and os.getenv('TRAE_JITTER', '1').strip() != '0':
        wait = random.randint(0, 20)
        print('🎲 [错峰] 随机等待 %d 秒再请求…' % wait)
        time.sleep(wait)

    prev_claimed = False
    for idx, acc in enumerate(batch):
        # 只有上一次真的发过 claim 才需要错峰；纯只读的 status 查询不必等待，
        # 否则"全部已签到"的巡检也要白等一分多钟。
        if idx > 0 and prev_claimed:
            gap = random.randint(GAP_MIN, GAP_MAX)
            print('\n⏳ [间隔] 等待 %d 秒后处理下一个账号...' % gap)
            time.sleep(gap)
        try:
            r = checkin_account(acc, cache)
            if r['status'] == '待重试':
                # 实测 9074 是按账号/时间片的容量门，与出口 IP 无关，
                # 所以不再"连坐"：失败的记冷却，后面的账号继续签。
                # 想恢复旧行为（一个被限就全体收工）设 TRAE_CIRCUIT=1。
                results.append(r)
                if os.getenv('TRAE_CIRCUIT', '0').strip() == '1':
                    rest = len(batch) - idx - 1
                    if rest > 0:
                        print('⏭  [熔断] 命中限流，跳过剩余 %d 个账号，等下一轮 cron' % rest)
                    break
                prev_claimed = True     # 刚发过 claim，下一个账号照常错峰
                continue
            if r['status'] in ('签到成功', '已签到'):
                mark_done(_acct_key(acc), {'status': r['status'], 'credits': r.get('credits'),
                                           'at': bj()})
            prev_claimed = bool(r.get('_claimed'))
            results.append(r)
        except Exception as e:
            prev_claimed = False
            results.append({'name': acc.get('_name', '?'), 'uid': acc.get('uid', '-'),
                            'icon': '❌', 'status': '异常', 'credits': '-', 'detail': str(e)})

    ok_n = sum(1 for r in results if r['status'] == '签到成功')
    already_n = sum(1 for r in results if r['status'] == '已签到')
    soft_n = sum(1 for r in results if r['status'] in SOFT)
    dead_n = sum(1 for r in results if r['status'] in DEAD)
    fail_n = len(results) - ok_n - already_n - soft_n - dead_n

    log_box(['✅ 成功 %d  ☑️ 已签 %d  ⏳ 待重试 %d  ❌ 失败 %d' % (ok_n, already_n, soft_n, fail_n + dead_n),
             '🕒 结束时间: %s' % bj()], '🏁 Trae SOLO 签到完成')

    out = ['🕒 时间：%s' % bj(),
           '✅ 成功 %d  ☑️ 已签 %d  ⏳ 待重试 %d  ❌ 失败 %d' % (ok_n, already_n, soft_n, fail_n + dead_n)]
    for r in results:
        out.append('%s %s(%s): %s | %s' % (r['icon'], r['name'], r['uid'], r['status'], r['detail']))
    push('🤖 Trae SOLO 多账号签到', '\n'.join(out))


if __name__ == '__main__':
    main()
