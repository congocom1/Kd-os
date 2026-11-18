"""Fail-closed action boundary; only registered, explicitly safe actions bypass auth.

The injected checker(principal_id, action, permissions) must resolve an
 authenticated NON-VOICE principal from trusted application state. It must not
 trust a supplied identifier alone. speaker_id is audit context, never authority.
This module does not sandbox handlers or enforce declaration timeouts.
"""
from __future__ import annotations

import json
import math
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Callable, Optional


def canonical_args(args: dict) -> str:
    """Exact JSON types only; no key coercion, NaN, tuples or custom objects."""
    def validate(value):
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise ValueError('JSON keys must be strings')
                validate(item)
        elif type(value) is list:
            for item in value:
                validate(item)
        elif type(value) not in (str, int, float, bool, type(None)):
            raise ValueError('Not a JSON value')
        elif type(value) is float and not math.isfinite(value):
            raise ValueError('Not a finite JSON number')
    if type(args) is not dict:
        raise ValueError('Arguments must be a JSON object')
    validate(args)
    return json.dumps(args, sort_keys=True, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class ActionPermissionDecl:
    name: str
    required_permissions: tuple[str, ...] = ()
    timeout_seconds: Optional[int] = None
    side_effects: tuple[str, ...] = ()
    needs_approval: bool = True
    description: str = ''


@dataclass(frozen=True)
class ApprovalGrant:
    action: str
    args_json: str
    approved_at: float
    approved_by: str
    expires_at: float

    @property
    def args(self):
        return json.loads(self.args_json)


@dataclass(frozen=True)
class ActionAuditRecord:
    run_id: str
    action: str
    args: dict
    speaker_id: Optional[str]
    approved: bool
    approval_reason: str
    started_at: float
    finished_at: float
    status: str
    result: Optional[str] = None
    error: Optional[str] = None


class ActionPermissionManager:
    def __init__(self, permission_checker: Optional[Callable[[str, str, list[str]], bool]] = None):
        self._permission_checker = permission_checker
        self._decls = {}
        self._approvals = {}
        self._audit = []
        self._max_audit = 1000
        self._lock = threading.RLock()

    def register_action(self, name, required_permissions=None, timeout_seconds=None,
                        side_effects=None, needs_approval=True, description=''):
        for tags in (required_permissions, side_effects):
            if tags is not None and (type(tags) not in (list, tuple) or
                                    any(type(t) is not str or not t for t in tags)):
                raise ValueError('Permission metadata must be string lists')
        if type(needs_approval) is not bool:
            raise ValueError('needs_approval must be boolean')
        if timeout_seconds is not None and (type(timeout_seconds) is not int or timeout_seconds <= 0):
            raise ValueError('timeout_seconds must be a positive integer')
        decl = ActionPermissionDecl(name, tuple(required_permissions or ()), timeout_seconds,
                                    tuple(side_effects or ()), needs_approval, description)
        with self._lock:
            if self._decls.get(name) != decl:
                self._approvals = {k: g for k, g in self._approvals.items() if g.action != name}
            self._decls[name] = decl
        return decl

    def get_decl(self, name):
        with self._lock:
            return self._decls.get(name)

    def _trusted(self, principal_id, decl):
        if not isinstance(principal_id, str) or not principal_id or self._permission_checker is None:
            return False
        try:
            return self._permission_checker(principal_id, decl.name, list(decl.required_permissions)) is True
        except Exception:
            return False

    def _purge(self):
        now = time.monotonic()
        self._approvals = {k: g for k, g in self._approvals.items() if g.expires_at > now}

    def approve(self, action, args, approved_by=None, expires_in_seconds=None, *, principal_id=None):
        """approved_by is legacy metadata, NOT authority. Grants default to 60s.

        expires_at uses the monotonic clock, not wall-clock time.
        """
        with self._lock:
            decl = self._decls.get(action)
            if decl is None or not self._trusted(principal_id, decl):
                self.record_execution(action, {}, None, False, 'permission_denied', 'refused')
                raise PermissionError('Approval requires a trusted non-voice principal')
            try:
                encoded = canonical_args(args)
                ttl = 60 if expires_in_seconds is None else expires_in_seconds
                if type(ttl) not in (int, float) or not math.isfinite(ttl) or not 0 < ttl <= 300:
                    raise ValueError('Approval lifetime must be in (0, 300] seconds')
            except (ValueError, TypeError, RecursionError):
                self.record_execution(action, {}, None, False, 'invalid_approval', 'refused')
                raise ValueError('Invalid approval arguments or lifetime') from None
            self._purge()
            now = time.monotonic()
            grant = ApprovalGrant(action, encoded, now, principal_id, now + ttl)
            self._approvals[(action, encoded, principal_id)] = grant
            return grant

    def revoke(self, action, args):
        encoded = canonical_args(args)
        with self._lock:
            keys = [k for k in self._approvals if k[:2] == (action, encoded)]
            for key in keys:
                del self._approvals[key]
            return bool(keys)

    def is_approved(self, action, args, *, principal_id=None):
        with self._lock:
            self._purge()
            return (action, canonical_args(args), principal_id) in self._approvals

    def check_and_authorize(self, action, args, speaker_id=None, *, principal_id=None):
        """Consumes a matching grant atomically. Do not use as a preview API."""
        with self._lock:
            reason = None
            decl = self._decls.get(action)
            try:
                encoded = canonical_args(args)
            except (ValueError, TypeError, RecursionError):
                reason = 'invalid_arguments'
            if reason is None:
                if decl is None:
                    reason = 'unknown_action'
                elif decl.needs_approval or decl.required_permissions or decl.side_effects:
                    if not self._trusted(principal_id, decl):
                        reason = 'permission_denied'
                    else:
                        self._purge()
                        key = (action, encoded, principal_id)
                        if self._approvals.pop(key, None) is None:
                            reason = 'approval_required'
                        else:
                            return True, 'approved'
                else:
                    return True, 'authorized'
            self.record_execution(action, {}, speaker_id, False, reason, 'refused')
            return False, reason

    def record_execution(self, action, args, speaker_id, approved, approval_reason,
                         status, result=None, error=None):
        """Never retain payload, result or exception contents (including nested data)."""
        with self._lock:
            now = time.time()
            record = ActionAuditRecord(str(uuid.uuid4()), action, {}, speaker_id, approved,
                                       approval_reason, now, now, status,
                                       '[REDACTED]' if result is not None else None,
                                       '[REDACTED]' if error is not None else None)
            self._audit.append(record)
            self._audit = self._audit[-self._max_audit:]
            return record.run_id

    def list_audit(self, action=None, limit=50):
        with self._lock:
            records = [r for r in reversed(self._audit) if action is None or r.action == action]
            return [asdict(r) for r in records[:max(0, limit)]]

    def list_decls(self):
        with self._lock:
            return [dict(asdict(d), required_permissions=list(d.required_permissions),
                         side_effects=list(d.side_effects)) for d in self._decls.values()]

    def status(self):
        with self._lock:
            self._purge()
            return {'declared_actions': len(self._decls), 'active_approvals': len(self._approvals),
                    'audit_records': len(self._audit),
                    'permission_checker_configured': self._permission_checker is not None}


_default_permission_manager = None
_default_lock = threading.Lock()


def get_default_permission_manager():
    global _default_permission_manager
    with _default_lock:
        if _default_permission_manager is None:
            _default_permission_manager = ActionPermissionManager()
        return _default_permission_manager
