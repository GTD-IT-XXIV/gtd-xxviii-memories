-- One-time setup for the web app's Telegram-login allowlist.
--
-- This table is owned by web/ (not the Python pipeline under backend/) and
-- is unrelated to the face-recognition schema (photos/clusters/faces) --
-- it's purely "who is allowed to log into this internal tool".
--
-- Run once against your Neon database:
--   npm run db:init-allowlist
-- (reads DATABASE_URL from web/.env.local -- see README.md "Allowlist
-- setup"). Alternatively, paste this file's contents into the Neon SQL
-- console, or run it with psql.
--
-- Safe to re-run: CREATE TABLE IF NOT EXISTS is idempotent.

CREATE TABLE IF NOT EXISTS allowed_reviewers (
  id                 BIGSERIAL PRIMARY KEY,

  -- Telegram's numeric user id -- the only identifier Telegram guarantees
  -- is stable (usernames can change or be removed). NULL until the
  -- person's first successful login *if* they were pre-authorized by
  -- @username only below (numeric id isn't known until someone actually
  -- logs in with the widget).
  telegram_user_id   BIGINT UNIQUE,

  -- @username, stored lowercase, without the leading "@". Two purposes:
  --   (a) admin readability in this table, and
  --   (b) pre-authorizing someone by username *before* their first login.
  -- Kept in sync with the live Telegram username on every login.
  telegram_username  TEXT UNIQUE,

  -- Optional human label for admins, e.g. "Audria - BFM lead".
  display_name       TEXT,

  added_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- A row must be identifiable by at least one of the two -- otherwise
  -- it's a no-op entry that can never match anyone.
  CONSTRAINT allowed_reviewers_identity_chk
    CHECK (telegram_user_id IS NOT NULL OR telegram_username IS NOT NULL)
);
