# Glimerz TikTok integration

This feature branch adds TikTok OAuth and Content Posting API support for the Glimerz automated social publishing bot.

## Web Login Kit redirect URI

Use this exact URI after the `tiktok-oauth` Edge Function is deployed:

`https://yayljmqelmsmcsuhxqdj.supabase.co/functions/v1/tiktok-oauth/callback`

The matching OAuth start URL is:

`https://yayljmqelmsmcsuhxqdj.supabase.co/functions/v1/tiktok-oauth/authorize`

## Required Supabase secrets

- `TIKTOK_CLIENT_KEY`
- `TIKTOK_CLIENT_SECRET`
- `TIKTOK_OAUTH_STATE_SECRET`
- `SB_URL`
- `SB_SERVICE_ROLE_KEY`
- `TIKTOK_REDIRECT_URI` (optional; defaults to the callback above)
- `TIKTOK_SCOPES` (optional; defaults to `user.info.basic,video.publish`)

Never commit these values.

## Portal configuration

Use Login Kit for Web and Content Posting API with Direct Post. Request only the scopes actually demonstrated during review.

The planned Glimerz publisher uses TikTok's Content Posting API photo Direct Post with public image URLs from glimerz.com. TikTok requires the media URL domain/prefix to be verified before using `PULL_FROM_URL`.

The publisher should query creator information first and use a privacy level returned by TikTok. Until the client is approved/audited, TikTok may restrict API-posted content to private viewing.
