import http from 'node:http';
import crypto from 'node:crypto';
import { URL, URLSearchParams } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';

function loadEnv() {
  const file = path.join(process.cwd(), '.env');
  if (!fs.existsSync(file)) return;
  for (const raw of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const i = line.indexOf('=');
    if (i < 1) continue;
    const key = line.slice(0, i).trim();
    let value = line.slice(i + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    if (!process.env[key]) process.env[key] = value;
  }
}
loadEnv();

const APP_ID = process.env.PINTEREST_APP_ID;
const APP_SECRET = process.env.PINTEREST_APP_SECRET;
const REDIRECT_URI = process.env.PINTEREST_REDIRECT_URI || 'http://localhost:3410/oauth/callback';
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
const SCOPES = process.env.PINTEREST_SCOPES || 'boards:read boards:write pins:read pins:write user_accounts:read';
const PORT = Number(process.env.PORT || 3410);

if (!APP_ID || !APP_SECRET || !SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY) {
  console.error('Missing required .env values. Copy .env.example to .env and fill them locally.');
  process.exit(1);
}

const states = new Set();
const html = (title, body) => `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title><style>body{font-family:system-ui;max-width:720px;margin:60px auto;padding:20px;line-height:1.6}code{background:#f4f4f4;padding:2px 5px}h1{font-size:28px}a,button{display:inline-block;padding:10px 16px;border-radius:6px;border:1px solid #ccc;background:#fff;text-decoration:none;cursor:pointer}button{font:inherit}</style></head><body>${body}</body></html>`;

function authUrl() {
  const state = crypto.randomBytes(24).toString('hex');
  states.add(state);
  const u = new URL('https://www.pinterest.com/oauth/');
  u.searchParams.set('client_id', APP_ID);
  u.searchParams.set('redirect_uri', REDIRECT_URI);
  u.searchParams.set('response_type', 'code');
  u.searchParams.set('scope', SCOPES);
  u.searchParams.set('state', state);
  return u.toString();
}

async function exchangeCode(code) {
  const basic = Buffer.from(`${APP_ID}:${APP_SECRET}`, 'utf8').toString('base64');
  const body = new URLSearchParams({ grant_type: 'authorization_code', code, redirect_uri: REDIRECT_URI });
  const r = await fetch('https://api.pinterest.com/v5/oauth/token', {
    method: 'POST',
    headers: { Authorization: `Basic ${basic}`, 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  const text = await r.text();
  let data; try { data = JSON.parse(text); } catch { data = { raw: text }; }
  if (!r.ok) throw new Error(`Pinterest token exchange failed (${r.status}). ${JSON.stringify(data)}`);
  return data;
}

async function pinterestGet(accessToken, endpoint) {
  const r = await fetch(`https://api.pinterest.com/v5/${endpoint}`, { headers: { Authorization: `Bearer ${accessToken}` } });
  const text = await r.text();
  let data; try { data = JSON.parse(text); } catch { data = { raw: text }; }
  if (!r.ok) throw new Error(`Pinterest API failed (${r.status}). ${JSON.stringify(data)}`);
  return data;
}

async function getExistingConfig() {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/platform_tokens?platform=eq.pinterest&select=config&limit=1`, {
    headers: { apikey: SUPABASE_SERVICE_ROLE_KEY, Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}` },
  });
  if (!r.ok) throw new Error(`Supabase read failed (${r.status}).`);
  const rows = await r.json();
  return rows[0]?.config || {};
}

async function saveToken(token, config) {
  const expiresAt = new Date(Date.now() + Number(token.expires_in || 0) * 1000).toISOString();
  const payload = {
    platform: 'pinterest',
    access_token: token.access_token,
    refresh_token: token.refresh_token || null,
    expires_at: expiresAt,
    config,
    updated_at: new Date().toISOString(),
  };
  const headers = {
    apikey: SUPABASE_SERVICE_ROLE_KEY,
    Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
    'Content-Type': 'application/json',
  };
  const check = await fetch(`${SUPABASE_URL}/rest/v1/platform_tokens?platform=eq.pinterest&select=platform&limit=1`, { headers });
  if (!check.ok) throw new Error(`Supabase lookup failed (${check.status}).`);
  const rows = await check.json();
  const url = `${SUPABASE_URL}/rest/v1/platform_tokens?platform=eq.pinterest`;
  const r = rows.length
    ? await fetch(url, { method: 'PATCH', headers: { ...headers, Prefer: 'return=minimal' }, body: JSON.stringify(payload) })
    : await fetch(`${SUPABASE_URL}/rest/v1/platform_tokens`, { method: 'POST', headers: { ...headers, Prefer: 'return=minimal' }, body: JSON.stringify(payload) });
  if (!r.ok) throw new Error(`Supabase token save failed (${r.status}). ${await r.text()}`);
  return expiresAt;
}

async function callback(code, state) {
  if (!state || !states.has(state)) throw new Error('Invalid or expired OAuth state. Start the connection again.');
  states.delete(state);
  if (!code) throw new Error('Pinterest did not return an authorization code.');
  const token = await exchangeCode(code);
  const existingConfig = await getExistingConfig();
  let boardId = existingConfig.board_id;
  let boards = [];
  try {
    const data = await pinterestGet(token.access_token, 'boards?page_size=250');
    boards = data.items || [];
    if (!boardId && boards.length === 1) boardId = boards[0].id;
  } catch (e) {
    console.warn('Could not read boards:', e.message);
  }
  if (!boardId) throw new Error('OAuth succeeded, but no existing board_id was found. Add a board_id to platform_tokens.config or grant boards:read and rerun.');
  const expiresAt = await saveToken(token, { ...existingConfig, board_id: boardId });
  return { expiresAt, boardId, boardName: boards.find(b => b.id === boardId)?.name || null, scopes: token.scope || null };
}

const server = http.createServer(async (req, res) => {
  try {
    const u = new URL(req.url, `http://localhost:${PORT}`);
    if (u.pathname === '/') {
      const link = authUrl();
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
      res.end(html('Glimerz Pinterest Connect', `<h1>Connect Glimerz to Pinterest</h1><p>This local helper will authorize the existing Glimerz Pinterest app and save the new token securely into Supabase.</p><p><a href="${link}">Connect Pinterest</a></p><p>Callback: <code>${REDIRECT_URI}</code></p>`));
      return;
    }
    if (u.pathname === '/oauth/callback') {
      const result = await callback(u.searchParams.get('code'), u.searchParams.get('state'));
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
      res.end(html('Pinterest Connected', `<h1>Pinterest connected</h1><p>Glimerz has a fresh Pinterest OAuth token stored in Supabase.</p><p><strong>Board:</strong> ${result.boardName || result.boardId}</p><p><strong>Access token expires:</strong> ${result.expiresAt}</p><p>You can close this window. Do not copy or share the token.</p>`));
      return;
    }
    res.writeHead(404); res.end('Not found');
  } catch (e) {
    res.writeHead(500, { 'content-type': 'text/html; charset=utf-8' });
    res.end(html('Pinterest OAuth Error', `<h1>Connection failed</h1><p>${String(e.message || e).replaceAll('<','&lt;')}</p><p><a href="/">Try again</a></p>`));
  }
});

server.listen(PORT, '127.0.0.1', () => console.log(`Pinterest OAuth helper running at http://localhost:${PORT}/`));
