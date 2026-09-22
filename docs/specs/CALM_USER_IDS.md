# CALM User ID Mapping (Required for Assignment)

**CALM strictly requires UUIDs for assignee_id** - emails don't work. Since OAuth2 
lacks user-read permissions (403), manually add user UUIDs here.

## How to Get Your UUID (3 easy ways)

### Method 1: Browser Developer Tools (Fastest)
1. Open CALM → Your Project → Settings → Team
2. Press F12 → Network tab → Reload page
3. Find the request to `/projects/{id}/users` or `/members`
4. Click it → Preview → Find your email → Copy the `id` field (36-char UUID)

### Method 2: Postman
1. GET `https://illumiti-corp-cloudalm.eu10.alm.cloud.sap/api/calm-projects/v1/projects/9dd45151-4393-4b06-9998-208ef3cd66c6/users`
2. Headers: `Authorization: Bearer YOUR_TOKEN`
3. Find your email in response → copy `id` field

### Method 3: Ask Your Admin
SAP BTP Cockpit shows user IDs for project members.

---

## Project: Delivery Excellence - Syntax Sugar (TRAINING)
Project ID: `9dd45151-4393-4b06-9998-208ef3cd66c6`

**PASTE YOUR UUIDs BELOW (one per team member):**

| Email | CALM User ID (36-char UUID) | Name |
|-------|------------------------------|------|
| eduardo.falluh@syntax.com | `PASTE_36_CHAR_UUID_HERE` | Eduardo Falluh |
| yassine.selmi@syntax.com | `PASTE_36_CHAR_UUID_HERE` | Yassine Selmi |
| EXAMPLE@syntax.com | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` | Example Format |

---

## For Other Projects

Add sections below following the same format:

## Project: [Project Name]
Project ID: `[project-id]`

| Email | CALM User ID | Name |
|-------|--------------|------|
| email@domain.com | `uuid-here` | Display Name |
