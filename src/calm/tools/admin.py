"""Admins add, change and remove clients (SAP Cloud ALMs) from a chat.

The client secret never passes through the chat: `add` / `new_secret` answer with a
one-time terminal command (one client, 10 minutes) that asks for the secret with a
hidden prompt and sends it over HTTPS straight to this server's /admin/client-secret.
The server checks it against the client's SAP login and keeps it in the encrypted
client store (tenant_store.py). Only people in CALM_ADMINS, signed in to the
connector with a sign-in this server verifies, can use the tool.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Literal, Optional

from fastmcp import Context, FastMCP
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from src.calm import tenant_store, tenants
from src.calm.config import build_auth_url
from src.calm.dependencies import _fp, _request, _token_from_authorization
from src.calm.oauth import issuer_for, public_mcp_url
from src.calm.token_manager import TokenManager
from src.calm.tools.health import DOCUMENTED_SCOPES, token_permissions

log = logging.getLogger("calm-mcp.admin")

_NAME = re.compile(r"[a-z0-9][a-z0-9_]{1,39}")
_ZONE = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")
_REGION = re.compile(r"[a-z0-9][a-z0-9-]{1,19}")
_PERSON = re.compile(r"[^@\s,;]*@[^@\s,;]+\.[^@\s,;]+")
_URL = re.compile(r"https?://[A-Za-z0-9.\-:/_]+")


def _admin(ctx: Context) -> str:
    """The admin's email, or a refusal saying why."""
    request = _request(ctx)
    if request is None:
        raise ValueError("Clients are added from a chat on the hosted SAP Cloud ALM MCP. On a local MCP, set "
                         "CALM_TENANT_<NAME>_* in your own environment instead.")
    person = tenants.verified_person(_token_from_authorization(request.headers.get("Authorization")))
    admins = {a.lower() for a in re.split(r"[\s,;]+", os.getenv("CALM_ADMINS", "")) if a}
    email = tenants.person_email(person) if person else ""
    if not email or email not in admins:
        raise ValueError("Only the MCP's admins (CALM_ADMINS), signed in to the SAP Cloud ALM connector, "
                         "can add or change clients.")
    missing = tenant_store.not_ready()
    if missing:
        raise ValueError(f"Adding clients from a chat is not set up on this MCP yet: {missing} "
                         "(ask whoever deploys it).")
    return email


def _people(value) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"[\s,;]+", str(value or ""))
    people = [str(p).strip().lower() for p in items if str(p).strip()]
    bad = [p for p in people if not _PERSON.fullmatch(p)]
    if bad or not people:
        raise ValueError("allowed_users: the emails and / or @domains (e.g. @syntax.com) of the people who may use "
                         "this client" + (f"; not an email or @domain: {', '.join(bad)}" if bad else "") + ".")
    return people


def _command(ctx: Context, name: str, code: str) -> str:
    headers = {k.lower(): v for k, v in _request(ctx).headers.items()}
    url = f"{issuer_for(public_mcp_url(headers))}/admin/client-secret"
    if not _URL.fullmatch(url):
        raise ValueError(f"This MCP's address ({url}) can't go in a command: set MCP_PUBLIC_URL to its https address.")
    send = (f"r.Request('{url}', data=json.dumps({{'code': '{code}', 'secret': s}}).encode(), "
            "headers={'Content-Type': 'application/json'})")
    return ("python3 -c \"import getpass, json, urllib.request as r; "
            f"s = getpass.getpass('Client secret for {name} (typing is hidden): '); "
            f"print(r.urlopen({send}).read().decode())\"")


def _secret_step(ctx: Context, name: str, code: str) -> dict:
    return {
        "Next Step": (f"Run this command in a terminal on your own computer and paste {name}'s client secret when it "
                      "asks (typing is hidden). The secret goes straight to the MCP over HTTPS, never into this chat. "
                      f"The command works once, for {tenant_store.CODE_TTL // 60} minutes."),
        "Command": _command(ctx, name, code),
        "Then": f'Ask to check SAP Cloud ALM tenant "{name}" (calm_health with tenant="{name}").',
    }


def save_client_secret(code: str, secret: str) -> str:
    """Check a client secret sent by the terminal command with the client's SAP login, then store it."""
    if tenant_store.not_ready():
        return "Not saved: adding clients from a chat is not set up on this MCP."
    p = tenant_store.pending(code)
    if p is None:
        return ("Not saved: this command has expired or was already used (each one works once, for "
                f"{tenant_store.CODE_TTL // 60} minutes). Ask Claude for a new one.")
    try:
        token = TokenManager(client_id=p["client_id"], client_secret=secret,
                             auth_url=build_auth_url(p["identity_zone"], p["region_zone"])).get_token()
    except Exception as exc:  # noqa: BLE001 — SAP's answer goes back to the admin
        tenant_store.failed(code)
        return (f"Not saved: SAP's login for {p['identity_zone']} ({p['region_zone']}) refused this client ID and "
                f"secret. Check them and run the same command again while it is valid. SAP said: {str(exc)[:300]}")
    tenant_store.complete(code, secret)
    log.info("Client %s saved from the terminal command", p["name"])
    perms = token_permissions(token)
    if "granted" not in perms:
        have = "Its permissions can't be read from its token."
    elif perms["missing"]:
        have = (f"It has {len(perms['granted'])} of the {len(DOCUMENTED_SCOPES)} CALM API permissions the MCP uses; "
                f"missing: {', '.join(perms['missing'])}.")
    else:
        have = "It has every CALM API permission the MCP uses."
    return (f"Saved: {p['name']} ({p['identity_zone']}, {p['region_zone']}). Its key works. {have} "
            f"Back in Claude, ask to check SAP Cloud ALM tenant {p['name']}.")


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def calm_admin_clients(
        ctx: Context,
        action: Literal["list", "add", "allow", "new_secret", "remove"] = "list",
        name: Optional[str] = None,
        identity_zone: Optional[str] = None,
        region_zone: Optional[str] = None,
        client_id: Optional[str] = None,
        allowed_users: Optional[list[str] | str] = None,
    ) -> dict:
        """ADMINS ONLY: add, change or remove the clients (SAP Cloud ALMs) this MCP serves, from a chat.
        Only the MCP's admins can use it; everyone else is refused.

        NEVER ask for, accept or pass a client secret in the chat; there is no argument for it.
        `add` and `new_secret` answer with a one-time command: give it to the user exactly as
        returned and tell them to run it in a terminal on their own computer. It asks for the secret
        with a hidden prompt and sends it straight to the MCP, which checks it with the client's SAP
        login and stores it encrypted. If the user pastes a secret in the chat anyway, don't use it:
        tell them it must be treated as exposed (the client's BTP admin creates a new key) and to use
        the command.

        Actions:
          list        the clients, who may use each, and those waiting for their secret
          add         name (short, e.g. "centerra"), identity_zone, region_zone, client_id (from the
                      client's CALM API service key: identityzone, the region in its url e.g. us10,
                      clientid) and allowed_users (emails and / or @domains) → a command for the secret
          allow       name, allowed_users → replaces who may use the client
          new_secret  name (client_id too if the new key has a new one) → a command for the new
                      secret; the current one keeps working until it is saved
          remove      name → the client is gone for everyone

        After a secret is saved, check the client with calm_health(tenant=name). Clients set on the
        server itself (CALM_TENANT_<NAME>_*) are changed in the deployment, not here.
        """
        email = _admin(ctx)
        stored = tenant_store.stored_tenants()
        server = tenants.server_names()
        if action == "list":
            now = time.time()
            return {
                "Clients": [{"Name": n, "Tenant": t.identity_zone, "Address": t.base_url,
                             "Allowed Users": list(t.allowed),
                             "Set": ("on the server (change it in the deployment)" if n in server
                                     else f"from a chat, {stored[n].get('added_at', '')}")}
                            for n, t in sorted(tenants.configured().items())],
                "Waiting For A Secret": [{"Name": p["name"], "Minutes Left": int((p["expires"] - now) // 60)}
                                         for p in tenant_store.load()["pending"].values() if p["expires"] > now],
            }
        key = tenants.norm(name or "")
        if not _NAME.fullmatch(key):
            raise ValueError("name: the short client name people will use, e.g. centerra (letters, digits, _).")
        if tenants.is_default(key):
            raise ValueError(f'"{key}" is the name of this connection\'s own SAP Cloud ALM: pick another name.')
        if key in server:
            raise ValueError(f'"{key}" is set on the server (CALM_TENANT_{key.upper()}_*): change or remove it in '
                             "the deployment.")
        if action == "add":
            if key in stored:
                raise ValueError(f'"{key}" already exists: use allow, new_secret or remove.')
            zone, region = (identity_zone or "").strip().lower(), (region_zone or "").strip().lower()
            cid = (client_id or "").strip()
            problems = [msg for ok, msg in (
                (_ZONE.fullmatch(zone), "identity_zone: the client's identityzone from its CALM API service key"),
                (_REGION.fullmatch(region), "region_zone: the client's region, e.g. us10 (in the key's url)"),
                (cid and len(cid) <= 200 and not any(c.isspace() for c in cid), "client_id: the key's clientid"),
            ) if not ok]
            if problems:
                raise ValueError("; ".join(problems) + ".")
            code = tenant_store.start({"name": key, "identity_zone": zone, "region_zone": region,
                                       "client_id": cid, "allowed": _people(allowed_users)})
            log.info("Admin %s: add %s (waiting for its secret)", _fp(email), key)
            return {"Client": key, "Status": "waiting for its secret", **_secret_step(ctx, key, code)}
        if key not in stored:
            raise ValueError(f'No client "{key}" added from a chat. Clients: {", ".join(sorted(stored)) or "none"}.')
        if action == "allow":
            people = _people(allowed_users)
            tenant_store.set_allowed(key, people)
            log.info("Admin %s: allow %s (%d entries)", _fp(email), key, len(people))
            return {"Client": key, "Allowed Users": people}
        if action == "new_secret":
            c = stored[key]
            cid = (client_id or "").strip() or c["client_id"]
            code = tenant_store.start({"name": key, "identity_zone": c["identity_zone"],
                                       "region_zone": c["region_zone"], "client_id": cid, "allowed": c["allowed"]})
            log.info("Admin %s: new secret for %s", _fp(email), key)
            return {"Client": key, "Status": "the current secret keeps working until the new one is saved",
                    **_secret_step(ctx, key, code)}
        tenant_store.remove(key)
        log.info("Admin %s: remove %s", _fp(email), key)
        return {"Client": key, "Removed": True}

    @mcp.custom_route("/admin/client-secret", methods=["POST"])
    async def receive_client_secret(request: Request) -> PlainTextResponse:
        # shortcut: always 200 with a sentence, since the terminal command prints the answer as is.
        try:
            body = await request.json()
            code, secret = str(body.get("code") or "").strip(), str(body.get("secret") or "").strip()
        except Exception:  # noqa: BLE001 — anything else than the command's JSON
            code = secret = ""
        if not code or not secret or len(code) > 100 or len(secret) > 1000:
            return PlainTextResponse("Not saved: use the exact command Claude gave you, and paste the client "
                                     "secret when it asks.\n")
        return PlainTextResponse(await run_in_threadpool(save_client_secret, code, secret) + "\n")
