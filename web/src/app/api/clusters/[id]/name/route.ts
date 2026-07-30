import { NextRequest, NextResponse } from "next/server";
import { getSql, nowIso } from "@/lib/db";

/**
 * Labels a cluster: sets person_name (+ optional og) and flips status to
 * 'labeled'. Used by both the "Yes, that's them" recommendation-confirm
 * path and the manual correction path (search / tab-pick / free-text) on
 * the review page -- they all funnel through this one handler, matching
 * the old Python `cluster_service.name_cluster` behavior plus an `og`.
 */
export async function POST(
  request: NextRequest,
  ctx: RouteContext<"/api/clusters/[id]/name">
) {
  const { id } = await ctx.params;
  const clusterId = Number(id);
  if (!Number.isInteger(clusterId)) {
    return NextResponse.json({ error: "Invalid cluster id" }, { status: 400 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const { person_name, og } = (body ?? {}) as {
    person_name?: unknown;
    og?: unknown;
  };

  if (typeof person_name !== "string" || person_name.trim().length === 0) {
    return NextResponse.json(
      { error: "person_name is required" },
      { status: 400 }
    );
  }
  const trimmedName = person_name.trim();
  const trimmedOg =
    typeof og === "string" && og.trim().length > 0 ? og.trim() : null;

  const sql = getSql();
  const rows = await sql`
    UPDATE clusters
    SET person_name = ${trimmedName},
        og = ${trimmedOg},
        status = 'labeled',
        updated_at = ${nowIso()}
    WHERE id = ${clusterId}
    RETURNING id, person_name, og, status
  `;

  if (rows.length === 0) {
    return NextResponse.json({ error: "Cluster not found" }, { status: 404 });
  }

  return NextResponse.json({ cluster: rows[0] });
}
