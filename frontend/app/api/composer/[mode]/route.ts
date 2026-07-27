import { NextResponse } from "next/server";

const API_BASE = (process.env.API_URL ?? "http://backend:8000").replace(/\/$/, "");
const ALLOWED_MODES = new Set(["idea", "paper", "github"]);

export async function POST(
  request: Request,
  { params }: { params: Promise<{ mode: string }> },
) {
  const { mode } = await params;
  if (!ALLOWED_MODES.has(mode)) {
    return NextResponse.json({ detail: "未知写作模式" }, { status: 404 });
  }
  const response = await fetch(`${API_BASE}/composer/${mode}`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: await request.text(),
  });
  const payload = await response.json().catch(() => ({ detail: "写作生成失败" }));
  return NextResponse.json(payload, { status: response.status });
}
