import React from "react";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { renderWithProviders } from "./test-utils";
import SimulatePanel from "@/components/panels/SimulatePanel";

jest.mock("@/lib/api", () => ({
  api: {
    pans: jest.fn().mockResolvedValue([
      { id: 1, pan_id: "PAN-1", name: "Pan A", status: "active" },
    ]),
    simulatePanRain: jest.fn().mockResolvedValue({
      pan_id: 1,
      pan_ref: "PAN-1",
      current_salinity_g_l: 245,
      current_depth_cm: 8,
      current_volume_m3: 192,
      rain_volume_m3: 36,
      predicted_salinity_after_rain_g_l: 215.4,
      predicted_depth_after_rain_cm: 9.5,
      predicted_harvest_delay_hours: 48,
      risk_before: "MEDIUM",
      risk_after: "LOW",
      recommended_action: "monitor",
      recommendation: "No urgent action needed.",
      forecast_source: "mock",
    }),
    simulateRain: jest.fn().mockResolvedValue({
      scenario_name: "what-if-rain",
      forecast_source: "mock",
      impact: {
        projected_yield_loss_kg: 0,
        salt_thickness_loss_mm: 0,
        risk_increase: 0.1,
        max_risk_after_rain: 0.4,
        max_risk_baseline: 0.2,
        readiness_drop_on_day: 0.1,
        readiness_before: 0.65,
        readiness_after: 0.55,
        event_date: "2025-01-16",
        days_setback_estimate: 2,
        risk_critical: false,
      },
      baseline: [{ label: "d1", readiness: 0.5, risk: 0.2 }],
      rain_scenario: [{ label: "d1", readiness: 0.4, risk: 0.4 }],
    }),
    digitalTwin: jest.fn().mockResolvedValue({
      pan_id: 1,
      pan_ref: "PAN-1",
      salinity_g_l: 245,
      water_depth_cm: 8,
      brine_volume_m3: 192,
      forecast_rainfall_mm: 0,
      forecast_rainfall_7d_mm: 5,
    }),
    status: jest.fn().mockResolvedValue({ seeded: true, pans: 1 }),
  },
  fmt: {
    kg: (n?: number) => String(n ?? "—"),
    mm: (n?: number) => `${n ?? "—"} mm`,
    cm: (n?: number) => `${n ?? "—"} cm`,
    pct: (n?: number) => `${Math.round((n ?? 0) * 100)}%`,
    date: (s?: string) => s ?? "—",
  },
  riskTone: () => ({ text: "text-emerald-400", bar: "bg-emerald-500" }),
}));

describe("SimulatePanel — rain simulation", () => {
  it("renders the rain impact simulator title", () => {
    renderWithProviders(<SimulatePanel />);
    expect(screen.getByText("Rain impact simulator")).toBeInTheDocument();
  });

  it("shows the rainfall range slider", async () => {
    renderWithProviders(<SimulatePanel />);
    await waitFor(() => {
      expect(screen.getByRole("slider")).toBeInTheDocument();
    });
  });

  it("runs quick simulation and shows post-rain salinity", async () => {
    const user = userEvent.setup();
    const api = require("@/lib/api").api;
    renderWithProviders(<SimulatePanel />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Simulate" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Simulate" }));

    await waitFor(() => {
      expect(api.simulatePanRain).toHaveBeenCalled();
      expect(screen.getByText("215 g/L")).toBeInTheDocument();
    });
    expect(screen.getByText("Salinity after rain")).toBeInTheDocument();
  });

  it("renders the ML what-if question title", () => {
    renderWithProviders(<SimulatePanel />);
    expect(screen.getByText(/What happens if it rains/)).toBeInTheDocument();
  });

  it("shows rain event numeric input", async () => {
    renderWithProviders(<SimulatePanel />);
    await waitFor(() => {
      expect(screen.getByText("Rain event (mm)")).toBeInTheDocument();
    });
  });
});
