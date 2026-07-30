import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
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
  title: "GTD Face Review",
  description: "Face cluster review tool for GTD event photos",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-gray-50 text-gray-900">
        <header className="border-b border-gray-200 bg-white">
          <nav className="max-w-6xl mx-auto px-6 py-3 flex items-center gap-4">
            <span className="font-semibold text-sm">GTD Face Review</span>
            <Link href="/review" className="text-sm text-gray-600 hover:text-gray-900">
              Review
            </Link>
            <Link href="/persons" className="text-sm text-gray-600 hover:text-gray-900">
              Persons
            </Link>
          </nav>
        </header>
        <main className="flex-1">{children}</main>
      </body>
    </html>
  );
}
