#!/usr/bin/env node
// Grants review access (can_review = true) to one or more Telegram usernames
// in the allowed_reviewers table (see sql/001_allowed_reviewers.sql). If a
// username isn't already in the table, this pre-authorizes them by username -
// their numeric telegram_user_id gets backfilled on first login (see
// lib/allowlist.ts). If they're already present (e.g. as a gallery-only,
// non-reviewer row), this upgrades them to can_review = true.
//
// Usage:
//   npm run db:add-reviewer -- username1 username2 ...
// (reads DATABASE_URL from web/.env.local via Node's --env-file flag)

import { neon } from "@neondatabase/serverless";

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) {
  console.error(
    "DATABASE_URL is not set.\n\n" +
      "Either create web/.env.local with a DATABASE_URL line (see .env.example) " +
      "and run `npm run db:add-reviewer -- username1 username2`, or pass it inline:\n" +
      "  DATABASE_URL=postgres://... node scripts/add-reviewer.mjs username1 username2"
  );
  process.exit(1);
}

const usernames = process.argv.slice(2).map((u) => u.trim().replace(/^@/, "").toLowerCase());
if (usernames.length === 0) {
  console.error("Usage: npm run db:add-reviewer -- username1 username2 ...");
  process.exit(1);
}

const sql = neon(databaseUrl);

for (const username of usernames) {
  const rows = await sql`
    INSERT INTO allowed_reviewers (telegram_username, can_review)
    VALUES (${username}, true)
    ON CONFLICT (telegram_username)
    DO UPDATE SET can_review = true
    RETURNING id, telegram_user_id, telegram_username, can_review
  `;
  console.log(`@${username} ->`, rows[0]);
}
