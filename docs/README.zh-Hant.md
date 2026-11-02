# Trae AutoCheckin

**零依賴、多帳號的 Trae 每日簽到、裝置號重試與積分監控工具。**

[简体中文](../README.md) | [English](README.en.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Português (BR)](README.pt-BR.md)

> 本頁是繁體中文快速指南；完整選項與排錯請看[簡體中文 README](../README.md)。

## 快速概覽

| 項目 | 說明 |
| :--- | :--- |
| 用途 | 多帳號 Trae 每日簽到與唯讀積分監控 |
| 憑證 | 建議使用 `TRAE_ACCOUNTS`；新版續期需要裝置金鑰 |
| 執行環境 | Python 3.8+、青龍、本機 cron、GitHub Actions |
| 依賴 | 僅使用 Python 標準庫 |
| 結果碼 | `9004` 與 `9095` 都代表此裝置今日已簽到 |

## 內含腳本

- `trae_checkin.py`：簽到、Token 續期與裝置號輪換。
- `trae_credit_monitor.py`：唯讀查詢積分餘額與用量。
- `trae_get_token.py`：從已登入客戶端提取憑證與裝置資訊。
- `trae_sms_login.py`：使用瀏覽器完成 OAuth 登入。

## 快速開始

```bash
python trae_get_token.py
python trae_get_token.py --export-keys
```

設定帳號與裝置資訊：

```bash
export TRAE_ACCOUNTS='[{"accessToken":"...","refreshToken":"...","uid":"account-1"}]'
export TRAE_DEVICE_KEY_PEM='...'
export TRAE_DEVICE_PUB_PEM='...'
export TRAE_DEVICE_ID='...'
python trae_checkin.py
```

青龍定時任務直接執行：

```bash
python trae_checkin.py
```

## GitHub Actions

Fork 並啟用 Actions 後，設定 `TRAE_ACCOUNTS`、`TRAE_DEVICE_KEY_PEM`、`TRAE_DEVICE_PUB_PEM`、`TRAE_DEVICE_ID`、`TRAE_MACHINE_ID`、`TRAE_CACHE_KEY`，以及可選的 `QYWX_TOKEN`。工作流會先加密輪換後的 Token 狀態，再寫入 Actions Cache。

同一個帳號不要同時在青龍與 Actions 執行，否則 refreshToken 會互相失效。

## 重要變數

| 變數 | 用途 |
| :--- | :--- |
| `TRAE_ACCOUNTS` | 多帳號 JSON 陣列 |
| `TRAE_REFRESH_TOKEN` | 舊版單帳號 refreshToken |
| `TRAE_DEVICE_KEY_PEM` | 新版續期所需的裝置私鑰 |
| `TRAE_DEVICE_PUB_PEM` | 裝置公鑰 |
| `TRAE_DEVICE_ID` | 已註冊的裝置號 |
| `TRAE_MACHINE_ID` | 裝置 machineId |
| `TRAE_CACHE_KEY` | Actions 狀態快取加密金鑰 |
| `QYWX_TOKEN` | 可選企業微信機器人 key |

## 安全提醒

AT、RT、裝置私鑰、快取與帳號檔都不要提交到 Git。使用環境變數或加密 Secrets，並避免同一帳號在多個部署間競爭刷新。

## 連結

- [Releases](https://github.com/L0NE-6/Trae-AutoCheckin/releases)
- [Issues](https://github.com/L0NE-6/Trae-AutoCheckin/issues)
- [更新日誌](../CHANGELOG.md)
- [完整簡體中文文件](../README.md)
