import React from "react";
import { screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { renderWithProviders } from "./test-utils";
import Dashboard from "@/components/panels/Dashboard";

jest.mock("@/lib/api", () => ({
  api: {
    status: jest.fn().mockResolvedValue({
      seeded: true,
      pans: 1,
      models: 5,
      model_kinds: {},
      any_active_model: true,
      datasets: 1,
      predictions: 2,
      recommendations: 3,
      outcomes: 1,
      training_pool_file: "",
      feedback_pool_file: "",
    }),
    pans: jest.fn().mockResolvedValue([
      {
        id: 1,
        pan_id: "PAN-1",
        name: "Tuticorin Salt Pan A",
        location: "Tuticorin",
        area_m2: 2400,
        status: "active",
        twin_state: {},
        latitude: 8.76,
        longitude: 78.13,
        created_at: "2025-01-01T00:00:00Z",
        updated_at: "2025-01-15T00:00:00Z",
      },
    ]),
    digitalTwin: jest.fn().mockResolvedValue({
      pan_id: 1,
      pan_ref: "PAN-1",
      timestamp: "2025-01-15T10:00:00Z",
      last_update: "2025-01-15",
      source: "prediction",
      forecast_source: "mock",
      salinity_g_l: 245.0,
      water_depth_cm: 8.0,
      brine_temperature_c: 28.5,
      brine_volume_m3: 192.0,
      estimated_salt_mass_kg: 11520.0,
      forecast_rainfall_mm: 0.0,
      forecast_rainfall_7d_mm: 5.0,
      rain_probability_pct: 20.0,
      predicted_depth_after_rain_cm: 8.0,
      predicted_salinity_after_rain_g_l: 245.0,
      evaporation_mm_day: 7.5,
      harvest_readiness: 0.65,
      climate_risk: 0.30,
      overflow_risk: 0.0,
      last_operation: null,
      demo_today: null,
      state: {},
    }),
    recommendations: jest.fn().mockResolvedValue([
      {
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
      },
    ]),
  },
  fmt: {
    kg: (n?: number) => String(n ?? "—"),
    mm: (n?: number) => `${n ?? "—"} mm`,
    cm: (n?: number) => `${n ?? "—"} cm`,
    pct: (n?: number) => `${Math.round((n ?? 0) * 100)}%`,
    date: (s?: string) => s ?? "—",
  },
  readinessTone: () => ({ text: "text-emerald-400", bar: "bg-emerald-500" }),
  riskTone: () => ({ text: "text-emerald-400", bar: "bg-emerald-500" }),
  severityColor: () => "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  recStatusTone: () => "border-amber-500/40 bg-amber-500/15 text-amber-300",
}));

describe("Dashboard — rendering", () => {
  it("renders the dashboard heading", async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText("Farmer dashboard")).toBeInTheDocument();
    });
  });

  it("shows fleet KPI strip", async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText("Total pans")).toBeInTheDocument();
      expect(screen.getByText("High-risk pans")).toBeInTheDocument();
      expect(screen.getByText("Harvest-ready")).toBeInTheDocument();
      expect(screen.getByText("Active alerts")).toBeInTheDocument();
    });
  });

  it("displays system ready badge", async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText("System ready")).toBeInTheDocument();
    });
  });

  it("shows current field conditions card", async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText("Current field conditions")).toBeInTheDocument();
    });
  });

  it("shows recommended action card", async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText(/Recommended action/)).toBeInTheDocument();
    });
  });

  it("shows pan status board", async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByText("Pan status board")).toBeInTheDocument();
    });
  });
});
