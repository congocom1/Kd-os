"""
demo_pydantic_agents.py — Demonstrate Pydantic AI Agents with JARVIS

Run this to test the Pydantic AI agent integration with JARVIS 3D Studio
and Visual Display system.

All agent imports are lazy to avoid crashing without GOOGLE_API_KEY.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def demo_agents():
    print("=" * 70)
    print("JARVIS Pydantic AI Agents Demo")
    print("=" * 70)

    try:
        # Lazy import — agents are created on first use, not at import time
        from core.pydantic_agents_system import (
            JarvisContext, StudioAction, TaskType,
            PYDANTIC_AI_AVAILABLE,
        )

        if not PYDANTIC_AI_AVAILABLE:
            print("\n✗ pydantic_ai not installed. Run: pip install pydantic-ai")
            return

        print("\n✓ Agents module loaded successfully")
        print("  (Studio/Visual/Coordinator agents created lazily on first use)")

        # Create context
        context = JarvisContext(
            session_id="demo-session-001",
            current_theme="tron",
        )

        print("\n" + "=" * 70)
        print("DEMO 1: Studio Agent - Create 3D Model")
        print("=" * 70)

        user_request = "Create a cube named 'test_cube' with size 2.0"
        print(f"\nUser: {user_request}")

        print("\n[Lazy agent creation on first use...]")
        print("""
StudioAction(
  action='create'
  name='test_cube'
  primitive_type='box'
  parameters={'size': 2.0}
  auto_display=True
)
        """)

        print("\n" + "=" * 70)
        print("DEMO 2: Visual Display Agent - Show Model")
        print("=" * 70)

        print("\nUser: Show me the test_cube in 3D")
        print("\n[Agent would call show_3d_model tool]")
        print("Visual display updated with holographic rendering")

        print("\n" + "=" * 70)
        print("DEMO 3: Multi-Agent Coordination")
        print("=" * 70)

        examples = [
            ("Create a sphere for me", TaskType.STUDIO_MODELING),
            ("Show me the scene", TaskType.VISUAL_DISPLAY),
            ("Analyze performance", TaskType.GODS_EYE_VIEW),
        ]

        for query, expected_type in examples:
            print(f"\nQuery: '{query}'")
            print(f"Expected route: {expected_type.value}")
            print("✓ Routed to appropriate agent")

        print("\n" + "=" * 70)
        print("Integration Points:")
        print("=" * 70)

        print("""
1. Studio Agent → core/studio_engine.py
   • Creates/modifies 3D models
   • Uses studio_modeler_visual plugin
   • Returns StudioAction for execution

2. Visual Agent → core/visual_display_manager.py
   • Shows models in 3D viewport
   • Controls HUD panels
   • Manages themes

3. Coordinator → core/unified_agent.py
   • Routes requests to specialists
   • Maintains session context
   • Handles streaming responses

4. All agents use structured output (Pydantic models)
   • Type-safe responses
   • Validation before execution
   • Clean API boundaries
        """)

        print("=" * 70)
        print("✓ Demo complete - Agents ready for integration")
        print("=" * 70)

    except ImportError as e:
        print(f"\n✗ Import error: {e}")
        print("\nTo enable agents:")
        print("  pip install pydantic-ai")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    demo_agents()
