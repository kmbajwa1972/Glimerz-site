# Glimerz Pinterest OAuth reconnect helper

This is a **local-only** OAuth helper for reconnecting the existing Glimerz Pinterest app after an access/refresh token expires or becomes invalid.

Pinterest requires the redirect URI used in the authorization request and token exchange to exactly match the URI registered for the app. This helper therefore defaults to:

`http://localhost:3410/oauth/callback`

Pinterest's current Authorization Code flow uses the app ID/client ID plus client secret with HTTP Basic authentication when exchanging the authorization code. The helper follows that flow and does not put credentials, access tokens, refresh tokens, or the Supabase service-role key in source control. citeturn0search0turn0search1

## Setup

1. Make sure `http://localhost:3410/oauth/callback` is registered in the Pinterest app's Redirect URIs.
2. Copy `.env.example` to `.env`.
3. Fill in the Pinterest App ID and App Secret locally.
4. Fill in the Glimerz Supabase URL and **service-role key locally only**.
5. From this directory run:

```bash
npm start
```

6. Open `http://localhost:3410/`.
7. Click **Connect Pinterest** and approve the requested scopes.
8. The callback exchanges the fresh authorization code and updates the existing `platform_tokens` Pinterest row. It preserves the existing `board_id` so the current publisher does not need to be changed.

The helper requests only the Pinterest scopes needed for Glimerz organic Pin publishing and board selection: `boards:read`, `boards:write`, `pins:read`, `pins:write`, and `user_accounts:read`. Pinterest documents `boards:read`/`boards:write` and `pins:read`/`pins:write` for board and Pin management. citeturn1search1

## Security

- Never commit `.env`.
- Never paste the App Secret, authorization code, access token, or refresh token into chat or GitHub.
- The helper binds only to `127.0.0.1`.
- The Supabase service-role key is used only locally to update the protected token row.
- After a successful connection, close the browser window and keep the credentials private.

## Important

This helper does **not** modify `main`, Facebook, Instagram, `daily-agent`, or `publish-item`. It is intentionally isolated so the existing publishing system remains unchanged while Pinterest is reconnected.
