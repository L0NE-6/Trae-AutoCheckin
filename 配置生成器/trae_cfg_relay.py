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
  4. 页面关闭（pagehide → sendBeacon /_bye）后 2 秒退出；心跳断 180 秒兜底退出

只依赖 Python 标准库。日志写入同目录 配置生成器.log。
"""
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
PAGE = os.path.join(HERE, 'trae_config_builder.html')
TOKEN_SCRIPT = os.path.join(HERE, 'trae_get_token.py')
if not os.path.isfile(TOKEN_SCRIPT):
    TOKEN_SCRIPT = os.path.join(PARENT, 'trae_get_token.py')
LOG_FILE = os.path.join(HERE, '配置生成器.log')

HOST = '127.0.0.1'
PORT_CANDIDATES = range(18765, 18786)
BYE_EXIT_SEC = 2          # 收到 pagehide 后等多久退出
IDLE_EXIT_SEC = 180       # 无任何请求多久兜底退出
EXTRACT_TIMEOUT = 120     # 单次提取脚本超时

_last_seen = time.time()
_exiting = False
_lock = threading.Lock()


def log(msg):
    line = '%s %s' % (time.strftime('%H:%M:%S'), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def touch():
    global _last_seen
    _last_seen = time.time()


def schedule_exit(delay):
    """延迟退出；期间只要有新请求就取消。"""
    global _exiting

    def worker():
        deadline = time.time() + delay
        while time.time() < deadline:
            time.sleep(0.2)
        with _lock:
            if _exiting:
                return
            if time.time() - _last_seen < delay - 0.5:
                return          # 期间有活动，不退出
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

  function blankAccount() {
    return { id: uid(), name: '', uid: '', refreshToken: '', accessToken: '', deviceId: '' };
  }

  function apply(mode) {
    if (!pending) return;

    if (mode === 'replace') {
      // 账号与设备整体覆盖；推送渠道不动（避免误删手填的 key）
      state.accounts = [blankAccount()];
      ['devKey', 'devPub', 'devMid', 'devDid'].forEach(function (id) {
        var d = el(id); if (d) d.value = '';
      });
      renderAccounts();
      el('autoBox').value = pending.text;
      autoParse();
      showMsg('已替换表单：' + pending.summary, 'ok');
    } else {
      // 只把新账号并进去，设备与推送字段保持原样
      var list = pickJsonArray(pending.text) || [];
      var kept = state.accounts.filter(function (a) { return String(a.refreshToken || '').trim(); });
      var seen = {};
      kept.forEach(function (a) { seen[String(a.refreshToken).trim()] = 1; });

      var added = 0;
      list.forEach(function (a) {
        var rt = String((a && a.refreshToken) || '').trim();
        if (!rt || seen[rt]) return;
        seen[rt] = 1;
        kept.push({
          id: uid(),
          name: String(a.name || '').trim(),
          uid: String(a.uid || '').trim(),
          refreshToken: rt,
          accessToken: String(a.accessToken || '').trim(),
          deviceId: String(a.deviceId || a.realDeviceId || '').trim()
        });
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
    showMsg('正在读取本机 Trae 客户端凭据，请稍候…（只在本机流转）', 'info');
    try {
      var r = await fetch('/_api/extract', { cache: 'no-store' });
      var j = await r.json();
      if (!j.ok) {
        showMsg('自动获取失败：' + (j.message || '未知原因')
          + ' —— 可手动运行 trae_get_token.py 后粘贴到上方输入框', 'warn');
        return;
      }
      pending = j;
      showChoice();          // 只提示，不自动改表单
    } catch (e) {
      showMsg('自动获取失败：' + e.message, 'warn');
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
    pull();               // 只读取并等待确认，不再自动覆盖
  });
  document.addEventListener('pagehide', function () {
    try { navigator.sendBeacon('/_bye'); } catch (e) {}
  });
  setInterval(function () { fetch('/_ping', { cache: 'no-store' }).catch(function () {}); }, 30000);
})();
</script>
'''


# ══════════════════ HTTP 服务 ══════════════════
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

    def do_GET(self):
        touch()
        path = self.path.split('?', 1)[0]

        if path == '/_alive':
            self._send(200, 'traecfg')
            return
        if path == '/_ping':
            self._send(204, '')
            return
        if path == '/_bye':
            self._send(204, '')
            schedule_exit(BYE_EXIT_SEC)
            return
        if path == '/_api/extract':
            log('页面请求自动提取')
            try:
                self._json(200, extract_all())
            except Exception as e:
                log('提取异常: %s' % e)
                self._json(500, {'ok': False, 'message': str(e)})
            return

        if path in ('/', '/index.html', '/trae_config_builder.html'):
            try:
                with open(PAGE, 'r', encoding='utf-8') as f:
                    html = f.read()
            except Exception as e:
                self._send(500, '读取页面失败：%s' % e)
                return
            idx = html.lower().rfind('</body>')
            html = (html[:idx] + INJECT + html[idx:]) if idx >= 0 else html + INJECT
            self._send(200, html, 'text/html; charset=utf-8')
            return

        self._send(404, 'not found')


def port_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((HOST, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def already_running(port):
    try:
        with socket.create_connection((HOST, port), 0.5) as s:
            s.sendall(b'GET /_alive HTTP/1.0\r\nHost: %s\r\n\r\n' % HOST.encode())
            return b'traecfg' in s.recv(2048)
    except Exception:
        return False


def open_browser(url):
    try:
        subprocess.Popen(['cmd', '/c', 'start', '', url], cwd=HERE,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception as e:
        log('打开浏览器失败: %s（请手动访问 %s）' % (e, url))


def watchdog():
    while True:
        time.sleep(5)
        if time.time() - _last_seen > IDLE_EXIT_SEC:
            log('超过 %d 秒无请求，中继退出' % IDLE_EXIT_SEC)
            os._exit(0)


def main():
    if not os.path.isfile(PAGE):
        log('找不到 trae_config_builder.html: %s' % PAGE)
        return 1
    if not os.path.isfile(TOKEN_SCRIPT):
        log('找不到 trae_get_token.py: %s' % TOKEN_SCRIPT)
        return 1

    for port in PORT_CANDIDATES:
        if already_running(port):
            log('已有中继在 %d 端口运行，直接打开浏览器' % port)
            if os.environ.get('TRAE_CFG_NO_BROWSER') != '1':
                open_browser('http://%s:%d/' % (HOST, port))
            return 0
        if not port_free(port):
            continue

        httpd = http.server.ThreadingHTTPServer((HOST, port), Handler)
        httpd.daemon_threads = True
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

    log('没有可用端口（%d-%d 都被占用）' % (PORT_CANDIDATES[0], PORT_CANDIDATES[-1]))
    return 1


if __name__ == '__main__':
    sys.exit(main())
