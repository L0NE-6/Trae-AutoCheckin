import http.client
import importlib.util
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "配置生成器" / "trae_config_builder.html"
RELAY_PATH = ROOT / "配置生成器" / "trae_cfg_relay.py"
VBS_PATH = ROOT / "配置生成器" / "启动.vbs"
JS_HARNESS = ROOT / "tests" / "config_builder_harness.js"
CHROME_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    sync_playwright = None
    PLAYWRIGHT_AVAILABLE = False

CHROME_PATH = next((path for path in CHROME_CANDIDATES if path.is_file()), None)
CHROME_AVAILABLE = PLAYWRIGHT_AVAILABLE and CHROME_PATH is not None


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKIN = load_module("cfg_test_trae_checkin", ROOT / "trae_checkin.py")
MONITOR = load_module("cfg_test_trae_monitor", ROOT / "trae_credit_monitor.py")
RELAY = load_module("cfg_test_trae_relay", RELAY_PATH)


class TraeConfigAdapterTests(unittest.TestCase):
    def test_adapter_preserves_supported_fields_and_access_token_only_accounts(self):
        secret = "SECRET_PREFIX_987654"
        account_at_only = {
            "accessToken": "AT_" + secret,
            "deviceId": "account-device",
            "realDeviceId": "account-real-device",
            "deviceKeyPem": "ACCOUNT_KEY",
            "devicePubPem": "ACCOUNT_PUB",
            "machineId": "account-machine",
            "icubeAuth": "ICUBE_" + secret,
            "storagePath": r"C:\Trae\storage.json",
            "uid": "uid-at",
        }
        account_storage_only = {
            "storagePath": r"D:\Trae\storage.json",
            "name": "storage-only",
        }
        cfg = {
            "clientId": "NEW_" + secret,
            "accounts": [account_at_only, account_storage_only],
            "device": {
                "keyPem": "GLOBAL_KEY",
                "pubPem": "GLOBAL_PUB",
                "machineId": "GLOBAL_MACHINE",
                "deviceId": "GLOBAL_DEVICE",
                "name": "DEVICE_NAME",
                "model": "DEVICE_MODEL",
                "brand": "DEVICE_BRAND",
            },
        }
        for module in (CHECKIN, MONITOR):
            with self.subTest(module=module.__name__):
                stdout = io.StringIO()
                stderr = io.StringIO()
                values = {
                    "TRAE_CONFIG": json.dumps(cfg, ensure_ascii=False),
                    "TRAE_CLIENT_ID": "OLD_" + secret,
                    "TRAE_ACCOUNTS": json.dumps([{"refreshToken": "OLD_" + secret}]),
                }
                with patch.dict(os.environ, values, clear=False), \
                        redirect_stdout(stdout), redirect_stderr(stderr):
                    module._apply_trae_config()
                    translated = json.loads(os.environ["TRAE_ACCOUNTS"])
                    self.assertEqual([account_at_only, account_storage_only], translated)
                    self.assertEqual("DEVICE_NAME", os.environ["TRAE_DEVICE_NAME"])
                    self.assertEqual("DEVICE_MODEL", os.environ["TRAE_DEVICE_MODEL"])
                    self.assertEqual("DEVICE_BRAND", os.environ["TRAE_DEVICE_BRAND"])
                logs = stdout.getvalue() + stderr.getvalue()
                self.assertNotIn(secret, logs)
                self.assertIn("TRAE_CLIENT_ID", logs)
                self.assertIn("TRAE_ACCOUNTS", logs)

    @unittest.skipUnless(os.name == "nt", "Windows GBK console regression")
    def test_adapter_logs_do_not_crash_in_gbk_console(self):
        secret = "SECRET_PREFIX_987654"
        cfg = {
            "clientId": "NEW_中文_" + secret + "🚀",
            "accounts": [{"accessToken": "AT_" + secret}],
        }
        probe = (
            "import runpy; "
            "runpy.run_path(%s, run_name='trae_gbk_probe')"
        )
        for filename in ("trae_checkin.py", "trae_credit_monitor.py"):
            with self.subTest(filename=filename):
                env = os.environ.copy()
                env.update({
                    "PYTHONIOENCODING": "gbk",
                    "TRAE_CONFIG": json.dumps(cfg, ensure_ascii=False),
                    "TRAE_CLIENT_ID": "OLD_中文_" + secret + "🚀",
                })
                completed = subprocess.run(
                    [sys.executable, "-c", probe % json.dumps(str(ROOT / filename))],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    timeout=20,
                )
                output = (completed.stdout + completed.stderr).decode("gbk", "replace")
                self.assertEqual(0, completed.returncode, output)
                self.assertNotIn(secret, output)
                self.assertNotIn("UnicodeEncodeError", output)

    def test_checkin_accepts_adapter_access_token_only_account(self):
        cfg = {
            "accounts": [{
                "accessToken": "AT_ONLY",
                "realDeviceId": "REAL_DEVICE",
                "deviceKeyPem": "ACCOUNT_KEY",
                "devicePubPem": "ACCOUNT_PUB",
                "machineId": "ACCOUNT_MACHINE",
                "uid": "adapter-uid",
            }],
        }
        values = {
            "TRAE_CONFIG": json.dumps(cfg),
            "TRAE_ACCOUNTS": "",
            "TRAE_ONLY": "",
        }
        with patch.dict(os.environ, values, clear=False), \
                patch.object(CHECKIN, "apply_cache", side_effect=lambda accounts: accounts), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            CHECKIN._apply_trae_config()
            accounts = CHECKIN.load_accounts()
        self.assertEqual(1, len(accounts))
        self.assertEqual("AT_ONLY", accounts[0]["accessToken"])
        self.assertEqual("REAL_DEVICE", accounts[0]["_realDid"])
        self.assertEqual("ACCOUNT_KEY", accounts[0]["deviceKeyPem"])
        self.assertEqual("ACCOUNT_PUB", accounts[0]["devicePubPem"])
        self.assertEqual("ACCOUNT_MACHINE", accounts[0]["machineId"])

    def test_checkin_accepts_adapter_refresh_token_only_account(self):
        fake_refresh = "FAKE_REFRESH_TOKEN_FOR_REGRESSION_ONLY"
        cfg = {
            "accounts": [{
                "refreshToken": fake_refresh,
                "deviceId": "FAKE_DEVICE_ID",
                "realDeviceId": "FAKE_REAL_DEVICE_ID",
                "deviceKeyPem": "FAKE_PRIVATE_KEY",
                "devicePubPem": "FAKE_PUBLIC_KEY",
                "machineId": "FAKE_MACHINE_ID",
                "uid": "fake-refresh-only",
            }],
        }
        values = {
            "TRAE_CONFIG": json.dumps(cfg),
            "TRAE_ACCOUNTS": "",
            "TRAE_ONLY": "",
        }
        with patch.dict(os.environ, values, clear=False), \
                patch.object(CHECKIN, "apply_cache", side_effect=lambda accounts: accounts), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            CHECKIN._apply_trae_config()
            accounts = CHECKIN.load_accounts()
        self.assertEqual(1, len(accounts))
        self.assertEqual("", accounts[0]["accessToken"])
        self.assertEqual(fake_refresh, accounts[0]["refreshToken"])
        self.assertEqual("FAKE_REAL_DEVICE_ID", accounts[0]["_realDid"])

    def test_refresh_token_only_uses_existing_ensure_token_path(self):
        account = CHECKIN.build_account(
            {"refreshToken": "FAKE_REFRESH_TOKEN_FOR_REGRESSION_ONLY"},
            "fake-refresh-only",
        )
        with patch.object(
                CHECKIN,
                "ensure_token",
                return_value=(False, "fake refresh stopped before network"),
        ) as ensure_token, redirect_stdout(io.StringIO()):
            result = CHECKIN.checkin_account(account, {})
        ensure_token.assert_called_once_with(account, {})
        self.assertEqual("token失效", result["status"])
        self.assertIn("fake refresh stopped before network", result["detail"])

    def test_refresh_token_only_signs_with_real_device_id(self):
        account = CHECKIN.build_account({
            "refreshToken": "FAKE_REFRESH_TOKEN_FOR_REGRESSION_ONLY",
            "deviceId": "1111111111111111",
            "realDeviceId": "2222222222222222",
            "deviceKeyPem": "FAKE_PRIVATE_KEY",
            "devicePubPem": "FAKE_PUBLIC_KEY",
            "machineId": "FAKE_MACHINE_ID",
        }, "fake-proof")
        keys = CHECKIN.device_keys_for(account)
        self.assertEqual("2222222222222222", keys["deviceId"])
        self.assertEqual(
            "2222222222222222",
            CHECKIN.device_id_for(account, account["deviceId"]),
        )

    def test_multiple_refresh_token_only_accounts_keep_default_labels(self):
        cfg = {
            "accounts": [
                {"refreshToken": "FAKE_REFRESH_ONE"},
                {"refreshToken": "FAKE_REFRESH_TWO"},
            ],
        }
        values = {
            "TRAE_CONFIG": json.dumps(cfg),
            "TRAE_ACCOUNTS": "",
            "TRAE_ONLY": "",
        }
        with patch.dict(os.environ, values, clear=False), \
                patch.object(CHECKIN, "apply_cache", side_effect=lambda accounts: accounts), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            CHECKIN._apply_trae_config()
            accounts = CHECKIN.load_accounts()
        self.assertEqual(2, len(accounts))
        self.assertEqual(["账号1", "账号2"], [item["_name"] for item in accounts])
        self.assertEqual(
            ["FAKE_REFRESH_ONE", "FAKE_REFRESH_TWO"],
            [item["refreshToken"] for item in accounts],
        )

    def test_icube_account_keeps_explicit_real_device_id(self):
        decrypted = {
            "accessToken": "FAKE_ACCESS_TOKEN",
            "refreshToken": "FAKE_REFRESH_TOKEN",
            "deviceId": "1111111111111111",
        }
        with patch.object(
                CHECKIN,
                "decrypt_storage_value",
                return_value=json.dumps(decrypted),
        ):
            account = CHECKIN.build_account({
                "icubeAuth": "FAKE_ICUBE_AUTH",
                "realDeviceId": "2222222222222222",
            }, "fake-icube")
        self.assertEqual("FAKE_ACCESS_TOKEN", account["accessToken"])
        self.assertEqual("2222222222222222", account["_realDid"])

    def test_monitor_prefers_real_device_id_for_multiple_accounts(self):
        raw = [
            {
                "name": "A",
                "refreshToken": "FAKE_REFRESH_A",
                "accessToken": "FAKE_ACCESS_A",
                "deviceId": "DEVICE_A",
                "realDeviceId": "REAL_A",
                "deviceKeyPem": "PRIVATE_A",
                "devicePubPem": "PUBLIC_A",
                "machineId": "MACHINE_A",
            },
            {
                "name": "B",
                "refreshToken": "FAKE_REFRESH_B",
                "deviceId": "DEVICE_B",
                "deviceKeyPem": "PRIVATE_B",
                "devicePubPem": "PUBLIC_B",
                "machineId": "MACHINE_B",
            },
        ]
        with patch.dict(
                os.environ,
                {"TRAE_ACCOUNTS": json.dumps(raw), "TRAE_ONLY": ""},
                clear=True,
        ):
            accounts = MONITOR.load_accounts()
        self.assertEqual(2, len(accounts))
        self.assertEqual("REAL_A", accounts[0][2])
        self.assertEqual("REAL_A", accounts[0][4]["deviceId"])
        self.assertEqual("FAKE_ACCESS_A", accounts[0][5])
        self.assertEqual("DEVICE_B", accounts[1][2])
        self.assertEqual("DEVICE_B", accounts[1][4]["deviceId"])

    def test_monitor_runtime_keeps_account_device_id_over_local_client(self):
        cache = {
            "1": {
                "accessToken": "FAKE_ACCESS_TOKEN",
                "refreshToken": "FAKE_REFRESH_TOKEN",
                "expiresAt": int(time.time()) + 3600,
            }
        }
        with patch.object(MONITOR, "real_device_id",
                          return_value="9999999999999999"):
            token, device_id, _, error = MONITOR.get_token(
                1,
                "FAKE_REFRESH_TOKEN",
                "2222222222222222",
                cache,
            )
        self.assertEqual("FAKE_ACCESS_TOKEN", token)
        self.assertEqual("2222222222222222", device_id)
        self.assertIsNone(error)


class ConfigBuilderJavaScriptTests(unittest.TestCase):
    def test_inline_javascript_has_valid_node_syntax(self):
        html = BUILDER.read_text(encoding="utf-8")
        match = re.search(r"<script>\s*(.*?)\s*</script>", html, re.S)
        self.assertIsNotNone(match)
        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / "trae_config_builder.inline.js"
            script_path.write_text(match.group(1), encoding="utf-8")
            completed = subprocess.run(
                ["node", "--check", str(script_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=20,
            )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_import_export_confirm_and_reset_behavior(self):
        completed = subprocess.run(
            ["node", str(JS_HARNESS), str(BUILDER)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_relay_injected_javascript_has_valid_node_syntax(self):
        inject = (RELAY.INJECT
                  .replace("__RELAY_TOKEN__", "test-token")
                  .replace("__RELAY_CLIENT_ID__", json.dumps("test-client-id-1234"))
                  .replace("__RELAY_SCRIPT_MISSING__", "false")
                  .replace("__RELAY_MISSING_MSG__", json.dumps("missing")))
        match = re.search(r"<script>\s*(.*?)\s*</script>", inject, re.S)
        self.assertIsNotNone(match)
        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / "trae_cfg_relay.inject.js"
            script_path.write_text(match.group(1), encoding="utf-8")
            completed = subprocess.run(
                ["node", "--check", str(script_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=20,
            )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_relay_replace_clears_all_device_description_fields(self):
        match = re.search(r"\['devKey'.*?\]\.forEach", RELAY.INJECT, re.S)
        self.assertIsNotNone(match)
        clear_fields = match.group(0)
        for field_id in (
                "devKey", "devPub", "devMid", "devDid",
                "devName", "devModel", "devBrand"):
            with self.subTest(field_id=field_id):
                self.assertIn("'%s'" % field_id, clear_fields)

    def test_relay_pagehide_sends_its_own_lease_id(self):
        self.assertIn("window.addEventListener('pagehide', onPageHide)", RELAY.INJECT)
        self.assertIn("document.addEventListener('pagehide', onPageHide)", RELAY.INJECT)
        self.assertIn("event && event.persisted", RELAY.INJECT)
        self.assertIn("window.addEventListener('pageshow'", RELAY.INJECT)
        self.assertIn("'/_bye?client=' + encodeURIComponent(relayClientId)", RELAY.INJECT)
        self.assertIn("'/_ping?client=' + encodeURIComponent(relayClientId)", RELAY.INJECT)


class RelayLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_patch = patch.object(RELAY, "LOG_FILE", os.path.join(self.tmp.name, "relay.log"))
        self.log_patch.start()
        self.exit_patch = patch.object(RELAY, "schedule_exit")
        self.schedule_exit = self.exit_patch.start()
        RELAY._leases.clear()
        RELAY._lease_generation = 0
        RELAY._exiting = False
        self.server = RELAY.RelayHTTPServer((RELAY.HOST, 0), RELAY.Handler)
        self.port = self.server.server_address[1]
        self.base = "http://%s:%d" % (RELAY.HOST, self.port)
        self.thread = __import__("threading").Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.exit_patch.stop()
        self.log_patch.stop()
        self.tmp.cleanup()

    def request(self, method, path, headers=None, body=None):
        status, _, response_body = self.request_with_headers(method, path, headers, body)
        return status, response_body

    def request_with_headers(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection(RELAY.HOST, self.port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def open_page(self):
        status, headers, body = self.request_with_headers("GET", "/")
        match = re.search(rb'var relayClientId = "([A-Za-z0-9_-]+)";', body)
        self.assertEqual(200, status)
        self.assertIsNotNone(match, body[:500])
        return headers, match.group(1).decode("ascii")

    def ping_lease(self, lease_id):
        return self.request(
            "GET",
            "/_ping?client=" + lease_id,
            {"Referer": self.base + "/"},
        )

    def source_headers(self, origin=None):
        return {
            "Origin": origin if origin is not None else self.base,
            "Referer": self.base + "/",
        }

    def test_ping_requires_same_origin_and_updates_activity(self):
        status, _ = self.request("GET", "/_ping")
        self.assertEqual(403, status)
        status, _ = self.request("GET", "/_ping", {
            "Host": "evil.example:%d" % self.port,
            **self.source_headers(),
        })
        self.assertEqual(403, status)
        status, _ = self.request("GET", "/_ping", {"Origin": "https://evil.example"})
        self.assertEqual(403, status)

        _, lease_id = self.open_page()
        status, _ = self.ping_lease(lease_id)
        self.assertEqual(204, status)

    def test_bye_requires_same_origin_and_schedules_exit(self):
        status, _ = self.request("POST", "/_bye", {"Origin": "https://evil.example"})
        self.assertEqual(403, status)
        self.schedule_exit.assert_not_called()

        _, lease_id = self.open_page()
        status, _ = self.ping_lease(lease_id)
        self.assertEqual(204, status)
        status, _ = self.request(
            "POST", "/_bye?client=" + lease_id, self.source_headers()
        )
        self.assertEqual(204, status)
        self.schedule_exit.assert_called_once_with(RELAY.BYE_EXIT_SEC)

    def test_lifecycle_requires_a_client_lease_id(self):
        status, _ = self.request("GET", "/_ping", {"Referer": self.base + "/"})
        self.assertEqual(400, status)
        status, _ = self.request("POST", "/_bye", self.source_headers())
        self.assertEqual(400, status)
        self.schedule_exit.assert_not_called()

    def test_page_has_anti_framing_headers_and_normal_local_html(self):
        headers, lease_id = self.open_page()
        self.assertEqual("DENY", headers.get("X-Frame-Options"))
        self.assertEqual(
            "frame-ancestors 'none'",
            headers.get("Content-Security-Policy"),
        )
        self.assertTrue(RELAY.valid_lease_id(lease_id))
        self.assertNotIn(lease_id, RELAY._leases)
        status, _ = self.ping_lease(lease_id)
        self.assertEqual(204, status)
        self.assertIn(lease_id, RELAY._leases)
        status, body = self.request("GET", "/")
        self.assertEqual(200, status)
        self.assertIn("Trae AutoCheckin".encode("utf-8"), body)
        self.assertIn(b"relayPullBtn", body)

    def test_two_tabs_only_exit_after_both_release_leases(self):
        _, first = self.open_page()
        _, second = self.open_page()
        self.assertNotEqual(first, second)
        self.assertEqual(204, self.ping_lease(first)[0])
        self.assertEqual(204, self.ping_lease(second)[0])

        status, _ = self.request(
            "POST", "/_bye?client=" + first, self.source_headers()
        )
        self.assertEqual(204, status)
        self.schedule_exit.assert_not_called()
        self.assertIn(second, RELAY._leases)

        status, _ = self.request(
            "POST", "/_bye?client=" + second, self.source_headers()
        )
        self.assertEqual(204, status)
        self.schedule_exit.assert_called_once_with(RELAY.BYE_EXIT_SEC)
        self.assertEqual({}, RELAY._leases)

    def test_duplicate_bye_for_one_tab_is_idempotent(self):
        _, lease_id = self.open_page()
        self.assertEqual(204, self.ping_lease(lease_id)[0])
        for _ in range(2):
            status, _ = self.request(
                "POST", "/_bye?client=" + lease_id, self.source_headers()
            )
            self.assertEqual(204, status)
        self.schedule_exit.assert_called_once_with(RELAY.BYE_EXIT_SEC)

    def test_expired_lease_keeps_relay_alive_while_another_tab_remains(self):
        now = time.monotonic()
        old_id = "expired-lease-" + uuid.uuid4().hex
        live_id = "live-lease-" + uuid.uuid4().hex
        RELAY._leases.update({
            old_id: now - RELAY.LEASE_TTL_SEC - 1,
            live_id: now,
        })
        expired = RELAY.expire_stale_leases(now)
        self.assertEqual([old_id], expired)
        self.assertEqual({live_id}, set(RELAY._leases))
        self.schedule_exit.assert_not_called()

    def test_all_expired_leases_schedule_exit(self):
        now = time.monotonic()
        old_ids = [
            "expired-lease-a-" + uuid.uuid4().hex,
            "expired-lease-b-" + uuid.uuid4().hex,
        ]
        RELAY._leases.update({
            old_ids[0]: now - RELAY.LEASE_TTL_SEC - 1,
            old_ids[1]: now - RELAY.LEASE_TTL_SEC - 1,
        })
        expired = RELAY.expire_stale_leases(now)
        self.assertEqual(set(old_ids), set(expired))
        self.assertEqual({}, RELAY._leases)
        self.schedule_exit.assert_called_once_with(RELAY.BYE_EXIT_SEC)

    def test_port_free_reports_existing_listener_occupied(self):
        self.assertFalse(RELAY.port_free(self.port))
        with self.assertRaises(OSError):
            RELAY.RelayHTTPServer((RELAY.HOST, self.port), RELAY.Handler)

    def test_port_free_rejects_existing_reuseaddr_listener(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((RELAY.HOST, 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            self.assertFalse(RELAY.port_free(port))
            with self.assertRaises(OSError):
                RELAY.RelayHTTPServer((RELAY.HOST, port), RELAY.Handler)
        finally:
            listener.close()

    def test_relay_server_disables_address_reuse(self):
        self.assertFalse(RELAY.RelayHTTPServer.allow_reuse_address)
        self.assertFalse(RELAY.RelayHTTPServer.allow_reuse_port)

    @unittest.skipUnless(CHROME_AVAILABLE, "Chrome + Playwright regression")
    def test_chrome_blocks_cross_origin_iframe_navigation(self):
        with patch.object(RELAY, "_find_token_script", return_value=None), \
                sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(CHROME_PATH),
                headless=True,
            )
            try:
                page = browser.new_page()
                page.set_content(
                    '<iframe id="relay" src="%s"></iframe>' % self.base
                )
                time.sleep(0.8)
                child_urls = [frame.url for frame in page.frames[1:]]
                self.assertTrue(child_urls)
                self.assertFalse(
                    any(url.startswith(self.base) for url in child_urls),
                    child_urls,
                )
                self.assertEqual({}, RELAY._leases)
            finally:
                browser.close()

    @unittest.skipUnless(CHROME_AVAILABLE, "Chrome + Playwright regression")
    def test_chrome_two_tabs_pagehide_keeps_relay_until_last_tab_closes(self):
        with patch.object(RELAY, "_find_token_script", return_value=None), \
                sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(CHROME_PATH),
                headless=True,
            )
            pages = []
            try:
                for _ in range(2):
                    page = browser.new_page()
                    page.on("dialog", lambda dialog: dialog.dismiss())
                    page.goto(
                        self.base + "/",
                        wait_until="domcontentloaded",
                        timeout=10_000,
                    )
                    pages.append(page)
                self.assertGreaterEqual(len(RELAY._leases), 2)

                pages[0].close(run_before_unload=True)
                time.sleep(1.0)
                self.schedule_exit.assert_not_called()

                pages[1].close(run_before_unload=True)
                deadline = time.monotonic() + 5
                while (
                    self.schedule_exit.call_count == 0
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.1)
                self.schedule_exit.assert_called_once_with(RELAY.BYE_EXIT_SEC)
                self.assertEqual({}, RELAY._leases)
            finally:
                for page in pages:
                    if not page.is_closed():
                        page.close(run_before_unload=True)
                browser.close()

    def test_alive_requires_same_origin(self):
        status, _ = self.request("GET", "/_alive")
        self.assertEqual(403, status)
        status, body = self.request("GET", "/_alive", self.source_headers())
        self.assertEqual(200, status)
        self.assertEqual(("traecfg:" + RELAY.instance_id()).encode("ascii"), body)

    def test_extract_requires_source_and_one_time_token(self):
        status, _ = self.request("GET", "/_api/extract", {"Referer": self.base + "/"})
        self.assertEqual(403, status)
        with patch.object(RELAY, "RELAY_TOKEN", "valid-token"):
            status, _ = self.request("GET", "/_api/extract", {
                "X-Relay-Token": "valid-token",
            })
        self.assertEqual(403, status)
        status, _ = self.request("GET", "/_api/extract", {
            **self.source_headers(),
            "X-Relay-Token": "wrong",
        })
        self.assertEqual(403, status)

        with patch.object(RELAY, "RELAY_TOKEN", "valid-token"), \
                patch.object(RELAY, "extract_all", return_value={"ok": True}):
            status, body = self.request("GET", "/_api/extract", {
                **self.source_headers(),
                "X-Relay-Token": "valid-token",
            })
        self.assertEqual(200, status)
        self.assertTrue(json.loads(body)["ok"])

    @staticmethod
    def free_port():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((RELAY.HOST, 0))
            return sock.getsockname()[1]
        finally:
            sock.close()

    def wait_alive(self, port, instance=None, timeout=15):
        deadline = time.monotonic() + timeout
        base = "http://%s:%d" % (RELAY.HOST, port)
        expected = ("traecfg:" + RELAY.instance_id(instance)).encode("ascii")
        while time.monotonic() < deadline:
            conn = http.client.HTTPConnection(RELAY.HOST, port, timeout=0.5)
            try:
                conn.request("GET", "/_alive", headers={
                    "Origin": base,
                    "Referer": base + "/",
                })
                response = conn.getresponse()
                body = response.read()
                if response.status == 200 and body == expected:
                    return True
            except OSError:
                pass
            finally:
                conn.close()
            time.sleep(0.15)
        return False

    def stop_external_relay(self, port):
        base = "http://%s:%d" % (RELAY.HOST, port)
        page_conn = http.client.HTTPConnection(RELAY.HOST, port, timeout=1)
        try:
            page_conn.request("GET", "/")
            page_response = page_conn.getresponse()
            page_body = page_response.read()
            match = re.search(
                rb'var relayClientId = "([A-Za-z0-9_-]+)";',
                page_body,
            )
            if page_response.status != 200 or not match:
                return None
            lease_id = match.group(1).decode("ascii")
            page_conn.request(
                "GET",
                "/_ping?client=" + lease_id,
                headers={"Referer": base + "/"},
            )
            ping_response = page_conn.getresponse()
            ping_response.read()
            if ping_response.status != 204:
                return None
        except OSError:
            return None
        finally:
            page_conn.close()

        conn = http.client.HTTPConnection(RELAY.HOST, port, timeout=1)
        try:
            conn.request("POST", "/_bye?client=" + lease_id, headers={
                "Origin": base,
                "Referer": base + "/",
            })
            response = conn.getresponse()
            response.read()
            return response.status
        except OSError:
            return None
        finally:
            conn.close()

    def wait_closed(self, port, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.settimeout(0.3)
                if sock.connect_ex((RELAY.HOST, port)) != 0:
                    return True
            finally:
                sock.close()
            time.sleep(0.15)
        return False

    @unittest.skipUnless(os.name == "nt", "Windows duplicate-start regression")
    def test_duplicate_start_reuses_existing_instance(self):
        port = self.free_port()
        instance = "dup-" + uuid.uuid4().hex
        env = os.environ.copy()
        env.update({
            "TRAE_CFG_NO_BROWSER": "1",
            "TRAE_CFG_TEST_PORT": str(port),
            "TRAE_CFG_TEST_MUTEX": instance,
            "PYTHONIOENCODING": "utf-8",
        })
        first = subprocess.Popen(
            [sys.executable, str(RELAY_PATH)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
        )
        self.addCleanup(lambda: first.terminate() if first.poll() is None else None)
        self.assertTrue(self.wait_alive(port, instance), "first relay instance did not start")
        self.assertIsNone(first.poll())

        second = subprocess.run(
            [sys.executable, str(RELAY_PATH)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        second_output = (second.stdout or "") + (second.stderr or "")
        self.assertEqual(0, second.returncode, second_output)
        self.assertIn("已有中继实例", second.stdout or "")
        self.assertIsNone(first.poll())

        self.assertEqual(204, self.stop_external_relay(port))
        try:
            first.wait(timeout=10)
        except subprocess.TimeoutExpired:
            first.terminate()
            first.wait(timeout=5)
            output = first.stdout.read() if first.stdout else ""
            if first.stdout:
                first.stdout.close()
            self.fail("relay did not exit after /_bye\n" + output)
        output = first.stdout.read() if first.stdout else ""
        if first.stdout:
            first.stdout.close()
        self.assertEqual(0, first.returncode, output)

    @unittest.skipUnless(os.name == "nt", "Windows launcher regression")
    def test_vbs_launcher_is_ascii_text_and_starts_relay(self):
        raw = VBS_PATH.read_bytes()
        self.assertFalse(raw.startswith((b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf")))
        text = raw.decode("ascii")
        self.assertIn("Option Explicit", text)

        port = self.free_port()
        instance = "vbs-" + uuid.uuid4().hex
        env = os.environ.copy()
        env.update({
            "TRAE_CFG_NO_BROWSER": "1",
            "TRAE_CFG_TEST_PORT": str(port),
            "TRAE_CFG_TEST_MUTEX": instance,
        })
        completed = subprocess.run(
            ["cscript.exe", "//nologo", "//B", str(VBS_PATH)],
            cwd=ROOT / "配置生成器",
            env=env,
            capture_output=True,
            timeout=20,
        )
        output = (completed.stdout + completed.stderr).decode("gbk", "replace")
        self.assertEqual(0, completed.returncode, output)
        self.addCleanup(self.stop_external_relay, port)
        self.assertTrue(self.wait_alive(port, instance), output)
        self.assertEqual(204, self.stop_external_relay(port))
        self.assertTrue(self.wait_closed(port), "VBS-launched relay did not exit")


if __name__ == "__main__":
    unittest.main()
