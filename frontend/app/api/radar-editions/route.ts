import { NextResponse } from "next/server";

const API_BASE = (process.env.API_URL ?? "http://backend:8000").replace(/\/$/, "");

export async function POST() {
  const response = await fetch(`${API_BASE}/radar-editions`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  const payload = await response.json().catch(() => ({ detail: "capture failed" }));
  return NextResponse.json(payload, { status: response.status });
}
