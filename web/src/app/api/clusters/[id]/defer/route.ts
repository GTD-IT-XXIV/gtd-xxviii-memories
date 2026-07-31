import { NextRequest, NextResponse } from "next/server";
import { getSql, nowIso } from "@/lib/db";

/**
 * Marks a cluster as deferred to the "Others" folder for later review, without
 * changing its `status` - it stays 'unlabeled' and fully eligible for future
 * incremental face-matching (see ClusterIndex.load() in
 * app/clustering/similarity.py, which filters on status, not this column).
 * Used by the review page's "No" -> "Move to Others (decide later)" action.
 */
export async function POST(
  _request: NextRequest,
  ctx: RouteContext<"/api/clusters/[id]/defer">
) {
  const { id } = await ctx.params;
  const clusterId = Number(id);
  if (!Number.isInteger(clusterId)) {
    return NextResponse.json({ error: "Invalid cluster id" }, { status: 400 });
  }

  const sql = getSql();
  const rows = await sql`
    UPDATE clusters
    SET deferred_to_others = true,
        updated_at = ${nowIso()}
    WHERE id = ${clusterId} AND status = 'unlabeled'
    RETURNING id, deferred_to_others, status
  `;

  if (rows.length === 0) {
    return NextResponse.json({ error: "Cluster not found" }, { status: 404 });
  }

  return NextResponse.json({ cluster: rows[0] });
}
