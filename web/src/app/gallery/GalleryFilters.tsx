"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

/**
 * Deliberately takes the current selection as props (derived server-side from
 * searchParams in page.tsx) rather than reading them itself via the
 * `useSearchParams` hook - that hook requires wrapping the page in a Suspense
 * boundary during prerendering, which this route (already `force-dynamic`)
 * has no other reason to need.
 */
export default function GalleryFilters({
  days,
  ogs,
  persons,
  selectedDays,
  selectedOgs,
  selectedFace,
}: {
  days: number[];
  ogs: string[];
  persons: string[];
  selectedDays: number[];
  selectedOgs: string[];
  selectedFace: string | null;
}) {
  const router = useRouter();
  const [faceQuery, setFaceQuery] = useState(selectedFace ?? "");

  function navigate(mutate: (params: URLSearchParams) => void) {
    const params = new URLSearchParams();
    selectedDays.forEach((d) => params.append("day", String(d)));
    selectedOgs.forEach((o) => params.append("og", o));
    if (selectedFace) params.set("face", selectedFace);
    mutate(params);
    // Any filter change invalidates the current page number.
    params.delete("page");
    router.push(`/gallery${params.toString() ? `?${params.toString()}` : ""}`);
  }

  function toggleDay(d: number) {
    navigate((params) => {
      const current = new Set(params.getAll("day"));
      const key = String(d);
      if (current.has(key)) {
        current.delete(key);
      } else {
        current.add(key);
      }
      params.delete("day");
      current.forEach((v) => params.append("day", v));
    });
  }

  function toggleOg(og: string) {
    navigate((params) => {
      const current = new Set(params.getAll("og"));
      if (current.has(og)) {
        current.delete(og);
      } else {
        current.add(og);
      }
      params.delete("og");
      current.forEach((v) => params.append("og", v));
    });
  }

  function selectFace(name: string | null) {
    navigate((params) => {
      if (name) params.set("face", name);
      else params.delete("face");
    });
  }

  const faceMatches = useMemo(() => {
    const q = faceQuery.trim().toLowerCase();
    if (!q) return [];
    return persons.filter((p) => p.toLowerCase().includes(q)).slice(0, 15);
  }, [faceQuery, persons]);

  const hasFilters = selectedDays.length > 0 || selectedOgs.length > 0 || !!selectedFace;

  return (
    <div className="border border-gray-200 rounded-lg bg-white p-4 mb-4 flex flex-col gap-3">
      {days.length > 0 && (
        <div>
          <p className="text-xs text-gray-500 mb-1">Day (any of)</p>
          <div className="flex flex-wrap gap-1">
            {days.map((d) => (
              <button
                key={d}
                onClick={() => toggleDay(d)}
                className={`px-2 py-1 rounded border text-xs ${
                  selectedDays.includes(d)
                    ? "bg-indigo-600 text-white border-indigo-600"
                    : "bg-white text-gray-700 border-gray-300"
                }`}
              >
                Day {d}
              </button>
            ))}
          </div>
        </div>
      )}

      {ogs.length > 0 && (
        <div>
          <p className="text-xs text-gray-500 mb-1">OG (any of)</p>
          <div className="flex flex-wrap gap-1">
            {ogs.map((og) => (
              <button
                key={og}
                onClick={() => toggleOg(og)}
                className={`px-2 py-1 rounded border text-xs ${
                  selectedOgs.includes(og)
                    ? "bg-indigo-600 text-white border-indigo-600"
                    : "bg-white text-gray-700 border-gray-300"
                }`}
              >
                {og}
              </button>
            ))}
          </div>
        </div>
      )}

      <div>
        <p className="text-xs text-gray-500 mb-1">Face (one person)</p>
        {selectedFace ? (
          <div className="flex items-center gap-2">
            <span className="px-2 py-1 rounded bg-indigo-600 text-white text-xs">{selectedFace}</span>
            <button
              onClick={() => {
                setFaceQuery("");
                selectFace(null);
              }}
              className="text-xs text-gray-500 hover:underline"
            >
              Clear
            </button>
          </div>
        ) : (
          <div className="relative max-w-xs">
            <input
              value={faceQuery}
              onChange={(e) => setFaceQuery(e.target.value)}
              placeholder="Search a person's name..."
              className="w-full border border-gray-300 rounded px-2 py-1 text-xs"
            />
            {faceMatches.length > 0 && (
              <ul className="absolute z-10 mt-1 w-full border border-gray-200 rounded bg-white shadow-sm divide-y max-h-48 overflow-y-auto">
                {faceMatches.map((name) => (
                  <li key={name}>
                    <button
                      onClick={() => selectFace(name)}
                      className="w-full text-left px-2 py-1 text-xs hover:bg-gray-50"
                    >
                      {name}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {hasFilters && (
        <button onClick={() => router.push("/gallery")} className="text-xs text-red-600 hover:underline self-start">
          Clear all filters
        </button>
      )}
    </div>
  );
}
