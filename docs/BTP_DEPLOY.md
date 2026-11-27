# Deploying the SAP Cloud ALM MCP on SAP BTP (for the Claude connector)

What you get:
- **One public HTTPS address** for the Claude connector.
- **Sign-in through the connector's own XSUAA instance.** People use their normal login for the subaccount.
- **Who can use the connector** is set by the BTP role collection "CALM MCP Claude".
- **Which client CALMs each person may open** is set by the lists you keep with `scripts/btp_set_client.sh`.
- **An audit line for every tool call**, without the content.

The design follows the SuccessFactors Intelligence Platform (SIP) connector, which is already live with Claude.

## Before you start

- **Space Developer** in a Cloud Foundry space of the subaccount (PS-Dev CodeGenie Suite, us10).
- **Entitlements on the subaccount:**
  - **Cloud Foundry Runtime:** at least 1 GB of memory.
  - **Authorization and Trust Management Service (xsuaa):** plan `application`.
- **The cf CLI v8:** `brew install cloudfoundry/tap/cf-cli@8`.
- **Someone who can assign role collections** in the subaccount (a subaccount administrator), for step 5.

## First deployment

1. **Log in.** The API endpoint is on the subaccount's Overview page, under Cloud Foundry Environment.

   ```bash
   cf login -a <API endpoint> --sso
   ```

2. **Create the connector's sign-in service.** It holds one scope, Claude's return address and nothing secret.

   ```bash
   cf create-service xsuaa application calm-mcp-claude-auth -c deploy/btp/xs-security-claude.json
   ```

3. **Deploy from the repository root.** The address is in the output under `routes:`.

   ```bash
   cf push
   ```

4. **Check it, in a browser:**
   - `https://<route>/.well-known/oauth-protected-resource/mcp` shows `resource` = `https://<route>/mcp` and `authorization_servers` = the XSUAA instance.
   - `https://<route>/mcp` answers 401.

   If the app didn't start, `cf logs syntax-calm-mcp --recent` says why. It refuses to start if the sign-in service isn't bound.
5. **Give yourself the role.** In the cockpit: Security → Role Collections → **CALM MCP Claude** → Edit → Users → add your email, with the identity provider people log in with.
6. **Add our own CALM and each client**, in your terminal. The secret is typed at a hidden prompt.

   ```bash
   scripts/btp_set_client.sh
   ```

   - **Our own CALM:** name `syntax`, zone `illumiti-corp-cloudalm`, region `eu10`, the internal CALM API key, and `@syntax.com` or named people. It is what "default" means.
   - **Each client:** a short name (`lutron`), the zone, region and key from that client's CALM API service key, and who may use it: the people allowed, or `signin` (next point).
   - **`signin` instead of a list:** each person signs in with the client's own SAP login the first time they open it in a chat (Claude shows a link), and the client's SAP decides who gets in. No list to keep, and CALM records the person instead of "API". The client's BTP admin does this once on their CALM API service instance:
     - adds `https://<route>/signin/callback` to its OAuth redirect URIs;
     - allows the `authorization_code` and `refresh_token` grants;
     - (the same `oauth2-configuration` block as in the CALM API setup guide).

     Each consultant needs a user in the client's subaccount with the CALM API permissions. Someone who can't sign in, or has no CALM API permission there, gets "Access not granted".
7. **The connector's client ID and secret for Ken.** Do this together with Ken (for example on a screen share), so the secret goes straight into the connector dialog and nowhere else.

   ```bash
   cf create-service-key calm-mcp-claude-auth claude-connector -c '{"credential-type": "binding-secret"}'
   ```

   ```bash
   cf service-key calm-mcp-claude-auth claude-connector
   ```
8. **Ken adds the connector:** Organization settings → Connectors → Add → Custom → Web.
   - Name: SAP Cloud ALM.
   - URL: `https://<route>/mcp`.
   - Advanced settings: OAuth Client ID and Client Secret from step 7.
   - These sign-in settings can't be edited later. To change them, remove the connector and add it again.
9. **Test alone first.** Connect, sign in, then ask Claude:
   - "run calm_health": it should show `tenants` and our own CALM's address.
   - "which SAP Cloud ALM tenants can I use?"
10. **Roll out.** Add people to the role collection, and to the clients they work on (`scripts/btp_set_client.sh`; Enter keeps every other value).

## Day to day

| Task | How |
|---|---|
| Add a client, change who may use it (or `signin`), set a new key | `scripts/btp_set_client.sh` |
| Remove a client | `scripts/btp_set_client.sh --remove lutron` |
| Let someone use the connector at all | Add them to the role collection CALM MCP Claude |
| See who used which client | `cf logs syntax-calm-mcp --recent \| grep AUDIT` |
| Deploy a new version | `git pull`, then `cf push`. When tool descriptions changed, people reconnect the connector. |
| Cut everyone off | Delete the service key from step 7. Sign-ins already issued keep working until they expire (the subaccount's token lifetime). |
| Cut one person off | Remove them from the role collection and from the client lists. Their current sign-in lasts until it expires. |

## Good to know

- **Clients added from a chat** (`calm_admin_clients`) need a lasting disk, which Cloud Foundry doesn't have. Use the script, and don't set `CALM_TENANT_STORE` here.
- **People's sign-ins to `signin` clients** are kept in the app's memory here (no lasting disk): run one instance, and people sign in again after every restart, including the one `scripts/btp_set_client.sh` does.
- **Changes in a client's CALM** are made with that client's key, so CALM shows "API" and comments end "Added by <person> via AI agent".
- **Only claude.ai's return address is registered,** so Claude Code in a terminal can't sign in to this connector.
- **GenAI Studio's connection** is a separate deployment and is unaffected.
- **What wasn't tested yet:** a real sign-in with this subaccount's XSUAA, a real sign-in to a `signin` client's SAP, and the first `cf push` on BTP. The tests cover the code with generated keys, a faked SAP login and a stand-in `cf`.
