import React from "react";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { renderWithProviders } from "./test-utils";
import RecommendationsPanel from "@/components/panels/RecommendationsPanel";

jest.mock("@/lib/api", () => {
  const rec = {
    id: 1,
    pan_id: 1,
    prediction_id: 1,
    recommendation_type: "harvest_soon",
    title: "Schedule harvest in the next 1-2 days",
    message: "Readiness is 65%",
    rationale: "Readiness is high.",
    expected_benefit: "Captures the crop.",
    risk_level: "medium",
    status: "pending",
    farmer_notes: "",
    created_at: "2025-01-15T10:00:00Z",
    responded_at: null,
    action_deadline: "2025-01-17",
    confidence_pct: 72,
    reasons: ["Reason 1", "Reason 2", "Reason 3"],
    instructions: ["Step 1", "Step 2", "Step 3"],
    consequence_if_waited: "Risk increases.",
  };
  return {
    api: {
      pans: jest.fn().mockResolvedValue([
        { id: 1, pan_id: "PAN-1", name: "Pan A", status: "active" },
      ]),
      recommendations: jest.fn().mockResolvedValue([
        { ...rec, id: 1, status: "pending" },
        { ...rec, id: 2, status: "accepted", title: "Accepted rec" },
        { ...rec, id: 3, status: "declined", title: "Declined rec" },
      ]),
      respondRecommendation: jest.fn().mockImplementation((id, body) =>
        Promise.resolve({ ...rec, id, status: body.status }),
      ),
      generateRecommendations: jest.fn().mockResolvedValue([]),
      completeRecommendation: jest.fn().mockResolvedValue({ ...rec, status: "completed" }),
      status: jest.fn().mockResolvedValue({ seeded: true, pans: 1 }),
    },
    fmt: {
      kg: (n?: number) => String(n ?? "—"),
      mm: (n?: number) => `${n ?? "—"} mm`,
      cm: (n?: number) => `${n ?? "—"} cm`,
      pct: (n?: number) => `${Math.round((n ?? 0) * 100)}%`,
      date: (s?: string) => s ?? "—",
    },
    severityColor: (level: string) =>
      level === "high"
        ? "bg-red-500/15 text-red-300 border-red-500/40"
        : level === "medium"
          ? "bg-amber-500/15 text-amber-300 border-amber-500/40"
          : "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
    recStatusTone: (status: string) =>
      status === "accepted"
        ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
        : status === "declined"
          ? "border-slate-400/40 bg-slate-500/15 text-slate-300"
          : "border-amber-500/40 bg-amber-500/15 text-amber-300",
  };
});;

describe("RecommendationsPanel — display and accept/reject", () => {
  it("renders the recommendations heading", async () => {
    renderWithProviders(<RecommendationsPanel />);
    await waitFor(() => {
      expect(screen.getByText("Farmer recommendations")).toBeInTheDocument();
    });
  });

  it("displays pending recommendation cards", async () => {
    renderWithProviders(<RecommendationsPanel />);
    await waitFor(() => {
      expect(screen.getByText("Schedule harvest in the next 1-2 days")).toBeInTheDocument();
    });
  });

  it("shows accept and decline buttons for pending recs", async () => {
    renderWithProviders(<RecommendationsPanel />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Decline" })).toBeInTheDocument();
    });
  });

  it("calls respondRecommendation on accept", async () => {
    const user = userEvent.setup();
    const api = require("@/lib/api").api;
    renderWithProviders(<RecommendationsPanel />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Accept" }));

    await waitFor(() => {
      expect(api.respondRecommendation).toHaveBeenCalledWith(1, {
        status: "accepted",
        farmer_notes: "",
      });
    });
  });

  it("calls respondRecommendation on decline", async () => {
    const user = userEvent.setup();
    const api = require("@/lib/api").api;
    renderWithProviders(<RecommendationsPanel />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Decline" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Decline" }));

    await waitFor(() => {
      expect(api.respondRecommendation).toHaveBeenCalledWith(1, {
        status: "declined",
        farmer_notes: "",
      });
    });
  });

  it("shows status filter tabs", async () => {
    renderWithProviders(<RecommendationsPanel />);
    await waitFor(() => {
      expect(screen.getByText("Active")).toBeInTheDocument();
      expect(screen.getByText("Accepted")).toBeInTheDocument();
      expect(screen.getByText("Rejected")).toBeInTheDocument();
      expect(screen.getByText("Completed")).toBeInTheDocument();
    });
  });

  it("displays the expected benefit line", async () => {
    renderWithProviders(<RecommendationsPanel />);
    await waitFor(() => {
      expect(screen.getByText(/Captures the crop/)).toBeInTheDocument();
    });
  });
});
