"""
core/task_orchestration.py — Autonomous Task Orchestration (KD Upgrade).

Provides:
  • Task planning and decomposition
  • Dependency management and scheduling
  • Autonomous execution with error recovery
  • Progress tracking and resumption
  • Integration with awareness engine and persistent memory
  • Zero-regression: gated by TASK_ORCHESTRATION flag

Requires: REALTIME_AWARENESS, PERSISTENT_MEMORY flags
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from core.feature_flags import is_enabled
from core.awareness_engine import get_awareness_engine, EventType, TaskPayload
from core.persistent_memory import get_persistent_memory

logger = logging.getLogger("jarvis.task_orchestration")


# ── Task Types and Status ────────────────────────────────────────────────────

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class TaskPriority(Enum):
    LOW = 0
    NORMAL = 50
    HIGH = 100
    CRITICAL = 200


@dataclass
class TaskStep:
    """A single step in a task plan."""
    id: str
    name: str
    action: str  # Tool/action name to execute
    parameters: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)  # Step IDs
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    retries: int = 0
    max_retries: int = 3


@dataclass
class Task:
    """A task with multiple steps."""
    id: str
    name: str
    description: str
    steps: list[TaskStep] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    progress: float = 0.0  # 0.0 - 1.0
    metadata: dict = field(default_factory=dict)
    parent_task_id: str | None = None  # For sub-tasks

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": [
                {
                    "id": s.id,
                    "name": s.name,
                    "action": s.action,
                    "parameters": s.parameters,
                    "depends_on": s.depends_on,
                    "status": s.status.value,
                    "result": str(s.result) if s.result else None,
                    "error": s.error,
                    "started_at": s.started_at,
                    "completed_at": s.completed_at,
                    "retries": s.retries,
                    "max_retries": s.max_retries,
                }
                for s in self.steps
            ],
            "status": self.status.value,
            "priority": self.priority.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress": self.progress,
            "metadata": self.metadata,
            "parent_task_id": self.parent_task_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        steps = []
        for s in data.get("steps", []):
            steps.append(TaskStep(
                id=s["id"],
                name=s["name"],
                action=s["action"],
                parameters=s.get("parameters", {}),
                depends_on=s.get("depends_on", []),
                status=TaskStatus(s["status"]),
                result=s.get("result"),
                error=s.get("error"),
                started_at=s.get("started_at"),
                completed_at=s.get("completed_at"),
                retries=s.get("retries", 0),
                max_retries=s.get("max_retries", 3),
            ))
        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            steps=steps,
            status=TaskStatus(data["status"]),
            priority=TaskPriority(data.get("priority", TaskPriority.NORMAL.value)),
            created_at=data.get("created_at", time.time()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            progress=data.get("progress", 0.0),
            metadata=data.get("metadata", {}),
            parent_task_id=data.get("parent_task_id"),
        )


# ── Task Planner ──────────────────────────────────────────────────────────────

class TaskPlanner:
    """
    Plans tasks by decomposing goals into executable steps.

    Uses LLM (via main.py's interface) for intelligent planning,
    with fallback to rule-based decomposition.
    """

    def __init__(self, action_registry=None, plugin_registry=None):
        self.action_registry = action_registry
        self.plugin_registry = plugin_registry
        self._llm_available = False

    def set_llm_available(self, available: bool) -> None:
        """Set whether LLM planning is available."""
        self._llm_available = available

    def plan(self, goal: str, context: dict | None = None) -> Task:
        """
        Create a task plan for a goal.

        Args:
            goal: Natural language goal description
            context: Optional context (available tools, current state, memory)

        Returns:
            Task with decomposed steps
        """
        task_id = str(uuid.uuid4())[:8]
        task = Task(
            id=task_id,
            name=goal[:80],
            description=goal,
            metadata={"goal": goal, "context": context or {}},
        )

        if self._llm_available:
            steps = self._plan_with_llm(goal, context)
        else:
            steps = self._plan_rule_based(goal, context)

        task.steps = steps
        return task

    def _plan_with_llm(self, goal: str, context: dict | None) -> list[TaskStep]:
        """Plan using LLM (placeholder - integrates with main.py's LLM)."""
        # This would call the LLM with a planning prompt
        # For now, fall back to rule-based
        return self._plan_rule_based(goal, context)

    def _plan_rule_based(self, goal: str, context: dict | None) -> list[TaskStep]:
        """Simple rule-based planning based on keywords."""
        steps = []
        goal_lower = goal.lower()

        # Common patterns
        if any(word in goal_lower for word in ["search", "find", "look up", "google"]):
            steps.append(TaskStep(
                id=str(uuid.uuid4())[:8],
                name="Search for information",
                action="web_search",
                parameters={"query": goal, "mode": "search"},
            ))

        if any(word in goal_lower for word in ["open", "launch", "start"]):
            # Extract app name (simplified)
            steps.append(TaskStep(
                id=str(uuid.uuid4())[:8],
                name="Open application",
                action="open_app",
                parameters={"app": self._extract_app_name(goal)},
            ))

        if any(word in goal_lower for word in ["screenshot", "capture", "screen"]):
            steps.append(TaskStep(
                id=str(uuid.uuid4())[:8],
                name="Take screenshot",
                action="screen_process",
                parameters={"action": "capture"},
            ))

        if any(word in goal_lower for word in ["remind", "reminder", "remember"]):
            steps.append(TaskStep(
                id=str(uuid.uuid4())[:8],
                name="Set reminder",
                action="reminder",
                parameters={"text": goal},
            ))

        if any(word in goal_lower for word in ["3d", "model", "create", "box", "sphere"]):
            steps.append(TaskStep(
                id=str(uuid.uuid4())[:8],
                name="3D modeling operation",
                action="studio_modeler",
                parameters=self._extract_3d_params(goal),
            ))

        if not steps:
            # Generic fallback
            steps.append(TaskStep(
                id=str(uuid.uuid4())[:8],
                name="Process request",
                action="process_request",
                parameters={"text": goal},
            ))

        return steps

    def _extract_app_name(self, goal: str) -> str:
        """Extract app name from goal (simplified)."""
        apps = ["chrome", "firefox", "code", "vscode", "terminal", "notepad", "calculator"]
        for app in apps:
            if app in goal.lower():
                return app
        return "unknown"

    def _extract_3d_params(self, goal: str) -> dict:
        """Extract 3D modeling parameters from goal."""
        return {"action": "create", "description": goal}


# ── Task Executor ─────────────────────────────────────────────────────────────

class TaskExecutor:
    """
    Executes task steps with dependency resolution and error handling.
    """

    def __init__(self, tool_runner: Callable[[str, dict], Any]):
        """
        Args:
            tool_runner: Function that executes a tool by name with parameters.
                         Should return the result or raise an exception.
        """
        self.tool_runner = tool_runner
        self._running_tasks: dict[str, Task] = {}
        self._lock = threading.RLock()

    def execute(self, task: Task, on_progress: Callable[[Task], None] | None = None) -> Task:
        """
        Execute a task to completion.

        Args:
            task: Task to execute
            on_progress: Optional callback for progress updates

        Returns:
            The task with updated status and results
        """
        with self._lock:
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()
            self._running_tasks[task.id] = task

        try:
            self._execute_steps(task, on_progress)
            task.status = TaskStatus.COMPLETED
        except Exception as e:
            task.status = TaskStatus.FAILED
            logger.error(f"Task {task.id} failed: {e}")
        finally:
            task.completed_at = time.time()
            task.progress = 1.0
            with self._lock:
                self._running_tasks.pop(task.id, None)

            # Publish completion event
            self._publish_task_event(task)

        return task

    def _execute_steps(self, task: Task, on_progress: Callable[[Task], None] | None) -> None:
        """Execute steps in dependency order."""
        completed = set()
        pending = {s.id: s for s in task.steps}

        while pending:
            # Find runnable steps (dependencies satisfied)
            runnable = []
            for step_id, step in pending.items():
                if all(dep in completed for dep in step.depends_on):
                    runnable.append(step)

            if not runnable:
                # Circular dependency or missing dependency
                raise RuntimeError("Circular or missing dependency in task steps")

            # Execute runnable steps (can parallelize independent steps)
            for step in runnable:
                self._execute_step(task, step)
                completed.add(step.id)
                del pending[step.id]

                # Update progress
                task.progress = len(completed) / len(task.steps)
                if on_progress:
                    on_progress(task)

                # Publish step event
                self._publish_step_event(task, step)

    def _execute_step(self, task: Task, step: TaskStep) -> None:
        """Execute a single step with retries."""
        step.status = TaskStatus.RUNNING
        step.started_at = time.time()

        while step.retries <= step.max_retries:
            try:
                logger.info(f"Executing step {step.id}: {step.action}")
                result = self.tool_runner(step.action, step.parameters)
                step.result = result
                step.status = TaskStatus.COMPLETED
                step.completed_at = time.time()
                logger.info(f"Step {step.id} completed")
                return
            except Exception as e:
                step.retries += 1
                step.error = str(e)
                logger.warning(f"Step {step.id} failed (attempt {step.retries}): {e}")
                if step.retries > step.max_retries:
                    step.status = TaskStatus.FAILED
                    step.completed_at = time.time()
                    raise RuntimeError(f"Step {step.name} failed after {step.max_retries} retries: {e}")
                time.sleep(1.0 * step.retries)  # Exponential backoff

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        with self._lock:
            task = self._running_tasks.get(task_id)
            if task:
                task.status = TaskStatus.CANCELLED
                return True
            return False

    def get_task(self, task_id: str) -> Task | None:
        """Get a running task."""
        with self._lock:
            return self._running_tasks.get(task_id)

    def _publish_task_event(self, task: Task) -> None:
        """Publish task event to awareness engine."""
        try:
            awareness = get_awareness_engine()
            if awareness and awareness._started:
                payload = TaskPayload(
                    task_id=task.id,
                    name=task.name,
                    status=task.status.value,
                    metadata=task.metadata,
                )
                awareness.publish(
                    EventType.TASK_COMPLETED if task.status == TaskStatus.COMPLETED else EventType.TASK_FAILED,
                    payload.__dict__
                )
        except Exception:
            pass

    def _publish_step_event(self, task: Task, step: TaskStep) -> None:
        """Publish step event to awareness engine."""
        try:
            awareness = get_awareness_engine()
            if awareness and awareness._started:
                payload = TaskPayload(
                    task_id=task.id,
                    name=f"{task.name} :: {step.name}",
                    status=step.status.value,
                    progress=task.progress,
                    metadata={"step_id": step.id, "action": step.action},
                )
                awareness.publish(
                    EventType.TASK_PROGRESS,
                    payload.__dict__
                )
        except Exception:
            pass


# ── Task Orchestrator ─────────────────────────────────────────────────────────

class TaskOrchestrator:
    """
    High-level task orchestration engine.

    Features:
    - Task queue with priority scheduling
    - Automatic planning from natural language
    - Persistent task state (survives restarts)
    - Integration with memory for context
    - Event-driven progress updates
    """

    def __init__(self, tool_runner: Callable[[str, dict], Any] | None = None):
        self._planner = TaskPlanner()
        self._executor = TaskExecutor(tool_runner or self._default_runner)
        self._lock = threading.RLock()
        self._task_queue: list[Task] = []
        self._completed_tasks: dict[str, Task] = {}
        self._worker_thread: threading.Thread | None = None
        self._running = False
        self._paused = False
        self._awareness = None
        self._memory = None

        # Storage
        base = Path(__file__).resolve().parent.parent
        self._tasks_dir = base / "memory" / "tasks"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)

    def _default_runner(self, action: str, parameters: dict) -> Any:
        """Default tool runner - integrates with main.py's action registry."""
        # This would be replaced with the actual tool runner from main.py
        logger.warning(f"No tool runner configured for action: {action}")
        return f"Action {action} not configured"

    def set_tool_runner(self, runner: Callable[[str, dict], Any]) -> None:
        """Set the tool runner function."""
        self._executor = TaskExecutor(runner)

    def initialize(self) -> bool:
        """Initialize the orchestrator."""
        if not is_enabled("TASK_ORCHESTRATION"):
            logger.info("Task orchestrator not initialized: flag is off")
            return False

        try:
            # Connect to awareness engine
            if is_enabled("REALTIME_AWARENESS"):
                self._awareness = get_awareness_engine()
                if not self._awareness._started:
                    self._awareness.start()

            # Connect to persistent memory
            if is_enabled("PERSISTENT_MEMORY"):
                self._memory = get_persistent_memory()

            # Load persisted tasks
            self._load_tasks()

            # Start worker
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._worker_loop, daemon=True, name="TaskOrchestrator"
            )
            self._worker_thread.start()

            logger.info("Task orchestrator initialized")
            return True
        except Exception as e:
            logger.warning(f"Task orchestrator initialization failed: {e}")
            return False

    def _worker_loop(self) -> None:
        """Background worker to process task queue."""
        while self._running:
            if self._paused:
                time.sleep(1.0)
                continue

            task = self._get_next_task()
            if task:
                self._execute_task(task)
            else:
                time.sleep(0.5)

    def _get_next_task(self) -> Task | None:
        """Get next task from queue (priority order)."""
        with self._lock:
            if not self._task_queue:
                return None
            # Sort by priority (highest first), then creation time
            self._task_queue.sort(key=lambda t: (-t.priority.value, t.created_at))
            return self._task_queue.pop(0)

    def _execute_task(self, task: Task) -> None:
        """Execute a task and store result."""
        def on_progress(t: Task):
            self._save_task(t)

        try:
            self._executor.execute(task, on_progress)
        finally:
            self._completed_tasks[task.id] = task
            self._save_task(task)

            # Store in persistent memory
            if self._memory:
                self._memory.store(
                    category="tasks",
                    key=task.id,
                    value=task.description,
                    importance=0.7 if task.status == TaskStatus.COMPLETED else 0.3,
                    tags=["task", task.status.value],
                    source="system",
                )

    def submit_task(self, goal: str, priority: TaskPriority = TaskPriority.NORMAL,
                    context: dict | None = None) -> Task:
        """
        Submit a goal for autonomous execution.

        Args:
            goal: Natural language goal
            priority: Task priority
            context: Optional context for planning

        Returns:
            The created task (queued for execution)
        """
        task = self._planner.plan(goal, context)
        task.priority = priority

        with self._lock:
            self._task_queue.append(task)
            self._save_task(task)

        logger.info(f"Submitted task {task.id}: {task.name} (priority: {priority.name})")
        return task

    def submit_planned_task(self, task: Task) -> Task:
        """Submit a pre-planned task."""
        with self._lock:
            self._task_queue.append(task)
            self._save_task(task)
        return task

    def get_task_status(self, task_id: str) -> Task | None:
        """Get task by ID (running, queued, or completed)."""
        with self._lock:
            # Check running
            running = self._executor.get_task(task_id)
            if running:
                return running
            # Check queue
            for t in self._task_queue:
                if t.id == task_id:
                    return t
            # Check completed
            return self._completed_tasks.get(task_id)

    def list_tasks(self, status: TaskStatus | None = None,
                   limit: int = 50) -> list[Task]:
        """List tasks with optional status filter."""
        with self._lock:
            all_tasks = list(self._completed_tasks.values()) + self._task_queue
            running = list(self._executor._running_tasks.values())
            all_tasks.extend(running)

            if status:
                all_tasks = [t for t in all_tasks if t.status == status]

            all_tasks.sort(key=lambda t: t.created_at, reverse=True)
            return all_tasks[:limit]

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a queued or running task."""
        with self._lock:
            # Check queue
            for i, t in enumerate(self._task_queue):
                if t.id == task_id:
                    t.status = TaskStatus.CANCELLED
                    self._task_queue.pop(i)
                    self._save_task(t)
                    return True

            # Check running
            return self._executor.cancel_task(task_id)

    def pause(self) -> None:
        """Pause task processing."""
        self._paused = True

    def resume(self) -> None:
        """Resume task processing."""
        self._paused = False

    def _save_task(self, task: Task) -> None:
        """Persist task to disk."""
        try:
            task_file = self._tasks_dir / f"{task.id}.json"
            task_file.write_text(json.dumps(task.to_dict(), indent=2))
        except Exception as e:
            logger.warning(f"Failed to save task {task.id}: {e}")

    def _load_tasks(self) -> None:
        """Load persisted tasks."""
        import json
        try:
            for task_file in self._tasks_dir.glob("*.json"):
                try:
                    data = json.loads(task_file.read_text())
                    task = Task.from_dict(data)
                    if task.status == TaskStatus.RUNNING:
                        # Was interrupted - re-queue
                        task.status = TaskStatus.PENDING
                        self._task_queue.append(task)
                    elif task.status == TaskStatus.PENDING:
                        self._task_queue.append(task)
                    else:
                        self._completed_tasks[task.id] = task
                except Exception:
                    pass
            logger.info(f"Loaded {len(self._completed_tasks)} completed tasks, "
                       f"{len(self._task_queue)} pending tasks")
        except Exception as e:
            logger.warning(f"Failed to load tasks: {e}")

    def shutdown(self) -> None:
        """Clean shutdown."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)

        # Save all running tasks
        with self._lock:
            for task in self._executor._running_tasks.values():
                task.status = TaskStatus.PAUSED
                self._save_task(task)
            for task in self._task_queue:
                self._save_task(task)


# ── Singleton ────────────────────────────────────────────────────────────────

_orchestrator: TaskOrchestrator | None = None


def get_task_orchestrator(tool_runner: Callable[[str, dict], Any] | None = None) -> TaskOrchestrator | None:
    """Get or create the global task orchestrator."""
    global _orchestrator
    if not is_enabled("TASK_ORCHESTRATION"):
        return None
    if _orchestrator is None:
        _orchestrator = TaskOrchestrator(tool_runner)
        _orchestrator.initialize()
    elif tool_runner:
        _orchestrator.set_tool_runner(tool_runner)
    return _orchestrator


# Import json at module level
import json