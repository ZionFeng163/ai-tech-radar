import Link from "next/link";

interface PaginationLinkProps {
  cursor: string | null;
  href: string;
}

export function PaginationLink({ cursor, href }: PaginationLinkProps) {
  if (!cursor) return null;
  const separator = href.includes("?") ? "&" : "?";
  return (
    <Link className="pagination-link" href={`${href}${separator}cursor=${encodeURIComponent(cursor)}`}>
      加载下一组信号 <span aria-hidden="true">↓</span>
    </Link>
  );
}
