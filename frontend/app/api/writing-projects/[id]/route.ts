import { NextResponse } from "next/server";

const API_BASE = (process.env.API_URL ?? "http://backend:8000").replace(/\/$/, "");

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const response = await fetch(`${API_BASE}/writing-projects/${encodeURIComponent(id)}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  const payload = await response.json().catch(() => ({ detail: "写作工作台读取失败" }));
  return NextResponse.json(payload, { status: response.status });
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const body = await request.text();
  const response = await fetch(`${API_BASE}/writing-projects/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body,
  });
  const payload = await response.json().catch(() => ({ detail: "草稿保存失败" }));
  return NextResponse.json(payload, { status: response.status });
}
