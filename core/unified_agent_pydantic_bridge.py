"""
core/unified_agent_pydantic_bridge.py — Bridge Pydantic AI with Unified Agent

Enables bidirectional communication between legacy unified agent system
and new Pydantic AI agents for seamless integration.

Gracefully degrades when pydantic_ai is not installed or API key missing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Any

logger = logging.getLogger("jarvis.agent.bridge")


class UnifiedAgentPydanticBridge:
    """Bridge between legacy unified agent and Pydantic AI agents."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._legacy_agent = None
        self._pydantic_integration = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> bool:
        """Initialize both agent systems (async)."""
        if self._initialized:
            return True

        async with getattr(self, "_init_lock", asyncio.Lock()):
            if self._initialized:
                return True

            # Initialize legacy agent
            try:
                from core.unified_agent import UnifiedJarvis
                self._legacy_agent = await asyncio.to_thread(UnifiedJarvis)
                await self._legacy_agent.initialize()
                logger.info("[Bridge] ✓ Legacy agent initialized")
            except Exception:
                logger.exception("[Bridge] Legacy agent init failed")

            # Initialize Pydantic AI integration
            try:
                from core.pydantic_ai_integration import (
                    get_pydantic_integration, PYDANTIC_AVAILABLE,
                )
                if PYDANTIC_AVAILABLE:
                    self._pydantic_integration = await (
                        get_pydantic_integration(self.session_id)
                    )
                    logger.info(
                        "[Bridge] ✓ Pydantic AI integration initialized"
                    )
                else:
                    logger.info(
                        "[Bridge] Pydantic AI not available "
                        "(no API key or package)"
                    )
            except Exception:
                logger.exception("[Bridge] Pydantic AI init failed")

            self._initialized = True
            return True

    async def process_request(
        self,
        user_input: str,
        use_pydantic: bool = True,
        fallback_to_legacy: bool = True,
    ) -> Dict[str, Any]:
        """
        Process request with intelligent routing.

        Args:
            user_input: User request
            use_pydantic: Prefer Pydantic AI agents
            fallback_to_legacy: Fallback to legacy if Pydantic fails
        """
        # Try Pydantic AI first for structured tasks
        if use_pydantic and self._pydantic_integration:
            try:
                result = await (
                    self._pydantic_integration.handle_coordinated_request(
                        user_input
                    )
                )

                if result.get("success"):
                    logger.info(
                        "[Bridge] ✓ Processed with Pydantic AI (session=%s)",
                        self.session_id,
                    )
                    return {
                        "result": result,
                        "structured": True,
                        "backend": "pydantic_ai",
                    }

                if not fallback_to_legacy:
                    return result

            except Exception:
                logger.exception(
                    "[Bridge] Pydantic AI failed, falling back (session=%s)",
                    self.session_id,
                )

        # Fallback to legacy unified agent
        if self._legacy_agent:
            try:
                result = await self._legacy_agent.process(user_input)
                logger.info(
                    "[Bridge] ✓ Processed with legacy agent (session=%s)",
                    self.session_id,
                )
                return {
                    "result": result,
                    "structured": False,
                    "backend": "legacy",
                }
            except Exception:
                logger.exception(
                    "[Bridge] Legacy agent failed (session=%s)",
                    self.session_id,
                )

        return {"error": "Both agent systems failed"}


    async def handle_studio_task(
        self,
        task_description: str,
        auto_visualize: bool = True,
    ) -> Dict[str, Any]:
        """Handle studio modeling task with full integration."""
        try:
            if self._pydantic_integration:
                result = await self._pydantic_integration.handle_studio_request(
                    task_description,
                )

                if auto_visualize and result.get("success"):
                    action = result.get("action", {})
                    model_name = action.get("name")
                    if model_name:
                        from core.visual_display_manager import show_3d_model
                        await asyncio.to_thread(show_3d_model, model_name)

                return result

            return await self.process_request(task_description, use_pydantic=False)

        except Exception:
            logger.exception(
                "[Bridge] Studio task failed (session=%s)", self.session_id
            )
            return {"error": "Studio task failed"}

    async def handle_visual_task(
        self,
        task_description: str,
    ) -> Dict[str, Any]:
        """Handle visual display task."""
        if self._pydantic_integration:
            return await self._pydantic_integration.handle_visual_request(
                task_description,
            )

        return await self.process_request(task_description, use_pydantic=False)

    def get_agent_stats(self) -> Dict[str, Any]:
        """Get statistics about agent usage."""
        return {
            "session_id": self.session_id,
            "legacy_agent_available": self._legacy_agent is not None,
            "pydantic_integration_available": (
                self._pydantic_integration is not None
            ),
            "bridge_active": self._initialized,
        }


# ── Session-keyed singleton manager (thread-safe) ───────────────────────────

_bridge_instances: Dict[str, UnifiedAgentPydanticBridge] = {}
_bridges_lock = asyncio.Lock()


async def get_agent_bridge(session_id: str) -> UnifiedAgentPydanticBridge:
    """Get or create a session-keyed bridge instance."""
    async with _bridges_lock:
        if session_id not in _bridge_instances:
            _bridge_instances[session_id] = UnifiedAgentPydanticBridge(session_id)
            await _bridge_instances[session_id].initialize()
        return _bridge_instances[session_id]


async def clear_agent_bridge(session_id: str) -> None:
    """Clear a session's bridge (retention/deletion support)."""
    async with _bridges_lock:
        _bridge_instances.pop(session_id, None)


# ── Convenience API ─────────────────────────────────────────────────────────

async def process_jarvis_request(
    user_input: str,
    session_id: str = "default",
    prefer_structured: bool = True,
) -> Dict[str, Any]:
    """
    Main entry point for JARVIS request processing.

    Automatically routes to best agent system based on request type
    and availability.
    """
    bridge = await get_agent_bridge(session_id)
    return await bridge.process_request(
        user_input, use_pydantic=prefer_structured
    )


__all__ = [
    'UnifiedAgentPydanticBridge',
    'get_agent_bridge',
    'clear_agent_bridge',
    'process_jarvis_request',
]
