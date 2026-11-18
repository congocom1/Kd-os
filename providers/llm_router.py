"""
providers/llm_router.py — Intelligent model routing for JARVIS.

Routes each turn to the right model based on task complexity, cost and
availability. Keeps the conversation on the cheapest model that can handle it,
and escalates to larger models only when needed.

WHY THIS EXISTS
    A single model for everything is wasteful: a 70B parameter model answering
    "what time is it" burns GPU cycles and costs money, while a tiny model
    attempting code review hallucinates. This router keeps a small model on the
    hot path and escalates only when the task demands it.

HOW ROUTING WORKS
    Each model is declared with a capability tier and a cost weight. The router
    starts every conversation on the cheapest capable model. If a tool call
    fails or the model signals it cannot handle the task, the router escalates
    to the next tier. On a fresh turn it de-escalates back down, so expensive
    models are only used when they are actually needed.

MODEL TIERS
    cheap    — small, fast, free/local models (e.g. llama3.2:3b on Ollama).
               For: greetings, simple facts, reminders, status checks.
    standard — mid-size models (e.g. llama3.1:8b). For: most conversation,
               tool use, light reasoning.
    premium  — large models (e.g. llama3.1:70b). For: complex reasoning,
               code generation, long context, creative writing.

USAGE
    The router replaces a single LLM provider. Configure it in the settings
    panel under "Intelligent model router" with a "models" JSON list:

    [
      { "name": "llama3.2:3b",    "base_url": "http://127.0.0.1:11434/v1",
        "tier": "cheap",  "cost": 1,  "vision": false, "tools": true },
      { "name": "llama3.1:8b",    "base_url": "http://127.0.0.1:11434/v1",
        "tier": "standard", "cost": 3,  "vision": false, "tools": true },
      { "name": "llama3.1:70b",   "base_url": "http://127.0.0.1:11434/v1",
        "tier": "premium", "cost": 10, "vision": true,  "tools": true },
    ]
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from . import llm_openai
from .base import DEFAULT_CAPS, Field

# ── Tier ordering ─────────────────────────────────────────────────────────────

_TIER_ORDER = ("cheap", "standard", "premium")
_TIER_RANK = {name: i for i, name in enumerate(_TIER_ORDER)}


def _tier_rank(tier: str) -> int:
    return _TIER_RANK.get(tier, 99)


import re as _re


def estimate_size_gb(name: str, declared: float = 0.0) -> float:
    """Estimated resident size of a model in GB.

    Order: the config's explicit size_gb, else the parameter count in the
    model name ("qwen3.5:27b") × ~0.65 GB/billion for Q4 quantization + 1 GB
    runtime overhead. An estimate, clearly labelled — Ollama still decides
    how much actually lands on the GPU.
    """
    if declared:
        return float(declared)
    m = _re.search(r"(\d+(?:\.\d+)?)\s*b\b", (name or "").lower())
    if not m:
        return 0.0          # unknown size: do not penalize what we cannot see
    return float(m.group(1)) * 0.65 + 1.0


def detect_vram_gb() -> float:
    """Total VRAM of the first NVIDIA GPU in GB, or 0.0 when unavailable."""
    try:
        import pynvml
        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            return pynvml.nvmlDeviceGetMemoryInfo(handle).total / 1e9
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return 0.0


# ── Model spec ────────────────────────────────────────────────────────────────

class ModelSpec:
    """One model in the router's fleet, backed by a live OpenAICompatLLM."""

    def __init__(self, d: dict) -> None:
        self.name = d.get("name", "")
        self.base_url = d.get("base_url", "http://127.0.0.1:11434/v1")
        self.tier = d.get("tier", "standard")
        self.cost = float(d.get("cost", 1))
        self.vision = bool(d.get("vision", False))
        self.tools = bool(d.get("tools", True))
        self.api_key = d.get("api_key", "")
        self.max_tools = int(d.get("max_tools", 0)) or 0
        self.max_tool_chars = int(d.get("max_tool_chars", 0)) or 0
        self.size_gb = estimate_size_gb(self.name, float(d.get("size_gb", 0)))
        self.failures = 0
        self._llm: Optional[llm_openai.OpenAICompatLLM] = None

    @property
    def llm(self) -> llm_openai.OpenAICompatLLM:
        """Lazily build the underlying OpenAICompatLLM provider."""
        if self._llm is None:
            self._llm = llm_openai.OpenAICompatLLM({
                "base_url": self.base_url,
                "model": self.name,
                "api_key": self.api_key,
                "vision": self.vision,
                "max_tools": self.max_tools,
                "max_tool_chars": self.max_tool_chars,
            })
        return self._llm

    def can_handle(self, needs_vision: bool, needs_tools: bool) -> bool:
        if needs_vision and not self.vision:
            return False
        if needs_tools and not self.tools:
            return False
        return self.failures < 3  # circuit breaker: skip recently-failed models

    def mark_failed(self) -> None:
        self.failures = min(self.failures + 1, 5)

    def mark_ok(self) -> None:
        self.failures = max(0, self.failures - 1)


# ── Router ────────────────────────────────────────────────────────────────────

class LLMRouter:
    """Picks the right model for each turn and escalates on failure.

    Holds a fleet of ModelSpec objects, each backed by a live
    OpenAICompatLLM. On each turn selects the cheapest capable model,
    runs the turn through it, and escalates to a more capable model if the
    current one fails or signals inability.
    """

    def __init__(self, cfg: dict) -> None:
        self.models: list[ModelSpec] = []
        for d in cfg.get("models", []):
            self.models.append(ModelSpec(d))
        # Default fleet if none declared — Ollama on localhost.
        if not self.models:
            self.models.append(ModelSpec({
                "name": "llama3.2:3b", "base_url": "http://127.0.0.1:11434/v1",
                "tier": "cheap", "cost": 1, "vision": False, "tools": True,
            }))
            self.models.append(ModelSpec({
                "name": "llama3.1:8b", "base_url": "http://127.0.0.1:11434/v1",
                "tier": "standard", "cost": 3, "vision": False, "tools": True,
            }))
            self.models.append(ModelSpec({
                "name": "llama3.1:70b", "base_url": "http://127.0.0.1:11434/v1",
                "tier": "premium", "cost": 10, "vision": True, "tools": True,
            }))
        self._current: Optional[ModelSpec] = None

        # VRAM budget (spec: never assume several large models fit at once).
        # Config override vram_budget_gb wins; else 85% of detected VRAM;
        # 0 = no GPU detected → no VRAM preference applied.
        if "vram_budget_gb" in cfg:
            # Explicit config wins, including 0 (= disable the budget).
            self.vram_budget_gb = float(cfg["vram_budget_gb"])
        else:
            self.vram_budget_gb = detect_vram_gb() * 0.85

    def _fits_vram(self, m: ModelSpec) -> bool:
        return (not self.vram_budget_gb) or (not m.size_gb) \
            or m.size_gb <= self.vram_budget_gb

    def _order(self, candidates: list[ModelSpec]) -> list[ModelSpec]:
        """Cheapest capable first, but models that fit the VRAM budget always
        outrank ones that would spill to CPU offload. Unknown sizes rank with
        fitting ones — an estimate must never hide a model."""
        fits = [m for m in candidates if self._fits_vram(m)]
        over = [m for m in candidates if not self._fits_vram(m)]
        fits.sort(key=lambda m: (m.cost, m.failures, m.name))
        over.sort(key=lambda m: (m.size_gb, m.cost, m.failures, m.name))
        return fits + over

    # ── selection ────────────────────────────────────────────────────────

    def select(self, needs_vision: bool = False, needs_tools: bool = False,
               escalate: bool = False) -> Optional[ModelSpec]:
        """Pick the cheapest capable model.

        If escalate is True, skip anything at or below the current tier.
        """
        candidates = [m for m in self.models if m.can_handle(needs_vision, needs_tools)]
        if not candidates:
            return None

        if escalate and self._current:
            cur_rank = _tier_rank(self._current.tier)
            candidates = [m for m in candidates
                          if _tier_rank(m.tier) > cur_rank]

        candidates = self._order(candidates)
        return candidates[0] if candidates else None

    def select_for_turn(self, needs_vision: bool = False,
                        needs_tools: bool = False) -> Optional[ModelSpec]:
        """Pick a model for a fresh turn, preferring the current healthy one."""
        # On a fresh turn, try the current model first if it is still healthy.
        if self._current and self._current.can_handle(needs_vision, needs_tools):
            if self._current.failures == 0:
                return self._current
        model = self.select(needs_vision, needs_tools, escalate=False)
        self._current = model
        return model

    def escalate(self, needs_vision: bool = False,
                 needs_tools: bool = False) -> Optional[ModelSpec]:
        """Move up one tier for the next turn.

        Returns None if already at the highest capable tier.
        """
        candidates = [m for m in self.models if m.can_handle(needs_vision, needs_tools)]
        if not candidates:
            return None

        if self._current:
            cur_rank = _tier_rank(self._current.tier)
            higher = [m for m in candidates if _tier_rank(m.tier) > cur_rank]
            if not higher:
                return None  # already at the top
            candidates = higher

        candidates = self._order(candidates)
        return candidates[0]

    def mark_ok(self) -> None:
        if self._current:
            self._current.mark_ok()

    def mark_failed(self) -> None:
        if self._current:
            self._current.mark_failed()

    @property
    def current(self) -> Optional[ModelSpec]:
        return self._current

    @property
    def fleet(self) -> list[dict]:
        return [
            {
                "name": m.name,
                "tier": m.tier,
                "cost": m.cost,
                "vision": m.vision,
                "tools": m.tools,
                "size_gb": m.size_gb,
                "fits_vram": self._fits_vram(m),
                "failures": m.failures,
            }
            for m in self.models
        ]

    # ── LLM provider interface ─────────────────────────────────────────

    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   **kwargs: Any) -> AsyncIterator[dict]:
        """Route a chat turn to the right model.

        Selects the cheapest capable model, delegates to its underlying
        OpenAICompatLLM.chat(), and escalates to a larger model on failure.
        Yields {"text": ...} chunks and a final {"tool_calls": [...]}.
        """
        needs_vision = any(
            any(p.get("type") == "image" for p in m.get("parts", []))
            for m in messages if isinstance(m, dict)
        ) or bool(kwargs.get("vision"))
        needs_tools = bool(tools)

        model = self.select_for_turn(needs_vision, needs_tools)
        if model is None:
            raise RuntimeError("No capable model available in router")

        self._current = model

        # Try the selected model
        try:
            async for event in model.llm.chat(messages, tools=tools, **kwargs):
                yield event
            model.mark_ok()
            return
        except Exception as exc:
            model.mark_failed()
            # Escalate once to a larger model
            escalated = self.escalate(needs_vision, needs_tools)
            if escalated is not None and escalated is not model:
                self._current = escalated
                try:
                    async for event in escalated.llm.chat(messages, tools=tools, **kwargs):
                        yield event
                    escalated.mark_ok()
                    self._current = escalated
                    return
                except Exception as exc2:
                    escalated.mark_failed()
                    raise exc2
            raise

    async def probe(self, check_vision: bool = True) -> tuple[bool, str]:
        """Probe the cheapest capable model."""
        model = self.select(needs_vision=check_vision, needs_tools=True)
        if model is None:
            return False, "No capable model available"
        try:
            ok, msg = await model.llm.probe(check_vision=check_vision)
            return ok, f"{model.name}: {msg}"
        except Exception as exc:
            return False, f"{model.name}: {exc}"

    @property
    def caps(self) -> dict:
        caps = dict(DEFAULT_CAPS)
        caps["tools"] = True
        caps["tool_format"] = "openai"
        if any(m.vision for m in self.models):
            caps["vision"] = True
        return caps


# ── Provider declaration (for providers.registry) ─────────────────────────────

def _make(cfg: dict) -> LLMRouter:
    return LLMRouter(cfg)


PROVIDER = {
    "id": "llm_router",
    "kind": "llm",
    "label": "Intelligent model router (Ollama multi-model)",
    "hint": "Routes each turn to the cheapest capable Ollama model and "
            "escalates only when needed. Local, no API keys required.",
    "requires": ("httpx",),
    "install": "httpx",
    "catalog": (),
    "needs": (
        Field("models", "Models", kind="choice", choices=(), default="",
              required=False,
              hint="JSON list of model declarations. See providers/llm_router.py "
                   "for the schema."),
    ),
    "caps": {"tools": True, "tool_format": "openai"},
    "factory": _make,
}


def available() -> bool:
    from importlib.util import find_spec
    return find_spec("httpx") is not None
