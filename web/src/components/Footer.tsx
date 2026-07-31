/* eslint-disable @next/next/no-img-element */

const SOCIAL_LINKS = {
  tiktok: "https://www.tiktok.com/@pintugtd",
  instagram: "https://www.instagram.com/pintugtd",
  linkedin: "https://www.linkedin.com/company/pintu-gtd/",
};

function TikTokIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">
      <path d="M16.6 5.82c-.9-.88-1.47-2.05-1.6-3.32V2h-3.36v13.7a2.6 2.6 0 1 1-2.6-2.6c.24 0 .48.03.7.09v-3.4a5.98 5.98 0 0 0-.7-.04A5.98 5.98 0 1 0 15.06 15.7V9.15a7.3 7.3 0 0 0 4.27 1.36V7.16a4.34 4.34 0 0 1-2.73-1.34Z" />
    </svg>
  );
}

function InstagramIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.3" cy="6.7" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}

function LinkedInIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">
      <path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5ZM3 9h4v12H3V9Zm7 0h3.83v1.64h.05c.53-1 1.84-2.06 3.78-2.06 4.04 0 4.79 2.66 4.79 6.11V21h-4v-5.6c0-1.34-.02-3.06-1.87-3.06-1.87 0-2.16 1.46-2.16 2.96V21h-4V9Z" />
    </svg>
  );
}

export default function Footer() {
  return (
    <footer className="relative z-40 w-full bg-white border-t border-gray-200">
      <div className="max-w-6xl mx-auto px-6 py-6 flex flex-col md:flex-row items-center justify-between gap-4">
        {/* ── Logo + name (left) ── */}
        <div className="flex items-center gap-3">
          <img src="/black_logo.png" alt="PINTU GTD logo" className="h-16 w-auto object-contain" />
          <span
            className="text-gray-800 font-bold tracking-wide text-lg"
            style={{ fontFamily: "'Inter', sans-serif" }}
          >
            PINTU GTD
          </span>
        </div>

        {/* ── Copyright (middle) ── */}
        <p className="text-sm text-gray-500 text-center">
          © 2026 PINTU GTD. All Rights Reserved.
        </p>

        {/* ── Social links (right) ── */}
        <div className="flex items-center gap-4 text-gray-700">
          <a href={SOCIAL_LINKS.tiktok} target="_blank" rel="noopener noreferrer" aria-label="TikTok" className="hover:text-black transition-colors">
            <TikTokIcon />
          </a>
          <a href={SOCIAL_LINKS.instagram} target="_blank" rel="noopener noreferrer" aria-label="Instagram" className="hover:text-black transition-colors">
            <InstagramIcon />
          </a>
          <a href={SOCIAL_LINKS.linkedin} target="_blank" rel="noopener noreferrer" aria-label="LinkedIn" className="hover:text-black transition-colors">
            <LinkedInIcon />
          </a>
        </div>
      </div>
    </footer>
  );
}
