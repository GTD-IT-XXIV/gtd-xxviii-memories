"use client";

import { useState } from "react";
import type { KnownPerson, ReviewClusterViewModel } from "@/lib/types";
import ReviewClusterCard from "./ReviewClusterCard";

export default function ReviewClusterGrid({
  clusters,
  knownPersons,
  defaultOg,
}: {
  clusters: ReviewClusterViewModel[];
  knownPersons: KnownPerson[];
  /** Folder being reviewed, preselected in each card's "new name" OG picker. */
  defaultOg?: string | null;
}) {
  // Clusters labeled/discarded/deferred this session - dropped from the grid
  // immediately rather than waiting on the next full data refresh. Remounted
  // fresh (see the `key={folder-page}` prop from page.tsx) on every folder
  // switch or page flip, so this never leaks across navigations.
  const [removedIds, setRemovedIds] = useState<Set<number>>(new Set());

  const visible = clusters.filter((c) => !removedIds.has(c.id));

  function markRemoved(id: number) {
    setRemovedIds((cur) => new Set(cur).add(id));
  }

  if (visible.length === 0) {
    return <p className="text-sm text-gray-500">Nothing left to review in this folder.</p>;
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
      {visible.map((cluster) => (
        <ReviewClusterCard
          key={cluster.id}
          cluster={cluster}
          knownPersons={knownPersons}
          defaultOg={defaultOg}
          onRemoved={() => markRemoved(cluster.id)}
        />
      ))}
    </div>
  );
}
