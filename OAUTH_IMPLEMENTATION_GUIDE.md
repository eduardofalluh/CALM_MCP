# CALM MCP OAuth Implementation Guide

**For GenAI Studio Team**

This guide explains how to implement user-delegated OAuth for the CALM MCP server so that CALM History shows actual user names instead of "API".

---

## Quick Start

**TL;DR:** The MCP server is **already OAuth-ready**. GenAI Studio just needs to:

1. Get an OAuth client ID/secret from SAP BTP
2. Redirect users to CALM's OAuth login
3. Store per-user tokens
4. Send `Authorization: Bearer <user_token>` in MCP request headers

---

## Table of Contents

1. [Why OAuth?](#why-oauth)
2. [Architecture Overview](#architecture-overview)
3. [Prerequisites](#prerequisites)
4. [OAuth Flow Implementation](#oauth-flow-implementation)
5. [Token Refresh Implementation](#token-refresh-implementation)
6. [MCP Integration](#mcp-integration)
7. [Testing](#testing)
8. [Security Considerations](#security-considerations)

---

## Why OAuth?

### Current Problem (Service Account)

```
User: Eduardo → GenAI Studio → MCP Server (API token) → CALM
                                    ↓
                          CALM History shows: "API"
```

- All users share one service account token
- CALM sees all actions as "API"
- No per-user audit trail

### Solution (User-Delegated OAuth)

```
User: Eduardo → GenAI Studio → MCP Server (Eduardo's token) → CALM
                                    ↓
                          CALM History shows: "Eduardo Falluh"
```

- Each user has their own OAuth token
- CALM sees each user's actual identity
- Full audit trail with real user names

---

## Architecture Overview

### What Changes

**MCP Server:** ✅ Already supports OAuth tokens (no changes needed!)

**GenAI Studio:** Needs to implement:
1. OAuth login flow (redirect user to CALM)
2. Token storage (per-user database)
3. Token refresh (background process)
4. Header injection (send user's token in MCP requests)

### OAuth Endpoints (CALM)

The MCP server exposes these discovery endpoints:

```
GET https://your-mcp-server/.well-known/oauth-protected-resource
GET https://your-mcp-server/.well-known/oauth-authorization-server
```

Or use the MCP tool:

```json
{
  "tool": "get_calm_oauth_endpoints",
  "parameters": {}
}
```

**For illumiti-corp-cloudalm tenant (eu10 region):**

```json
{
  "tenant": "illumiti-corp-cloudalm",
  "region": "eu10",
  "authorization_endpoint": "https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com/oauth/authorize",
  "token_endpoint": "https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com/oauth/token",
  "revocation_endpoint": "https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com/oauth/revoke",
  "issuer": "https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com",
  "resource": "https://illumiti-corp-cloudalm.eu10.alm.cloud.sap"
}
```

---

## Prerequisites

### 1. OAuth Client Registration (SAP BTP)

You need OAuth client credentials from SAP BTP:

1. Log into **SAP BTP Cockpit**
2. Navigate to **Subscriptions** → **Cloud ALM**
3. Go to **Security** → **OAuth Clients**
4. Click **Create New Client**
5. Configure:
   - **Grant Types:** `authorization_code`, `refresh_token`
   - **Redirect URIs:** `https://studio.ai.syntax-rnd.com/oauth/calm/callback`
   - **Scopes:** `openid` (minimal - more requested via step-up)
   - **Token Lifetime:** Default (12 hours access, 30 days refresh)

6. Save the credentials:
   ```
   Client ID: <your-client-id>
   Client Secret: <your-client-secret>
   ```

**⚠️ Important:** This is a DIFFERENT OAuth client than your service account!
- Service account: Client Credentials flow (app → CALM)
- User OAuth: Authorization Code flow (user → CALM via GenAI Studio)

---

## OAuth Flow Implementation

### Step 1: Redirect User to CALM Login

When a user needs to authenticate (first login, token expired):

```javascript
// GenAI Studio backend
import crypto from 'crypto';

function redirectToCALMOAuth(req, res) {
  // 1. Generate PKCE parameters (security)
  const codeVerifier = crypto.randomBytes(32).toString('base64url');
  const codeChallenge = crypto
    .createHash('sha256')
    .update(codeVerifier)
    .digest('base64url');

  // 2. Generate state (CSRF protection)
  const state = crypto.randomBytes(16).toString('hex');

  // 3. Store verifier and state in session (needed for step 2)
  req.session.pkce = { codeVerifier, state };

  // 4. Build authorization URL
  const params = new URLSearchParams({
    response_type: 'code',
    client_id: process.env.CALM_OAUTH_CLIENT_ID,
    redirect_uri: 'https://studio.ai.syntax-rnd.com/oauth/calm/callback',
    scope: 'openid',
    state: state,
    code_challenge: codeChallenge,
    code_challenge_method: 'S256',
    // RFC 8707: Resource parameter (identifies the MCP server)
    resource: 'https://illumiti-corp-cloudalm.eu10.alm.cloud.sap',
  });

  const authUrl = `https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com/oauth/authorize?${params}`;

  // 5. Redirect user to CALM login
  res.redirect(authUrl);
}
```

**What happens:**
1. User's browser is redirected to CALM
2. User logs in with their SAP credentials
3. CALM redirects back to your callback URL with an authorization code

---

### Step 2: Exchange Code for Tokens

CALM redirects to: `https://studio.ai.syntax-rnd.com/oauth/calm/callback?code=ABC123&state=xyz`

```javascript
// GenAI Studio backend - callback handler
async function handleCALMOAuthCallback(req, res) {
  const { code, state, iss } = req.query;

  // 1. Validate state (CSRF protection)
  if (state !== req.session.pkce?.state) {
    throw new Error('Invalid state parameter - possible CSRF attack');
  }

  // 2. Validate issuer (RFC 9207)
  const expectedIssuer = 'https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com';
  if (iss && iss !== expectedIssuer) {
    throw new Error('Invalid issuer - possible token confusion attack');
  }

  // 3. Exchange authorization code for tokens
  const tokenResponse = await fetch(
    'https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com/oauth/token',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        code: code,
        redirect_uri: 'https://studio.ai.syntax-rnd.com/oauth/calm/callback',
        client_id: process.env.CALM_OAUTH_CLIENT_ID,
        client_secret: process.env.CALM_OAUTH_CLIENT_SECRET,
        code_verifier: req.session.pkce.codeVerifier,
        resource: 'https://illumiti-corp-cloudalm.eu10.alm.cloud.sap',
      }),
    }
  );

  const tokens = await tokenResponse.json();
  /*
  {
    "access_token": "eyJhbGciOiJSUzI1NiIs...",
    "refresh_token": "def50200ab12cd34ef56...",
    "expires_in": 43200,  // 12 hours
    "token_type": "Bearer",
    "scope": "openid"
  }
  */

  // 4. Store tokens in database (per user)
  await db.storeUserTokens(req.user.id, {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    expiresAt: Date.now() + tokens.expires_in * 1000,
    scope: tokens.scope,
  });

  // 5. Clean up session
  delete req.session.pkce;

  // 6. Redirect to chat
  res.redirect('/chat?oauth=success');
}
```

**Token Storage Schema:**

```sql
CREATE TABLE user_calm_tokens (
  user_id VARCHAR(255) PRIMARY KEY,
  access_token TEXT NOT NULL,
  refresh_token TEXT NOT NULL,
  expires_at BIGINT NOT NULL,  -- Unix timestamp
  scope TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Token Refresh Implementation

SAP Cloud ALM access tokens expire after 12 hours. Implement automatic refresh:

```javascript
// GenAI Studio backend - token manager
async function getValidCALMToken(userId) {
  const stored = await db.getUserTokens(userId);

  if (!stored) {
    throw new Error('User not authenticated - redirect to OAuth login');
  }

  // Check if token is expired or will expire soon (5 min buffer)
  const expiresIn = stored.expiresAt - Date.now();
  if (expiresIn > 5 * 60 * 1000) {
    // Token still valid
    return stored.accessToken;
  }

  // Token expired or expiring soon - refresh it
  console.log(`Refreshing CALM token for user ${userId}`);

  try {
    const tokenResponse = await fetch(
      'https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com/oauth/token',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: new URLSearchParams({
          grant_type: 'refresh_token',
          refresh_token: stored.refreshToken,
          client_id: process.env.CALM_OAUTH_CLIENT_ID,
          client_secret: process.env.CALM_OAUTH_CLIENT_SECRET,
          resource: 'https://illumiti-corp-cloudalm.eu10.alm.cloud.sap',
        }),
      }
    );

    if (!tokenResponse.ok) {
      // Refresh token expired - user needs to re-authenticate
      await db.deleteUserTokens(userId);
      throw new Error('Refresh token expired - user needs to login again');
    }

    const tokens = await tokenResponse.json();
    /*
    {
      "access_token": "eyJhbGciOiJSUzI1NiIs...",
      "refresh_token": "ghi78900jk12lm34no56...",  // New refresh token!
      "expires_in": 43200,
      "token_type": "Bearer"
    }
    */

    // Update stored tokens (refresh token rotates!)
    await db.storeUserTokens(userId, {
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token,  // Store the NEW refresh token
      expiresAt: Date.now() + tokens.expires_in * 1000,
    });

    return tokens.access_token;
  } catch (error) {
    // Refresh failed - delete stored tokens and force re-authentication
    await db.deleteUserTokens(userId);
    throw error;
  }
}
```

**⚠️ Important:** SAP Cloud ALM uses **refresh token rotation**. Each time you refresh, you get a NEW refresh token. Always store the new one!

---

## MCP Integration

### Inject User Token in MCP Requests

When GenAI Studio calls the CALM MCP server, inject the user's OAuth token:

```javascript
// GenAI Studio - MCP client
async function callCALMMCP(userId, tool, parameters) {
  // 1. Get valid token (auto-refreshes if needed)
  const userToken = await getValidCALMToken(userId);

  // 2. Call MCP server with user's token
  const response = await fetch('http://mcp-server:8000/mcp/v1/call', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      // 🔑 This is the key change - pass user's token!
      'Authorization': `Bearer ${userToken}`,
    },
    body: JSON.stringify({
      tool: tool,
      parameters: parameters,
    }),
  });

  return response.json();
}
```

**That's it!** The MCP server already:
- Accepts `Authorization: Bearer` header (line 76 in dependencies.py)
- Extracts the token and uses it for all CALM API calls
- CALM sees the user's identity from the token

---

## Testing

### 1. Test OAuth Endpoints Discovery

```bash
curl https://your-mcp-server/.well-known/oauth-protected-resource
```

Expected response:
```json
{
  "resource": "https://illumiti-corp-cloudalm.eu10.alm.cloud.sap",
  "authorization_servers": [
    "https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com"
  ],
  "scopes_supported": ["openid"]
}
```

### 2. Test OAuth Flow in Browser

1. Navigate to: `https://studio.ai.syntax-rnd.com/connect-calm`
2. Should redirect to CALM login
3. Log in with your SAP credentials
4. Should redirect back with a code
5. Check database - tokens should be stored

### 3. Test MCP Request with User Token

```javascript
// Get Eduardo's token from database
const eduardoToken = await db.getUserTokens('eduardo.falluh@syntax.com');

// Call MCP server
const response = await fetch('http://mcp-server:8000/mcp/v1/call', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${eduardoToken.accessToken}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    tool: 'create_calm_task',
    parameters: {
      project_id: '9dd45151-4393-4b06-9998-208ef3cd66c6',
      title: 'OAuth Test Task',
      task_type: 'Project Task',
      assignee_id: 'eduardo.falluh@syntax.com',
      acting_user_email: 'eduardo.falluh@syntax.com',
    },
  }),
});

const result = await response.json();
console.log(result);
```

4. Check CALM History - should show "Eduardo Falluh" instead of "API" ✅

### 4. Test Token Refresh

```javascript
// Manually expire the token
await db.query(
  'UPDATE user_calm_tokens SET expires_at = $1 WHERE user_id = $2',
  [Date.now() - 1000, 'eduardo.falluh@syntax.com']
);

// Call MCP - should automatically refresh
const token = await getValidCALMToken('eduardo.falluh@syntax.com');
console.log('Token refreshed:', token);
```

---

## Security Considerations

### 1. Token Storage

**❌ DON'T:**
- Store tokens in browser localStorage (XSS vulnerable)
- Log tokens to console or files
- Send tokens in URL query parameters

**✅ DO:**
- Store tokens in encrypted database
- Use HTTP-only secure cookies for session management
- Implement token encryption at rest

```javascript
// Example: Encrypt tokens before storing
import crypto from 'crypto';

const ENCRYPTION_KEY = process.env.TOKEN_ENCRYPTION_KEY; // 32 bytes

function encryptToken(token) {
  const iv = crypto.randomBytes(16);
  const cipher = crypto.createCipheriv('aes-256-gcm', ENCRYPTION_KEY, iv);
  const encrypted = Buffer.concat([cipher.update(token, 'utf8'), cipher.final()]);
  const authTag = cipher.getAuthTag();
  return Buffer.concat([iv, authTag, encrypted]).toString('base64');
}

function decryptToken(encryptedToken) {
  const buffer = Buffer.from(encryptedToken, 'base64');
  const iv = buffer.slice(0, 16);
  const authTag = buffer.slice(16, 32);
  const encrypted = buffer.slice(32);
  const decipher = crypto.createDecipheriv('aes-256-gcm', ENCRYPTION_KEY, iv);
  decipher.setAuthTag(authTag);
  return decipher.update(encrypted) + decipher.final('utf8');
}
```

### 2. PKCE (Proof Key for Code Exchange)

Always use PKCE for OAuth flows. The code above includes it:
- `code_challenge`: SHA256 hash of a random string
- `code_verifier`: The original random string (sent in token request)

This prevents authorization code interception attacks.

### 3. State Parameter

Always validate the `state` parameter to prevent CSRF:
```javascript
if (state !== req.session.pkce?.state) {
  throw new Error('Invalid state - possible CSRF attack');
}
```

### 4. Issuer Validation (RFC 9207)

Always validate the `iss` parameter in the authorization response:
```javascript
if (iss && iss !== expectedIssuer) {
  throw new Error('Invalid issuer - possible mix-up attack');
}
```

### 5. Token Scope

Start with minimal scope (`openid`) and request additional permissions via step-up authorization when needed. The MCP server will return `403 Forbidden` with required scopes if needed.

---

## User Experience

### With Refresh Token (Recommended)

```
Day 1: User logs in with SAP credentials
       ↓
       Tokens stored (access: 12h, refresh: 30 days)
       ↓
Day 1-30: GenAI Studio auto-refreshes access token every 12h
          User works seamlessly, no interruption
       ↓
Day 30: Refresh token expires
       ↓
       User prompted: "Your CALM session expired, please login again"
```

**User sees:** Login once per month ✅

### Without Refresh Token (Fallback)

```
Day 1: User logs in
       ↓
       Access token stored (12h only)
       ↓
12 hours later: Access token expires
       ↓
       User prompted: "Please login to CALM again"
```

**User sees:** Re-login every 12 hours ❌

**Recommendation:** Implement refresh token support!

---

## Migration Path

### Phase 1: Add OAuth Support (Keep Service Account)

1. Implement OAuth login flow
2. Store per-user tokens
3. Use user token when available, fall back to service account
4. Test with a few users

```javascript
async function getCALMToken(userId) {
  // Try user OAuth token first
  const userToken = await db.getUserTokens(userId);
  if (userToken && userToken.expiresAt > Date.now()) {
    return userToken.accessToken;
  }

  // Fall back to service account
  return process.env.CALM_SERVICE_ACCOUNT_TOKEN;
}
```

### Phase 2: Require OAuth for All Users

1. Remove service account fallback
2. Prompt all users to login
3. Monitor success rate

### Phase 3: Deprecate Service Account

1. Revoke service account credentials
2. OAuth-only

---

## Troubleshooting

### Error: "Invalid redirect_uri"

**Problem:** OAuth client not configured with correct redirect URI

**Solution:** Add `https://studio.ai.syntax-rnd.com/oauth/calm/callback` to allowed redirect URIs in SAP BTP OAuth client settings

### Error: "Invalid grant" during refresh

**Problem:** Refresh token expired or revoked

**Solution:** Delete stored tokens, prompt user to re-authenticate

```javascript
await db.deleteUserTokens(userId);
res.redirect('/connect-calm');
```

### Error: "Invalid audience" when calling CALM API

**Problem:** Access token not issued for CALM resource

**Solution:** Include `resource` parameter in both authorization and token requests:
```javascript
resource: 'https://illumiti-corp-cloudalm.eu10.alm.cloud.sap'
```

### CALM History still shows "API"

**Problem:** GenAI Studio not sending user token

**Solution:** Verify Authorization header is set:
```javascript
console.log('Sending token:', userToken.substring(0, 20) + '...');
// Should see: "Sending token: eyJhbGciOiJSUzI1NiIs..."
```

---

## Summary

✅ **MCP Server:** Already OAuth-ready (accepts `Authorization: Bearer` header)

✅ **GenAI Studio needs to implement:**
1. OAuth login flow (redirect user → exchange code → store tokens)
2. Token refresh (every 12 hours, automatic in background)
3. Header injection (send user's token in MCP requests)

✅ **Result:** CALM History shows "Eduardo Falluh" instead of "API"

✅ **User Experience:** Login once per month (with refresh token support)

---

## References

- [MCP OAuth Specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- [OAuth 2.1 (IETF Draft)](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-13)
- [RFC 9728 - OAuth 2.0 Protected Resource Metadata](https://datatracker.ietf.org/doc/html/rfc9728)
- [RFC 8414 - OAuth 2.0 Authorization Server Metadata](https://datatracker.ietf.org/doc/html/rfc8414)
- [RFC 8707 - Resource Indicators for OAuth 2.0](https://www.rfc-editor.org/rfc/rfc8707.html)
- [RFC 9207 - OAuth 2.0 Authorization Server Issuer Identification](https://datatracker.ietf.org/doc/html/rfc9207)
- [SAP Cloud ALM API Documentation](https://help.sap.com/docs/cloud-alm-api)

---

## Need Help?

Contact the MCP server maintainer or check the MCP server logs for OAuth-related errors.
