# Trae AutoCheckin

**Daily Trae check-in with per-run device IDs, credit monitoring, and multi-account reporting with zero Python dependencies.**

[简体中文](../README.md) | [English](README.en.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Português (BR)](README.pt-BR.md)

> This is a localized quick start. See the [complete Simplified Chinese README](../README.md) for every option and troubleshooting detail.

## At a glance

| Item | Details |
| :--- | :--- |
| Purpose | Multi-account Trae daily check-in and read-only credit monitoring |
| Credentials | `TRAE_ACCOUNTS` is recommended; device keys are required for newer token refresh |
| Runtime | Python 3.8+, Qinglong, local cron, or GitHub Actions |
| Dependencies | Python standard library only |
| Result codes | `9004` and `9095` both mean this device has already checked in today |

## Included scripts

- `trae_checkin.py`: check-in workflow with token refresh and a fresh 16-digit check-in device ID per run.
- `trae_credit_monitor.py`: read-only credit balance and usage report.
- `trae_get_token.py`: extract client credentials and export device information.
- `trae_sms_login.py`: browser-based OAuth login flow.

Login and token refresh keep the account-bound device proof. The temporary check-in device ID is reused only for that run's status, claim, and verification calls.

## Quick start

Extract the token and device material from a logged-in Trae client:

```bash
python trae_get_token.py
python trae_get_token.py --export-keys
```

Run the check-in:

```bash
export TRAE_ACCOUNTS='[{"accessToken":"...","refreshToken":"...","uid":"account-1"}]'
export TRAE_DEVICE_KEY_PEM='...'
export TRAE_DEVICE_PUB_PEM='...'
export TRAE_DEVICE_ID='...'
python trae_checkin.py
```

For Qinglong, create a task that runs:

```bash
python trae_checkin.py
```

## GitHub Actions

Fork the repository, enable Actions, and configure these Secrets:

- `TRAE_ACCOUNTS`
- `TRAE_DEVICE_KEY_PEM`
- `TRAE_DEVICE_PUB_PEM`
- `TRAE_DEVICE_ID`
- `TRAE_MACHINE_ID`
- `TRAE_CACHE_KEY`
- Optional: `QYWX_TOKEN`, a supported PushPlus variable, or `TG_BOT_TOKEN` + `TG_CHAT_ID`

The workflow encrypts rotated token state before writing it to Actions Cache. Do not run Qinglong and Actions for the same account at the same time.

## Important variables

| Variable | Purpose |
| :--- | :--- |
| `TRAE_ACCOUNTS` | JSON array containing one or more accounts |
| `TRAE_REFRESH_TOKEN` | Legacy single-account refresh token |
| `TRAE_DEVICE_KEY_PEM` | Device private key required for newer refresh flows |
| `TRAE_DEVICE_PUB_PEM` | Device public key |
| `TRAE_DEVICE_ID` | Registered device identifier |
| `TRAE_MACHINE_ID` | Device machine identifier |
| `TRAE_CACHE_KEY` | Encryption key for Actions state cache |
| `QYWX_TOKEN` | Optional WeCom bot webhook key |
| `PLUSPLUS_TOKEN` | Optional PushPlus token (`PLUSHPLUS_TOKEN` / `PUSHPLUS_TOKEN` also work) |
| `TG_BOT_TOKEN` | Optional Telegram Bot token from `@BotFather` |
| `TG_CHAT_ID` | Optional Telegram chat ID; required together with `TG_BOT_TOKEN` |

## Security

Access tokens, refresh tokens, device private keys, caches, and account files must stay outside Git. Use environment variables or encrypted GitHub Secrets. Avoid refreshing the same account from multiple deployments.

## Usage and redistribution

The official repository, scripts, documentation, and Releases are free. Do not repackage them as paid resources, remove attribution, impersonate the author, use the author's identity or QR codes as endorsement, or repost them through unrelated accounts or groups for traffic. See the [Usage and Redistribution Notice](../NOTICE.md). Violations may result in takedown requests; the author may pause updates, archive, or delete the repository.

## Links

- [Releases](https://github.com/L0NE-6/Trae-AutoCheckin/releases)
- [Issues](https://github.com/L0NE-6/Trae-AutoCheckin/issues)
- [Changelog](../CHANGELOG.md)
- [Complete Chinese documentation](../README.md)
