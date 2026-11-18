"""
core/pydantic_agents_system.py — Pydantic AI Agents for JARVIS

Production-grade AI agents using Pydantic AI framework,
integrated with JARVIS unified agent, 3D Studio, and Visual Display.

All agent creation is LAZY (deferred until first use) so the module
imports cleanly without an API key. Agents are created on-demand via
factory functions.
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("jarvis.pydantic_agents")

# ── Module-level flags ──────────────────────────────────────────────────────
try:
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent
    PYDANTIC_AI_AVAILABLE = True
except ImportError:
    PYDANTIC_AI_AVAILABLE = False
    Agent = None  # type: ignore
    BaseModel = None  # type: ignore
    Field = None  # type: ignore


# ── Structured Output Models ────────────────────────────────────────────────

class TaskType(str, Enum):
    """Types of tasks JARVIS can handle."""
    STUDIO_MODELING = "studio_modeling"
    VISUAL_DISPLAY = "visual_display"
    GODS_EYE_VIEW = "gods_eye_view"
    KRONOS_ANALYSIS = "kronos_analysis"
    GENERAL_CHAT = "general_chat"
    CODE_GENERATION = "code_generation"
    SYSTEM_CONTROL = "system_control"


class StudioAction(BaseModel):
    """3D Studio action with structured parameters."""
    action: str = Field(
        description="Studio action: create, transform, boolean, etc."
    )
    primitive_type: Optional[str] = Field(
        None, description="Primitive type for create"
    )
    name: str = Field(description="Object name")
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Action parameters"
    )
    auto_display: bool = Field(
        True, description="Auto-display in visual panel"
    )


class VisualDisplayRequest(BaseModel):
    """Request to display visual content."""
    display_type: str = Field(description="Type: 3d_model, image, scene")
    content_id: str = Field(description="Model name or image path")
    title: Optional[str] = Field(None, description="Display title")
    theme: Optional[str] = Field("tron", description="Visual theme")


class AgentResponse(BaseModel):
    """Structured agent response."""
    task_type: TaskType
    confidence: float = Field(ge=0.0, le=1.0)
    message: str
    structured_data: Optional[Dict[str, Any]] = None
    requires_visual: bool = False
    visual_request: Optional[VisualDisplayRequest] = None
    follow_up_questions: List[str] = Field(default_factory=list)


# ── Dependency Context ──────────────────────────────────────────────────────

@dataclass
class JarvisContext:
    """Context passed to Pydantic AI agents."""
    session_id: str
    user_id: Optional[str] = None
    studio_scene: Optional[Any] = None
    visual_display_manager: Optional[Any] = None
    unified_agent: Optional[Any] = None
    current_theme: str = "tron"
    task_mode: str = "idle"


# ── Lazy Agent Factory ──────────────────────────────────────────────────────

# Module-level placeholders (set on first use)
_studio_agent: Optional[Agent] = None
_visual_agent: Optional[Agent] = None
_coordinator_agent: Optional[Agent] = None

# Model selection: respect user's Gemini key by default
PYDANTIC_MODEL = os.environ.get(
    "JARVIS_PYDANTIC_MODEL", "google:gemini-2.0-flash"
)


def _ensure_studio_agent():
    """Create the Studio Agent lazily on first use."""
    global _studio_agent
    if _studio_agent is not None:
        return _studio_agent
    if not PYDANTIC_AI_AVAILABLE:
        raise RuntimeError(
            "pydantic_ai not installed. Run: pip install pydantic-ai"
        )
    _studio_agent = Agent(
        model=PYDANTIC_MODEL,
        deps_type=JarvisContext,
        instructions=(
            "You are JARVIS's 3D Studio AI assistant. Help users create and "
            "manipulate 3D models. Return StudioAction with proper parameters. "
            "Always suggest visual display after creation."
        ),
        output_type=StudioAction
    )
    return _studio_agent


def _ensure_visual_agent():
    """Create the Visual Display Agent lazily on first use."""
    global _visual_agent
    if _visual_agent is not None:
        return _visual_agent
    if not PYDANTIC_AI_AVAILABLE:
        raise RuntimeError(
            "pydantic_ai not installed. Run: pip install pydantic-ai"
        )
    _visual_agent = Agent(
        model=PYDANTIC_MODEL,
        deps_type=JarvisContext,
        instructions=(
            "You are JARVIS Visual Display AI. Manage 3D model visualization. "
            "Coordinate with visual_display_manager for rendering."
        ),
        output_type=AgentResponse,
    )
    return _visual_agent


def _ensure_coordinator_agent():
    """Create the Coordinator Agent lazily on first use."""
    global _coordinator_agent
    if _coordinator_agent is not None:
        return _coordinator_agent
    if not PYDANTIC_AI_AVAILABLE:
        raise RuntimeError(
            "pydantic_ai not installed. Run: pip install pydantic-ai"
        )
    _coordinator_agent = Agent(
        model=PYDANTIC_MODEL,
        deps_type=JarvisContext,
        instructions=(
            "You are JARVIS Agent Coordinator. Route requests to "
            "appropriate agents: - studio_modeling → studio_agent "
            "- visual display → visual_agent - general → respond directly"
        ),
        output_type=AgentResponse,
    )
    return _coordinator_agent


# Backward-compatible module-level references (resolve on first use)
def __getattr__(name: str):
    """Lazy attribute resolution for module-level agent names."""
    if name == "studio_agent":
        return _ensure_studio_agent()
    if name == "visual_agent":
        return _ensure_visual_agent()
    if name == "coordinator_agent":
        return _ensure_coordinator_agent()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'StudioAction', 'AgentResponse', 'TaskType', 'JarvisContext',
    'VisualDisplayRequest', 'PYDANTIC_AI_AVAILABLE', 'PYDANTIC_MODEL',
]

logger.info("[Pydantic Agents] Module loaded (agents created lazily)")
