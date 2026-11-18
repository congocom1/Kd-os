# Awesome LLM Apps

LLM-assisted safe code editing for team members.

## Safety model
* Owner scoping – a member can only propose changes under `apps/<owner>/` unless admin.
* Proposals go through JARVIS `code_evolve` – never auto applied.
* Git backup + commit before every change.
* LLM review endpoint flags TODOs, size, etc.

## Run
```bash
cd apps/awesome-llm
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 7862
```

## Endpoints
* POST /review – static LLM-style review
* POST /refactor – creates a code_evolve proposal, backs up via git
* POST /docgen – generates markdown docs

Integrate with JARVIS actions via `actions/team_code_safety.py` to expose these as voice commands.
