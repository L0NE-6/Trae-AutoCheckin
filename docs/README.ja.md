# Trae AutoCheckin

**依存パッケージ不要の Trae 毎日チェックイン、デバイス再試行、クレジット監視ツール。**

[简体中文](../README.md) | [English](README.en.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Português (BR)](README.pt-BR.md)

> これは日本語クイックガイドです。全オプションとトラブルシューティングは[簡体字中国語 README](../README.md)を参照してください。

## 概要

| 項目 | 内容 |
| :--- | :--- |
| 目的 | 複数アカウントの Trae チェックインと読み取り専用クレジット監視 |
| 認証情報 | `TRAE_ACCOUNTS` 推奨。新しい更新フローではデバイスキーが必要 |
| 実行環境 | Python 3.8+、Qinglong、ローカル cron、GitHub Actions |
| 依存関係 | Python 標準ライブラリのみ |
| 結果コード | `9004` と `9095` はどちらも本日チェックイン済み |

## 収録スクリプト

- `trae_checkin.py`: チェックイン、Token 更新、デバイス ID 切り替え。
- `trae_credit_monitor.py`: クレジット残高と使用量の読み取り専用監視。
- `trae_get_token.py`: クライアントから認証情報とデバイス情報を抽出。
- `trae_sms_login.py`: ブラウザ OAuth ログイン。

## クイックスタート

```bash
python trae_get_token.py
python trae_get_token.py --export-keys
```

認証情報とデバイス情報を設定します。

```bash
export TRAE_ACCOUNTS='[{"accessToken":"...","refreshToken":"...","uid":"account-1"}]'
export TRAE_DEVICE_KEY_PEM='...'
export TRAE_DEVICE_PUB_PEM='...'
export TRAE_DEVICE_ID='...'
python trae_checkin.py
```

Qinglong では `python trae_checkin.py` をタスクに設定します。

## GitHub Actions

Fork して Actions を有効化し、`TRAE_ACCOUNTS`、`TRAE_DEVICE_KEY_PEM`、`TRAE_DEVICE_PUB_PEM`、`TRAE_DEVICE_ID`、`TRAE_MACHINE_ID`、`TRAE_CACHE_KEY` を Secrets に登録します。通知を使う場合は `QYWX_TOKEN` も設定します。

同じアカウントを Qinglong と Actions で同時に更新しないでください。

## 主な変数

| 変数 | 用途 |
| :--- | :--- |
| `TRAE_ACCOUNTS` | 複数アカウントの JSON 配列 |
| `TRAE_REFRESH_TOKEN` | 旧式の単一アカウント refreshToken |
| `TRAE_DEVICE_KEY_PEM` | 新しい更新フロー用の秘密鍵 |
| `TRAE_DEVICE_PUB_PEM` | デバイス公開鍵 |
| `TRAE_DEVICE_ID` | 登録済みデバイス ID |
| `TRAE_MACHINE_ID` | デバイス machineId |
| `TRAE_CACHE_KEY` | Actions キャッシュ暗号化キー |
| `QYWX_TOKEN` | 任意の WeCom Bot キー |

## セキュリティ

AT、RT、秘密鍵、キャッシュ、アカウントファイルを Git に保存しないでください。環境変数または暗号化された Secrets を使用してください。

## リンク

- [Releases](https://github.com/L0NE-6/Trae-AutoCheckin/releases)
- [Issues](https://github.com/L0NE-6/Trae-AutoCheckin/issues)
- [変更履歴](../CHANGELOG.md)
- [完全な中国語ドキュメント](../README.md)
