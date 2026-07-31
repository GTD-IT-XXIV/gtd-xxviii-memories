"use client";

import { useMemo, useState } from "react";
import type { KnownPerson, ReviewClusterViewModel } from "@/lib/types";
import ReviewClusterCard from "./ReviewClusterCard";

export interface ReviewFolder {
  key: string;
  label: string;
  clusters: ReviewClusterViewModel[];
}

const OTHERS_KEY = "OTHERS";

export default function ReviewFolders({
  folders,
  knownPersons,
}: {
  folders: ReviewFolder[];
  knownPersons: KnownPerson[];
}) {
  const [openFolder, setOpenFolder] = useState<string | null>(null);
  // Clusters "No"-ed out of an OG folder - shown in Others instead, client-side
  // only (never persisted; a page refresh recomputes fresh recommendations).
  const [rejectedIds, setRejectedIds] = useState<Set<number>>(new Set());
  // Clusters labeled/discarded this session - dropped from folder counts
  // immediately rather than waiting on the next full data refresh.
  const [removedIds, setRemovedIds] = useState<Set<number>>(new Set());

  const foldersByKey = useMemo(() => new Map(folders.map((f) => [f.key, f])), [folders]);

  function visibleClusters(folderKey: string): ReviewClusterViewModel[] {
    if (folderKey === OTHERS_KEY) {
      const ownOthers = foldersByKey.get(OTHERS_KEY)?.clusters ?? [];
      const rejectedFromOgFolders = folders
        .filter((f) => f.key !== OTHERS_KEY)
        .flatMap((f) => f.clusters)
        .filter((c) => rejectedIds.has(c.id));
      return [...ownOthers, ...rejectedFromOgFolders].filter((c) => !removedIds.has(c.id));
    }
    const clusters = foldersByKey.get(folderKey)?.clusters ?? [];
    return clusters.filter((c) => !rejectedIds.has(c.id) && !removedIds.has(c.id));
  }

  function markRemoved(id: number) {
    setRemovedIds((cur) => new Set(cur).add(id));
  }

  if (openFolder === null) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4">
        {folders.map((f) => (
          <button
            key={f.key}
            onClick={() => setOpenFolder(f.key)}
            className="border border-gray-200 rounded-lg p-4 flex flex-col items-center gap-1 bg-white hover:bg-gray-50"
          >
            <span className="text-3xl">&#128193;</span>
            <span className="font-medium text-sm">{f.label}</span>
            <span className="text-xs text-gray-500">{visibleClusters(f.key).length} to review</span>
          </button>
        ))}
      </div>
    );
  }

  const folder = foldersByKey.get(openFolder);
  const clusters = visibleClusters(openFolder);
  const isOthers = openFolder === OTHERS_KEY;

  return (
    <div>
      <button
        onClick={() => setOpenFolder(null)}
        className="text-sm text-indigo-600 hover:underline mb-3"
      >
        &larr; Back to folders
      </button>
      <h2 className="text-lg font-semibold mb-3">
        {folder?.label} <span className="text-sm font-normal text-gray-500">({clusters.length})</span>
      </h2>

      {clusters.length === 0 ? (
        <p className="text-sm text-gray-500">Nothing left to review in this folder.</p>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
          {clusters.map((cluster) => (
            <ReviewClusterCard
              key={cluster.id}
              cluster={isOthers ? { ...cluster, recommendation: null } : cluster}
              knownPersons={knownPersons}
              onReject={isOthers ? undefined : () => setRejectedIds((cur) => new Set(cur).add(cluster.id))}
              onRemoved={() => markRemoved(cluster.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
