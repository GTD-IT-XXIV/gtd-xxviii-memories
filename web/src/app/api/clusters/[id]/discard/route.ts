import { NextRequest, NextResponse } from "next/server";
import { getSql, nowIso } from "@/lib/db";

/** Marks a cluster as 'discarded' (not a real person / false detection). */
export async function POST(
  _request: NextRequest,
  ctx: RouteContext<"/api/clusters/[id]/discard">
) {
  const { id } = await ctx.params;
  const clusterId = Number(id);
  if (!Number.isInteger(clusterId)) {
    return NextResponse.json({ error: "Invalid cluster id" }, { status: 400 });
  }

  const sql = getSql();
  const rows = await sql`
    UPDATE clusters
    SET status = 'discarded',
        updated_at = ${nowIso()}
    WHERE id = ${clusterId}
    RETURNING id, status
  `;

  if (rows.length === 0) {
    return NextResponse.json({ error: "Cluster not found" }, { status: 404 });
  }

  return NextResponse.json({ cluster: rows[0] });
}
