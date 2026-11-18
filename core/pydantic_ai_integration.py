"""
core/pydantic_ai_integration.py — Integration Layer for Pydantic AI Agents

Integrates Pydantic AI agents with existing JARVIS unified system,
3D Studio, and Visual Display for seamless operation.

Gracefully degrades when pydantic_ai is not installed or API key missing.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional, Dict, Any

logger = logging.getLogger("jarvis.pydantic.integration")

# ── Conditional imports ─────────────────────────────────────────────────────
try:
    from core.pydantic_agents_system import (
        JarvisContext, StudioAction, AgentResponse,
        PYDANTIC_AI_AVAILABLE,
    )
    PYDANTIC_AVAILABLE = PYDANTIC_AI_AVAILABLE
except ImportError:
    PYDANTIC_AVAILABLE = False
    JarvisContext = None  # type: ignore
    StudioAction = None  # type: ignore
    AgentResponse = None  # type: ignore
    logger.warning("[Pydantic Integration] Agents not available")

# ── Constants ───────────────────────────────────────────────────────────────
_ALLOWED_PRIMITIVES = {"box", "sphere", "cube", "plane", "cylinder"}
_NAME_RE = re.compile(r"^[a-zA-Z0-9_]{1,64}$")
_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9_./-]{1,128}$")
_LLM_TIMEOUT = 30.0  # seconds


def _validate_name(name: str) -> str:
    """Validate a model/object name — alphanumeric + underscore only."""
    if not _NAME_RE.match(name or ""):
        raise ValueError(f"Invalid name: {name!r}")
    return name


def _validate_model_name(name: str) -> str:
    """Validate a model name for display — safe identifier only."""
    if not _MODEL_NAME_RE.match(name or ""):
        raise ValueError(f"Invalid model name: {name!r}")
    return name


def _validate_primitive(primitive_type: Optional[str]) -> Optional[str]:
    """Validate primitive type against allowlist."""
    if primitive_type is None:
        return None
    if primitive_type not in _ALLOWED_PRIMITIVES:
        raise ValueError(f"Invalid primitive type: {primitive_type!r}")
    return primitive_type


def _get_studio_agent():
    """Lazy import of studio_agent."""
    from core.pydantic_agents_system import studio_agent
    return studio_agent


def _get_visual_agent():
    """Lazy import of visual_agent."""
    from core.pydantic_agents_system import visual_agent
    return visual_agent


class PydanticAIIntegration:
    """Integration layer for Pydantic AI with JARVIS core systems."""

    def __init__(
        self,
        session_id: str,
        studio_engine: Optional[Any] = None,
        visual_manager: Optional[Any] = None,
        unified_agent: Optional[Any] = None,
    ):
        self.session_id = session_id
        self.context = (
            JarvisContext(session_id=session_id) if JarvisContext else None
        )
        self._studio_engine = studio_engine
        self._visual_manager = visual_manager
        self._unified_agent = unified_agent
        self._initialized = False
        self._legacy_ready = asyncio.Event()

    async def initialize(self) -> bool:
        """Initialize connections to JARVIS systems (async,
        awaits legacy init).
        """
        if self._initialized:
            return True

        try:
            from core.studio_engine import Scene
            from core.visual_display_manager import VisualDisplayManager
            from core.unified_agent import UnifiedJarvis

            if self._studio_engine is None:
                self._studio_engine = await asyncio.to_thread(Scene)
            if self._visual_manager is None:
                self._visual_manager = await asyncio.to_thread(
                    VisualDisplayManager
                )
            if self._unified_agent is None:
                self._unified_agent = await asyncio.to_thread(UnifiedJarvis)
                await self._unified_agent.initialize()

            if self.context:
                self.context.studio_scene = self._studio_engine
                self.context.visual_display_manager = self._visual_manager
                self.context.unified_agent = self._unified_agent

            self._initialized = True
            self._legacy_ready.set()
            logger.info("[Pydantic Integration] ✓ Systems initialized")
            return True
        except Exception:
            logger.exception("[Pydantic Integration] Init failed")
            self._legacy_ready.set()  # unblock waiters even on failure
            return False

    async def _ensure_legacy_ready(self) -> bool:
        """Wait for legacy agent to be ready (with timeout)."""
        try:
            await asyncio.wait_for(self._legacy_ready.wait(), timeout=10.0)
            return self._initialized
        except asyncio.TimeoutError:
            logger.warning("[Pydantic Integration] Legacy init timed out")
            return False

    async def handle_studio_request(self, user_input: str) -> Dict[str, Any]:
        """Handle 3D studio requests via Pydantic AI agent."""
        if not PYDANTIC_AVAILABLE:
            return {"error": "Pydantic AI not available"}

        if not await self._ensure_legacy_ready():
            return {"error": "Legacy agent not ready"}

        try:
            studio_agent = _get_studio_agent()
            result = await asyncio.wait_for(
                studio_agent.run(user_input, deps=self.context),
                timeout=_LLM_TIMEOUT,
            )

            action = result.output
            logger.info(
                "[Studio Agent] Action: %s - %s (session=%s)",
                action.action, action.name, self.session_id,
            )

            # Validate LLM output before execution
            _validate_name(action.name)
            _validate_primitive(action.primitive_type)

            # Execute the action
            success = await self._execute_studio_action(action)

            # Auto-display if requested
            if success and action.auto_display:
                _validate_model_name(action.name)
                await self._display_model(action.name)

            return {
                "success": success,
                "action": action.model_dump(),
                "message": (
                    f"Created {action.name} with {action.primitive_type}"
                ),
            }

        except asyncio.TimeoutError:
            logger.error(
                "[Studio Agent] LLM call timed out (session=%s)", self.session_id
            )
            return {"error": "LLM request timed out"}
        except ValueError as e:
            logger.error(
                "[Studio Agent] Validation error: %s", e
            )
            return {"error": f"Invalid agent output: {e}"}
        except Exception:
            logger.exception(
                "[Studio Agent] Error (session=%s)", self.session_id
            )
            return {"error": "Studio request failed"}

    async def handle_visual_request(self, user_input: str) -> Dict[str, Any]:
        """Handle visual display requests."""
        if not PYDANTIC_AVAILABLE:
            return {"error": "Pydantic AI not available"}

        try:
            visual_agent = _get_visual_agent()
            result = await asyncio.wait_for(
                visual_agent.run(user_input, deps=self.context),
                timeout=_LLM_TIMEOUT,
            )

            response = result.output
            logger.info(
                "[Visual Agent] %s (session=%s)",
                response.message, self.session_id,
            )

            return {
                "success": True,
                "response": response.model_dump(),
            }

        except asyncio.TimeoutError:
            logger.error(
                "[Visual Agent] LLM call timed out (session=%s)", self.session_id
            )
            return {"error": "LLM request timed out"}
        except Exception:
            logger.exception(
                "[Visual Agent] Error (session=%s)", self.session_id
            )
            return {"error": "Visual request failed"}

    async def handle_coordinated_request(
        self, user_input: str
    ) -> Dict[str, Any]:
        """Route request directly to the appropriate specialist agent.

        Routes studio_modeling → studio agent, visual_display → visual agent,
        general → visual agent (as fallback). No coordinator pre-classification
        — avoids double LLM invocation.
        """
        if not PYDANTIC_AVAILABLE:
            return {"error": "Pydantic AI not available"}

        text_lower = (user_input or "").lower()

        # Direct routing keywords — single LLM call, no pre-classification
        studio_keywords = {
            "create", "cube", "sphere", "box", "model", "3d",
            "studio", "build", "make",
        }
        visual_keywords = {
            "show", "display", "visual", "view", "render",
            "scene", "hide", "clear",
        }

        if any(k in text_lower for k in studio_keywords):
            return await self.handle_studio_request(user_input)
        if any(k in text_lower for k in visual_keywords):
            return await self.handle_visual_request(user_input)

        # Default: treat as visual/general
        return await self.handle_visual_request(user_input)

    async def _execute_studio_action(self, action: StudioAction) -> bool:
        """Execute studio action on 3D engine."""
        try:
            if self._studio_engine is None:
                return False

            if action.action == "create":
                primitive = _validate_primitive(action.primitive_type)
                if primitive == "box":
                    from plugins.studio_modeler_visual import box
                    await asyncio.to_thread(
                        box, action.name, action.parameters.get("size", 1.0)
                    )
                elif primitive == "sphere":
                    from plugins.studio_modeler_visual import sphere
                    await asyncio.to_thread(
                        sphere,
                        action.name,
                        action.parameters.get("radius", 1.0),
                    )
                # Add more primitives...

            elif action.action == "transform":
                # Handle transforms
                pass

            logger.info(
                "[Studio] Executed %s on %s (session=%s)",
                action.action, action.name, self.session_id,
            )
            return True

        except Exception:
            logger.exception(
                "[Studio] Execution failed (session=%s)", self.session_id
            )
            return False

    async def _display_model(self, model_name: str) -> bool:
        """Display model in visual viewport (offloaded from event loop)."""
        try:
            if self._visual_manager is None:
                return False

            from core.visual_display_manager import show_3d_model
            return await asyncio.to_thread(show_3d_model, model_name)

        except Exception:
            logger.exception(
                "[Visual] Display failed (session=%s)", self.session_id
            )
            return False


# ── Singleton instance (session-keyed, thread-safe) ─────────────────────────

_integrations: Dict[str, PydanticAIIntegration] = {}
_integrations_lock = asyncio.Lock()


async def get_pydantic_integration(
    session_id: str,
    studio_engine: Optional[Any] = None,
    visual_manager: Optional[Any] = None,
    unified_agent: Optional[Any] = None,
) -> PydanticAIIntegration:
    """Get or create a session-keyed integration instance."""
    async with _integrations_lock:
        if session_id not in _integrations:
            _integrations[session_id] = PydanticAIIntegration(
                session_id, studio_engine, visual_manager, unified_agent,
            )
            await _integrations[session_id].initialize()
        return _integrations[session_id]


async def clear_pydantic_integration(session_id: str) -> None:
    """Clear a session's integration (retention/deletion support)."""
    async with _integrations_lock:
        _integrations.pop(session_id, None)


# ── Convenience functions ───────────────────────────────────────────────────

async def process_with_agents(
    user_input: str, session_id: str
) -> Dict[str, Any]:
    """Process user input through Pydantic AI agents."""
    integration = await get_pydantic_integration(session_id)
    return await integration.handle_coordinated_request(user_input)


__all__ = [
    'PydanticAIIntegration',
    'get_pydantic_integration',
    'clear_pydantic_integration',
    'process_with_agents',
    'PYDANTIC_AVAILABLE',
]
