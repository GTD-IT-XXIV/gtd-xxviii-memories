// This page reads searchParams and reflects the current
// TELEGRAM_OIDC_CLIENT_ID config, so there's no benefit to static
// generation.
export const dynamic = "force-dynamic";

const ERROR_MESSAGES: Record<string, string> = {
  not_authorized:
    "Your Telegram account is not authorized to access this gallery. Ask an admin to add your Telegram @username or numeric ID to the allowlist.",
  verification_failed:
    "We couldn't verify that this login actually came from Telegram. Please try again.",
  server_misconfigured:
    "Telegram login isn't fully configured on this server yet. Contact an admin.",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const params = await searchParams;
  const errorMessage = params.error
    ? (ERROR_MESSAGES[params.error] ?? "Login failed. Please try again.")
    : null;

  const clientConfigured = Boolean(process.env.TELEGRAM_OIDC_CLIENT_ID);

  return (
    <div className="max-w-sm mx-auto p-10 flex flex-col items-center gap-4 text-center">
      <h1 className="text-xl font-semibold">GTD Memories</h1>
      <p className="text-sm text-gray-600">
        Sign in with Telegram to access the gallery. Only pre-approved
        reviewers can log in.
      </p>

      {errorMessage && (
        <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
          {errorMessage}
        </p>
      )}

      {clientConfigured ? (
        // Plain top-level navigation (not a popup/iframe) to
        // /api/auth/telegram/start, which redirects to Telegram's OIDC
        // authorization endpoint. A real top-level redirect is what lets
        // Telegram hand off to the installed app on mobile instead of
        // falling back to a phone-number-only web prompt.
        <a
          href="/api/auth/telegram/start"
          className="inline-flex items-center justify-center rounded-md bg-[#26A5E4] px-4 py-2 text-sm font-medium text-white hover:bg-[#1e96d6]"
        >
          Log in with Telegram
        </a>
      ) : (
        <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2">
          TELEGRAM_OIDC_CLIENT_ID is not configured. See README.md for setup
          instructions.
        </p>
      )}
    </div>
  );
}
