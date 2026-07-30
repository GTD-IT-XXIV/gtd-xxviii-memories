"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type OpenDropdown = "day" | "og" | "face" | null;

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
  const [open, setOpen] = useState<OpenDropdown>(null);
  const [faceQuery, setFaceQuery] = useState(selectedFace ?? "");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

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
    setOpen(null);
  }

  const faceMatches = useMemo(() => {
    const q = faceQuery.trim().toLowerCase();
    if (!q) return persons.slice(0, 15);
    return persons.filter((p) => p.toLowerCase().includes(q)).slice(0, 15);
  }, [faceQuery, persons]);

  const hasFilters = selectedDays.length > 0 || selectedOgs.length > 0 || !!selectedFace;

  const dayLabel = selectedDays.length === 0 ? "Day" : `Day (${selectedDays.length})`;
  const ogLabel = selectedOgs.length === 0 ? "OG" : `OG (${selectedOgs.length})`;
  const faceLabel = selectedFace ?? "Face";

  function toggleOpen(which: OpenDropdown) {
    setOpen((cur) => (cur === which ? null : which));
  }

  return (
    <div ref={containerRef} className="flex flex-wrap items-center gap-2 mb-4">
      {days.length > 0 && (
        <div className="relative">
          <button
            onClick={() => toggleOpen("day")}
            className={`px-3 py-1.5 rounded border text-xs flex items-center gap-1 ${
              selectedDays.length > 0
                ? "bg-indigo-50 border-indigo-300 text-indigo-700"
                : "bg-white border-gray-300 text-gray-700"
            }`}
          >
            {dayLabel} <span className="text-[10px]">&#9662;</span>
          </button>
          {open === "day" && (
            <div className="absolute z-20 mt-1 border border-gray-200 rounded bg-white shadow-md p-2 flex flex-col gap-1 min-w-[110px]">
              {days.map((d) => (
                <label key={d} className="flex items-center gap-2 text-xs cursor-pointer whitespace-nowrap">
                  <input type="checkbox" checked={selectedDays.includes(d)} onChange={() => toggleDay(d)} />
                  Day {d}
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      {ogs.length > 0 && (
        <div className="relative">
          <button
            onClick={() => toggleOpen("og")}
            className={`px-3 py-1.5 rounded border text-xs flex items-center gap-1 ${
              selectedOgs.length > 0
                ? "bg-indigo-50 border-indigo-300 text-indigo-700"
                : "bg-white border-gray-300 text-gray-700"
            }`}
          >
            {ogLabel} <span className="text-[10px]">&#9662;</span>
          </button>
          {open === "og" && (
            <div className="absolute z-20 mt-1 border border-gray-200 rounded bg-white shadow-md p-2 flex flex-col gap-1 min-w-[140px] max-h-56 overflow-y-auto">
              {ogs.map((og) => (
                <label key={og} className="flex items-center gap-2 text-xs cursor-pointer whitespace-nowrap">
                  <input type="checkbox" checked={selectedOgs.includes(og)} onChange={() => toggleOg(og)} />
                  {og}
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="relative">
        <button
          onClick={() => toggleOpen("face")}
          className={`px-3 py-1.5 rounded border text-xs flex items-center gap-1 max-w-[180px] ${
            selectedFace
              ? "bg-indigo-50 border-indigo-300 text-indigo-700"
              : "bg-white border-gray-300 text-gray-700"
          }`}
        >
          <span className="truncate">{faceLabel}</span> <span className="text-[10px] shrink-0">&#9662;</span>
        </button>
        {open === "face" && (
          <div className="absolute z-20 mt-1 border border-gray-200 rounded bg-white shadow-md p-2 w-56">
            <input
              value={faceQuery}
              onChange={(e) => setFaceQuery(e.target.value)}
              placeholder="Search a person's name..."
              autoFocus
              className="w-full border border-gray-300 rounded px-2 py-1 text-xs mb-1"
            />
            {selectedFace && (
              <button
                onClick={() => {
                  setFaceQuery("");
                  selectFace(null);
                }}
                className="text-[11px] text-red-600 hover:underline mb-1"
              >
                Clear face filter
              </button>
            )}
            <ul className="divide-y max-h-48 overflow-y-auto">
              {faceMatches.map((name) => (
                <li key={name}>
                  <button
                    onClick={() => {
                      setFaceQuery(name);
                      selectFace(name);
                    }}
                    className={`w-full text-left px-1 py-1 text-xs hover:bg-gray-50 ${
                      name === selectedFace ? "font-medium text-indigo-700" : ""
                    }`}
                  >
                    {name}
                  </button>
                </li>
              ))}
              {faceMatches.length === 0 && <li className="px-1 py-1 text-xs text-gray-400">No matches</li>}
            </ul>
          </div>
        )}
      </div>

      {hasFilters && (
        <button onClick={() => router.push("/gallery")} className="text-xs text-red-600 hover:underline">
          Clear all
        </button>
      )}
    </div>
  );
}
