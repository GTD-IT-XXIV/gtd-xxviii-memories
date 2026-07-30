# GTD Face Review

Internal Next.js app for reviewing and labeling face clusters produced by the
separate offline Python face-recognition pipeline (scan -> detect -> embed ->
cluster). This app is the read/write "backend" (via Next.js Route Handlers /
Server Components) and UI organizers use to name clusters and browse results.
It does not run any long-lived server process of its own -- it's meant to be
deployed on Vercel.

## Data ownership

This app **does not create or migrate any database schema**. It assumes the
`photos`, `clusters`, and `faces` tables already exist in Postgres, created
and maintained by the separate Python pipeline. It only ever runs
`SELECT`/`UPDATE` statements against that existing schema.

It also assumes photo originals and thumbnails have already been uploaded to
a Cloudflare R2 bucket by that same pipeline, keyed by `photos.r2_key` /
`photos.r2_thumbnail_key` / `clusters.r2_thumbnail_key`.

## Required environment variables

See `.env.example`. All of these must be set for the app to function --
there are no fallback/mock modes:

- `DATABASE_URL` -- Neon Postgres connection string.
- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`
  -- Cloudflare R2 credentials. The bucket is private; the app generates
  short-lived (1 hour) presigned GET URLs server-side for every image it
  displays, rather than exposing a public bucket URL.
- `TELEGRAM_BOT_USERNAME`, `TELEGRAM_BOT_TOKEN`, `SESSION_SECRET` -- gate the
  whole app behind Telegram login. See "Authentication" below.

## Running locally

```bash
npm install
cp .env.example .env.local   # then fill in real values
npm run db:init-allowlist    # one-time: creates the allowed_reviewers table
npm run dev
```

Open http://localhost:3000.

## Authentication

The entire app (every page and API route except `/login` itself and the
Telegram callback) is gated behind **Telegram Login** -- the official
["Login with Telegram" web widget](https://core.telegram.org/widgets/login),
restricted to a predefined allowlist stored in Postgres. There is no
password / email login; only Telegram accounts an admin has explicitly
allowed can get in.

### 1. One-time: create a Telegram bot (manual prerequisite)

This app does not, and cannot, create the Telegram bot for you. A human
must do this once via Telegram:

1. Message [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`,
   and follow the prompts to create a bot. Note the bot's `@username` and
   the token BotFather gives you.
2. Send BotFather `/setdomain` and pick your bot, then give it the exact
   domain this app is deployed at (e.g. `review.example.com`, no
   `https://`, no trailing slash). The Login Widget only works on the
   domain registered this way. For local development you'll need a
   publicly reachable domain/tunnel (e.g. ngrok) pointed at
   `localhost:3000`, since Telegram's widget won't talk to plain
   `localhost`.
3. Set the env vars:
   - `TELEGRAM_BOT_USERNAME` = the bot's `@username`, without the `@`.
   - `TELEGRAM_BOT_TOKEN` = the token from BotFather. Server-side secret
     only -- never exposed to the client.

### 2. One-time: generate a session secret

```bash
openssl rand -base64 32
```

Set the result as `SESSION_SECRET`. This signs the session cookie (a JWT,
via the `jose` library) issued after a successful, allowlisted login.

### 3. Allowlist setup -- who's allowed to log in

The allowlist lives in a Postgres table this app owns and creates itself
(`allowed_reviewers` -- **not** part of the `photos`/`clusters`/`faces`
schema owned by the Python pipeline in `backend/`, and not touched by it).

Create the table once per database:

```bash
npm run db:init-allowlist
```

This reads `DATABASE_URL` from `web/.env.local` and runs
[`sql/001_allowed_reviewers.sql`](./sql/001_allowed_reviewers.sql), which is
a plain, idempotent `CREATE TABLE IF NOT EXISTS` -- safe to re-run, and also
safe to just paste into the Neon SQL console or run via `psql` yourself if
you'd rather not use the script. Run this once per environment (e.g. once
against your Production Neon database, once against a dev/preview one, if
you use separate databases).

Table shape:

```sql
CREATE TABLE allowed_reviewers (
  id                 BIGSERIAL PRIMARY KEY,
  telegram_user_id   BIGINT UNIQUE,   -- Telegram's numeric id (nullable, see below)
  telegram_username  TEXT UNIQUE,     -- lowercase, no leading "@" (nullable, see below)
  display_name       TEXT,            -- optional human label, e.g. "Audria - BFM lead"
  added_at           TIMESTAMPTZ NOT NULL DEFAULT now()
  -- (plus a CHECK that at least one of the two id columns is set)
);
```

**Adding a person, as a non-technical admin:** open the Neon SQL console (or
ask someone technical to run one `INSERT` for you) and use one of:

- **You know their numeric Telegram ID** (e.g. they already tried to log in
  once and you saw the rejection in the server logs, or you got it from
  another bot):
  ```sql
  INSERT INTO allowed_reviewers (telegram_user_id, display_name)
  VALUES (123456789, 'Audria - BFM lead');
  ```
- **You only know their `@username`** (the common case -- pre-authorizing
  someone before they've ever logged in). Use their username in lowercase,
  without the `@`:
  ```sql
  INSERT INTO allowed_reviewers (telegram_username, display_name)
  VALUES ('audria_bfm', 'Audria - BFM lead');
  ```
  The first time that person logs in, the app automatically fills in their
  real numeric `telegram_user_id` on this same row -- you don't need to do
  anything else, and their access keeps working even if they later change
  their `@username`.

  Note: a Telegram account without a public `@username` set can only be
  pre-authorized by numeric ID, since Telegram never reveals a username
  that doesn't exist.

To remove access, delete the row: `DELETE FROM allowed_reviewers WHERE telegram_username = 'audria_bfm';`
(or `WHERE telegram_user_id = 123456789`).

### How it works, briefly

- `/login` embeds Telegram's widget script. On success, Telegram redirects
  the browser to `GET /api/auth/telegram/callback` with a signed payload
  (`id`, `username`, `auth_date`, `hash`, ...).
- That Route Handler verifies the signature server-side using
  `TELEGRAM_BOT_TOKEN` (HMAC-SHA256 over the sorted fields, constant-time
  compare, `auth_date` freshness check per Telegram's documented
  algorithm), then checks `allowed_reviewers`.
- If allowed, it signs a short-lived (7 day) JWT session cookie (`jose`,
  `HttpOnly`, `Secure` in production, `SameSite=Lax`) and redirects to
  `/review`. If not, it redirects to `/login?error=not_authorized` with a
  clear message.
- `src/proxy.ts` (Next.js 16 renamed `middleware.ts` to `proxy.ts` -- same
  mechanism, see `node_modules/next/dist/docs/.../16-proxy.md`) runs on
  every request except `/login`, the two auth routes, and Next's static
  assets, and redirects to `/login` if the session cookie is missing or
  invalid.
- `POST /api/auth/logout` clears the cookie; the "Log out" link in the
  header posts to it.

## Pages

- `/login` -- Telegram Login Widget. Shows a clear error (e.g. "not
  authorized") if verification fails or the account isn't on the allowlist.
- `/review` -- main workflow. Paginated list of `unlabeled` clusters (sorted
  by face count, descending), each with a recommended match against existing
  `labeled` clusters (cosine similarity of centroids, computed server-side
  in Node -- no vector DB extension needed at this scale). Reviewers can
  accept the suggestion, correct it (search / tab-by-group / free-text new
  name), or discard the cluster as not-a-person.
- `/persons` -- distinct labeled people with photo counts and a
  representative thumbnail.
- `/persons/[name]` -- paginated photo gallery for one person.

All of the above except `/login` require a logged-in, allowlisted session
(enforced by `src/proxy.ts`).

Labeling/discarding goes through:

- `POST /api/clusters/[id]/name` -- body `{ person_name, og? }`, sets
  `status = 'labeled'`.
- `POST /api/clusters/[id]/discard` -- sets `status = 'discarded'`.

Auth-related routes:

- `GET /api/auth/telegram/callback` -- Telegram redirects here after widget
  login; verifies the signature, checks the allowlist, sets the session
  cookie.
- `POST /api/auth/logout` -- clears the session cookie.

## Stack

- Next.js App Router + TypeScript. Note: this project is on **Next.js 16**,
  which renamed `middleware.ts` to `proxy.ts` (see `src/proxy.ts`) and made
  several other breaking changes vs. older Next.js docs/training data --
  when in doubt, check `node_modules/next/dist/docs/` before assuming an
  older API shape.
- `@neondatabase/serverless` (Neon's HTTP-based driver) for Postgres access
  via raw parameterized SQL -- no ORM, since the `photos`/`clusters`/`faces`
  schema is small, fixed, and owned by the Python pipeline. The
  `allowed_reviewers` table (owned by this app, see "Authentication" above)
  is queried the same way.
- `@aws-sdk/client-s3` + `@aws-sdk/s3-request-presigner` for R2 presigned
  URLs (R2 is S3-compatible).
- `jose` for signing/verifying the session JWT -- chosen over
  `jsonwebtoken` because it works on both the Node.js and Edge runtimes
  (needed since the session check runs in `src/proxy.ts`).
- Tailwind CSS for styling (kept minimal -- this is an internal tool).

## Deploying

Standard Next.js app, importable into Vercel with no extra build
configuration. Set the environment variables above in the Vercel project
settings for all environments you deploy (Production/Preview/Development),
run `npm run db:init-allowlist` once against each database you deploy
against (or paste `sql/001_allowed_reviewers.sql` into the Neon SQL
console), and complete the Telegram bot setup in "Authentication" above
(in particular, `/setdomain` must match the deployed domain exactly).
