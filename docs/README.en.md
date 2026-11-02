# Trae AutoCheckin

**Daily Trae check-in, device-aware retry, credit monitoring, and multi-account reporting with zero Python dependencies.**

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

- `trae_checkin.py`: check-in workflow with token refresh and device rotation.
- `trae_credit_monitor.py`: read-only credit balance and usage report.
- `trae_get_token.py`: extract client credentials and export device information.
- `trae_sms_login.py`: browser-based OAuth login flow.

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
- Optional: `QYWX_TOKEN` or a supported PushPlus variable

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

## Security

Access tokens, refresh tokens, device private keys, caches, and account files must stay outside Git. Use environment variables or encrypted GitHub Secrets. Avoid refreshing the same account from multiple deployments.

## Links

- [Releases](https://github.com/L0NE-6/Trae-AutoCheckin/releases)
- [Issues](https://github.com/L0NE-6/Trae-AutoCheckin/issues)
- [Changelog](../CHANGELOG.md)
- [Complete Chinese documentation](../README.md)
