"""
actions/cyber_tools.py — Cybersecurity essentials for JARVIS.

Pure-Python security utilities using only stdlib + dnspython (already
installed). Nothing is logged, stored, or transmitted — results exist only
for this response.

Actions:
  hash         — hash a string (sha256, sha512, sha1, md5)
  encode       — base64 encode text
  decode       — base64 decode text
  url_encode   — URL-encode a string
  url_decode   — URL-decode a string
  hmac         — HMAC-SHA256 sign a message (needs 'key', 'message')
  port_scan    — TCP port scan on a host (needs 'host', optional 'ports')
  dns_lookup   — DNS resolution (needs 'host', optional 'record_type')
  ssl_info     — SSL certificate info for a host (needs 'host')
  net_info     — local network/interface info
  uuid         — random UUID v4
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets
import socket
import ssl
import urllib.parse
import uuid

import dns.resolver

from core import outcome

_COMMON_PORTS = [21, 22, 23, 25, 53, 80, 110, 443, 445, 3306, 3389, 8080]


def _hash_text(text: str, algo: str) -> str:
    algo = algo.lower()
    if algo == "sha256":
        return hashlib.sha256(text.encode()).hexdigest()
    if algo == "sha512":
        return hashlib.sha512(text.encode()).hexdigest()
    if algo == "sha1":
        return hashlib.sha1(text.encode()).hexdigest()
    if algo == "md5":
        return hashlib.md5(text.encode()).hexdigest()
    raise ValueError(f"unsupported hash algorithm: {algo}")


def _port_scan(host: str, ports: list[int]) -> list[dict]:
    results = []
    for port in ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                err = s.connect_ex((host, port))
                results.append({"port": port, "open": err == 0})
        except Exception:
            results.append({"port": port, "open": False, "error": "unreachable"})
    return results


def _dns_lookup(host: str, record_type: str) -> list[str]:
    try:
        answers = dns.resolver.resolve(host, record_type)
        return [str(r) for r in answers]
    except Exception as exc:
        return [f"error: {exc}"]


def _ssl_info(host: str) -> dict:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=5.0) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                return {
                    "subject": dict(x[0] for x in cert.get("subject", [])),
                    "issuer": dict(x[0] for x in cert.get("issuer", [])),
                    "version": cert.get("version"),
                    "serial": cert.get("serialNumber"),
                    "not_before": cert.get("notBefore"),
                    "not_after": cert.get("notAfter"),
                }
    except Exception as exc:
        return {"error": str(exc)}


def _net_info() -> dict:
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        return {
            "hostname": hostname,
            "local_ip": local_ip,
            "fqdn": socket.getfqdn(),
        }
    except Exception as exc:
        return {"error": str(exc)}


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "hash").strip().lower()

    try:
        if action == "hash":
            text = parameters.get("text", "")
            algo = parameters.get("algo", "sha256")
            return outcome.done(
                "cyber_tools",
                algorithm=algo,
                hash=_hash_text(text, algo),
            )

        if action == "encode":
            text = parameters.get("text", "")
            return outcome.done(
                "cyber_tools",
                encoded=base64.b64encode(text.encode()).decode(),
            )

        if action == "decode":
            text = parameters.get("text", "")
            return outcome.done(
                "cyber_tools",
                decoded=base64.b64decode(text).decode(),
            )

        if action == "url_encode":
            text = parameters.get("text", "")
            return outcome.done(
                "cyber_tools",
                encoded=urllib.parse.quote(text),
            )

        if action == "url_decode":
            text = parameters.get("text", "")
            return outcome.done(
                "cyber_tools",
                decoded=urllib.parse.unquote(text),
            )

        if action == "hmac":
            key = parameters.get("key", "")
            message = parameters.get("message", "")
            return outcome.done(
                "cyber_tools",
                hmac=hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest(),
            )

        if action == "port_scan":
            host = parameters.get("host", "")
            ports_str = parameters.get("ports", "")
            if ports_str:
                ports = [int(p.strip()) for p in ports_str.split(",") if p.strip()]
            else:
                ports = _COMMON_PORTS
            return outcome.done("cyber_tools", host=host, ports=_port_scan(host, ports))

        if action == "dns_lookup":
            host = parameters.get("host", "")
            rtype = parameters.get("record_type", "A")
            return outcome.done("cyber_tools", host=host, records=_dns_lookup(host, rtype))

        if action == "ssl_info":
            host = parameters.get("host", "")
            return outcome.done("cyber_tools", host=host, certificate=_ssl_info(host))

        if action == "net_info":
            return outcome.done("cyber_tools", network=_net_info())

        if action == "uuid":
            return outcome.done("cyber_tools", uuid=str(uuid.uuid4()))

        return outcome.failed("cyber_tools", f"unknown action: {action}")

    except Exception as e:
        return outcome.failed("cyber_tools", str(e))


TOOL = {
    "name": "cyber_tools",
    "description": (
        "Cybersecurity essentials: hash, base64 encode/decode, URL encode/decode, "
        "HMAC-SHA256, TCP port scan, DNS lookup, SSL certificate info, network "
        "info, UUID. Nothing is logged or stored."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "hash | encode | decode | url_encode | url_decode | hmac | port_scan | dns_lookup | ssl_info | net_info | uuid",
            },
            "text": {"type": "STRING", "description": "Text to hash/encode/decode"},
            "algo": {"type": "STRING", "description": "Hash algorithm: sha256 | sha512 | sha1 | md5 (default sha256)"},
            "key": {"type": "STRING", "description": "HMAC key"},
            "message": {"type": "STRING", "description": "HMAC message"},
            "host": {"type": "STRING", "description": "Target host for port_scan/dns_lookup/ssl_info"},
            "ports": {"type": "STRING", "description": "Comma-separated ports (default: common ports)"},
            "record_type": {"type": "STRING", "description": "DNS record type: A | AAAA | MX | TXT | CNAME (default A)"},
        },
        "required": ["action"],
    },
    "handler": run,
}
