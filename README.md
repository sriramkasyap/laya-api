# laya-api

Jev/TypeSafe-compatible HTTP API around [Laya](https://github.com/NandhaKishorM/laya).
`POST /v1/systemone` with `{state, questions, model?}` -> `{model, answers, usage}`. Also `GET /health`.

```bash
docker build -t laya-api .
docker run -d --name laya-api -p 8008:8008 -e LAYA_API_KEY=secret -v laya-models:/models laya-api
```

The first start downloads ~2GB of weights into the `laya-models` volume (a few minutes; `/health` answers once ready).

| env | default | |
|---|---|---|
| `LAYA_API_KEY` | unset (no auth) | required as `Authorization: Bearer <key>` when set |
| `LAYA_PRELOAD` | `english,multilingual` | checkpoints loaded at start (`typed-decisions` also available) |
| `LAYA_DEVICE` | auto | e.g. `cuda` |
| `HF_TOKEN` | unset | faster HF downloads |

`model`: `laya-latest`/`jev-latest`/omitted = auto-route by language; or `english`, `multilingual`, `typed-decisions`.
