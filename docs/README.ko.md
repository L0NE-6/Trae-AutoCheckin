# Trae AutoCheckin

**외부 패키지 없이 동작하는 Trae 일일 체크인, 기기 재시도, 크레딧 모니터링 도구입니다.**

[简体中文](../README.md) | [English](README.en.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Português (BR)](README.pt-BR.md)

> 이 문서는 한국어 빠른 안내입니다. 전체 옵션과 문제 해결은 [중국어 간체 README](../README.md)를 확인하세요.

## 개요

| 항목 | 설명 |
| :--- | :--- |
| 목적 | 여러 Trae 계정의 일일 체크인과 읽기 전용 크레딧 모니터링 |
| 자격 증명 | `TRAE_ACCOUNTS` 권장, 최신 갱신 흐름에는 기기 키 필요 |
| 실행 환경 | Python 3.8+, Qinglong, 로컬 cron, GitHub Actions |
| 의존성 | Python 표준 라이브러리만 사용 |
| 결과 코드 | `9004`와 `9095`는 모두 오늘 이미 체크인했다는 의미 |

## 포함 스크립트

- `trae_checkin.py`: 체크인, Token 갱신, 기기 ID 전환.
- `trae_credit_monitor.py`: 읽기 전용 크레딧 잔액 및 사용량 조회.
- `trae_get_token.py`: 클라이언트에서 자격 증명과 기기 정보 추출.
- `trae_sms_login.py`: 브라우저 OAuth 로그인.

## 빠른 시작

```bash
python trae_get_token.py
python trae_get_token.py --export-keys
```

계정과 기기 정보를 설정합니다.

```bash
export TRAE_ACCOUNTS='[{"accessToken":"...","refreshToken":"...","uid":"account-1"}]'
export TRAE_DEVICE_KEY_PEM='...'
export TRAE_DEVICE_PUB_PEM='...'
export TRAE_DEVICE_ID='...'
python trae_checkin.py
```

Qinglong에서는 `python trae_checkin.py` 작업을 생성합니다.

## GitHub Actions

Fork 후 Actions를 활성화하고 `TRAE_ACCOUNTS`, `TRAE_DEVICE_KEY_PEM`, `TRAE_DEVICE_PUB_PEM`, `TRAE_DEVICE_ID`, `TRAE_MACHINE_ID`, `TRAE_CACHE_KEY`를 Secrets에 추가합니다. 알림이 필요하면 `QYWX_TOKEN`도 설정합니다.

동일 계정을 Qinglong과 Actions에서 동시에 갱신하지 마세요.

## 주요 변수

| 변수 | 용도 |
| :--- | :--- |
| `TRAE_ACCOUNTS` | 여러 계정을 담은 JSON 배열 |
| `TRAE_REFRESH_TOKEN` | 구형 단일 계정 refreshToken |
| `TRAE_DEVICE_KEY_PEM` | 최신 갱신 흐름에 필요한 기기 개인 키 |
| `TRAE_DEVICE_PUB_PEM` | 기기 공개 키 |
| `TRAE_DEVICE_ID` | 등록된 기기 ID |
| `TRAE_MACHINE_ID` | 기기 machineId |
| `TRAE_CACHE_KEY` | Actions 캐시 암호화 키 |
| `QYWX_TOKEN` | 선택형 WeCom Bot 키 |

## 보안

AT, RT, 개인 키, 캐시, 계정 파일을 Git에 커밋하지 마세요. 환경 변수 또는 암호화된 Secrets를 사용해야 합니다.

## 사용 범위 및 재배포 안내

공식 저장소, 스크립트, 문서 및 Releases는 무료로 공개됩니다. 유료 리소스로 재포장하거나 저작자 표시를 제거하고, 작성자를 사칭하거나 작성자 이름 또는 QR 코드를 보증 수단으로 사용하는 행위, 무관한 계정이나 그룹으로 옮겨 트래픽을 유도하는 행위를 금지합니다. 자세한 내용은 [사용 범위 및 재배포 안내](../NOTICE.md)를 참고하세요. 위반 시 삭제 요청 대상이 될 수 있으며 작성자는 업데이트 중단, 보관 또는 저장소 삭제를 진행할 수 있습니다.

## 링크

- [Releases](https://github.com/L0NE-6/Trae-AutoCheckin/releases)
- [Issues](https://github.com/L0NE-6/Trae-AutoCheckin/issues)
- [변경 로그](../CHANGELOG.md)
- [전체 중국어 문서](../README.md)
