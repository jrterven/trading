import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "/Users/juanterven/dev/trading/outputs/strategy_search";
const csvPath = path.join(outputDir, "strategy_search_results.csv");
const jsonPath = path.join(outputDir, "top_strategy.json");
const xlsxPath = path.join(outputDir, "strategy_search_report.xlsx");
const previewPath = path.join(outputDir, "strategy_search_report_summary.png");
const resultsPreviewPath = path.join(outputDir, "strategy_search_report_results.png");

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const headers = lines[0].split(",");
  return lines.slice(1).map((line) => {
    const values = line.split(",");
    const row = {};
    headers.forEach((header, index) => {
      const raw = values[index] ?? "";
      const numeric = Number(raw);
      row[header] = raw !== "" && Number.isFinite(numeric) ? numeric : raw;
    });
    return row;
  });
}

function matrixFromRows(headers, rows) {
  return [headers, ...rows.map((row) => headers.map((header) => row[header] ?? ""))];
}

const csvText = await fs.readFile(csvPath, "utf8");
const rows = parseCsv(csvText);
const top = JSON.parse(await fs.readFile(jsonPath, "utf8"));
const topRow = rows.find((row) => row.Strategy === top.config.name) ?? rows[0];
const assets = ["AMD", "AMZN", "GOOGL", "NVDA", "AAPL", "META", "TSLA", "NFLX"];

const workbook = Workbook.create();
const summary = workbook.worksheets.add("Summary");
const results = workbook.worksheets.add("Results");
summary.showGridLines = false;
results.showGridLines = false;

summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["Trading Strategy Search Report"]];
summary.getRange("A1").format = {
  fill: "#0F3D3E",
  font: { bold: true, color: "#FFFFFF", size: 16 },
};
summary.getRange("A2:H2").merge();
summary.getRange("A2").values = [[
  "100 per-asset model variations trained on 2025 daily data and backtested from 2026-01-01 through 2026-06-30.",
]];
summary.getRange("A2").format = { font: { color: "#475569" }, wrapText: true };

summary.getRange("A4:B12").values = [
  ["Top Strategy", top.config.name],
  ["Iterations Completed", rows.length],
  ["Stopping Conditions Met", top.summary.meets_stopping_conditions ? "Yes" : "No"],
  ["Average Return", top.summary.avg_return_pct / 100],
  ["Minimum Asset Return", top.summary.min_return_pct / 100],
  ["Worst Max Drawdown", top.summary.max_drawdown_pct / 100],
  ["Average Sharpe", top.summary.avg_sharpe],
  ["Positive Assets", top.summary.positive_asset_count],
  ["Objective Score", top.summary.objective_score],
];
summary.getRange("A4:A12").format = {
  fill: "#E2E8F0",
  font: { bold: true, color: "#0F172A" },
};
summary.getRange("B4:B12").format = { fill: "#F8FAFC" };
summary.getRange("B7:B9").format.numberFormat = "0.0%";
summary.getRange("B10:B12").format.numberFormat = "0.00";
summary.getRange("A4:B12").format.borders = { preset: "all", style: "thin", color: "#CBD5E1" };

const assetHeaders = ["Asset", "Return", "Max Drawdown", "Sharpe", "Trades"];
const assetRows = assets.map((asset) => [
  asset,
  topRow[`${asset}_ReturnPct`] / 100,
  topRow[`${asset}_MaxDrawdownPct`] / 100,
  topRow[`${asset}_Sharpe`],
  topRow[`${asset}_Trades`],
]);
summary.getRange("D4:H4").values = [assetHeaders];
summary.getRangeByIndexes(4, 3, assetRows.length, assetHeaders.length).values = assetRows;
summary.getRange("D4:H4").format = {
  fill: "#0F766E",
  font: { bold: true, color: "#FFFFFF" },
};
summary.getRange("E5:F12").format.numberFormat = "0.0%";
summary.getRange("G5:G12").format.numberFormat = "0.00";
summary.getRange("H5:H12").format.numberFormat = "#,##0";
summary.getRange("D4:H12").format.borders = { preset: "all", style: "thin", color: "#CBD5E1" };

const resultHeaders = Object.keys(rows[0]);
results.getRangeByIndexes(0, 0, rows.length + 1, resultHeaders.length).values = matrixFromRows(resultHeaders, rows);
results.getRangeByIndexes(0, 0, 1, resultHeaders.length).format = {
  fill: "#1E293B",
  font: { bold: true, color: "#FFFFFF" },
};
results.freezePanes.freezeRows(1);
results.freezePanes.freezeColumns(1);
results.getRangeByIndexes(0, 0, rows.length + 1, resultHeaders.length).format.borders = {
  preset: "inside",
  style: "thin",
  color: "#E2E8F0",
};
results.getRangeByIndexes(1, 11, rows.length, 7).format.numberFormat = "0.00";
for (let col = 18; col < resultHeaders.length; col += 4) {
  results.getRangeByIndexes(1, col, rows.length, 2).format.numberFormat = "0.0%";
  results.getRangeByIndexes(1, col + 2, rows.length, 1).format.numberFormat = "0.00";
  results.getRangeByIndexes(1, col + 3, rows.length, 1).format.numberFormat = "#,##0";
}

summary.getRange("A1:H12").format.autofitColumns();
summary.getRange("A1:H12").format.autofitRows();
results.getRangeByIndexes(0, 0, rows.length + 1, resultHeaders.length).format.autofitColumns();
results.getRange("A:A").format.columnWidth = 28;

const inspectSummary = await workbook.inspect({
  kind: "table",
  sheetId: "Summary",
  range: "A1:H12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 8,
});
console.log(inspectSummary.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const preview = await workbook.render({
  sheetName: "Summary",
  range: "A1:H12",
  scale: 2,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

const resultsPreview = await workbook.render({
  sheetName: "Results",
  range: "A1:R24",
  scale: 1,
  format: "png",
});
await fs.writeFile(resultsPreviewPath, new Uint8Array(await resultsPreview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(xlsxPath);
console.log(JSON.stringify({ xlsxPath, previewPath, resultsPreviewPath }));
