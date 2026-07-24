import { NextResponse } from "next/server";

const API_BASE = (process.env.API_URL ?? "http://backend:8000").replace(/\/$/, "");
const ALLOWED_ACTIONS = new Set(["angles", "draft", "review"]);

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; action: string }> },
) {
  const { id, action } = await params;
  if (!ALLOWED_ACTIONS.has(action)) {
    return NextResponse.json({ detail: "未知写作操作" }, { status: 404 });
  }
  const body = action === "draft" ? await request.text() : undefined;
  const response = await fetch(
    `${API_BASE}/writing-projects/${encodeURIComponent(id)}/${action}`,
    {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body,
    },
  );
  const payload = await response.json().catch(() => ({ detail: "写作操作失败" }));
  return NextResponse.json(payload, { status: response.status });
}
