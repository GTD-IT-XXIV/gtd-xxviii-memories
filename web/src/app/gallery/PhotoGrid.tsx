"use client";

import { useEffect, useMemo, useState } from "react";

export interface GalleryPhoto {
  id: number;
  filename: string;
  day: number | null;
  thumbnailUrl: string | null;
}

export default function PhotoGrid({ photos }: { photos: GalleryPhoto[] }) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [downloading, setDownloading] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState<{ done: number; total: number } | null>(null);
  // Set once a run finishes, to prompt the user to verify nothing was blocked.
  // The page cannot observe whether a download actually saved, so this asks
  // rather than claims success.
  const [finishedCount, setFinishedCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewPhoto, setPreviewPhoto] = useState<GalleryPhoto | null>(null);

  useEffect(() => {
    if (!previewPhoto) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setPreviewPhoto(null);
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [previewPhoto]);

  const allOnPageSelected = photos.length > 0 && photos.every((p) => selected.has(p.id));

  function toggle(id: number) {
    setFinishedCount(null); // stale once the selection no longer matches the run
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setFinishedCount(null);
    setSelected((cur) => {
      if (allOnPageSelected) {
        const next = new Set(cur);
        photos.forEach((p) => next.delete(p.id));
        return next;
      }
      const next = new Set(cur);
      photos.forEach((p) => next.add(p.id));
      return next;
    });
  }

  function clearSelection() {
    setFinishedCount(null);
    setSelected(new Set());
  }

  const selectedCount = selected.size;

  const selectedIds = useMemo(() => Array.from(selected), [selected]);

  // Browsers rate-limit rapid programmatic downloads (and some prompt once a
  // page requests several), so the anchor clicks are spaced out rather than
  // fired in a tight loop. Slow enough to be reliable, fast enough that a
  // typical selection finishes quickly.
  const DOWNLOAD_GAP_MS = 350;
  // Past this many files the "allow multiple downloads?" prompt and the sheer
  // number of save dialogs stop being a footnote, so confirm before starting.
  const CONFIRM_ABOVE = 20;

  async function downloadSelected() {
    if (
      selectedIds.length > CONFIRM_ABOVE &&
      !window.confirm(
        `This will download ${selectedIds.length} separate files, one after another.\n\n` +
          `Your browser will likely ask permission to download multiple files - you must click "Allow", ` +
          `or only the first photo will be saved.\n\n` +
          `It takes about ${Math.ceil((selectedIds.length * DOWNLOAD_GAP_MS) / 1000)}s to start them all. Continue?`
      )
    ) {
      return;
    }
    setError(null);
    setFinishedCount(null);
    setDownloading(true);
    setDownloadProgress(null);
    try {
      // The server hands back presigned R2 URLs; the actual image bytes are
      // fetched by the browser straight from R2, never through our server.
      // See the note in api/gallery/download/route.ts for why.
      const res = await fetch("/api/gallery/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ photoIds: selectedIds }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error ?? `Download failed (${res.status})`);
      }
      const { files } = (await res.json()) as {
        files: Array<{ id: number; filename: string; url: string }>;
      };
      if (!files?.length) throw new Error("No downloadable photos found");

      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        setDownloadProgress({ done: i, total: files.length });
        const a = document.createElement("a");
        a.href = file.url;
        // Only a hint: `download` is ignored for cross-origin URLs, so R2's
        // own Content-Disposition decides the saved name. Harmless to set.
        a.download = file.filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        if (i < files.length - 1) {
          await new Promise((resolve) => setTimeout(resolve, DOWNLOAD_GAP_MS));
        }
      }
      setDownloadProgress({ done: files.length, total: files.length });
      setFinishedCount(files.length);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed");
    } finally {
      setDownloading(false);
    }
  }

  if (photos.length === 0) {
    return <p className="text-sm text-gray-500">No photos match these filters.</p>;
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 mb-3 text-sm">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={allOnPageSelected} onChange={toggleSelectAll} />
          Select all on this page
        </label>
        {selectedCount > 0 && (
          <>
            <span className="text-gray-500">{selectedCount} selected</span>
            <button
              onClick={downloadSelected}
              disabled={downloading}
              className="px-3 py-1 rounded bg-indigo-600 text-white text-xs disabled:opacity-50"
            >
              {downloading && downloadProgress
                ? `Downloading ${downloadProgress.done}/${downloadProgress.total}...`
                : downloading
                  ? "Preparing..."
                  : "Download selected"}
            </button>
            <button onClick={clearSelection} className="text-xs text-red-600 hover:underline">
              Clear selection
            </button>
          </>
        )}
        {error && <span className="text-xs text-red-600">{error}</span>}
      </div>

      {/* Photos download individually straight from storage rather than as one
          zip, so browsers treat a multi-photo selection as a burst of downloads
          and gate it behind a permission prompt. Warn up front - a dismissed or
          missed prompt silently saves only the first file. */}
      {selectedCount > 1 && !downloading && (
        <div className="mb-3 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <strong>Heads up:</strong> these download as {selectedCount} separate files, not a zip.
          Your browser will probably ask permission to download multiple files &ndash; choose{" "}
          <strong>Allow</strong>, otherwise only the first photo is saved. If nothing happens, look
          for a blocked-download icon in the address bar.
        </div>
      )}

      {downloading && downloadProgress && (
        <div className="mb-3 rounded border border-indigo-300 bg-indigo-50 px-3 py-2 text-xs text-indigo-900">
          Starting download {downloadProgress.done}/{downloadProgress.total} &ndash; keep this tab open
          until it finishes. If your browser asked permission and you missed it, click{" "}
          <strong>Allow</strong> and download again.
        </div>
      )}

      {finishedCount !== null && !downloading && (
        <div className="mb-3 rounded border border-green-300 bg-green-50 px-3 py-2 text-xs text-green-900">
          Started {finishedCount} download{finishedCount === 1 ? "" : "s"}.{" "}
          <strong>Check your downloads folder</strong> &ndash; if you got fewer files than expected,
          your browser blocked the rest. Allow multiple downloads for this site, then click Download
          again.
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
        {photos.map((p) => {
          const isSelected = selected.has(p.id);
          return (
            <div
              key={p.id}
              className={`relative aspect-square bg-gray-100 rounded-md overflow-hidden flex items-center justify-center border-2 ${
                isSelected ? "border-indigo-500" : "border-transparent"
              }`}
              title={p.day ? `Day ${p.day}` : undefined}
            >
              <label className="absolute top-1.5 left-1.5 z-10 flex items-center justify-center w-5 h-5 rounded bg-black/50 cursor-pointer">
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => toggle(p.id)}
                  className="w-3.5 h-3.5"
                />
              </label>
              {p.thumbnailUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={p.thumbnailUrl}
                  alt={p.filename}
                  className="w-full h-full object-cover cursor-pointer"
                  onClick={() => setPreviewPhoto(p)}
                />
              ) : (
                <span className="text-gray-400 text-xs">No image</span>
              )}
            </div>
          );
        })}
      </div>

      {previewPhoto && previewPhoto.thumbnailUrl && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6"
          onClick={() => setPreviewPhoto(null)}
        >
          <button
            onClick={() => setPreviewPhoto(null)}
            className="absolute top-4 right-4 text-white text-2xl leading-none hover:opacity-75"
            aria-label="Close preview"
          >
            &#10005;
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={previewPhoto.thumbnailUrl}
            alt={previewPhoto.filename}
            className="max-w-[90vw] max-h-[90vh] object-contain rounded shadow-lg"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </div>
  );
}
