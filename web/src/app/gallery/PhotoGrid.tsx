"use client";

import { useEffect, useMemo, useState } from "react";
import JSZip from "jszip";

export interface GalleryPhoto {
  id: number;
  filename: string;
  day: number | null;
  thumbnailUrl: string | null;
  /** Mid-size image for the lightbox. Falls back to the thumbnail server-side when a
   * photo predates previews, so this is never sharper-but-missing. */
  previewUrl: string | null;
}

export default function PhotoGrid({ photos }: { photos: GalleryPhoto[] }) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [downloading, setDownloading] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewPhoto, setPreviewPhoto] = useState<GalleryPhoto | null>(null);
  const [previewLoaded, setPreviewLoaded] = useState(false);

  /** Opening a lightbox always starts from "preview not yet loaded", so the blurred
   * thumbnail placeholder shows again rather than the previous photo's loaded state
   * leaking into the next one. */
  function openPreview(photo: GalleryPhoto) {
    setPreviewLoaded(false);
    setPreviewPhoto(photo);
  }

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
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
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
    setSelected(new Set());
  }

  const selectedCount = selected.size;

  const selectedIds = useMemo(() => Array.from(selected), [selected]);

  // Fetching all 500 originals at once would hit the browser's per-origin
  // connection limit and stall; a small worker pool keeps several R2 fetches
  // in flight without opening hundreds of connections at once.
  const DOWNLOAD_CONCURRENCY = 6;
  // Originals run 8-15MB each, and the whole batch sits in memory as JSZip
  // packs it, so a big selection is a real memory/time cost worth confirming
  // up front rather than a footnote.
  const CONFIRM_ABOVE = 60;

  async function downloadSelected() {
    if (
      selectedIds.length > CONFIRM_ABOVE &&
      !window.confirm(
        `This will fetch and zip ${selectedIds.length} full-size photos in your browser, which can take a ` +
          `while and use a lot of memory on the device. Continue?`
      )
    ) {
      return;
    }
    setError(null);
    setDownloading(true);
    setDownloadProgress({ done: 0, total: selectedIds.length });
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

      // Packed into one zip client-side (rather than one download per photo)
      // so the browser only ever sees a single download - triggering several
      // separate downloads at once runs into the browser's "allow multiple
      // downloads?" gate, which silently blocks everything past the first
      // file once a site has ever been denied.
      const zip = new JSZip();
      let doneCount = 0;
      let failedCount = 0;
      setDownloadProgress({ done: 0, total: files.length });

      let nextIndex = 0;
      async function worker() {
        while (nextIndex < files.length) {
          const file = files[nextIndex++];
          try {
            const blob = await (await fetch(file.url)).blob();
            zip.file(file.filename, blob);
          } catch (err) {
            console.error(`gallery download: failed to fetch ${file.filename}`, err);
            failedCount++;
          }
          doneCount++;
          setDownloadProgress({ done: doneCount, total: files.length });
        }
      }
      await Promise.all(
        Array.from({ length: Math.min(DOWNLOAD_CONCURRENCY, files.length) }, worker)
      );

      if (failedCount === files.length) throw new Error("All photos failed to download");

      const zipBlob = await zip.generateAsync({ type: "blob" });
      const url = URL.createObjectURL(zipBlob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `gtd-photos-${new Date().toISOString().slice(0, 10)}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);

      if (failedCount > 0) {
        setError(`${failedCount} of ${files.length} photos failed to download and were left out of the zip`);
      }
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
                ? `Zipping ${downloadProgress.done}/${downloadProgress.total}...`
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

      {downloading && downloadProgress && (
        <div className="mb-3 rounded border border-indigo-300 bg-indigo-50 px-3 py-2 text-xs text-indigo-900">
          Fetching and zipping photo {downloadProgress.done}/{downloadProgress.total} &ndash; keep this
          tab open until the download starts.
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
                  onClick={() => openPreview(p)}
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
          <div className="relative" onClick={(e) => e.stopPropagation()}>
            {/* The already-cached grid thumbnail renders instantly, upscaled and soft,
                and the sharp preview fades in on top once it arrives. Without this the
                lightbox is empty for as long as the ~300KB preview takes on mobile. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={previewPhoto.thumbnailUrl}
              alt=""
              aria-hidden="true"
              className="max-w-[90vw] max-h-[90vh] object-contain rounded shadow-lg blur-[2px]"
            />
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              key={previewPhoto.id}
              src={previewPhoto.previewUrl ?? previewPhoto.thumbnailUrl}
              alt={previewPhoto.filename}
              onLoad={() => setPreviewLoaded(true)}
              className={`absolute inset-0 w-full h-full object-contain rounded shadow-lg transition-opacity duration-200 ${
                previewLoaded ? "opacity-100" : "opacity-0"
              }`}
            />
          </div>
        </div>
      )}
    </div>
  );
}
