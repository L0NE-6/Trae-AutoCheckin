# Trae AutoCheckin

**Check-in diário do Trae, repetição por dispositivo, monitoramento de créditos e múltiplas contas sem dependências externas.**

[简体中文](../README.md) | [English](README.en.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Português (BR)](README.pt-BR.md)

> Este é um guia rápido em português. Consulte o [README completo em chinês simplificado](../README.md) para todas as opções e soluções de problemas.

## Visão geral

| Item | Detalhes |
| :--- | :--- |
| Objetivo | Check-in diário de várias contas Trae e monitoramento somente leitura de créditos |
| Credenciais | `TRAE_ACCOUNTS` é recomendado; o fluxo novo de renovação exige chaves do dispositivo |
| Ambiente | Python 3.8+, Qinglong, cron local ou GitHub Actions |
| Dependências | Apenas a biblioteca padrão do Python |
| Códigos | `9004` e `9095` indicam que o dispositivo já fez check-in hoje |

## Scripts

- `trae_checkin.py`: check-in, renovação de tokens e troca controlada de dispositivo.
- `trae_credit_monitor.py`: consulta somente leitura de saldo e uso.
- `trae_get_token.py`: extrai credenciais e dados do dispositivo do cliente.
- `trae_sms_login.py`: login OAuth pelo navegador.

## Início rápido

```bash
python trae_get_token.py
python trae_get_token.py --export-keys
```

Configure a conta e o dispositivo:

```bash
export TRAE_ACCOUNTS='[{"accessToken":"...","refreshToken":"...","uid":"account-1"}]'
export TRAE_DEVICE_KEY_PEM='...'
export TRAE_DEVICE_PUB_PEM='...'
export TRAE_DEVICE_ID='...'
python trae_checkin.py
```

No Qinglong, crie uma tarefa executando `python trae_checkin.py`.

## GitHub Actions

Faça Fork, habilite Actions e cadastre `TRAE_ACCOUNTS`, `TRAE_DEVICE_KEY_PEM`, `TRAE_DEVICE_PUB_PEM`, `TRAE_DEVICE_ID`, `TRAE_MACHINE_ID`, `TRAE_CACHE_KEY` e, se necessário, `QYWX_TOKEN`.

Não renove a mesma conta simultaneamente no Qinglong e no Actions.

## Variáveis principais

| Variável | Finalidade |
| :--- | :--- |
| `TRAE_ACCOUNTS` | Array JSON com várias contas |
| `TRAE_REFRESH_TOKEN` | refreshToken legado de conta única |
| `TRAE_DEVICE_KEY_PEM` | Chave privada exigida pelo fluxo novo |
| `TRAE_DEVICE_PUB_PEM` | Chave pública do dispositivo |
| `TRAE_DEVICE_ID` | Identificador registrado do dispositivo |
| `TRAE_MACHINE_ID` | machineId do dispositivo |
| `TRAE_CACHE_KEY` | Chave de criptografia do cache do Actions |
| `QYWX_TOKEN` | Chave opcional de bot do WeCom |

## Segurança

Nunca envie AT, RT, chaves privadas, caches ou arquivos de conta para o Git. Use variáveis de ambiente ou GitHub Secrets criptografados.

## Limites de uso e redistribuição

O repositório oficial, scripts, documentação e Releases são gratuitos. Não os repackage como recursos pagos, remova a atribuição, personifique o autor, use a identidade ou os QR codes do autor como endosso, nem reposte o projeto em contas ou grupos não relacionados para desviar tráfego. Consulte o [Aviso de uso e redistribuição](../NOTICE.md). Violações podem resultar em pedidos de remoção; o autor pode pausar atualizações, arquivar ou excluir o repositório.

## Links

- [Releases](https://github.com/L0NE-6/Trae-AutoCheckin/releases)
- [Issues](https://github.com/L0NE-6/Trae-AutoCheckin/issues)
- [Changelog](../CHANGELOG.md)
- [Documentação completa em chinês](../README.md)
