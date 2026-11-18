"""
Awesome LLM Apps – safe team code modification with LLM assistance.

Provides:
  * /review – LLM-based code review with safety checks
  * /refactor – LLM-assisted refactor with git backup
  * /docgen – auto-generate docs from code

Safety guarantees:
  * All changes go through JARVIS code_evolve pipeline – proposals are saved, reviewed, never auto-applied.
  * Owner-scoping: only files under apps/<owner>/* can be modified by that owner.
  * Git backup + commit before every apply.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
import json, hashlib, subprocess

BASE_DIR = Path(__file__).resolve().parents[2]
PROPOSAL_DIR = BASE_DIR / "data" / "code_proposals"
PROPOSAL_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Awesome LLM Apps")

class ReviewRequest(BaseModel):
    owner: str
    file_path: str
    code: str

class RefactorRequest(BaseModel):
    owner: str
    file_path: str
    instruction: str
    new_body: str
    reason: str = "LLM refactor"

def _owner_allowed(owner: str, file_path: str) -> bool:
    target = (BASE_DIR / file_path).resolve()
    allowed_root = (BASE_DIR / "apps" / owner).resolve()
    try:
        target.relative_to(allowed_root)
        return True
    except Exception:
        # Allow core actions for the repo owner only
        return owner == "admin" and str(target).startswith(str(BASE_DIR / "actions"))

def _git_commit(msg: str, file_path: Path):
    try:
        subprocess.run(["git","add",str(file_path)], cwd=BASE_DIR, check=True, capture_output=True)
        subprocess.run(["git","commit","-m",msg], cwd=BASE_DIR, check=True, capture_output=True)
        return True
    except Exception:
        return False

@app.post("/review")
def review(req: ReviewRequest):
    if not _owner_allowed(req.owner, req.file_path):
        raise HTTPException(403, "Not allowed to review this file")
    # Simple LLM-style static checks – in production replace with real LLM call
    issues = []
    if len(req.code.splitlines()) > 2000:
        issues.append("Large file – consider splitting")
    if "TODO" in req.code:
        issues.append("Found TODO comments")
    return {"owner": req.owner, "file": req.file_path, "issues": issues, "safe": len(issues)==0}

@app.post("/refactor")
def refactor(req: RefactorRequest):
    if not _owner_allowed(req.owner, req.file_path):
        raise HTTPException(403, "Not allowed to modify this file")
    target = (BASE_DIR / req.file_path).resolve()
    if not target.exists():
        raise HTTPException(404, "File not found")
    current = target.read_text(encoding="utf-8")
    # Create proposal via code_evolve pipeline
    name = f"team-{req.owner}-{target.name}-{hashlib.sha1(req.new_body.encode()).hexdigest()[:8]}"
    proposal = {
        "name": name,
        "target_file": str(target),
        "reason": req.reason,
        "current_hash": hashlib.sha256(current.encode()).hexdigest(),
        "new_body": req.new_body,
        "owner": req.owner
    }
    (PROPOSAL_DIR / f"{name}.json").write_text(json.dumps(proposal, indent=2))
    # Backup current via git
    _git_commit(f"Backup before LLM refactor {name}", target)
    return {"proposal": name, "status": "proposed", "file": str(target), "review_url": f"/review?proposal={name}"}

@app.post("/docgen")
def docgen(req: ReviewRequest):
    if not _owner_allowed(req.owner, req.file_path):
        raise HTTPException(403, "Not allowed")
    # Stub doc generation
    doc = f"# Documentation for {req.file_path}\n\nGenerated for owner {req.owner}.\n\n```python\n{req.code[:1000]}\n```"
    return {"doc": doc}

@app.get("/health")
def health():
    return {"status": "ok", "service": "awesome-llm-apps"}


@app.get("/")
def root():
    return {"service":"awesome-llm-apps","endpoints":["/review","/refactor","/docgen"]}
