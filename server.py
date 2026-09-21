"""Jev/TypeSafe-compatible HTTP API around laya.Router: POST /v1/systemone."""
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional, Union

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from laya import Router

API_KEY = os.environ.get("LAYA_API_KEY")  # unset = no auth (local dev only)
AUTO = {None, "", "auto", "laya-latest", "jev-latest"}  # -> language router picks the checkpoint
router: Router


@asynccontextmanager
async def lifespan(_: FastAPI):
    global router
    router = Router(device=os.environ.get("LAYA_DEVICE"))
    # ponytail: add typed-decisions via LAYA_PRELOAD=english,multilingual,typed-decisions
    router.preload(os.environ.get("LAYA_PRELOAD", "english,multilingual").split(","))
    yield


app = FastAPI(title="Laya", lifespan=lifespan)
# ponytail: wide-open CORS (auth is a Bearer header, not cookies); restrict origins for prod
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def auth(authorization: Optional[str] = Header(None)):
    if API_KEY and authorization != "Bearer " + API_KEY:
        raise HTTPException(401, "Invalid or missing API key")


class SystemOneRequest(BaseModel):
    state: Union[str, Dict[str, Any], list]
    questions: Dict[str, Any]
    model: Optional[str] = "laya-latest"  # or english | multilingual | typed-decisions


@app.get("/health")
def health():
    return {"status": "ok", "loaded": router.loaded}


# plain `def` -> runs in FastAPI's threadpool so the blocking forward pass doesn't stall the loop
@app.post("/v1/systemone", dependencies=[Depends(auth)])
def systemone(req: SystemOneRequest):
    try:
        res = router.predict(req.state, req.questions, model=None if req.model in AUTO else req.model)
    except (KeyError, ValueError) as e:  # unknown model / question shape / options too long
        raise HTTPException(422, str(e))
    for a in res["answers"].values():
        a.pop("action", None)  # laya-only field, not in Jev's schema
    res["model"] = "laya-" + res["routing"]["model"]
    return res
