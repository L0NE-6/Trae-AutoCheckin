import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKIN = load_module("trae_checkin", "trae_checkin.py")
MONITOR = load_module("trae_credit_monitor", "trae_credit_monitor.py")


class TraeAlreadyCheckedInTests(unittest.TestCase):
    def test_claim_with_retry_treats_9004_as_already(self):
        with patch.object(
            CHECKIN, "claim", return_value=(200, 9004, "device already", None)
        ) as claim:
            ok, code, msg, points = CHECKIN.claim_with_retry(
                {"accessToken": "token", "deviceId": "device", "refreshToken": "refresh"},
                {},
            )
        self.assertFalse(ok)
        self.assertEqual(9004, code)
        self.assertEqual("device already", msg)
        self.assertIsNone(points)
        self.assertEqual(1, claim.call_count)

    def test_claim_with_retry_treats_9095_as_already(self):
        with patch.object(
            CHECKIN, "claim", return_value=(200, 9095, "already checked in", None)
        ) as claim:
            ok, code, msg, points = CHECKIN.claim_with_retry(
                {"accessToken": "token", "deviceId": "device", "refreshToken": "refresh"},
                {},
            )
        self.assertFalse(ok)
        self.assertEqual(9095, code)
        self.assertIsNone(points)
        self.assertEqual(1, claim.call_count)

    def test_checkin_account_reports_9004_as_signed(self):
        account = {"accessToken": "token", "deviceId": "device", "name": "tester"}
        with patch.object(CHECKIN, "device_id_for", return_value="device"), \
                patch.object(CHECKIN, "status_of", return_value=(False, 0, True, 0, "{}")), \
                patch.object(CHECKIN, "claim_with_retry", return_value=(False, 9004, "already", None)), \
                patch.object(CHECKIN, "credits_summary", return_value=250):
            with redirect_stdout(io.StringIO()):
                result = CHECKIN.checkin_account(account, {})
        self.assertEqual("已签到", result["status"])
        self.assertEqual("☑️", result["icon"])
        self.assertIn("9004", result["detail"])

    def test_checkin_account_reports_9095_as_signed(self):
        account = {"accessToken": "token", "deviceId": "device", "name": "tester"}
        with patch.object(CHECKIN, "device_id_for", return_value="device"), \
                patch.object(CHECKIN, "status_of", return_value=(False, 0, True, 0, "{}")), \
                patch.object(CHECKIN, "claim_with_retry", return_value=(False, 9095, "already", None)), \
                patch.object(CHECKIN, "credits_summary", return_value=250):
            with redirect_stdout(io.StringIO()):
                result = CHECKIN.checkin_account(account, {})
        self.assertEqual("已签到", result["status"])
        self.assertEqual("☑️", result["icon"])
        self.assertIn("9095", result["detail"])


class TraeEntitlementPackTests(unittest.TestCase):
    def test_skips_exhausted_packs_and_reports_earliest_remaining(self):
        payload = {
            "data": {
                "user_entitlement_pack_list": [
                    {
                        "expire_time": "2026-11-02 00:00:00",
                        "entitlement_base_info": {"quota": {"credits_limit": 100}},
                        "usage": {"credits_amount": 40},
                    },
                    {
                        "expire_time": "2026-10-30 00:00:00",
                        "quota": {"credits_limit": 50},
                        "usage": {"credits_amount": 50},
                    },
                    {
                        "expire_time": "2026-11-01 00:00:00",
                        "quota": {"credits_limit": 200},
                        "usage": {"credits_amount": 10},
                    },
                ]
            }
        }
        packs = MONITOR.parse_entitlement_packs(payload)
        self.assertEqual(2, len(packs))
        self.assertEqual("2026-11-01 00:00:00", packs[0]["expire_time"])
        self.assertEqual(190.0, packs[0]["remaining"])
        self.assertEqual(60.0, packs[1]["remaining"])

    def test_accepts_root_level_pack_list(self):
        payload = {
            "user_entitlement_pack_list": [
                {
                    "expire_time": 1761955200000,
                    "quota": {"credits_limit": 10},
                    "usage": {"credits_amount": 3},
                }
            ]
        }
        packs = MONITOR.parse_entitlement_packs(payload)
        self.assertEqual(1, len(packs))
        self.assertEqual(7.0, packs[0]["remaining"])

    def test_falls_back_to_root_list_when_data_is_present(self):
        payload = {
            "data": {},
            "user_entitlement_pack_list": [
                {
                    "expire_time": "2026-11-01 00:00:00",
                    "quota": {"credits_limit": 20},
                    "usage": {"credits_amount": 5},
                }
            ],
        }
        packs = MONITOR.parse_entitlement_packs(payload)
        self.assertEqual(1, len(packs))
        self.assertEqual(15.0, packs[0]["remaining"])

    def test_missing_pack_list_is_empty(self):
        self.assertEqual([], MONITOR.parse_entitlement_packs({"data": {}}))
        self.assertEqual([], MONITOR.parse_entitlement_packs({}))


if __name__ == "__main__":
    unittest.main()
