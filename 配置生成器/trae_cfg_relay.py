# -*- coding: utf-8 -*-
"""
配置生成器本地中继。

作用：浏览器里的 trae_config_builder.html 本身读不了本地文件、也跑不了 Python，
      本脚本在 127.0.0.1 上起一个小服务，代它执行 trae_get_token.py 并把结果回传，
      页面就能"一键自动获取" refreshToken / accessToken / 设备密钥。

流程（与「推送配置/启动.vbs」同一套模式）：
  1. 启动时挑一个空闲端口，只绑定 127.0.0.1
  2. 返回页面时在 </body> 前注入一小段 JS（磁盘上的 HTML 不做任何修改）
  3. 注入的 JS 自动请求 /_api/extract，把结果塞进「一键解析」框并触发解析
  4. 每个标签页持有独立租约；关闭一页只释放自己的租约，全部关闭或租约过期后退出
  5. 同一目录只允许一个中继进程；重复双击会复用已运行页面

安全：/_api/extract 校验 Host / Origin / Referer 并要求一次性随机令牌；
      /_bye、/_ping、/_alive 同样校验 Host 与页面来源，防跨站停止或保活。
      页面响应禁止 iframe 嵌入；页面路由同样校验 Host（页面内嵌令牌）。
只依赖 Python 标准库。日志写入同目录 配置生成器.log。
"""
import hashlib
import http.client
import http.server
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
PAGE = os.path.join(HERE, 'trae_config_builder.html')
def _find_token_script():
    """实时解析提取脚本位置：本目录优先，其次上一级；找不到返回 None。"""
    for cand in (os.path.join(HERE, 'trae_get_token.py'),
                 os.path.join(PARENT, 'trae_get_token.py')):
        if os.path.isfile(cand):
            return cand
    return None


TOKEN_SCRIPT = _find_token_script() or os.path.join(PARENT, 'trae_get_token.py')
LOG_FILE = os.path.join(HERE, '配置生成器.log')

HOST = '127.0.0.1'
PORT_CANDIDATES = range(18765, 18786)
BYE_EXIT_SEC = 2          # 收到 pagehide 后等多久退出
LEASE_TTL_SEC = 180       # 单标签页租约；兼容后台标签页的计时器节流
IDLE_EXIT_SEC = 180       # 启动后等待首次页面连接的上限
EXTRACT_TIMEOUT = 120     # 单次提取脚本超时
RELAY_TOKEN = secrets.token_urlsafe(32)   # 提取接口一次性令牌，通过校验后轮换
MISSING_SCRIPT_MSG = (
    '一键提取不可用：没有找到 trae_get_token.py（已尝试本目录和上一级目录）。\n\n'
    '恢复方式（任选其一）：\n'
    '1. 把 trae_get_token.py 放回本目录或上一级目录，再点「读取本机凭据」即可恢复，无需重启；\n'
    '2. 运行 python trae_get_token.py --accounts 与 --export-keys，把输出粘贴到下方文本框；\n'
    '3. 双击 无python独立提取凭据.bat 导出凭据文件，再用「读取凭据文件」导入。'
)

_started_at = time.monotonic()
_exiting = False
_lock = threading.Lock()
_leases = {}
_lease_generation = 0
_INSTANCE_MUTEX_HANDLE = None


def candidate_ports():
    """返回监听端口；测试可指定单端口，生产沿用固定候选区间。"""
    raw = os.environ.get('TRAE_CFG_TEST_PORT', '').strip()
    if not raw:
        return list(PORT_CANDIDATES)
    try:
        port = int(raw)
    except ValueError as e:
        raise ValueError('TRAE_CFG_TEST_PORT 不是整数') from e
    if not 1 <= port <= 65535:
        raise ValueError('TRAE_CFG_TEST_PORT 超出 1..65535')
    return [port]


def instance_id(suffix=None):
    """同一目录固定实例 ID；测试后缀仅用于隔离并行回归。"""
    path_key = hashlib.sha256(
        os.path.normcase(os.path.realpath(HERE)).encode('utf-8')
    ).hexdigest()[:16]
    if suffix is None:
        suffix = os.environ.get('TRAE_CFG_TEST_MUTEX', '')
    suffix = ''.join(ch for ch in suffix
                     if ch.isascii() and (ch.isalnum() or ch in '-_'))[:40]
    tail = ('-' + suffix) if suffix else ''
    return path_key + tail


def instance_mutex_name():
    """同一目录使用固定命名互斥体。"""
    return r'Local\TraeConfigRelay-%s' % instance_id()


def acquire_instance_mutex():
    """获取 Windows 命名互斥体；False 表示已有实例。"""
    global _INSTANCE_MUTEX_HANDLE
    if _INSTANCE_MUTEX_HANDLE:
        return True
    if os.name != 'nt':
        return None

    import ctypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool

    handle = kernel32.CreateMutexW(None, False, instance_mutex_name())
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _INSTANCE_MUTEX_HANDLE = handle
    return True


def find_running_relay(ports, wait_sec=5.0):
    """探测同目录已运行实例，返回可打开的本机 URL。"""
    expected = ('traecfg:' + instance_id()).encode('ascii')
    deadline = time.monotonic() + wait_sec
    while True:
        for port in ports:
            base = 'http://%s:%d' % (HOST, port)
            conn = http.client.HTTPConnection(HOST, port, timeout=0.25)
            try:
                conn.request('GET', '/_alive', headers={
                    'Origin': base,
                    'Referer': base + '/',
                    'Connection': 'close',
                })
                response = conn.getresponse()
                body = response.read(128).decode('ascii', 'ignore').strip()
                if response.status == 200 and body.encode('ascii', 'ignore') == expected:
                    return base + '/'
            except (OSError, http.client.HTTPException):
                pass
            finally:
                conn.close()
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.15)


def log(msg):
    line = '%s %s' % (time.strftime('%H:%M:%S'), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def valid_lease_id(value):
    """标签页租约 ID 只允许 URL-safe 字符，避免异常值写入状态或页面脚本。"""
    value = str(value or '').strip()
    return 16 <= len(value) <= 80 and all(
        ch.isascii() and (ch.isalnum() or ch in '-_') for ch in value
    )


def register_lease(lease_id=None):
    """注册或续租一个标签页，返回租约 ID。"""
    global _lease_generation
    lease_id = lease_id or secrets.token_urlsafe(18)
    if not valid_lease_id(lease_id):
        raise ValueError('租约 ID 不合法')
    with _lock:
        if lease_id not in _leases:
            _lease_generation += 1
        _leases[lease_id] = time.monotonic()
    return lease_id


def release_lease(lease_id):
    """释放一个标签页；返回 (是否找到, 是否仍有其它标签页)。"""
    with _lock:
        existed = _leases.pop(lease_id, None) is not None
        remaining = bool(_leases)
    return existed, remaining


def expire_stale_leases(now=None):
    """清理过期租约；全部过期时调度退出，返回已过期的租约 ID。"""
    now = time.monotonic() if now is None else now
    with _lock:
        expired = [key for key, seen in _leases.items()
                   if now - seen > LEASE_TTL_SEC]
        for key in expired:
            _leases.pop(key, None)
        remaining = bool(_leases)
    if expired:
        log('清理 %d 个过期页面租约' % len(expired))
        if not remaining:
            schedule_exit(BYE_EXIT_SEC)
    return expired


def schedule_exit(delay):
    """延迟退出；期间出现新标签页租约就取消。"""
    global _exiting
    with _lock:
        expected_generation = _lease_generation

    def worker():
        global _exiting
        deadline = time.time() + delay
        while time.time() < deadline:
            time.sleep(0.2)
        with _lock:
            if _exiting:
                return
            if _leases or _lease_generation != expected_generation:
                return          # 新标签页已注册，不退出
            _exiting = True
        log('页面已关闭，中继退出')
        os._exit(0)

    threading.Thread(target=worker, daemon=True).start()


# ══════════════════ 调用 trae_get_token.py ══════════════════
def run_token_script(flag):
    """执行 trae_get_token.py 的某个模式，返回 (ok, stdout, stderr)。"""
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    try:
        p = subprocess.run(
            [sys.executable, TOKEN_SCRIPT, flag],
            cwd=HERE, env=env, capture_output=True,
            timeout=EXTRACT_TIMEOUT,
        )
        out = p.stdout.decode('utf-8', 'replace')
        err = p.stderr.decode('utf-8', 'replace')
        return p.returncode == 0, out, err
    except subprocess.TimeoutExpired:
        return False, '', '脚本执行超时（%d 秒）' % EXTRACT_TIMEOUT
    except Exception as e:
        return False, '', str(e)


def extract_all():
    """合并账号与设备密钥两段输出，供页面解析。"""
    global TOKEN_SCRIPT
    script = _find_token_script()
    if script is None:
        log('提取中止：未找到 trae_get_token.py（已尝试 %s 和 %s）' % (HERE, PARENT))
        return {'ok': False, 'reason': 'script_missing', 'message': MISSING_SCRIPT_MSG}
    TOKEN_SCRIPT = script   # 放回脚本后无需重启，自动切换到新位置
    ok_acc, acc_out, acc_err = run_token_script('--accounts')
    ok_key, key_out, key_err = run_token_script('--export-keys')

    acc_count = 0
    for line in acc_out.splitlines():
        s = line.strip()
        if s.startswith('[') and s.endswith(']'):
            try:
                acc_count = len(json.loads(s))
            except Exception:
                pass

    key_count = sum(1 for k in ('TRAE_DEVICE_ID=', 'TRAE_MACHINE_ID=',
                                'TRAE_DEVICE_KEY_PEM=', 'TRAE_DEVICE_PUB_PEM=')
                    if k in key_out)

    if acc_err.strip():
        log('账号提取 stderr: ' + acc_err.strip()[:300])
    if key_err.strip():
        log('设备密钥 stderr: ' + key_err.strip()[:300])

    if not ok_acc and not ok_key:
        msg = (acc_out.strip() or acc_err.strip() or '未找到本机 Trae 登录态')
        return {'ok': False,
                'message': msg.splitlines()[0][:200] if msg else '未找到凭据'}

    parts = []
    if ok_acc and acc_out.strip():
        parts.append('# ===== 账号（trae_get_token.py --accounts）=====\n' + acc_out.rstrip())
    if ok_key and key_out.strip():
        parts.append('# ===== 设备密钥（trae_get_token.py --export-keys）=====\n' + key_out.rstrip())

    summary = '%d 个账号 / %d 项设备字段' % (acc_count, key_count)
    log('提取完成：%s' % summary)
    return {'ok': True, 'text': '\n\n'.join(parts), 'summary': summary,
            'accounts': acc_count, 'deviceFields': key_count}


# ══════════════════ 页面注入 ══════════════════
INJECT = r'''
<script>
/* 由 trae_cfg_relay.py 在响应时注入，磁盘上的 html 未被修改。
   读取结果先进暂存区，由用户选择：替换表单 / 仅追加账号 / 取消。 */
(function () {
  var pending = null;          // 暂存本次提取结果
  var hideTimer = null;
  var relayToken = '__RELAY_TOKEN__';   // 服务端注入，成功提取后随响应轮换
  var relayClientId = __RELAY_CLIENT_ID__;  // 每个标签页独立，关闭时只释放自己的租约
  var relayScriptMissing = __RELAY_SCRIPT_MISSING__;   // 打开页面时检查一次：提取脚本是否存在
  var relayMissingMsg = __RELAY_MISSING_MSG__;   // 脚本缺失时的弹窗文案（服务端注入）

  function el(id) { return document.getElementById(id); }

  function bannerNode() {
    var b = el('relayBanner');
    if (!b) {
      b = document.createElement('div');
      b.id = 'relayBanner';
      b.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:999;padding:9px 16px;'
        + 'font:12.5px/1.6 -apple-system,"Microsoft YaHei",sans-serif;box-shadow:0 -1px 8px rgba(0,0,0,.08)';
      document.body.appendChild(b);
    }
    return b;
  }

  function showMsg(text, kind) {
    var b = bannerNode();
    b.innerHTML = '';
    b.style.display = 'block';
    b.style.background = kind === 'ok' ? '#eaf7ee' : (kind === 'warn' ? '#fff4e5' : '#eef3ff');
    b.style.color = kind === 'ok' ? '#1a7f37' : (kind === 'warn' ? '#8a6100' : '#2b6ef6');
    b.textContent = text;
    if (hideTimer) clearTimeout(hideTimer);
    if (kind !== 'info') {
      hideTimer = setTimeout(function () { b.style.display = 'none'; }, 6000);
    }
  }

  function mkBtn(text, primary, fn) {
    var btn = document.createElement('button');
    btn.textContent = text;
    btn.style.cssText = 'margin-left:8px;padding:5px 12px;border-radius:6px;font:12.5px/1.4 inherit;cursor:pointer;'
      + (primary
        ? 'background:#2b6ef6;border:1px solid #2b6ef6;color:#fff;'
        : 'background:#fff;border:1px solid #c9d3e4;color:#1f2329;');
    btn.onclick = fn;
    return btn;
  }

  function showChoice() {
    var b = bannerNode();
    b.innerHTML = '';
    b.style.display = 'block';
    b.style.background = '#eef3ff';
    b.style.color = '#1f2329';
    if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }

    var span = document.createElement('span');
    span.textContent = '已读取到 ' + pending.summary + '，请选择处理方式：';
    b.appendChild(span);
    b.appendChild(mkBtn('替换表单', true, function () { apply('replace'); }));
    b.appendChild(mkBtn('仅追加新账号', false, function () { apply('append'); }));
    b.appendChild(mkBtn('取消', false, function () {
      pending = null;
      showMsg('已取消，表单未做任何改动', 'info');
    }));
  }

  function apply(mode) {
    if (!pending) return;

    if (mode === 'replace') {
      // 账号与设备整体覆盖；推送渠道不动（避免误删手填的 key）
      state.accounts = [blankAccount()];
      ['devKey', 'devPub', 'devMid', 'devDid', 'devName', 'devModel', 'devBrand'].forEach(function (id) {
        var d = el(id); if (d) d.value = '';
      });
      renderAccounts();
      el('autoBox').value = pending.text;
      autoParse();
      showMsg('已替换表单：' + pending.summary, 'ok');
    } else {
      // 只把新账号并进去，设备与推送字段保持原样
      var list = pickJsonArray(pending.text) || [];
      var kept = state.accounts.filter(accountHasCredential);
      var seen = {};
      kept.forEach(function (a) { seen[accountCredentialKey(a)] = 1; });

      var added = 0;
      list.forEach(function (a) {
        if (!a || typeof a !== 'object' || !accountHasCredential(a)) return;
        var key = accountCredentialKey(a);
        if (!key || seen[key]) return;
        seen[key] = 1;
        kept.push(accountFromRaw(a));
        added++;
      });

      if (!added) {
        showMsg('没有新账号可追加（都已存在）', 'warn');
      } else {
        state.accounts = kept;
        renderAccounts();
        render();
        showMsg('已追加 ' + added + ' 个账号，设备与推送未改动', 'ok');
      }
    }
    pending = null;
  }

  async function pull() {
    var btn = el('relayPullBtn');
    if (btn && btn.disabled) return;      // 防止飞行中重复请求拿到旧令牌
    if (btn) btn.disabled = true;
    showMsg('正在读取本机 Trae 客户端凭据，请稍候…（只在本机流转）', 'info');
    try {
      var r = await fetch('/_api/extract', {
        cache: 'no-store',
        headers: { 'X-Relay-Token': relayToken }
      });
      var j = await r.json();
      if (j && j.nextToken) relayToken = j.nextToken;
      if (!j.ok) {
        if (j.reason === 'script_missing') {
          alert(j.message || relayMissingMsg);   // 脚本缺失：弹窗说明原因与恢复方式
        } else {
          showMsg('自动获取失败：' + (j.message || '未知原因')
            + ' —— 可手动运行 trae_get_token.py 后粘贴到上方输入框', 'warn');
        }
        return;
      }
      pending = j;
      showChoice();          // 只提示，不自动改表单
    } catch (e) {
      showMsg('自动获取失败：' + e.message, 'warn');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function addButton() {
    var box = el('autoBox');
    if (!box) return;
    var tb = box.parentNode.querySelector('.toolbar');
    if (!tb || el('relayPullBtn')) return;
    var btn = document.createElement('button');
    btn.id = 'relayPullBtn';
    btn.className = 'primary';
    btn.textContent = '读取本机凭据';
    btn.onclick = pull;
    tb.insertBefore(btn, tb.firstChild);
  }

  window.traeAutoExtract = pull;

  window.addEventListener('load', function () {
    addButton();
    if (relayScriptMissing) {
      alert(relayMissingMsg);   // 缺失时弹窗说明原因与恢复方式，不自动发提取请求
    } else {
      pull();             // 只读取并等待确认，不再自动覆盖
    }
  });
  // pagehide 派发目标是 window；双通道发送，服务端按标签页租约幂等处理。
  var byeSent = false;
  function bye() {
    if (byeSent) return;
    byeSent = true;
    var url = '/_bye?client=' + encodeURIComponent(relayClientId);
    try { navigator.sendBeacon(url); } catch (e) {}
    try { fetch(url, { method: 'POST', keepalive: true }).catch(function () {}); } catch (e) {}
  }
  function onPageHide(event) {
    if (event && event.persisted) return;  // 进入 BFCache 不等于关闭标签页
    bye();
  }
  window.addEventListener('pagehide', onPageHide);
  document.addEventListener('pagehide', onPageHide);
  window.addEventListener('pageshow', function () { byeSent = false; ping(); });
  function ping() {
    fetch('/_ping?client=' + encodeURIComponent(relayClientId),
      { cache: 'no-store' }).catch(function () {});
  }
  ping();
  setInterval(ping, 10000);
})();
</script>
'''


# ══════════════════ HTTP 服务 ══════════════════
class RelayHTTPServer(http.server.ThreadingHTTPServer):
    """Windows 上禁用地址复用，避免已有监听器被误判为可绑定。"""
    allow_reuse_address = False
    allow_reuse_port = False
    daemon_threads = True


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass

    def handle(self):
        # 浏览器关标签时会直接掐断 keep-alive 连接，属正常现象，不打印堆栈
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def _send(self, code, body, ctype='text/plain; charset=utf-8', extra=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), 'application/json; charset=utf-8')

    def _host_ok(self):
        """Host 必须是本机回环地址加当前端口，防 DNS rebinding。"""
        port = self.server.server_address[1]
        host = (self.headers.get('Host') or '').strip().lower()
        return host in ('127.0.0.1:%d' % port, 'localhost:%d' % port)

    def _query_value(self, name):
        query = urllib.parse.urlsplit(self.path).query
        values = urllib.parse.parse_qs(query, keep_blank_values=True)
        return (values.get(name) or [''])[0].strip()

    def _guard_source(self):
        """校验 Host 与浏览器来源；生命周期接口不允许匿名跨站请求。"""
        if not self._host_ok():
            return 'Host 不合法'
        port = self.server.server_address[1]
        loopback = ('http://127.0.0.1:%d' % port,
                    'http://localhost:%d' % port)
        origin = (self.headers.get('Origin') or '').strip()
        if origin and origin.lower() not in loopback:
            return 'Origin 不合法'
        referer = (self.headers.get('Referer') or '').strip().lower()
        if referer and not any(referer == base or referer.startswith(base + '/')
                               for base in loopback):
            return 'Referer 不合法'
        if not origin and not referer:
            return '缺少来源'
        return None

    def _guard_extract(self):
        """/_api/extract 校验来源并要求一次性令牌；返回拒绝原因。"""
        reason = self._guard_source()
        if reason:
            return reason
        token = (self.headers.get('X-Relay-Token') or '').strip()
        if not token or token != RELAY_TOKEN:
            return '令牌不匹配'
        return None

    def _guard_lifecycle(self, label):
        reason = self._guard_source()
        if not reason:
            return True
        log('拒绝%s（%s，来自 %s）' % (label, reason, self.client_address[0]))
        self._send(403, 'forbidden')
        return False

    def _handle_bye(self, lease_id):
        """释放当前标签页；只有最后一个标签页关闭时才调度退出。"""
        existed, remaining = release_lease(lease_id)
        if existed and not remaining:
            schedule_exit(BYE_EXIT_SEC)
        try:
            self._send(204, '')
        except Exception:
            pass

    def do_POST(self):
        """sendBeacon 发的是 POST：页面关闭信标 /_bye 从这里进。"""
        path = self.path.split('?', 1)[0]
        if path == '/_bye':
            if not self._guard_lifecycle('关闭请求'):
                return
            lease_id = self._query_value('client')
            if not valid_lease_id(lease_id):
                self._send(400, 'missing or invalid client lease')
                return
            self._handle_bye(lease_id)
            return
        self._send(404, 'not found')

    def do_GET(self):
        path = self.path.split('?', 1)[0]

        if path == '/_alive':
            if not self._guard_lifecycle('存活探测'):
                return
            self._send(200, 'traecfg:' + instance_id())
            return
        if path == '/_ping':
            if not self._guard_lifecycle('心跳'):
                return
            lease_id = self._query_value('client')
            if not valid_lease_id(lease_id):
                self._send(400, 'missing or invalid client lease')
                return
            register_lease(lease_id)
            self._send(204, '')
            return
        if path == '/_bye':
            if not self._guard_lifecycle('关闭请求'):
                return
            lease_id = self._query_value('client')
            if not valid_lease_id(lease_id):
                self._send(400, 'missing or invalid client lease')
                return
            self._handle_bye(lease_id)
            return
        if path == '/_api/extract':
            reason = self._guard_extract()
            if reason:
                log('拒绝提取请求（%s，来自 %s）' % (reason, self.client_address[0]))
                self._json(403, {'ok': False, 'message': '本地中继已拒绝该请求（%s）' % reason})
                return
            global RELAY_TOKEN
            RELAY_TOKEN = secrets.token_urlsafe(32)   # 一次性：用后即轮换
            log('页面请求自动提取')
            try:
                result = extract_all()
            except Exception as e:
                log('提取异常: %s' % e)
                result = {'ok': False, 'message': str(e)}
            result['nextToken'] = RELAY_TOKEN
            self._json(200, result)
            return

        if path in ('/', '/index.html', '/trae_config_builder.html'):
            if not self._host_ok():
                log('拒绝页面请求（Host 不合法，来自 %s）' % self.client_address[0])
                self._send(403, 'forbidden')
                return
            try:
                with open(PAGE, 'r', encoding='utf-8') as f:
                    html = f.read()
            except Exception as e:
                self._send(500, '读取页面失败：%s' % e)
                return
            lease_id = secrets.token_urlsafe(18)
            idx = html.lower().rfind('</body>')
            inject = (INJECT
                      .replace('__RELAY_TOKEN__', RELAY_TOKEN)
                      .replace('__RELAY_CLIENT_ID__', json.dumps(lease_id))
                      .replace('__RELAY_SCRIPT_MISSING__',
                               'true' if _find_token_script() is None else 'false')
                      .replace('__RELAY_MISSING_MSG__',
                               json.dumps(MISSING_SCRIPT_MSG, ensure_ascii=False)))
            html = (html[:idx] + inject + html[idx:]) if idx >= 0 else html + inject
            self._send(200, html, 'text/html; charset=utf-8', {
                'X-Frame-Options': 'DENY',
                'Content-Security-Policy': "frame-ancestors 'none'",
            })
            return

        self._send(404, 'not found')


def port_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((HOST, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def open_browser(url):
    try:
        subprocess.Popen(['cmd', '/c', 'start', '', url], cwd=HERE,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception as e:
        log('打开浏览器失败: %s（请手动访问 %s）' % (e, url))


def watchdog():
    while True:
        time.sleep(5)
        expire_stale_leases()
        with _lock:
            never_leased = _lease_generation == 0
        if never_leased and time.monotonic() - _started_at > IDLE_EXIT_SEC:
            log('超过 %d 秒没有页面连接，中继退出' % IDLE_EXIT_SEC)
            os._exit(0)


def main():
    if not os.path.isfile(PAGE):
        log('找不到 trae_config_builder.html: %s' % PAGE)
        return 1
    try:
        ports = candidate_ports()
    except ValueError as e:
        log('端口配置错误：%s' % e)
        return 1

    try:
        singleton = acquire_instance_mutex()
    except OSError as e:
        log('创建单实例锁失败：%s' % e)
        return 1
    if singleton is False:
        url = find_running_relay(ports)
        if url:
            log('已有中继实例，复用：%s' % url)
            if os.environ.get('TRAE_CFG_NO_BROWSER') != '1':
                open_browser(url)
            return 0
        log('检测到已有实例锁，但未找到可复用的中继页面')
        return 1

    if _find_token_script() is None:
        log('警告：未找到 trae_get_token.py（已尝试 %s 和 %s），'
            '一键提取不可用，页面其余功能不受影响' % (HERE, PARENT))

    for port in ports:
        try:
            # 直接原子绑定，避免 port_free() 与真正监听之间的 TOCTOU 假空闲。
            httpd = RelayHTTPServer((HOST, port), Handler)
        except OSError:
            continue
        url = 'http://%s:%d/' % (HOST, port)
        log('页面：%s' % PAGE)
        log('中继已启动：%s' % url)
        threading.Thread(target=watchdog, daemon=True).start()
        if os.environ.get('TRAE_CFG_NO_BROWSER') != '1':
            open_browser(url)
        try:
            httpd.serve_forever(poll_interval=0.3)
        except KeyboardInterrupt:
            pass
        return 0

    log('没有可用端口（%d-%d 都被占用）' % (ports[0], ports[-1]))
    return 1


if __name__ == '__main__':
    sys.exit(main())
