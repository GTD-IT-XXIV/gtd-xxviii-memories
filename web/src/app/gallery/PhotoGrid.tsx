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

  async function downloadSelected() {
    setError(null);
    setDownloading(true);
    try {
      const res = await fetch("/api/gallery/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ photoIds: selectedIds }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error ?? `Download failed (${res.status})`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `gtd-photos-${new Date().toISOString().slice(0, 10)}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
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
              {downloading ? "Preparing zip..." : "Download selected"}
            </button>
            <button onClick={clearSelection} className="text-xs text-red-600 hover:underline">
              Clear selection
            </button>
          </>
        )}
        {error && <span className="text-xs text-red-600">{error}</span>}
      </div>

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
