import React from "react";
import { screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { renderWithProviders } from "./test-utils";
import DataPanel from "@/components/panels/DataPanel";

jest.mock("@/lib/api", () => ({
  api: {
    datasets: jest.fn().mockResolvedValue([
      {
        id: 1,
        name: "test_dataset",
        filename: "test.csv",
        rows_count: 500,
        columns: ["pan_id", "date", "temperature_c"],
        dataset_type: "combined",
        status: "valid",
        validation_report: {},
        source: "upload",
        created_at: "2025-01-15T10:00:00Z",
      },
    ]),
    datasetPreview: jest.fn().mockResolvedValue({ columns: ["col1"], rows: [] }),
    datasetAnalysis: jest.fn().mockResolvedValue({
      valid_rows: 500,
      rejected_rows: 5,
      dataset_type: "combined",
      detection_confidence: 0.95,
      status: "valid",
      quality: { missing: {}, outliers: {} },
      conversions: [],
      duplicates: 0,
    }),
    previewUpload: jest.fn(),
    uploadDataset: jest.fn(),
    validateDataset: jest.fn().mockResolvedValue({ id: 1, status: "valid" }),
    promoteDataset: jest.fn().mockResolvedValue({ id: 1, status: "promoted" }),
    importDataset: jest.fn().mockResolvedValue({
      dataset: { id: 1 },
      summary: { imported_rows: 500, tables: ["sensor_readings"], created_pans: [] },
    }),
    invalidRowsUrl: jest.fn().mockReturnValue("http://localhost:8000/api/datasets/1/invalid_rows"),
  },
  fmt: {
    kg: (n?: number) => String(n ?? "—"),
    mm: (n?: number) => `${n ?? "—"} mm`,
    cm: (n?: number) => `${n ?? "—"} cm`,
    pct: (n?: number) => `${Math.round((n ?? 0) * 100)}%`,
    date: (s?: string) => s ?? "—",
  },
}));

describe("DataPanel — dataset upload", () => {
  it("renders the upload card title", async () => {
    renderWithProviders(<DataPanel />);
    await waitFor(() => {
      expect(screen.getByText(/Upload a salt-pan dataset/)).toBeInTheDocument();
    });
  });

  it("displays registered datasets", async () => {
    renderWithProviders(<DataPanel />);
    await waitFor(() => {
      expect(screen.getByText("Registered datasets")).toBeInTheDocument();
    });
    expect(screen.getByText("test_dataset")).toBeInTheDocument();
  });

  it("shows dataset type dropdown", async () => {
    renderWithProviders(<DataPanel />);
    await waitFor(() => {
      expect(screen.getByDisplayValue("Auto-detect")).toBeInTheDocument();
    });
  });

  it("shows file input for CSV upload", async () => {
    renderWithProviders(<DataPanel />);
    await waitFor(() => {
      const fileInput = document.querySelector('input[type="file"]');
      expect(fileInput).toBeInTheDocument();
      expect(fileInput).toHaveAttribute("accept", ".csv,.tsv");
    });
  });
});
