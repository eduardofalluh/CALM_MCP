# CALM MCP OAuth Support - Summary

**Status:** ✅ **READY FOR GENAI STUDIO INTEGRATION**

Branch: `oauth-testing` (GitHub & GitLab)

---

## What Was Done

Added **MCP OAuth 2.1 support** to the CALM MCP server per the [Model Context Protocol OAuth specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization).

**Key Changes:**
1. ✅ OAuth metadata endpoints (RFC 9728 / RFC 8414)
2. ✅ MCP tools for OAuth endpoint discovery
3. ✅ Comprehensive implementation guide for GenAI Studio team
4. ✅ Token handling already working (Authorization: Bearer header)

---

## What This Solves

### Before (Current)
```
User: Eduardo → GenAI Studio → MCP Server (service account) → CALM
                                       ↓
                         CALM History: "API" ❌
```

### After (With OAuth)
```
User: Eduardo → GenAI Studio → MCP Server (Eduardo's OAuth token) → CALM
                                       ↓
                         CALM History: "Eduardo Falluh" ✅
```

---

## What GenAI Studio Needs to Do

**3 Simple Steps:**

### 1. Get OAuth Credentials from SAP BTP
- Create new OAuth client in BTP Cockpit → Cloud ALM → Security → OAuth Clients
- Grant type: `authorization_code` + `refresh_token`
- Redirect URI: `https://studio.ai.syntax-rnd.com/oauth/calm/callback`

### 2. Implement User Login Flow
```javascript
// When user needs to authenticate:
redirectToCALM() {
  // Build OAuth URL with PKCE
  const authUrl = 'https://tenant.authentication.region.hana.ondemand.com/oauth/authorize?' +
    'response_type=code&client_id=XXX&redirect_uri=YYY&scope=openid&resource=ZZZ';
  
  // Redirect user to CALM login
  window.location = authUrl;
}

// When CALM redirects back with code:
async handleCallback(code) {
  // Exchange code for tokens
  const tokens = await fetch('https://tenant.authentication.region.hana.ondemand.com/oauth/token', {
    method: 'POST',
    body: 'grant_type=authorization_code&code=' + code + '&...'
  });
  
  // Store per-user: { access_token, refresh_token, expires_in: 43200 }
  await db.storeTokens(userId, tokens);
}
```

### 3. Send User Token in MCP Requests
```javascript
// Before calling MCP server:
const userToken = await getValidToken(userId);  // Auto-refreshes if expired

// Add to MCP request:
fetch('http://mcp-server:8000/mcp/v1/call', {
  headers: {
    'Authorization': `Bearer ${userToken}`,  // ← This is the key change!
  },
  body: JSON.stringify({ tool: 'create_calm_task', ... })
});
```

**That's it!** MCP server handles the rest.

---

## Token Lifecycle

**SAP Cloud ALM OAuth tokens:**
- Access token: **12 hours** (43,200 seconds)
- Refresh token: **~30 days** (tenant configurable)
- Refresh token **ROTATES** (new refresh token issued on each refresh)

**Refresh Implementation:**
```javascript
async function getValidToken(userId) {
  const stored = await db.getTokens(userId);
  
  // Check expiry (5 min buffer)
  if (stored.expiresAt > Date.now() + 300000) {
    return stored.accessToken;  // Still valid
  }
  
  // Refresh automatically
  const newTokens = await fetch(tokenEndpoint, {
    body: 'grant_type=refresh_token&refresh_token=' + stored.refreshToken
  });
  
  await db.storeTokens(userId, newTokens);  // Store NEW refresh token!
  return newTokens.access_token;
}
```

**User Experience:**
- With refresh: Login once per month ✅
- Without refresh: Re-login every 12 hours ❌

**Recommendation:** Implement refresh token support!

---

## Testing OAuth

### 1. Call MCP Tool to Get OAuth Endpoints
```json
{
  "tool": "get_calm_oauth_endpoints",
  "parameters": {}
}
```

Returns:
```json
{
  "authorization_endpoint": "https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com/oauth/authorize",
  "token_endpoint": "https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com/oauth/token",
  "implementation_guide": { ... }
}
```

### 2. Test User Login Flow
1. Redirect user to authorization_endpoint
2. User logs in with SAP credentials
3. CALM redirects back with code
4. Exchange code for tokens
5. Store tokens in database

### 3. Test MCP Request with User Token
```bash
curl http://mcp-server:8000/mcp/v1/call \
  -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIs..." \
  -H "Content-Type: application/json" \
  -d '{"tool":"create_calm_task","parameters":{...}}'
```

4. Check CALM History → Should show "Eduardo Falluh" ✅

---

## Documentation

**For GenAI Studio developers:**
📄 **[OAUTH_IMPLEMENTATION_GUIDE.md](./OAUTH_IMPLEMENTATION_GUIDE.md)** - Complete implementation guide with:
- Step-by-step OAuth flow code
- Token refresh implementation
- Security best practices
- Troubleshooting guide
- Testing instructions

**For Quick Reference:**
- MCP OAuth Spec: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
- RFC 9728 (Protected Resource Metadata): https://datatracker.ietf.org/doc/html/rfc9728
- RFC 8414 (Authorization Server Metadata): https://datatracker.ietf.org/doc/html/rfc8414

---

## Migration Strategy

### Phase 1: Test with oauth-testing Branch
- GenAI Studio points to `oauth-testing` branch
- Test OAuth flow with a few users
- Validate CALM History shows user names
- Keep service account as fallback

### Phase 2: Merge to Main
- Once validated, merge oauth-testing → main
- Deploy to production
- All new users use OAuth
- Existing service account still works (backward compatible)

### Phase 3: Migrate All Users
- Prompt existing users to login with OAuth
- Gradually deprecate service account

---

## Key Points

✅ **MCP server is OAuth-ready** (no further MCP changes needed)

✅ **Backward compatible** (existing service account still works)

✅ **Follows MCP OAuth specification** (RFC 9728/8414 compliant)

✅ **Supports refresh tokens** (SAP Cloud ALM confirmed support)

✅ **Complete implementation guide** (see OAUTH_IMPLEMENTATION_GUIDE.md)

✅ **Ready for GenAI Studio integration** (all endpoints exposed)

---

## Next Steps

**For GenAI Studio Team:**
1. Read [OAUTH_IMPLEMENTATION_GUIDE.md](./OAUTH_IMPLEMENTATION_GUIDE.md)
2. Get OAuth client credentials from SAP BTP
3. Implement user login flow (Step 1)
4. Implement token storage and refresh (Step 2)
5. Inject user token in MCP requests (Step 3)
6. Test with `oauth-testing` branch
7. Report results

**Timeline Estimate:**
- OAuth client registration: 1 hour
- Implementation: 2-3 days
- Testing: 1 day
- **Total: ~4 days**

---

## Questions?

Contact Eduardo or check the implementation guide. All OAuth endpoints are live on the `oauth-testing` branch.

**Branch URLs:**
- GitHub: https://github.com/eduardofalluh/CALM_MCP/tree/oauth-testing
- GitLab: https://gitlab.com/syntax-cloud/CloudAdmin/genai/third-parties/mcp-servers/mcp-sap-calm/-/tree/oauth-testing
