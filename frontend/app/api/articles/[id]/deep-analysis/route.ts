import { NextResponse } from "next/server";

const API_BASE = (process.env.API_URL ?? "http://backend:8000").replace(/\/$/, "");

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const response = await fetch(
    `${API_BASE}/articles/${encodeURIComponent(id)}/deep-analysis`,
    { method: "POST", headers: { Accept: "application/json" } },
  );
  const payload = await response.json().catch(() => ({ detail: "analysis failed" }));
  return NextResponse.json(payload, { status: response.status });
}
