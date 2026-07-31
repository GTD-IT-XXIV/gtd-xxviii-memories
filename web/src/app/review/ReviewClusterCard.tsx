"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { KnownPerson, ReviewClusterViewModel } from "@/lib/types";

type Mode = "idle" | "correcting" | "submitting" | "removed";

async function postJson(url: string, body?: unknown) {
  const res = await fetch(url, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? `Request failed (${res.status})`);
  }
  return res.json();
}

export default function ReviewClusterCard({
  cluster,
  knownPersons,
  onRemoved,
}: {
  cluster: ReviewClusterViewModel;
  knownPersons: KnownPerson[];
  /** Called once the cluster has been labeled/discarded/deferred, so the parent
   * can drop it from folder counts immediately instead of waiting on router.refresh(). */
  onRemoved?: () => void;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("idle");
  const [error, setError] = useState<string | null>(null);
  const [imageIndex, setImageIndex] = useState(0);
  const [search, setSearch] = useState("");
  const [activeOg, setActiveOg] = useState<string | null>(null);
  const [freeText, setFreeText] = useState("");
  const [confirmingYes, setConfirmingYes] = useState(false);
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);

  const ogGroups = useMemo(() => {
    const groups = new Map<string, KnownPerson[]>();
    for (const p of knownPersons) {
      const key = p.og ?? "Unassigned";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(p);
    }
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [knownPersons]);

  const searchResults = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return [];
    return knownPersons
      .filter((p) => p.person_name.toLowerCase().includes(q))
      .slice(0, 20);
  }, [search, knownPersons]);

  const currentTab = activeOg ?? ogGroups[0]?.[0] ?? null;
  const currentTabPeople =
    ogGroups.find(([og]) => og === currentTab)?.[1] ?? [];

  async function submitLabel(person_name: string, og: string | null) {
    setError(null);
    setMode("submitting");
    try {
      await postJson(`/api/clusters/${cluster.id}/name`, { person_name, og });
      setMode("removed");
      onRemoved?.();
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
      setMode("correcting");
    }
  }

  async function discard() {
    setError(null);
    setMode("submitting");
    try {
      await postJson(`/api/clusters/${cluster.id}/discard`);
      setMode("removed");
      onRemoved?.();
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to discard");
      setMode("idle");
    }
  }

  async function defer() {
    setError(null);
    setMode("submitting");
    try {
      await postJson(`/api/clusters/${cluster.id}/defer`);
      setMode("removed");
      onRemoved?.();
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to move to Others");
      setMode("correcting");
    }
  }

  if (mode === "removed") {
    // Optimistically hide the card; router.refresh() will drop it from the
    // list for real once the server re-renders.
    return null;
  }

  const images = cluster.thumbnail_urls;
  const safeIndex = images.length > 0 ? imageIndex % images.length : 0;

  function prevImage() {
    setImageIndex((i) => (images.length === 0 ? 0 : (i - 1 + images.length) % images.length));
  }
  function nextImage() {
    setImageIndex((i) => (images.length === 0 ? 0 : (i + 1) % images.length));
  }

  return (
    <div className="border border-gray-200 rounded-lg bg-white p-3 flex flex-col gap-2">
      <div className="relative aspect-square bg-gray-100 rounded-md overflow-hidden flex items-center justify-center">
        {images.length > 0 ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={images[safeIndex]}
              alt="face"
              className="w-full h-full object-cover"
            />
            {images.length > 1 && (
              <>
                <button
                  onClick={prevImage}
                  aria-label="Previous face"
                  className="absolute left-1 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center rounded-full bg-black/50 text-white text-xs hover:bg-black/70"
                >
                  &#8249;
                </button>
                <button
                  onClick={nextImage}
                  aria-label="Next face"
                  className="absolute right-1 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center rounded-full bg-black/50 text-white text-xs hover:bg-black/70"
                >
                  &#8250;
                </button>
                <span className="absolute bottom-1 right-1 text-[10px] bg-black/50 text-white px-1.5 py-0.5 rounded">
                  {safeIndex + 1}/{images.length}
                </span>
              </>
            )}
          </>
        ) : (
          <span className="text-gray-400 text-xs">No thumbnail</span>
        )}
      </div>
      <p className="text-xs text-gray-500">{cluster.face_count} face(s)</p>

      {error && <p className="text-xs text-red-600">{error}</p>}

      {mode !== "correcting" && (
        <>
          {cluster.recommendation ? (
            <div className="text-xs">
              <p className="text-gray-500">Suggested match:</p>
              <p className="font-medium text-gray-900">
                {cluster.recommendation.person_name}
                {cluster.recommendation.og ? ` (${cluster.recommendation.og})` : ""}
              </p>
              <p className="text-gray-400">
                similarity {cluster.recommendation.similarity.toFixed(2)}
              </p>
              <div className="flex gap-2 mt-1">
                <button
                  disabled={mode === "submitting"}
                  onClick={() => setConfirmingYes(true)}
                  className="px-2 py-1 rounded bg-green-600 text-white text-xs disabled:opacity-50"
                >
                  Yes
                </button>
                <button
                  disabled={mode === "submitting"}
                  onClick={() => {
                    // Default the OG tab to the recommendation's own group, since a
                    // wrong-name-same-group correction (e.g. right person picked up by
                    // a slightly different face) is the most likely "No" case.
                    setActiveOg(cluster.recommendation!.og);
                    setMode("correcting");
                  }}
                  className="px-2 py-1 rounded bg-gray-200 text-gray-800 text-xs disabled:opacity-50"
                >
                  No
                </button>
              </div>
            </div>
          ) : (
            <div className="text-xs">
              <p className="text-gray-400 mb-1">No recommendation.</p>
              <button
                disabled={mode === "submitting"}
                onClick={() => setMode("correcting")}
                className="px-2 py-1 rounded bg-indigo-600 text-white text-xs disabled:opacity-50"
              >
                Label
              </button>
            </div>
          )}

          <button
            disabled={mode === "submitting"}
            onClick={() => setConfirmingDiscard(true)}
            className="text-xs text-red-600 hover:underline self-start disabled:opacity-50"
          >
            Discard (not a person)
          </button>
        </>
      )}

      {mode === "correcting" && (
        <div className="flex flex-col gap-2 text-xs border-t border-gray-100 pt-2">
          <div>
            <label className="text-gray-500 block mb-1">Search people</label>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Start typing a name..."
              className="w-full border border-gray-300 rounded px-2 py-1"
            />
            {searchResults.length > 0 && (
              <ul className="mt-1 border border-gray-200 rounded divide-y max-h-32 overflow-y-auto">
                {searchResults.map((p) => (
                  <li key={p.person_name}>
                    <button
                      className="w-full text-left px-2 py-1 hover:bg-gray-50"
                      onClick={() => submitLabel(p.person_name, p.og)}
                    >
                      {p.person_name}
                      {p.og ? (
                        <span className="text-gray-400"> ({p.og})</span>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {ogGroups.length > 0 && (
            <div>
              <p className="text-gray-500 mb-1">or pick from list below</p>
              <div className="flex flex-wrap gap-1 mb-1">
                {ogGroups.map(([og]) => (
                  <button
                    key={og}
                    onClick={() => setActiveOg(og)}
                    className={`px-2 py-0.5 rounded border text-[11px] ${
                      currentTab === og
                        ? "bg-indigo-600 text-white border-indigo-600"
                        : "bg-white text-gray-700 border-gray-300"
                    }`}
                  >
                    {og}
                  </button>
                ))}
              </div>
              <ul className="border border-gray-200 rounded divide-y max-h-32 overflow-y-auto">
                {currentTabPeople.map((p) => (
                  <li key={p.person_name}>
                    <button
                      className="w-full text-left px-2 py-1 hover:bg-gray-50"
                      onClick={() => submitLabel(p.person_name, p.og)}
                    >
                      {p.person_name}
                    </button>
                  </li>
                ))}
                {currentTabPeople.length === 0 && (
                  <li className="px-2 py-1 text-gray-400">No people in this group</li>
                )}
              </ul>
            </div>
          )}

          <div>
            <label className="text-gray-500 block mb-1">
              or type a new name
            </label>
            <form
              className="flex gap-1"
              onSubmit={(e) => {
                e.preventDefault();
                if (freeText.trim()) submitLabel(freeText.trim(), null);
              }}
            >
              <input
                value={freeText}
                onChange={(e) => setFreeText(e.target.value)}
                placeholder="New person's name"
                className="flex-1 min-w-0 border border-gray-300 rounded px-2 py-1"
              />
              <button
                type="submit"
                disabled={!freeText.trim()}
                className="px-2 py-1 rounded bg-indigo-600 text-white disabled:opacity-50"
              >
                Save
              </button>
            </form>
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => setMode("idle")}
              className="text-gray-500 hover:underline self-start"
            >
              Cancel
            </button>
            <button
              onClick={defer}
              className="text-indigo-600 hover:underline self-start"
            >
              Move to Others (decide later)
            </button>
          </div>
        </div>
      )}

      {confirmingYes && cluster.recommendation && (
        <div
          className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-6"
          onClick={() => setConfirmingYes(false)}
        >
          <div
            className="bg-white rounded-lg shadow-xl w-full max-w-sm p-5 flex flex-col gap-4"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="text-sm text-gray-900">
              Are you sure this is{" "}
              <span className="font-semibold">{cluster.recommendation.person_name}</span>
              {cluster.recommendation.og ? ` (${cluster.recommendation.og})` : ""}?
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirmingYes(false)}
                className="px-3 py-1.5 rounded border border-gray-300 text-sm text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setConfirmingYes(false);
                  submitLabel(cluster.recommendation!.person_name, cluster.recommendation!.og);
                }}
                className="px-3 py-1.5 rounded bg-green-600 text-white text-sm hover:bg-green-700"
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmingDiscard && (
        <div
          className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-6"
          onClick={() => setConfirmingDiscard(false)}
        >
          <div
            className="bg-white rounded-lg shadow-xl w-full max-w-sm p-5 flex flex-col gap-4"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="text-sm text-gray-900">
              Discard this cluster as not a person? This marks all{" "}
              <span className="font-semibold">{cluster.face_count}</span> face(s) in it as a
              false detection.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirmingDiscard(false)}
                className="px-3 py-1.5 rounded border border-gray-300 text-sm text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setConfirmingDiscard(false);
                  discard();
                }}
                className="px-3 py-1.5 rounded bg-red-600 text-white text-sm hover:bg-red-700"
              >
                Discard
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
