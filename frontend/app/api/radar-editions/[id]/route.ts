import { NextResponse } from "next/server";

const API_BASE = (process.env.API_URL ?? "http://backend:8000").replace(/\/$/, "");

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const response = await fetch(`${API_BASE}/radar-editions/${encodeURIComponent(id)}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  const payload = await response.json().catch(() => ({ detail: "status unavailable" }));
  return NextResponse.json(payload, { status: response.status });
}
