import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ComposePage from "./page";

describe("ComposePage", () => {
  it("offers idea and paper writing without persistence", () => {
    render(<ComposePage />);

    expect(screen.getByRole("heading", { name: /从半个想法/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /整理碎片想法/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: /从论文链接写短帖/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "扩写成短推文" })).toBeDisabled();
  });
});
