import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("Home", () => {
  it("shows the MVP foundation status", () => {
    render(<Home />);

    expect(screen.getByRole("heading", { name: /每日 AI 技术动态/ })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("MVP foundation online");
  });
});
