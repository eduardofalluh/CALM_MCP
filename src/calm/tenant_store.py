"""Clients (SAP Cloud ALMs) an admin added from a chat: an encrypted file the server keeps.

    CALM_TENANT_STORE      path of the file, on a volume that survives restarts and
                           that every copy of the MCP shares
    CALM_TENANT_STORE_KEY  the key that encrypts it (a Fernet key; a deployment secret)

The whole file is encrypted — client secrets and the lists of allowed people alike.
Secrets reach it only through the one-time terminal command (tools/admin.py), never
through a chat. Pending additions (waiting for their secret) are kept here too, so
any copy of the MCP can receive the secret.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken

CODE_TTL = 600  # seconds a one-time code stays valid
MAX_ATTEMPTS = 5  # wrong secrets sent with one code before it stops working

_cache: dict = {"key": None, "data": None}


def not_ready() -> str:
    """What is missing before clients can be added from a chat ('' when ready)."""
    missing = [v for v in ("CALM_TENANT_STORE", "CALM_TENANT_STORE_KEY") if not os.getenv(v, "").strip()]
    if missing:
        return ", ".join(missing) + " not set"
    try:
        Fernet(os.environ["CALM_TENANT_STORE_KEY"].strip())
    except ValueError:
        return "CALM_TENANT_STORE_KEY is not a valid key"
    return ""


def _fernet() -> Fernet:
    return Fernet(os.environ["CALM_TENANT_STORE_KEY"].strip())


def load() -> dict:
    """The store's content ({"tenants": …, "pending": …}); empty when there is none yet."""
    empty = {"tenants": {}, "pending": {}}
    if not (os.getenv("CALM_TENANT_STORE", "").strip() and os.getenv("CALM_TENANT_STORE_KEY", "").strip()):
        return empty
    if not_ready():  # set but unusable: say so, never quietly drop the clients it holds
        raise RuntimeError(f"The client store can't be used: {not_ready()}.")
    path = os.environ["CALM_TENANT_STORE"].strip()
    try:
        stamp = (path, os.stat(path).st_mtime_ns)
    except FileNotFoundError:
        return empty
    if _cache["key"] != stamp:
        try:
            with open(path, "rb") as f:
                data = json.loads(_fernet().decrypt(f.read()))
        except InvalidToken as exc:
            raise RuntimeError(f"The client store {path} can't be read with CALM_TENANT_STORE_KEY "
                               "(a different key, or a damaged file).") from exc
        _cache.update(key=stamp, data=data)
    return json.loads(json.dumps(_cache["data"]))  # a copy: callers may change it


def save(data: dict) -> None:
    # shortcut: last write wins if two admins change clients in the same instant; a lock is needed only if that happens.
    path = os.environ["CALM_TENANT_STORE"].strip()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{secrets.token_hex(4)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(_fernet().encrypt(json.dumps(data).encode()))
    os.replace(tmp, path)
    _cache.update(key=(path, os.stat(path).st_mtime_ns), data=json.loads(json.dumps(data)))


def stored_tenants() -> dict[str, dict]:
    return load()["tenants"]


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def start(entry: dict) -> str:
    """Keep a client waiting for its secret; returns the one-time code (only its hash is stored)."""
    data = load()
    now = time.time()
    data["pending"] = {h: p for h, p in data["pending"].items()
                       if p["expires"] > now and p["name"] != entry["name"]}
    code = secrets.token_urlsafe(24)
    data["pending"][_hash(code)] = {**entry, "expires": now + CODE_TTL, "attempts": 0}
    save(data)
    return code


def pending(code: str) -> dict | None:
    """The client waiting for this code's secret, while the code is still valid."""
    p = load()["pending"].get(_hash(code))
    if not p or p["expires"] < time.time() or p["attempts"] >= MAX_ATTEMPTS:
        return None
    return p


def failed(code: str) -> None:
    data = load()
    if _hash(code) in data["pending"]:
        data["pending"][_hash(code)]["attempts"] += 1
        save(data)


def complete(code: str, client_secret: str) -> dict:
    """Store the client with its secret; the code stops working."""
    data = load()
    p = data["pending"].pop(_hash(code))
    data["tenants"][p["name"]] = {
        "identity_zone": p["identity_zone"], "region_zone": p["region_zone"], "client_id": p["client_id"],
        "client_secret": client_secret, "allowed": p["allowed"],
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    save(data)
    return p


def set_allowed(name: str, allowed: list[str]) -> None:
    data = load()
    data["tenants"][name]["allowed"] = allowed
    save(data)


def remove(name: str) -> None:
    data = load()
    data["tenants"].pop(name, None)
    data["pending"] = {h: p for h, p in data["pending"].items() if p["name"] != name}
    save(data)
