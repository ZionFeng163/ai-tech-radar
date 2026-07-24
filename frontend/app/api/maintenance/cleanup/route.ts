import { NextResponse } from "next/server";

const API_BASE = (process.env.API_URL ?? "http://backend:8000").replace(/\/$/, "");

function keepEditions(request: Request): string {
  return new URL(request.url).searchParams.get("keep_editions") ?? "10";
}

async function forward(request: Request, method: "GET" | "DELETE") {
  const endpoint = method === "GET" ? "cleanup-preview" : "data";
  const response = await fetch(
    `${API_BASE}/maintenance/${endpoint}?keep_editions=${encodeURIComponent(keepEditions(request))}`,
    { method, cache: "no-store", headers: { Accept: "application/json" } },
  );
  const payload = await response.json().catch(() => ({ detail: "cleanup unavailable" }));
  return NextResponse.json(payload, { status: response.status });
}

export function GET(request: Request) {
  return forward(request, "GET");
}

export function DELETE(request: Request) {
  return forward(request, "DELETE");
}
