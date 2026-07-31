// This page hits the network (Telegram's widget script) and reads
// searchParams, so there's no benefit to static generation and every
// benefit to always reflecting the current TELEGRAM_BOT_USERNAME config.
export const dynamic = "force-dynamic";

const ERROR_MESSAGES: Record<string, string> = {
  not_authorized:
    "Your Telegram account is not authorized to access this gallery. Ask an admin to add your Telegram @username or numeric ID to the allowlist.",
  verification_failed:
    "We couldn't verify that this login actually came from Telegram. Please try again.",
  server_misconfigured:
    "Telegram login isn't fully configured on this server yet. Contact an admin.",
};

// Telegram usernames are 5-32 chars, letters/digits/underscore. Validating
// before interpolating it into a raw <script> tag below is cheap insurance
// even though the value comes from server config, not user input.
const VALID_BOT_USERNAME = /^[A-Za-z0-9_]{5,32}$/;

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const params = await searchParams;
  const errorMessage = params.error
    ? (ERROR_MESSAGES[params.error] ?? "Login failed. Please try again.")
    : null;

  const rawBotUsername = process.env.TELEGRAM_BOT_USERNAME;
  const botUsername =
    rawBotUsername && VALID_BOT_USERNAME.test(rawBotUsername)
      ? rawBotUsername
      : null;

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

      {botUsername ? (
        <div
          // Telegram's widget script renders its own "Log in with
          // Telegram" button and, on success, navigates the browser to
          // data-auth-url with the signed payload as query params. No
          // client-side JS of ours is involved -- the redirect is handled
          // entirely by Telegram's script and our server-side callback.
          suppressHydrationWarning
          dangerouslySetInnerHTML={{
            __html:
              `<script async src="https://telegram.org/js/telegram-widget.js?22" ` +
              `data-telegram-login="${botUsername}" ` +
              `data-size="large" ` +
              `data-auth-url="/api/auth/telegram/callback" ` +
              `data-request-access="write"></script>`,
          }}
        />
      ) : (
        <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2">
          TELEGRAM_BOT_USERNAME is not configured. See README.md for setup
          instructions.
        </p>
      )}
    </div>
  );
}
