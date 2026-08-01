#!/usr/bin/env node
// Grants gallery-only access to one or more Telegram usernames in the
// allowed_reviewers table (see sql/001_allowed_reviewers.sql). Presence in that
// table is what allows logging in and browsing /gallery at all; can_review is the
// separate, additional gate for /review. This script therefore inserts with
// can_review = false.
//
// Deliberately NOT the same script as add-reviewer.mjs: that one hardcodes
// can_review = true and *upgrades* an existing row. This one must never silently
// downgrade someone who already has review access, so its ON CONFLICT leaves
// can_review alone (it only refreshes nothing - the row already grants gallery
// access by existing). Use add-reviewer.mjs to promote someone later.
//
// Usage:
//   npm run db:add-viewer -- username1 username2 ...
// (reads DATABASE_URL from web/.env.local via Node's --env-file flag)

import { neon } from "@neondatabase/serverless";

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) {
  console.error(
    "DATABASE_URL is not set.\n\n" +
      "Either create web/.env.local with a DATABASE_URL line (see .env.example) " +
      "and run `npm run db:add-viewer -- username1 username2`, or pass it inline:\n" +
      "  DATABASE_URL=postgres://... node scripts/add-viewer.mjs username1 username2"
  );
  process.exit(1);
}

const usernames = process.argv.slice(2).map((u) => u.trim().replace(/^@/, "").toLowerCase());
if (usernames.length === 0) {
  console.error("Usage: npm run db:add-viewer -- username1 username2 ...");
  process.exit(1);
}

const sql = neon(databaseUrl);

for (const username of usernames) {
  // DO NOTHING, not DO UPDATE: re-running this for someone who was later granted
  // review access must not revoke it.
  const rows = await sql`
    INSERT INTO allowed_reviewers (telegram_username, can_review)
    VALUES (${username}, false)
    ON CONFLICT (telegram_username) DO NOTHING
    RETURNING id, telegram_user_id, telegram_username, can_review
  `;
  if (rows.length > 0) {
    console.log(`@${username} -> added`, rows[0]);
  } else {
    const existing = await sql`
      SELECT id, telegram_user_id, telegram_username, can_review
      FROM allowed_reviewers WHERE telegram_username = ${username}
    `;
    console.log(`@${username} -> already present, left unchanged`, existing[0]);
  }
}
