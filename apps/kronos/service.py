"""apps/kronos/service.py — FastAPI inference service for Kronos.

Exposes Kronos financial-market predictions over HTTP so JARVIS can call them
without importing PyTorch into the main JARVIS process.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Ensure the apps/kronos model package is importable whether we are run from
# repo root or from apps/kronos.
KRONOS_DIR = Path(__file__).resolve().parent
if str(KRONOS_DIR) not in sys.path:
    sys.path.insert(0, str(KRONOS_DIR))

from model import Kronos, KronosPredictor, KronosTokenizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kronos.service")

DEFAULT_MODEL = os.environ.get("KRONOS_MODEL", "NeoQuasar/Kronos-small")
DEFAULT_TOKENIZER = os.environ.get("KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-base")

_state = {
    "tokenizer": None,
    "model": None,
    "predictor": None,
    "model_name": DEFAULT_MODEL,
    "tokenizer_name": DEFAULT_TOKENIZER,
}


def _load_model():
    """Lazy-load the Kronos model and tokenizer."""
    if _state["predictor"] is not None:
        return _state["predictor"]

    logger.info("Loading tokenizer %s ...", _state["tokenizer_name"])
    tokenizer = KronosTokenizer.from_pretrained(_state["tokenizer_name"])
    logger.info("Loading model %s ...", _state["model_name"])
    model = Kronos.from_pretrained(_state["model_name"])
    predictor = KronosPredictor(model, tokenizer, max_context=512)

    _state["tokenizer"] = tokenizer
    _state["model"] = model
    _state["predictor"] = predictor
    return predictor


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Defer model load until first request to keep service startup fast.
    yield
    # Cleanup is optional; PyTorch tensors are released on process exit.


app = FastAPI(
    title="Kronos Inference Service",
    description="Financial K-line forecasting endpoint for the Mark-LVI unified app.",
    version="1.0.0",
    lifespan=lifespan,
)


class PredictRequest(BaseModel):
    csv_content: Optional[str] = Field(None, description="Raw CSV string with OHLCV data")
    csv_path: Optional[str] = Field(None, description="Path to a CSV file relative to repo root or absolute")
    lookback: int = Field(400, description="Number of input timesteps")
    pred_len: int = Field(120, description="Number of future timesteps to predict")
    columns: list[str] = Field(default_factory=lambda: ["open", "high", "low", "close", "volume", "amount"],
                                description="Column names for price/volume features")
    timestamp_col: str = Field("timestamps", description="Name of the timestamp column")
    T: float = Field(1.0, description="Sampling temperature")
    top_p: float = Field(0.9, description="Top-p nucleus sampling parameter")
    sample_count: int = Field(1, description="Number of forecast samples")


class HealthResponse(BaseModel):
    status: str
    model: str
    tokenizer: str
    loaded: bool


class ModelInfo(BaseModel):
    default_model: str
    default_tokenizer: str
    loaded: bool


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        model=_state["model_name"],
        tokenizer=_state["tokenizer_name"],
        loaded=_state["predictor"] is not None,
    )


@app.get("/models", response_model=ModelInfo)
def models():
    return ModelInfo(
        default_model=_state["model_name"],
        default_tokenizer=_state["tokenizer_name"],
        loaded=_state["predictor"] is not None,
    )


@app.post("/predict")
def predict(req: PredictRequest):
    if not req.csv_content and not req.csv_path:
        raise HTTPException(status_code=400, detail="Provide either csv_content or csv_path")

    try:
        predictor = _load_model()
    except Exception as exc:
        logger.exception("Failed to load Kronos model")
        raise HTTPException(status_code=503, detail=f"Model load failed: {exc}")

    try:
        if req.csv_content:
            df = pd.read_csv(io.StringIO(req.csv_content))
        else:
            path = Path(req.csv_path)
            if not path.is_absolute():
                path = Path(__file__).resolve().parent.parent.parent / path
            df = pd.read_csv(path)

        if req.timestamp_col in df.columns:
            df[req.timestamp_col] = pd.to_datetime(df[req.timestamp_col])

        missing = [c for c in req.columns if c not in df.columns]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing columns: {missing}")

        if len(df) < req.lookback + req.pred_len:
            raise HTTPException(
                status_code=400,
                detail=f"Need at least {req.lookback + req.pred_len} rows, got {len(df)}",
            )

        x_df = df.loc[:req.lookback - 1, req.columns]
        x_timestamp = df.loc[:req.lookback - 1, req.timestamp_col]
        y_timestamp = df.loc[req.lookback:req.lookback + req.pred_len - 1, req.timestamp_col]

        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=req.pred_len,
            T=req.T,
            top_p=req.top_p,
            sample_count=req.sample_count,
            verbose=False,
        )

        return {
            "status": "done",
            "lookback": req.lookback,
            "pred_len": req.pred_len,
            "columns": req.columns,
            "forecast": pred_df.to_dict(orient="records"),
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Prediction failed")
        raise HTTPException(status_code=500, detail=f"Prediction failed: {exc}")


def main():
    parser = argparse.ArgumentParser(description="Kronos inference service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--tokenizer", default=DEFAULT_TOKENIZER)
    args = parser.parse_args()

    _state["model_name"] = args.model
    _state["tokenizer_name"] = args.tokenizer

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
