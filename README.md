# laya-api

A self-hosted, Jev/TypeSafe-compatible HTTP API around [Laya](https://github.com/NandhaKishorM/laya) (`laya==0.3.4` on PyPI, Apache 2.0, by Convai Innovations).

Laya is a non-autoregressive "System 1" decision engine. You give it any text or JSON state and a set of typed questions (`choice`, `score`, `noul`), and it answers all of them in **one forward pass** (about 33 ms on a T4 GPU). There is no text generation, so there is nothing to parse and nothing to hallucinate. Laya ships as a Python library only; this repo adds the server.

The API mirrors [TypeSafe Jev](https://docs.typesafe.ai/introduction/quickstart), so Jev clients and request bodies work by changing the base URL:

```
POST /v1/systemone
Authorization: Bearer <key>
body:     {state, model, questions}
response: {model, answers, usage}
```

The companion frontend is [`laya-demo-web`](https://github.com/sriramkasyap/laya-demo-web) (a Vite + React playground on port 3007).

## Features

- `POST /v1/systemone` with the Jev request/response shape, plus `GET /health`.
- Three question primitives: `choice`, `score`, `noul`.
- Automatic checkpoint routing per request (English vs. multilingual) via `laya.Router`. The response includes a `routing` object explaining the decision.
- Optional Bearer-token auth via `LAYA_API_KEY`.
- CORS enabled for all origins, so a browser client such as `laya-demo-web` can call it directly.
- CPU-only Docker image by default; runs on GPU with a one-line change.
- Model weights are cached in a Docker volume, so only the first start downloads them.

## Architecture

```
                    +-----------------------------------------+
                    |            laya-api (FastAPI)            |
  client  --------> |  POST /v1/systemone                      |
  (Bearer key)      |    auth -> validate -> router.predict()  |
                    |                          |               |
                    |                    laya.Router           |
                    |                   /            \         |
                    |            english          multilingual |
                    |          (ModernBERT-large)  (mmBERT-base)|
                    +-----------------------------------------+
                      (typed-decisions is also available; see below)
```

`server.py` is a single file. At startup it builds a `laya.Router` and preloads the checkpoints listed in `LAYA_PRELOAD`. Each request calls `router.predict(state, questions, model=...)`, removes Laya's internal `action` field from each answer, and sets the response `model` to `laya-<routed checkpoint>`. The endpoint is a plain `def`, so FastAPI runs the blocking forward pass in its threadpool instead of on the event loop.

### Checkpoints

Laya has three checkpoints (Hugging Face: `convaiinnovations/laya`):

| Name | Base model | Params | Context | Notes |
|---|---|---|---|---|
| `english` | ModernBERT-large | 421M | 512 | Default for English text |
| `multilingual` | mmBERT-base | 322M | 1024 | 100+ languages |
| `typed-decisions` | ModernBERT-large | - | 1024 | Fine-tuned for typed-decisions workflows |

With auto-routing, `laya.Router` sends non-Latin-script text and non-English Latin-script text to `multilingual`, and everything else to `english`.

## Quick start

```bash
docker build -t laya-api .
docker run -d --name laya-api -p 8008:8008 \
  -e LAYA_API_KEY=secret \
  -v laya-models:/models \
  laya-api
```

The first start downloads about 2 GB of weights (english + multilingual) into the `laya-models` volume and takes a few minutes. `GET /health` only answers once the models are loaded, because startup blocks on preload. Later starts are fast.

Then:

```bash
curl -s http://localhost:8008/health
# {"status":"ok","loaded":["english","multilingual"]}
```

## API reference

Base URL: `http://localhost:8008` (or wherever you deploy it).

### `GET /health`

No authentication. Returns the status and the checkpoints currently loaded.

```json
{"status": "ok", "loaded": ["english", "multilingual"]}
```

### `POST /v1/systemone`

Answers a set of typed questions about a state in one forward pass.

**Headers**

| Header | Required | Description |
|---|---|---|
| `Authorization: Bearer <key>` | Only when `LAYA_API_KEY` is set | Must equal `Bearer ` followed by the exact value of `LAYA_API_KEY` |
| `Content-Type: application/json` | Yes | |

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| `state` | string, object, or array | Yes | The text or JSON the questions are asked about |
| `questions` | object | Yes | Map of question name to question definition (see below) |
| `model` | string | No (default `laya-latest`) | `laya-latest`, `jev-latest`, `auto`, or omitted: auto-route by language. Or force one of `english`, `multilingual`, `typed-decisions`, plus Laya's own aliases such as `en`, `ml`, `multi`, `typed` |

**Question types**

Each entry in `questions` has a `type`, human-readable `instructions`, and type-specific `criteria`.

| `type` | `criteria` | Answer |
|---|---|---|
| `choice` | Object mapping option label to a description | The top label, per-option probabilities, and confidence |
| `score` | Ordered list of rubric strings (low to high) | Expected level as a float, a legend, per-level probabilities, and confidence |
| `noul` | None (yes/no question) | `P(true)` between 0 and 1 |

**Response body (200)**

| Field | Type | Description |
|---|---|---|
| `model` | string | `laya-english`, `laya-multilingual`, or `laya-typed-decisions`: the checkpoint that answered |
| `answers` | object | One entry per question name, keyed as in the request |
| `answers.<q>.type` | string | Echoes the question type |
| `answers.<q>.choice` | string | `choice` only: the top-scoring option |
| `answers.<q>.probabilities` | object | `choice`: option to probability. `score`: level index to probability |
| `answers.<q>.score` | number | `score` only: the probability-weighted expected level |
| `answers.<q>.legend` | object | `score` only: level index to rubric string |
| `answers.<q>.noul` | number | `noul` only: probability the answer is yes, 0 to 1 |
| `answers.<q>.confidence` | number | Confidence for the answer (present on all three types) |
| `usage` | object | `{input_tokens, output_tokens}`. `output_tokens` is always `0` |
| `routing` | object | Extension beyond Jev's schema: `{model, repo, reason, detection, workflow}` |

**Errors**

| Status | When | Body |
|---|---|---|
| 401 | `LAYA_API_KEY` is set and the header is missing or wrong | `{"detail":"Invalid or missing API key"}` |
| 422 | A required field is missing (FastAPI validation error list) | `{"detail":[...]}` |
| 422 | Unknown `model` name; the message lists valid names and aliases | `{"detail":"..."}` |
| 422 | Invalid question shape, or a question's options exceed the head token budget | `{"detail":"..."}` |

The server maps `KeyError` and `ValueError` raised by `router.predict` to 422 with the exception's message.

### Differences from Jev

- Laya's internal `action` field is stripped from every answer.
- The response has an extra `routing` object.
- `usage.output_tokens` is always `0`.
- `noul` answers also carry `confidence`.
- `score` is the probability-weighted expected level.

## Examples

### English, auto-routed

```bash
curl -s http://localhost:8008/v1/systemone \
  -H "Authorization: Bearer secret" \
  -H "Content-Type: application/json" \
  -d '{
    "state": "We were billed twice for March. Refund the duplicate today or we cancel our plan.",
    "model": "jev-latest",
    "questions": {
      "department": {
        "type": "choice",
        "instructions": "Which department should handle this request?",
        "criteria": {
          "billing": "invoices, payments, refunds",
          "technical": "bugs, outages",
          "sales": "pricing",
          "other": "else"
        }
      },
      "urgency": {
        "type": "score",
        "instructions": "How urgent?",
        "criteria": ["not urgent", "soon", "critical"]
      },
      "churn_risk": {
        "type": "noul",
        "instructions": "Does the user threaten to cancel?"
      }
    }
  }'
```

Response (200):

```json
{
  "model": "laya-english",
  "answers": {
    "department": {
      "type": "choice",
      "choice": "billing",
      "probabilities": {"billing": 0.9708, "technical": 0.0117, "sales": 0.0088, "other": 0.0086},
      "confidence": 0.882
    },
    "urgency": {
      "type": "score",
      "score": 1.5228,
      "legend": {"0": "not urgent", "1": "soon", "2": "critical"},
      "probabilities": {"0": 0.0735, "1": 0.3301, "2": 0.5964},
      "confidence": 0.2117
    },
    "churn_risk": {"type": "noul", "noul": 0.8494, "confidence": 0.8494}
  },
  "usage": {"input_tokens": 152, "output_tokens": 0},
  "routing": {
    "model": "english",
    "repo": "convaiinnovations/laya",
    "reason": "English Latin text",
    "detection": {
      "script": "latin",
      "script_profile": {"latin": 1.0},
      "language": "en",
      "is_english": true,
      "non_latin_fraction": 0.0
    },
    "workflow": null
  }
}
```

### Hindi, auto-routed to multilingual

Non-Latin text is routed to the multilingual checkpoint automatically. This Hindi state ("I was charged twice, please refund the money") returns `model: "laya-multilingual"`, `department: "billing"`, and a `routing.reason` of `non-Latin script (devanagari, 100% of letters); the English checkpoint cannot read it`.

```bash
curl -s http://localhost:8008/v1/systemone \
  -H "Authorization: Bearer secret" \
  -H "Content-Type: application/json" \
  -d '{
    "state": "मुझसे दो बार शुल्क लिया गया, कृपया पैसे वापस करें।",
    "questions": {
      "department": {
        "type": "choice",
        "instructions": "Which department should handle this request?",
        "criteria": {
          "billing": "invoices, payments, refunds",
          "technical": "bugs, outages",
          "sales": "pricing",
          "other": "else"
        }
      }
    }
  }'
```

### Forcing a checkpoint

Set `model` to `english`, `multilingual`, or `typed-decisions` to skip routing. To have a checkpoint loaded at startup, add it to `LAYA_PRELOAD` (for example, `typed-decisions` is not preloaded by default).

```bash
curl -s http://localhost:8008/v1/systemone \
  -H "Authorization: Bearer secret" \
  -H "Content-Type: application/json" \
  -d '{
    "state": "Checkout page returns a 500 error since this morning.",
    "model": "multilingual",
    "questions": {
      "churn_risk": {"type": "noul", "instructions": "Does the user threaten to cancel?"}
    }
  }'
```

### Python

```python
import requests

resp = requests.post(
    "http://localhost:8008/v1/systemone",
    headers={"Authorization": "Bearer secret"},
    json={
        "state": "We were billed twice for March. Refund the duplicate today or we cancel our plan.",
        "model": "jev-latest",
        "questions": {
            "department": {
                "type": "choice",
                "instructions": "Which department should handle this request?",
                "criteria": {
                    "billing": "invoices, payments, refunds",
                    "technical": "bugs, outages",
                    "sales": "pricing",
                    "other": "else",
                },
            },
            "churn_risk": {"type": "noul", "instructions": "Does the user threaten to cancel?"},
        },
    },
    timeout=30,
)
resp.raise_for_status()
data = resp.json()
print(data["model"])                              # laya-english
print(data["answers"]["department"]["choice"])    # billing
print(data["answers"]["churn_risk"]["noul"])      # probability, 0..1
```

## Configuration

All configuration is through environment variables.

| Variable | Default | Description |
|---|---|---|
| `LAYA_API_KEY` | unset | When set, `POST /v1/systemone` requires `Authorization: Bearer <key>`. **When unset there is no auth at all** (local development only). `/health` is never authenticated |
| `LAYA_PRELOAD` | `english,multilingual` | Comma-separated checkpoints loaded at startup. Add `typed-decisions` to load it too (`english,multilingual,typed-decisions`) |
| `LAYA_DEVICE` | auto | Device passed to `laya.Router`, for example `cuda`. Unset lets Laya choose |
| `HF_TOKEN` | unset | Optional Hugging Face token for faster downloads |
| `HF_HOME` | `/models` (set in the Dockerfile) | Where Hugging Face caches weights |

## Running

### Docker

```bash
docker build -t laya-api .
docker run -d --name laya-api -p 8008:8008 \
  -e LAYA_API_KEY=secret \
  -v laya-models:/models \
  laya-api
```

The image is based on `python:3.11-slim`, installs CPU-only PyTorch from `https://download.pytorch.org/whl/cpu`, then `requirements.txt` (`laya==0.3.4`, `fastapi>=0.110`, `uvicorn>=0.29`), and serves `uvicorn server:app --host 0.0.0.0 --port 8008`. It has a `HEALTHCHECK` on `/health` with a 300 s start period to cover the first-run download.

### Without Docker

Requires Python 3.11.

```bash
python -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # or a CUDA build of torch
pip install -r requirements.txt
LAYA_API_KEY=secret uvicorn server:app --port 8008
```

Weights are downloaded to the default Hugging Face cache (or `HF_HOME` if you set it) on first start.

## Deployment notes

- **Persistent volume.** Mount a volume at `/models` (`-v laya-models:/models`). Without it, every new container re-downloads the weights.
- **Sizing.** Plan for about 2 GB of weights on disk for the default `english` + `multilingual` preload, plus enough RAM to hold both models. Adding `typed-decisions` loads a third checkpoint.
- **Startup time.** Startup blocks until preload finishes, so the container is not healthy (and `/health` does not respond) until then. The first start includes the download.
- **GPU.** Remove the `--index-url` line from the `torch` install in the `Dockerfile` (or install a CUDA build of torch), run the container on a CUDA-capable host with GPU access, and set `LAYA_DEVICE=cuda`. The approximately 33 ms per pass figure is Laya's number on a T4 GPU. On CPU, three English questions took about 0.5 s per request in testing.
- **Production.** See [Security notes](#security-notes) before exposing this publicly.

## Development notes

- The whole server is `server.py`; the Docker image copies only that file and `requirements.txt` (`.dockerignore` excludes `.git` and `*.md`).
- Routing and inference are entirely Laya's. The wrapper only handles auth, validation error mapping, removing `action`, and setting the response `model`.
- Only the `laya.Router` predict path is exposed. There are no preset endpoints, no batching endpoint, no `/v1/models` endpoint, and no streaming.
- FastAPI generates interactive docs at `/docs` and the schema at `/openapi.json` by default; the app does not disable them.

## Limitations

These come from Laya itself and from what this wrapper exposes.

**Model quality**

- Laya is "a fast base to specialise, not a zero-shot decision engine". On the typed-decisions benchmark, the base checkpoints are near chance zero-shot (0.36 and 0.34, against 0.318 random and a 0.461 majority baseline). The 0.766 figure comes from the fine-tuned `typed-decisions` checkpoint on that benchmark's own split. The value is in fine-tuning on your own data (there is a notebook in the upstream repo).
- High-cardinality `choice` questions (50 or more options) degrade, because the options share a fixed head token budget (192 tokens for English, 256 for multilingual). This server does not expose the budget, so split the question hierarchically (coarse category first, then a second question), or change the server code to raise Laya's `agent.cfg["head_max_len"]` / `max_len`. A question whose options exceed the budget returns 422.
- The English checkpoint collapses on non-Latin scripts. This is why auto-routing is on by default; forcing `english` on such text is not recommended.
- Probabilities are over-confident as shipped, and the multilingual checkpoint ships without fitted temperatures.
- Ordinal `score` is the weakest of the three primitives.

**Wrapper**

- No rate limiting, no batching, no streaming, no `/v1/models`, no presets endpoints.
- `usage.output_tokens` is always `0`.

## Security notes

- CORS is wide open (`allow_origins=["*"]`). Auth is a Bearer header rather than cookies, so this is not a cookie-CSRF risk, but you should still restrict origins for production.
- There is one shared API key, compared with plain string equality on every request (it is not hashed, and there are no per-client keys).
- With `LAYA_API_KEY` unset, the API is unauthenticated.
- There is no rate limiting. Put the service behind a TLS-terminating reverse proxy, and add rate limiting there if needed.

## Licence and credits

- [Laya](https://github.com/NandhaKishorM/laya) is Apache 2.0, by Convai Innovations. This repo is a thin HTTP wrapper around it and does not modify it.
- Jev/TypeSafe is a separate product. This API is shape-compatible with its `/v1/systemone` endpoint so that clients can be reused; there is no affiliation with TypeSafe.
