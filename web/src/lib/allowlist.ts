import { getSql } from "./db";

export interface ResolvedReviewer {
  telegramUserId: number;
  displayName: string | null;
  /** Whether this account can access /review, not just /gallery - see
   * sql/001_allowed_reviewers.sql. */
  canReview: boolean;
}

interface AllowlistIdRow {
  id: number;
  telegram_username: string | null;
  display_name: string | null;
  can_review: boolean;
}

/**
 * Checks whether a Telegram account is allowed to log in, and -- if an
 * admin pre-authorized them by @username only, before they'd ever logged
 * in -- backfills the numeric `telegram_user_id` now that we finally have
 * it (see `web/sql/001_allowed_reviewers.sql` for why both columns exist).
 *
 * Match order:
 *   1. `telegram_user_id` already equals the authenticated numeric id --
 *      the common case for anyone who has logged in before.
 *   2. `telegram_user_id IS NULL` and `telegram_username` (case-
 *      insensitive) equals the authenticated username -- a pre-authorized
 *      entry. We fill in the numeric id here so future logins hit case (1)
 *      even if the person later changes their @username.
 *
 * Returns `null` if neither matches (not authorized).
 */
export async function resolveAllowedReviewer(
  telegramUserId: number,
  telegramUsername: string | null
): Promise<ResolvedReviewer | null> {
  const sql = getSql();

  const byIdRows = await runAllowlistQuery(() =>
    sql`
      SELECT id, telegram_username, display_name, can_review
      FROM allowed_reviewers
      WHERE telegram_user_id = ${telegramUserId}
      LIMIT 1
    `
  );

  if (byIdRows.length > 0) {
    const row = byIdRows[0] as AllowlistIdRow;
    // Keep the stored @username fresh for admin readability (best-effort,
    // not security-relevant -- the numeric id is already what matched).
    if (telegramUsername && row.telegram_username !== telegramUsername) {
      await sql`
        UPDATE allowed_reviewers
        SET telegram_username = ${telegramUsername}
        WHERE id = ${row.id}
      `;
    }
    return { telegramUserId, displayName: row.display_name, canReview: row.can_review };
  }

  if (!telegramUsername) {
    return null;
  }

  const byUsernameRows = await runAllowlistQuery(() =>
    sql`
      SELECT id, display_name, can_review
      FROM allowed_reviewers
      WHERE telegram_user_id IS NULL
        AND lower(telegram_username) = lower(${telegramUsername})
      LIMIT 1
    `
  );

  if (byUsernameRows.length === 0) {
    return null;
  }

  const match = byUsernameRows[0] as { id: number; display_name: string | null; can_review: boolean };
  await sql`
    UPDATE allowed_reviewers
    SET telegram_user_id = ${telegramUserId},
        telegram_username = ${telegramUsername}
    WHERE id = ${match.id}
  `;

  return { telegramUserId, displayName: match.display_name, canReview: match.can_review };
}

/** Looks up whether an already-authenticated Telegram account may access
 * /review, by numeric id (the only stable identifier - see resolveAllowedReviewer). */
export async function canReviewerAccessReview(telegramUserId: number): Promise<boolean> {
  const sql = getSql();
  const rows = await runAllowlistQuery(
    () =>
      sql`
        SELECT can_review FROM allowed_reviewers WHERE telegram_user_id = ${telegramUserId} LIMIT 1
      ` as unknown as Promise<{ can_review: boolean }[]>
  );
  return rows[0]?.can_review ?? false;
}

/** Wraps "table doesn't exist" into a message that points at the setup step. */
async function runAllowlistQuery<T>(query: () => Promise<T>): Promise<T> {
  try {
    return await query();
  } catch (err) {
    if (
      err &&
      typeof err === "object" &&
      "code" in err &&
      (err as { code?: string }).code === "42P01"
    ) {
      throw new Error(
        "The allowed_reviewers table does not exist yet. Run the one-time " +
          "setup described in README.md (`npm run db:init-allowlist`) " +
          "against your Neon database."
      );
    }
    throw err;
  }
}
