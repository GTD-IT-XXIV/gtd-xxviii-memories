import type { Metadata } from "next";
import Link from "next/link";
import { cookies } from "next/headers";
import { Geist, Geist_Mono } from "next/font/google";
import { COOKIE_NAME, verifySessionToken } from "@/lib/session";
import { canReviewerAccessReview } from "@/lib/allowlist";
import Footer from "@/components/Footer";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "GTD Memories",
  description: "Face cluster review tool for GTD event photos",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const cookieStore = await cookies();
  const token = cookieStore.get(COOKIE_NAME)?.value;
  const session = token ? await verifySessionToken(token) : null;
  const canReview = session ? await canReviewerAccessReview(session.telegram_user_id) : false;

  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-gray-50 text-gray-900">
        <header className="border-b border-gray-200 bg-white">
          <nav className="max-w-6xl mx-auto px-6 py-3 flex items-center gap-4">
            <span className="font-semibold text-sm text-black">GTD Memories</span>
            <Link href="/gallery" className="text-sm text-gray-600 hover:text-gray-900">
              Gallery
            </Link>
            {canReview && (
              <Link href="/review" className="text-sm text-gray-600 hover:text-gray-900">
                Review
              </Link>
            )}
            {session && (
              <form action="/api/auth/logout" method="POST" className="ml-auto">
                <button
                  type="submit"
                  className="text-sm text-gray-600 hover:text-gray-900"
                >
                  Log out
                </button>
              </form>
            )}
          </nav>
        </header>
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
