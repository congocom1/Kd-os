"""
plugins/google_connector.py — Google services connector for JARVIS.

Connects to Gmail, Google Calendar, and Google Drive via OAuth2 using the
already-installed google-api-python-client and google-auth-oauthlib packages.

No credentials are ever logged or spoken. All OAuth tokens live in your local
config under the `google_connector` namespace.

Actions:
  init_oauth       — generate the Google authorization URL (needs client_id,
                     client_secret in settings first)
  complete_oauth   — exchange an authorization code for access tokens
                     (needs 'code' from the Google redirect)
  gmail_read       — read recent emails (max 10, needs auth)
  gmail_send       — send an email (needs 'to', 'subject', 'body', needs auth)
  calendar_list    — list upcoming events (next 10, needs auth)
  calendar_create  — create an event (needs 'title', 'start_time', 'end_time',
                     needs auth)
  drive_list       — list recent Drive files (needs auth)
  status           — report connection state

Settings (⚙ → PLUGINS → google_connector):
  client_id    — OAuth client ID from Google Cloud Console
  client_secret — OAuth client secret from Google Cloud Console
  redirect_uri  — OAuth redirect URI (default: urn:ietf:wg:oauth:2.0:oob)
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

from memory.config_manager import get_plugin_config, save_plugin_config
from core.lazyimport import LazyModule, installed

_GOOGLE_API = installed("googleapiclient")
_GOOGLE_AUTH = installed("google_auth_oauthlib")

# Imported lazily — never at module load.
googleapiclient_discovery = LazyModule("googleapiclient.discovery")
google_auth_oauthlib_flow = LazyModule("google_auth_oauthlib.flow")
google_auth_oauthlib_credentials = LazyModule(
    "google.oauth2.credentials"
)


def _creds() -> dict:
    return get_plugin_config("google_connector")


def _save(values: dict) -> None:
    save_plugin_config("google_connector", values)


def _build_service(service_name: str, version: str, token_data: dict):
    """Build a Google API service from stored credentials."""
    creds = google_auth_oauthlib_credentials.Credentials(
        token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes", []),
    )
    return googleapiclient_discovery.build(service_name, version, credentials=creds)


def _init_oauth(values: dict) -> str:
    client_id = values.get("client_id", "").strip()
    client_secret = values.get("client_secret", "").strip()
    redirect_uri = values.get("redirect_uri", "").strip() or (
        "urn:ietf:wg:oauth:2.0:oob"
    )
    if not client_id or not client_secret:
        return (
            "Sir, please set your Google client_id and client_secret in the "
            "plugin settings first (⚙ → PLUGINS → google_connector)."
        )
    flow = google_auth_oauthlib_flow.InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uris": [redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    _save(
        {
            **values,
            "_flow_state": {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
        }
    )
    return (
        "Sir, please open this URL in your browser and authorize JARVIS:\n"
        f"{auth_url}\n\n"
        "After you authorize, Google will show you an authorization code. "
        "Copy it and tell me: 'complete oauth with code <your-code>'."
    )


def _complete_oauth(values: dict, parameters: dict) -> str:
    code = (parameters.get("code") or "").strip()
    if not code:
        return "Sir, I need the authorization code from Google."
    stored = _creds()
    flow_state = stored.get("_flow_state", {})
    if not flow_state.get("client_id"):
        return (
            "Sir, no OAuth flow was started. Say 'init oauth' first to get "
            "the authorization URL."
        )
    try:
        flow = google_auth_oauthlib_flow.InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": flow_state["client_id"],
                    "client_secret": flow_state["client_secret"],
                    "redirect_uris": [flow_state.get("redirect_uri", "urn:ietf:wg:oauth:2.0:oob")],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/drive.readonly",
            ],
        )
        flow.fetch_token(code=code)
        creds = flow.credentials
        token_data = {
            **flow_state,
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "scopes": list(creds.scopes or []),
        }
        token_data.pop("_flow_state", None)
        _save(token_data)
        return (
            "Sir, Google OAuth is complete. JARVIS can now access your Gmail, "
            "Calendar, and Drive. Say 'google status' to confirm."
        )
    except Exception as exc:
        return f"Sir, OAuth failed: {exc}"


def _gmail_read(values: dict) -> str:
    token_data = {k: v for k, v in values.items() if k in (
        "access_token", "refresh_token", "client_id", "client_secret", "scopes"
    )}
    if not token_data.get("access_token") and not token_data.get("refresh_token"):
        return (
            "Sir, you are not connected to Google. Say 'init oauth' to start."
        )
    try:
        service = _build_service("gmail", "v1", token_data)
        result = (
            service.users()
            .messages()
            .list(userId="me", maxResults=10)
            .execute()
        )
        messages = result.get("messages", [])
        if not messages:
            return "Sir, your inbox has no recent messages."
        lines = ["Sir, here are your recent emails:"]
        for m in messages[:5]:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=m["id"], format="metadata")
                .execute()
            )
            headers = msg.get("payload", {}).get("headers", [])
            subject = next(
                (h["value"] for h in headers if h["name"] == "Subject"), "(no subject)"
            )
            sender = next(
                (h["value"] for h in headers if h["name"] == "From"), "(unknown)"
            )
            lines.append(f"• {subject} — from {sender}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Sir, reading Gmail failed: {exc}"


def _gmail_send(values: dict, parameters: dict) -> str:
    token_data = {k: v for k, v in values.items() if k in (
        "access_token", "refresh_token", "client_id", "client_secret", "scopes"
    )}
    if not token_data.get("access_token") and not token_data.get("refresh_token"):
        return (
            "Sir, you are not connected to Google. Say 'init oauth' to start."
        )
    to = (parameters.get("to") or "").strip()
    subject = (parameters.get("subject") or "").strip()
    body = (parameters.get("body") or "").strip()
    if not to or not subject or not body:
        return "Sir, I need 'to', 'subject', and 'body' to send an email."
    try:
        import base64
        from email.mime.text import MIMEText

        service = _build_service("gmail", "v1", token_data)
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"Sir, email sent to {to}."
    except Exception as exc:
        return f"Sir, sending email failed: {exc}"


def _calendar_list(values: dict) -> str:
    token_data = {k: v for k, v in values.items() if k in (
        "access_token", "refresh_token", "client_id", "client_secret", "scopes"
    )}
    if not token_data.get("access_token") and not token_data.get("refresh_token"):
        return (
            "Sir, you are not connected to Google. Say 'init oauth' to start."
        )
    try:
        import datetime

        service = _build_service("calendar", "v3", token_data)
        now = datetime.datetime.utcnow().isoformat() + "Z"
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                maxResults=10,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])
        if not events:
            return "Sir, you have no upcoming events."
        lines = ["Sir, your upcoming calendar events:"]
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            lines.append(f"• {start} — {event.get('summary', '(no title)')}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Sir, reading Calendar failed: {exc}"


def _calendar_create(values: dict, parameters: dict) -> str:
    token_data = {k: v for k, v in values.items() if k in (
        "access_token", "refresh_token", "client_id", "client_secret", "scopes"
    )}
    if not token_data.get("access_token") and not token_data.get("refresh_token"):
        return (
            "Sir, you are not connected to Google. Say 'init oauth' to start."
        )
    title = (parameters.get("title") or "").strip()
    start_time = (parameters.get("start_time") or "").strip()
    end_time = (parameters.get("end_time") or "").strip()
    if not title or not start_time or not end_time:
        return "Sir, I need 'title', 'start_time', and 'end_time' to create an event."
    try:
        service = _build_service("calendar", "v3", token_data)
        event = {
            "summary": title,
            "start": {"dateTime": start_time, "timeZone": "UTC"},
            "end": {"dateTime": end_time, "timeZone": "UTC"},
        }
        service.events().insert(calendarId="primary", body=event).execute()
        return f"Sir, event '{title}' created on your calendar."
    except Exception as exc:
        return f"Sir, creating calendar event failed: {exc}"


def _drive_list(values: dict) -> str:
    token_data = {k: v for k, v in values.items() if k in (
        "access_token", "refresh_token", "client_id", "client_secret", "scopes"
    )}
    if not token_data.get("access_token") and not token_data.get("refresh_token"):
        return (
            "Sir, you are not connected to Google. Say 'init oauth' to start."
        )
    try:
        service = _build_service("drive", "v3", token_data)
        result = (
            service.files()
            .list(pageSize=10, fields="files(id, name, mimeType, modifiedTime)")
            .execute()
        )
        files = result.get("files", [])
        if not files:
            return "Sir, your Drive has no recent files."
        lines = ["Sir, here are your recent Drive files:"]
        for f in files:
            lines.append(f"• {f['name']} ({f.get('mimeType', 'unknown')})")
        return "\n".join(lines)
    except Exception as exc:
        return f"Sir, reading Drive failed: {exc}"


def _status(values: dict) -> str:
    token_data = {k: v for k, v in values.items() if k in (
        "access_token", "refresh_token", "client_id", "client_secret"
    )}
    has_creds = bool(token_data.get("client_id") and token_data.get("client_secret"))
    has_token = bool(token_data.get("access_token") or token_data.get("refresh_token"))
    if not has_creds:
        return "Sir, Google OAuth is not configured. Set client_id and client_secret in settings, then say 'init oauth'."
    if not has_token:
        return "Sir, Google OAuth is configured but not authorized. Say 'init oauth' to get an authorization URL."
    return "Sir, Google OAuth is connected. You can use gmail_read, gmail_send, calendar_list, calendar_create, and drive_list."


PLUGIN = {
    "name": "google_connector",
    "description": (
        "Connect JARVIS to Google services: Gmail, Google Calendar, and Google "
        "Drive. Use 'init oauth' to start the OAuth flow, then 'complete oauth "
        "with code <code>' to finish. After that you can read/send emails, "
        "list/create calendar events, and list Drive files. All credentials stay "
        "on your machine — nothing is logged or spoken."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "'init_oauth', 'complete_oauth', 'gmail_read', "
                "'gmail_send', 'calendar_list', 'calendar_create', 'drive_list', 'status'",
            },
            "code": {
                "type": "STRING",
                "description": "OAuth authorization code from Google (for complete_oauth)",
            },
            "to": {
                "type": "STRING",
                "description": "Recipient email address (for gmail_send)",
            },
            "subject": {
                "type": "STRING",
                "description": "Email subject (for gmail_send)",
            },
            "body": {
                "type": "STRING",
                "description": "Email body text (for gmail_send)",
            },
            "title": {
                "type": "STRING",
                "description": "Calendar event title (for calendar_create)",
            },
            "start_time": {
                "type": "STRING",
                "description": "Event start time in ISO format (for calendar_create)",
            },
            "end_time": {
                "type": "STRING",
                "description": "Event end time in ISO format (for calendar_create)",
            },
        },
        "required": ["action"],
    },
}

# ── Plugin settings (shown in ⚙ → PLUGINS → google_connector) ────────────────
PLUGIN_SETTINGS = {
    "namespace": "google_connector",
    "title": "Google Connector",
    "fields": [
        {
            "key": "client_id",
            "label": "OAuth Client ID",
            "type": "text",
            "default": "",
            "placeholder": "From Google Cloud Console",
        },
        {
            "key": "client_secret",
            "label": "OAuth Client Secret",
            "type": "password",
            "default": "",
            "placeholder": "From Google Cloud Console",
        },
        {
            "key": "redirect_uri",
            "label": "OAuth Redirect URI",
            "type": "text",
            "default": "urn:ietf:wg:oauth:2.0:oob",
            "placeholder": "urn:ietf:wg:oauth:2.0:oob",
        },
    ],
    "action": {
        "label": "INIT OAUTH",
        "run": _init_oauth,
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Run Google API operations.

    Supports Gmail, Calendar, Drive, and other Google API operations.

    Parameters:
        parameters: Dict with "service" and "operation" keys.

    Returns:
        Result from Google API or error message.
    """
    action = (parameters.get("action") or "").strip().lower()
    values = _creds()
    if not action:
        return (
            "Sir, please specify an action: init_oauth, complete_oauth, "
            "gmail_read, gmail_send, calendar_list, calendar_create, drive_list, status."
        )
    try:
        if action == "init_oauth":
            return _init_oauth(values)
        if action == "complete_oauth":
            return _complete_oauth(values, parameters)
        if action == "gmail_read":
            return _gmail_read(values)
        if action == "gmail_send":
            return _gmail_send(values, parameters)
        if action == "calendar_list":
            return _calendar_list(values)
        if action == "calendar_create":
            return _calendar_create(values, parameters)
        if action == "drive_list":
            return _drive_list(values)
        if action == "status":
            return _status(values)
        return f"Sir, I don't recognize the Google action '{action}'."
    except Exception as exc:
        return f"Sir, google_connector failed: {exc}"
