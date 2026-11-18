"""Headless data-analysis agent service.

Port of awesome-llm-apps-main/starter_ai_agents/ai_data_analysis_agent
(ai_data_analyst.py) with Streamlit removed. The agno agent (DuckDB +
Pandas tools over an uploaded table) is exposed as a small FastAPI app so
JARVIS can run analyses without loading agno/duckdb/pandas into its own
process.

Endpoints:
    GET  /health   -> {"status": "ok"}
    POST /analyze  {question, csv_path? | rows?} -> {answer, tables?}

LLM endpoint comes from the environment at launch:
    OPENAI_BASE_URL  (default http://localhost:11434/v1)
    OPENAI_API_KEY   (default "ollama")
    OPENAI_MODEL_NAME or DATA_ANALYST_MODEL (default "gpt-4o")
"""

import csv
import os
import tempfile

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckdb import DuckDbTools
from agno.tools.pandas import PandasTools

OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:11434/v1")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "ollama")
MODEL_ID = os.environ.get(
    "DATA_ANALYST_MODEL", os.environ.get("OPENAI_MODEL_NAME", "gpt-4o")
)

app = FastAPI(title="JARVIS Data Analyst")


class AnalyzeRequest(BaseModel):
    question: str
    csv_path: str | None = None
    rows: list[dict] | None = None


def preprocess_and_save(df: pd.DataFrame):
    """Preprocess a DataFrame and save it to a temp CSV (ported verbatim in spirit)."""
    # Parse dates and numeric columns
    for col in df.columns:
        if "date" in str(col).lower():
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif df[col].dtype == "object":
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass  # keep as is if conversion fails

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as temp_file:
        temp_path = temp_file.name
        df.to_csv(temp_path, index=False, quoting=csv.QUOTE_ALL)

    return temp_path, df.columns.tolist(), df


def load_dataframe(req: AnalyzeRequest) -> pd.DataFrame:
    if req.rows:
        return pd.DataFrame(req.rows)
    if req.csv_path:
        path = req.csv_path
        if not os.path.exists(path):
            raise HTTPException(status_code=400, detail=f"CSV not found: {path}")
        if path.endswith(".csv"):
            return pd.read_csv(path, encoding="utf-8", na_values=["NA", "N/A", "missing"])
        if path.endswith(".xlsx"):
            try:
                return pd.read_excel(path, na_values=["NA", "N/A", "missing"])
            except ImportError:
                raise HTTPException(
                    status_code=400,
                    detail="Excel support needs openpyxl; upload a CSV instead.",
                )
        raise HTTPException(status_code=400, detail="Unsupported file format. Use CSV or Excel.")
    raise HTTPException(status_code=400, detail="Provide csv_path or rows.")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")

    df = load_dataframe(req)
    temp_path, columns, df = preprocess_and_save(df)

    duckdb_tools = DuckDbTools()
    duckdb_tools.load_local_csv_to_table(path=temp_path, table="uploaded_data")

    agent = Agent(
        model=OpenAIChat(
            id=MODEL_ID,
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
        ),
        tools=[duckdb_tools, PandasTools()],
        system_message=(
            "You are an expert data analyst. Use the 'uploaded_data' table to "
            "answer user queries. Generate SQL queries using DuckDB tools to "
            "solve the user's query. Provide clear and concise answers with "
            "the results."
        ),
        markdown=True,
    )

    try:
        response = agent.run(req.question)
        content = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent error: {e}")
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass

    return {
        "answer": content,
        "tables": [
            {
                "name": "uploaded_data",
                "columns": [str(c) for c in columns],
                "row_count": int(len(df)),
                "preview": df.head(10).astype(str).to_dict(orient="records"),
            }
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "7863")))
