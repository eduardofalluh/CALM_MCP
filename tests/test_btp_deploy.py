"""The SAP BTP deployment: its files agree with the code, the client script sets the right
variables (the secret never printed), and every tool call leaves one audit line without content.
The cf CLI is a stand-in that records its arguments; nothing reaches BTP."""
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.calm.audit import AuditMiddleware

ROOT = Path(__file__).resolve().parent.parent


def test_manifest_and_sign_in_descriptor_agree():
    app = yaml.safe_load((ROOT / "manifest.yml").read_text())["applications"][0]
    assert "--http" in app["command"] and "$PORT" in app["command"] and "0.0.0.0" in app["command"]
    assert app["env"]["CALM_SIGNIN_INSTANCE"] in app["services"]  # the sign-in it trusts is the one bound
    assert app["env"]["CALM_MULTI_TENANT"] == "true"
    assert not [k for k in app["env"] if any(w in k for w in ("SECRET", "TOKEN", "CLIENT_ID", "PASSWORD"))]
    xs = json.loads((ROOT / "deploy/btp/xs-security-claude.json").read_text())
    oauth = xs["oauth2-configuration"]
    assert oauth["redirect-uris"] == ["https://claude.ai/api/mcp/auth_callback"]
    assert sorted(oauth["grant-types"]) == ["authorization_code", "refresh_token"]
    assert oauth["credential-types"] == ["binding-secret"]
    assert [s["name"] for s in xs["scopes"]] == ["$XSAPPNAME.Claude"]  # what tenants.signin() requires
    template = xs["role-templates"][0]["name"]
    assert xs["role-collections"][0]["role-template-references"] == [f"$XSAPPNAME.{template}"]


def test_what_goes_to_cloud_foundry():
    assert (ROOT / "runtime.txt").read_text().strip() == "python-3.12.x"
    ignored = (ROOT / ".cfignore").read_text().split()
    for path in (".env", ".env.*", "venv/", "tests/", ".git/", "*.md", "*.html", ".claude/"):
        assert path in ignored, path  # secrets, handoff notes and local state never uploaded
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            assert "==" in line or " @ https://" in line, f"not pinned: {line}"
            assert "git+" not in line  # the buildpack installs without git


@pytest.fixture
def fake_cf(tmp_path):
    log = tmp_path / "cf.log"
    cf = tmp_path / "bin" / "cf"
    cf.parent.mkdir()
    cf.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    cf.chmod(0o755)
    env = {**os.environ, "PATH": f"{cf.parent}{os.pathsep}{os.environ['PATH']}"}
    return SimpleNamespace(log=log, env=env)


def _script(fake_cf, *args, answers=""):
    return subprocess.run(["bash", str(ROOT / "scripts/btp_set_client.sh"), *args], input=answers,
                          capture_output=True, text=True, env=fake_cf.env, timeout=30)


def test_the_client_script_sets_a_client_and_never_prints_the_secret(fake_cf):
    out = _script(fake_cf, answers="lutron\nlutron-cloudalm\nus10\nsb-calm!b1\nsecret-test-value\njane@example.com, @partner.example\n")
    assert out.returncode == 0, out.stderr
    calls = fake_cf.log.read_text().splitlines()
    assert calls == [
        "set-env syntax-calm-mcp CALM_TENANT_LUTRON_IDENTITY_ZONE lutron-cloudalm",
        "set-env syntax-calm-mcp CALM_TENANT_LUTRON_REGION_ZONE us10",
        "set-env syntax-calm-mcp CALM_TENANT_LUTRON_CLIENT_ID sb-calm!b1",
        "set-env syntax-calm-mcp CALM_TENANT_LUTRON_CLIENT_SECRET secret-test-value",
        "set-env syntax-calm-mcp CALM_TENANT_LUTRON_ALLOWED_USERS jane@example.com, @partner.example",
        "restart syntax-calm-mcp --strategy rolling",
    ]
    assert "secret-test-value" not in out.stdout + out.stderr
    assert "check SAP Cloud ALM tenant lutron" in out.stdout


def test_the_client_script_changes_only_what_is_typed_and_removes(fake_cf):
    out = _script(fake_cf, answers="Lutron\n\n\n\n\nbob@example.com\n")
    assert out.returncode == 0, out.stderr
    assert fake_cf.log.read_text().splitlines() == [
        "set-env syntax-calm-mcp CALM_TENANT_LUTRON_ALLOWED_USERS bob@example.com",
        "restart syntax-calm-mcp --strategy rolling"]
    fake_cf.log.unlink()
    out = _script(fake_cf, "--remove", "lutron")
    assert out.returncode == 0 and "Removed LUTRON" in out.stdout
    assert len(fake_cf.log.read_text().splitlines()) == 6  # five unset-env and a restart
    for bad in ("lut ron\n", "x\n", "lutron\nBad Zone\n\n\n\n\n"):
        assert _script(fake_cf, answers=bad).returncode != 0


def _call(middleware, name, args, fails=False):
    async def call_next(context):
        if fails:
            raise ValueError("SAP said no")
        return "result"
    context = SimpleNamespace(message=SimpleNamespace(name=name, arguments=args))
    return asyncio.run(middleware.on_call_tool(context, call_next))


def test_every_tool_call_leaves_one_audit_line_without_content(caplog):
    caplog.set_level(logging.INFO, logger="calm-mcp.audit")
    middleware = AuditMiddleware()
    assert _call(middleware, "calm_resource", {"tenant": "lutron", "resource": "tasks", "operation": "list",
                                                "data": {"search": "salary of jane"}}) == "result"
    with pytest.raises(ValueError):
        _call(middleware, "calm_resource", {"tenant": "x; drop", "resource": "tasks", "operation": "create"},
              fails=True)
    lines = [r.getMessage() for r in caplog.records]
    assert lines[0].startswith("AUDIT user=local tenant=lutron tool=calm_resource resource=tasks operation=list "
                               "outcome=ok ms=")
    assert "tenant=? " in lines[1] and "outcome=failed (ValueError)" in lines[1]
    assert not any("salary" in line or "SAP said" in line for line in lines)  # never the content
