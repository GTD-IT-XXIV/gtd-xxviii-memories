"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type OpenDropdown = "day" | "og" | null;

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
  const [faceSuggestionsOpen, setFaceSuggestionsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(null);
        setFaceSuggestionsOpen(false);
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
    setFaceSuggestionsOpen(false);
  }

  const faceMatches = useMemo(() => {
    const q = faceQuery.trim().toLowerCase();
    if (!q) return persons.slice(0, 15);
    return persons.filter((p) => p.toLowerCase().includes(q)).slice(0, 15);
  }, [faceQuery, persons]);

  const hasFilters = selectedDays.length > 0 || selectedOgs.length > 0 || !!selectedFace;

  const dayLabel = selectedDays.length === 0 ? "Day" : `Day (${selectedDays.length})`;
  const ogLabel = selectedOgs.length === 0 ? "OG" : `OG (${selectedOgs.length})`;

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
        <input
          value={faceQuery}
          onChange={(e) => {
            setFaceQuery(e.target.value);
            setFaceSuggestionsOpen(true);
          }}
          onFocus={() => setFaceSuggestionsOpen(true)}
          placeholder="Search a person's name..."
          className={`px-3 py-1.5 rounded border text-xs w-56 ${
            selectedFace ? "bg-indigo-50 border-indigo-300 text-indigo-700" : "bg-white border-gray-300 text-gray-700"
          }`}
        />
        {selectedFace && (
          <button
            onClick={() => {
              setFaceQuery("");
              selectFace(null);
            }}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-red-600 text-xs"
            aria-label="Clear face filter"
          >
            &#10005;
          </button>
        )}
        {faceSuggestionsOpen && (
          <ul className="absolute z-20 mt-1 w-56 border border-gray-200 rounded bg-white shadow-md divide-y max-h-48 overflow-y-auto">
            {faceMatches.map((name) => (
              <li key={name}>
                <button
                  onClick={() => {
                    setFaceQuery(name);
                    selectFace(name);
                  }}
                  className={`w-full text-left px-2 py-1 text-xs hover:bg-gray-50 ${
                    name === selectedFace ? "font-medium text-indigo-700" : ""
                  }`}
                >
                  {name}
                </button>
              </li>
            ))}
            {faceMatches.length === 0 && <li className="px-2 py-1 text-xs text-gray-400">No matches</li>}
          </ul>
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
