"""
core/unified_agent.py — JARVIS Unified Agent System (Single Entry Point)

All JARVIS capabilities accessed through ONE interface:
  • Wake word ("Hey Jarvis") + speech recognition + text-to-speech
  • 44 Actions (computer control, screen watch, social media, 3D studio,
    cyber tools, clipboard, currency, screen watch, etc.)
  • 11 Plugins (calculator, current_time, personal_notes, system_info,
    unit_converter, vision_learner, whatsapp_connector,
    google_connector, sqlite_commands, studio_modeler)
  • 8 Skills from 2 repositories (build-site, morning-brief-starter,
    web-researcher, youtube-analyzer, bambulab-printer, fusion360,
    globe-view, ma-preset)
  • Tiny ML engine for local learning
  • Task-based cinematic HUD (8 color modes)
  • Code evolution (safe human-gated code modification)
  • SQLite command database
  • TUI (terminal UI) fallback

ARCHITECTURE:
    Single agent class that wraps all capabilities. No multiple windows,
    no multiple processes — everything flows through one interface.

USAGE:
    jarvis = UnifiedJarvis()
    await jarvis.initialize()
    response = await jarvis.process("Hey Jarvis, take a screenshot")
    print(response)
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [JARVIS] %(levelname)s: %(message)s",
)
logger = logging.getLogger("jarvis.unified")

# Add project root to path
from core.paths import get_base_dir as _get_base_dir
BASE_DIR = _get_base_dir()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ── Unified Interface ────────────────────────────────────────────────
# All actions, plugins, and providers are discovered and run through
# core.interface. This is the single point of entry for all capabilities.
from core.paths import get_base_dir as _get_base_dir
from core.interface import (
    discover_all,
    run_tool,
)

# ── Capability Detection ──────────────────────────────────────────────

def _check_module(module_name: str) -> bool:
    """Check if a Python module is available without importing it."""
    from importlib.util import find_spec
    return find_spec(module_name) is not None


CAPABILITIES = {
    "wake_word": _check_module("core.wake_word"),
    "tts": _check_module("providers.tts_system") or _check_module("providers.tts_piper"),
    "stt": _check_module("providers.stt_whisper"),
    "llm": _check_module("providers.llm_openai") or _check_module("providers.llm_router"),
    "computer_control": True,  # Always available (stdlib)
    "screen_watch": _check_module("mss"),
    "computer_vision": _check_module("cv2"),
    "tiny_ml": True,  # Always available (numpy)
    "code_evolution": True,  # Always available
    "social_media": True,  # Always available
    "screen_capture": _check_module("mss"),
    "ocr": _check_module("cv2") and _check_module("pytesseract"),
    "database": True,  # Always available (sqlite3)
    "http": _check_module("requests"),
    "yaml": _check_module("yaml"),
}

_active_count = sum(1 for v in CAPABILITIES.values() if v)
total_count = len(CAPABILITIES)


# ── UnifiedJarvis ──────────────────────────────────────────────────

class UnifiedJarvis:
    """JARVIS Unified Agent — All capabilities in ONE agent.

    This is the single entry point for all JARVIS functionality.
    No multiple windows, no multiple processes — everything flows here.
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.name = "JARVIS"
        self.version = "Mark-LVI Unified"
        self.initialized = False
        self.awake = False
        self.muted = False

        # Capability state
        self.caps = CAPABILITIES.copy()

        # Component instances (lazy-loaded)
        self._wake_detector = None
        self._tts_engine = None
        self._stt_engine = None
        self._llm_provider = None
        self._tiny_ml = None
        self._code_evolution = None
        self._scene = None  # 3D studio scene
        self._screen_watcher = None

        # Action/plugin registry (unified via core.interface)
        self._actions: dict = {}  # name -> PluginRecord
        self._plugins: dict = {}  # name -> PluginRecord

        # Task mode for HUD
        self.task_mode = "idle"
        self._task_modes = {
            "idle": "cyan",
            "listening": "green",
            "speaking": "amber",
            "thinking": "gold",
            "social": "gold",
            "cinema": "violet",
            "studio": "green",
            "security": "red",
        }

        # Statistics
        self.stats = {
            "commands_processed": 0,
            "wake_detections": 0,
            "actions_executed": 0,
            "start_time": time.time(),
        }

    # ── Initialization ──────────────────────────────────────────────

    async def initialize(self) -> dict:
        """Initialize all JARVIS subsystems."""
        logger.info("=" * 60)
        logger.info("JARVIS Unified Agent Initializing...")
        logger.info(f"  Version: {self.version}")
        logger.info(f"  Capabilities: {_active_count}/{total_count} modules available")
        logger.info("=" * 60)

        # ── Initialize results dict (tracks per-capability init status) ──
        results: dict = {}

        # ── Load all actions and plugins via unified interface ──────────
        self._actions = discover_all()
        # discover_all() merges actions + plugins + providers keyed by name;
        # keep the merged dict for lookup, and index plugins separately so
        # run_plugin() can actually find them.
        self._plugins = {n: r for n, r in self._actions.items() if r.kind == "plugin"}
        logger.info(f"  Actions: {len(self._actions)} loaded")
        logger.info(f"  Plugins: {len(self._plugins)} loaded")

        # ── Initialize individual systems ─────────────────────────────

        # Wake word
        if self.caps["wake_word"]:
            try:
                from core.wake_word import is_installed, is_ready
                self.caps["wake_word"] = is_installed() and is_ready()
                logger.info(f"  Wake word: {'READY' if self.caps['wake_word'] else 'NOT READY'}")
            except Exception as e:
                self.caps["wake_word"] = False
                logger.warning(f"  Wake word: NOT AVAILABLE ({e})")

        # TTS
        if self.caps["tts"]:
            try:
                from providers.tts_system import SystemTTS
                self._tts_engine = SystemTTS({})
                logger.info("  TTS: READY (system)")
            except Exception as e:
                self.caps["tts"] = False
                logger.warning(f"  TTS: NOT AVAILABLE ({e})")

        # STT
        if self.caps["stt"]:
            try:
                from providers.stt_whisper import WhisperSTT
                self._stt_engine = WhisperSTT({})
                logger.info("  STT: READY (whisper)")
            except Exception as e:
                self.caps["stt"] = False
                logger.warning(f"  STT: NOT AVAILABLE ({e})")

        # LLM
        if self.caps["llm"]:
            try:
                from providers.llm_router import LLMRouter
                self._llm_provider = LLMRouter({})
                logger.info("  LLM: READY (intelligent router)")
            except Exception as e:
                self.caps["llm"] = False
                logger.warning(f"  LLM: NOT AVAILABLE ({e})")

        # Tiny ML Engine
        if self.caps["tiny_ml"]:
            try:
                from core.tiny_ml import TinyML, TinyMLConfig
                self._tiny_ml = TinyML(TinyMLConfig((8, 2), learning_rate=0.1, seed=42))
                logger.info("  Tiny ML: READY")
            except Exception as e:
                self.caps["tiny_ml"] = False
                logger.warning(f"  Tiny ML: NOT AVAILABLE ({e})")

        # Code Evolution
        if self.caps["code_evolution"]:
            try:
                from core.code_evolution import propose, review, apply, list_proposals, delete
                self._code_evolution = {
                    "propose": propose,
                    "review": review,
                    "apply": apply,
                    "list": list_proposals,
                    "delete": delete,
                }
                results["code_evolution"] = True
                logger.info("  Code Evolution: READY")
            except Exception as e:
                self.caps["code_evolution"] = False
                results["code_evolution"] = False
                logger.warning(f"  Code Evolution: NOT AVAILABLE ({e})")

        # 3D Studio Scene
        try:
            from core.studio_engine import Scene, box, sphere
            self._scene = Scene()
            self._scene.add("cube", box((2, 2, 2)))
            self._scene.add("sphere", sphere(0.8, 16, 8))
            results["studio"] = True
            logger.info("  3D Studio: READY (cube + sphere primed)")
        except Exception as e:
            self._scene = None
            results["studio"] = False
            logger.warning(f"  3D Studio: NOT AVAILABLE ({e})")

        # Screen Watcher
        if self.caps["screen_capture"]:
            try:
                from actions.screen_watch import run as screen_watch_run
                self._screen_watcher = screen_watch_run
                results["screen_watch"] = True
                logger.info("  Screen Watch: READY")
            except Exception as e:
                self.caps["screen_capture"] = False
                results["screen_watch"] = False
                logger.warning(f"  Screen Watch: NOT AVAILABLE ({e})")

        self.initialized = True

        logger.info("=" * 60)
        logger.info(f"JARVIS Initialized: {_active_count}/{total_count} capabilities")
        logger.info(f"  Actions: {results.get('actions', 0)}")
        logger.info(f"  Plugins: {results.get('plugins', 0)}")
        logger.info("=" * 60)

        return {
            "initialized": True,
            "name": self.name,
            "version": self.version,
            "capabilities": self.caps,
            "actions_count": results.get("actions", 0),
            "plugins_count": results.get("plugins", 0),
            "results": results,
        }

    # ── Capability Query ──────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return full system status."""
        uptime = time.time() - self.stats["start_time"]
        return {
            "name": self.name,
            "version": self.version,
            "initialized": self.initialized,
            "awake": self.awake,
            "muted": self.muted,
            "task_mode": self.task_mode,
            "capabilities": self.caps,
            "stats": {
                **self.stats,
                "uptime_seconds": round(uptime, 2),
            },
        }

    def set_task_mode(self, mode: str) -> str:
        """Change HUD task mode (cinema, social, studio, security, etc.)."""
        mode = (mode or "idle").strip().lower()
        valid = {
            "idle", "listening", "speaking", "thinking",
            "social", "cinema", "studio", "security",
        }
        if mode not in valid:
            mode = "idle"
        self.task_mode = mode
        return f"HUD mode: {mode}"

    def speak(self, text: str) -> str:
        """Speak text through TTS if available."""
        if self.muted:
            return "[MUTED]"
        if self._tts_engine:
            try:
                if hasattr(self._tts_engine, "speak"):
                    self._tts_engine.speak(text)
                elif hasattr(self._tts_engine, "say"):
                    self._tts_engine.say(text)
                return f"[SPOKEN] {text}"
            except Exception as e:
                return f"[TTS ERROR] {e}"
        return f"[TEXT] {text}"

    def listen(self) -> str | None:
        """Listen for speech via STT if available."""
        if self._stt_engine:
            try:
                if hasattr(self._stt_engine, "listen"):
                    return self._stt_engine.listen()
            except Exception as e:
                logger.warning(f"STT error: {e}")
        return None

    # ── Action Execution ──────────────────────────────────────────────

    async def run_action(self, name: str, parameters: dict | None = None) -> str:
        """Execute any registered action by name."""
        if name not in self._actions:
            return f"Unknown action: {name}"

        rec = self._actions[name]
        parameters = parameters or {}

        # Map task modes for HUD
        task_map = {
            "social_media": "social",
            "studio_modeler": "studio",
            "screen_watch": "cinema",
            "cyber_tools": "security",
            "vision_learner": "cinema",
            "screen_process": "cinema",
            "gesture_control": "cinema",
            "people_recognition": "cinema",
            "tui": "studio",
            "code_evolve": "studio",
        }
        _task = task_map.get(name, "idle")
        self.set_task_mode(_task)

        try:
            handler = rec.handler
            result = handler(parameters)
            self.stats["actions_executed"] += 1
            return result or "Done."
        except Exception as exc:
            return f"Action '{name}' failed: {exc}"

    async def run_plugin(self, name: str, parameters: dict | None = None) -> str:
        """Execute any registered plugin by name."""
        if name not in self._plugins:
            return f"Unknown plugin: {name}"

        rec = self._plugins[name]
        parameters = parameters or {}

        try:
            result = await run_tool(rec, parameters)
            self.stats["actions_executed"] += 1
            return result or "Done."
        except Exception as exc:
            return f"Plugin '{name}' failed: {exc}"

    # ── High-Level Commands ──────────────────────────────────────────

    async def process(self, text: str) -> str:
        """Process a natural language command through JARVIS."""
        self.stats["commands_processed"] += 1
        text = (text or "").strip()
        if not text:
            return "I didn't catch that. Could you repeat?"

        text_lower = text.lower()

        # Wake word detection
        if not self.awake:
            wake_phrases = ["hey jarvis", "jarvis", "wake up"]
            if any(wp in text_lower for wp in wake_phrases):
                self.awake = True
                self.stats["wake_detections"] += 1
                self.set_task_mode("listening")
                return self.speak("Yes, sir?")
            return "I'm asleep. Say 'Hey Jarvis' to wake me."

        # Mute check
        if self.muted and text_lower not in ("unmute", "unmute jarvis"):
            return "[MUTED] Say 'unmute' to enable audio."

        # System commands
        if text_lower in ("mute", "mute jarvis"):
            self.muted = True
            return "[MUTED]"
        if text_lower in ("unmute", "unmute jarvis"):
            self.muted = False
            return "[UNMUTED]"
        if text_lower in ("sleep", "go to sleep"):
            self.awake = False
            self.set_task_mode("idle")
            return "Going to sleep. Say 'Hey Jarvis' to wake me."
        if text_lower in ("status", "system status"):
            return self._format_status()
        if text_lower in ("help", "help me"):
            return self._help_text()
        if text_lower in ("clear", "clear screen"):
            return "[SCREEN CLEARED]"

        # Try action first
        result = await self._try_action(text_lower)
        if result:
            return result

        # Try plugin
        result = await self._try_plugin(text_lower)
        if result:
            return result

        # Fallback: speak through LLM if available
        if self._llm_provider:
            try:
                response = await self._llm_provider.chat(
                    [{"role": "user", "parts": [{"text": text}]}]
                )
                return str(response)
            except Exception as e:
                return f"I'm not sure how to help with that: {e}"

        return f"I heard: {text}. I'm not sure what to do with that yet."

    async def _try_action(self, text: str) -> str | None:
        """Try to match text to an action."""
        # Direct action name match
        if text in self._actions:
            return await self.run_action(text, {})

        # Keyword-based action mapping
        _action_map = {
            "open": "open_app",
            "launch": "open_app",
            "start": "open_app",
            "screenshot": "screen_capture",
            "capture screen": "screen_capture",
            "watch screen": "screen_watch_start",
            "stop watching": "screen_watch_stop",
            "clipboard": "screen_capture",
            "copy": "screen_capture",
            "paste": "clipboard",
            "password": "password_gen",
            "generate password": "password_gen",
            "currency": "currency",
            "convert": "currency",
            "social": "social_media",
            "post": "social_media",
            "3d": "studio_modeler",
            "model": "studio_modeler",
            "boolean": "studio_modeler",
            "subdivide": "studio_modeler",
            "mirror": "studio_modeler",
            "screen": "screen_watch",
            "watch": "screen_watch",
            "skills": "skills",
            "tui": "tui",
            "knowledge base": "knowledge_rag",
            "ingest": "knowledge_rag",
            "analyze data": "data_analyst",
            "data analysis": "data_analyst",
            "spreadsheet": "data_analyst",
            "team review": "team_code_safety",
            "code review service": "team_code_safety",
        }

        for keyword, action_name in _action_map.items():
            if keyword in text:
                return await self.run_action(action_name, {})

        # Skill-domain phrases activate the matching knowledge skill.
        _skill_phrases = {
            "dependency doctor": "dependency-doctor",
            "dependency check": "dependency-doctor",
            "first reader": "first-reader",
            "scope creep": "scope-creep-detector",
            "commit archaeologist": "commit-archaeologist",
            "project graveyard": "project-graveyard",
        }
        for phrase, skill_name in _skill_phrases.items():
            if phrase in text:
                return await self.run_action(
                    "skills", {"action": "activate", "name": skill_name})

        if "knowledge" in text and any(
                w in text for w in ("domain", "domains", "list", "what")):
            domains = ["skills (say 'list skills')", "globe (geospatial)",
                       "kronos (finance)", "knowledge_rag (your documents)",
                       "data_analyst (spreadsheets)"]
            return "Sir, my knowledge domains: " + ", ".join(domains) + "."

        return None

    async def _try_plugin(self, text: str) -> str | None:
        """Try to match text to a plugin."""
        if not self._plugins:
            return None

        _plugin_map = {
            "social media": "social_media",
            "studio": "studio_modeler",
            "3d studio": "studio_modeler",
            "vision": "vision_learner",
            "camera": "vision_learner",
            "system": "system_info",
            "calculator": "calculator",
            "unit converter": "unit_converter",
            "whatsapp": "whatsapp_connector",
            "google": "google_connector",
            "gmail": "google_connector",
            "calendar": "google_connector",
            "drive": "google_connector",
            "sqlite": "sqlite_commands",
            "database": "sqlite_commands",
        }

        for keyword, plugin_name in _plugin_map.items():
            if keyword in text:
                return await self.run_plugin(plugin_name, {})

        return None

    # ── Helpers ─────────────────────────────────────────────────────

    def _format_status(self) -> str:
        caps = self.caps
        return (
            f"JARVIS Status Report\n"
            f"  Version: {self.version}\n"
            f"  State: {'Awake' if self.awake else 'Asleep'}\n"
            f"  Muted: {self.muted}\n"
            f"  Task Mode: {self.task_mode}\n"
            f"  Capabilities: {sum(1 for v in caps.values() if v)}/{len(caps)}\n"
            f"  Commands Processed: {self.stats['commands_processed']}\n"
            f"  Actions Executed: {self.stats['actions_executed']}\n"
            f"  Wake Detections: {self.stats['wake_detections']}\n"
            f"  Uptime: {time.time() - self.stats['start_time']:.1f}s"
        )

    def _help_text(self) -> str:
        return (
            "JARVIS Commands:\n"
            "  Wake: 'Hey Jarvis'\n"
            "  Sleep: 'sleep'\n"
            "  Mute/Unmute: 'mute' / 'unmute'\n"
            "  Status: 'status'\n"
            "  Help: 'help'\n"
            "\nActions:\n"
            "  'open <app>' — Open an application\n"
            "  'screenshot' / 'capture screen' — Take a screenshot\n"
            "  'watch screen' / 'stop watching' — Continuous screen watch\n"
            "  'copy' / 'paste' — Clipboard operations\n"
            "  'password' / 'generate password' — Generate a password\n"
            "  'convert' / 'currency' — Currency conversion\n"
            "  'post' / 'social media' — Social media actions\n"
            "  '3d' / 'studio' / 'model' — 3D studio modeling\n"
            "  'boolean' / 'subdivide' / 'mirror' — 3D modeling ops\n"
            "  'create' / 'transform' / 'mirror' / 'export' / 'import' — 3D model ops\n"
            "  'skills' — List available skills\n"
            "  'tui' — Terminal UI\n"
            "\nReview:\n"
            "  'review' / 'review list' — Review code/documentation\n"
            "\nSay 'Hey Jarvis' to begin."
        )


# ── Singleton Instance ──────────────────────────────────────────────

_jarvis_instance: UnifiedJarvis | None = None


async def get_jarvis() -> UnifiedJarvis:
    """Get or create the singleton JARVIS instance."""
    global _jarvis_instance
    if _jarvis_instance is None:
        _jarvis_instance = UnifiedJarvis()
        await _jarvis_instance.initialize()
    return _jarvis_instance


async def quick_say(text: str) -> str:
    """Quickly speak text through JARVIS (initialize if needed)."""
    jarvis = await get_jarvis()
    return jarvis.speak(text)


async def quick_process(text: str) -> str:
    """Quickly process a command through JARVIS (initialize if needed)."""
    jarvis = await get_jarvis()
    return await jarvis.process(text)


# ── CLI Entry Point ─────────────────────────────────────────────────

async def _cli_main():
    jarvis = await get_jarvis()
    print(f"{jarvis.name} {jarvis.version} — Unified Agent Ready")
    print(f"Capabilities: {sum(1 for v in jarvis.caps.values() if v)}/{len(jarvis.caps)}")
    print("Type 'help' for commands, 'quit' to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye, sir.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "bye"):
            print("Goodbye, sir.")
            break

        response = await jarvis.process(user_input)
        print(f"JARVIS: {response}\n")


if __name__ == "__main__":
    asyncio.run(_cli_main())
