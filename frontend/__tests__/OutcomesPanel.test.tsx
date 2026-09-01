import React from "react";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { renderWithProviders } from "./test-utils";
import OutcomesPanel from "@/components/panels/OutcomesPanel";

jest.mock("@/lib/api", () => ({
  api: {
    pans: jest.fn().mockResolvedValue([
      { id: 1, pan_id: "PAN-1", name: "Pan A", status: "active" },
    ]),
    predictions: jest.fn().mockResolvedValue([
      { id: 1, pan_id: 1, prediction_date: "2025-01-14", status: "completed" },
    ]),
    recommendations: jest.fn().mockResolvedValue([
      {
        id: 1,
        pan_id: 1,
        title: "Schedule harvest in the next 1-2 days",
        status: "pending",
      },
    ]),
    outcomes: jest.fn().mockResolvedValue([]),
    createOutcome: jest.fn().mockResolvedValue({ id: 2 }),
    verifyOutcome: jest.fn().mockResolvedValue({ id: 1 }),
    status: jest.fn().mockResolvedValue({ seeded: true, pans: 1 }),
  },
  fmt: {
    kg: (n?: number) => (n == null ? "—" : String(n)),
    mm: (n?: number) => (n == null ? "—" : `${n} mm`),
    cm: (n?: number) => (n == null ? "—" : `${n} cm`),
    pct: (n?: number) => (n == null ? "—" : `${Math.round(n * 100)}%`),
    date: (s?: string) => s ?? "—",
    hours: (n?: number | null) => (n == null ? "—" : `${n} min`),
    lit: (n?: number | null) => (n == null ? "—" : String(n)),
  },
}));

describe("OutcomesPanel — outcome form", () => {
  it("renders the record actual outcome form title", async () => {
    renderWithProviders(<OutcomesPanel />);
    await waitFor(() => {
      expect(screen.getByText("Record actual outcome")).toBeInTheDocument();
    });
  });

  it("shows pan selector", async () => {
    renderWithProviders(<OutcomesPanel />);
    await waitFor(() => {
      expect(screen.getByText(/PAN-1/)).toBeInTheDocument();
    });
  });

  it("submits an outcome with actual yield", async () => {
    const user = userEvent.setup();
    const api = require("@/lib/api").api;
    renderWithProviders(<OutcomesPanel />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Record outcome" })).toBeInTheDocument();
    });

    const yieldInput = screen.getByPlaceholderText("e.g. 90000");
    await user.type(yieldInput, "950");

    await user.click(screen.getByRole("button", { name: "Record outcome" }));

    await waitFor(() => {
      expect(api.createOutcome).toHaveBeenCalled();
      const body = api.createOutcome.mock.calls[0][0];
      expect(body.actual_yield_kg).toBe(950);
      expect(body.pan_id).toBe(1);
    });
  });
});
