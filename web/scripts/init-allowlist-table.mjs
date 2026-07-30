#!/usr/bin/env node
// One-time setup: creates the `allowed_reviewers` table used to gate
// Telegram login (see sql/001_allowed_reviewers.sql). Safe to re-run.
//
// Usage:
//   npm run db:init-allowlist
// (reads DATABASE_URL from web/.env.local via Node's --env-file flag --
// create that file first, see README.md / .env.example)
//
// Or, without the npm script:
//   DATABASE_URL=postgres://... node scripts/init-allowlist-table.mjs

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { neon } from "@neondatabase/serverless";

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) {
  console.error(
    "DATABASE_URL is not set.\n\n" +
      "Either create web/.env.local with a DATABASE_URL line (see " +
      ".env.example) and run `npm run db:init-allowlist`, or pass it " +
      "inline:\n" +
      "  DATABASE_URL=postgres://... node scripts/init-allowlist-table.mjs"
  );
  process.exit(1);
}

const sqlPath = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "sql",
  "001_allowed_reviewers.sql"
);
const statement = readFileSync(sqlPath, "utf8");

const sql = neon(databaseUrl);
await sql.query(statement);

console.log("allowed_reviewers table is ready.");
