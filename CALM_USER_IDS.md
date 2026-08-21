# CALM User ID Mapping (Workaround for 403)

Since the OAuth2 client lacks permission to query project users, manually map emails to CALM user IDs here.

Get user IDs from CALM UI:
1. Go to Project Settings → Team
2. Inspect network tab when page loads
3. Find the user list API call
4. Extract user IDs

## Project: Delivery Excellence - Syntax Sugar (TRAINING)
Project ID: `9dd45151-4393-4b06-9998-208ef3cd66c6`

| Email | CALM User ID | Name |
|-------|--------------|------|
| eduardo.falluh@syntax.com | `PASTE_ID_HERE` | Eduardo Falluh |
| user2@syntax.com | `PASTE_ID_HERE` | User 2 Name |

## Instructions for Agent

When assigning tasks, if `get_calm_project_users` fails with 403:
1. Read this file
2. Look up the user's ID by email
3. Use that ID for assignee_id
4. Log a warning that manual mapping was used
