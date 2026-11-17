"""Bundle the dashboard CSVs into one Excel workbook for the dashboard tool.

    python scripts/05_export_xlsx.py

Reads the 7 CSVs in dashboard/data/ and writes dashboard/data/netflix_gap_marts.xlsx,
one sheet per CSV named after the file. Reads the CSVs only: no database connection,
and the marts are not touched. Values are written as-is: numbers stay numbers, rates
stay decimals (0.481, not 48.1), no formulas, and the only formatting is a bold header row.

After writing, the script reads the workbook back, checks it and prints the results.
It exits with status 1 if any check fails.
"""
import sys
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font

DATA = Path("dashboard/data")
OUT = DATA / "netflix_gap_marts.xlsx"
SHEETS = ["catalog_summary", "quality_index", "coverage_gap_genre", "country_votes_context",
          "indonesia_vs_global", "growth_by_year_added", "sensitivity_genre"]


def read_csv(name):
    # Only an empty field is missing; text such as "None" or "NA" stays text.
    return pd.read_csv(DATA / f"{name}.csv", keep_default_na=False, na_values=[""])


def write(frames):
    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        for name, df in frames.items():
            df.to_excel(xw, sheet_name=name, index=False)
            # pandas styles the header with borders and centering; keep bold only.
            for cell in xw.sheets[name][1]:
                cell.font = Font(bold=True)
                cell.border = Border()
                cell.alignment = Alignment()


def verify(frames):
    results = []

    def check(label, ok, detail):
        results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")

    wb = load_workbook(OUT)
    check("sheet names", wb.sheetnames == SHEETS, ", ".join(wb.sheetnames))

    back = pd.read_excel(OUT, sheet_name=None, engine="openpyxl")
    for name, df in frames.items():
        ws = wb[name]
        n_xlsx = ws.max_row - 1
        check(f"{name} rows", n_xlsx == len(df), f"sheet {n_xlsx:,} vs CSV {len(df):,}")

        header = [c.value for c in ws[1]]
        bold = all(c.font.bold for c in ws[1])
        check(f"{name} header", header == list(df.columns) and bold,
              f"{len(header)} columns in row 1, bold={bold}")

        numeric = [i for i, col in enumerate(df.columns, 1) if pd.api.types.is_numeric_dtype(df[col])
                   and not pd.api.types.is_bool_dtype(df[col])]
        as_text = [ws.cell(1, i).value for i in numeric
                   if any(isinstance(ws.cell(r, i).value, str) for r in range(2, ws.max_row + 1))]
        formulas = sum(c.data_type == "f" for row in ws.iter_rows() for c in row)
        check(f"{name} types", not as_text and formulas == 0,
              f"{len(numeric)} numeric columns stored as numbers"
              + (f"; stored as text: {', '.join(as_text)}" if as_text else "")
              + f"; {formulas} formulas")

    cv = back["country_votes_context"].set_index("country")
    taiwan = cv.loc["Taiwan", "visibility_penalty"]
    check("Taiwan visibility_penalty", round(taiwan, 3) == 0.481, f"{taiwan} (0.481 at 3 dp)")
    unknown = cv.loc["Unknown", "match_rate"]
    check("Unknown match_rate", round(unknown, 4) == 0.5523, f"{unknown}")

    cs = back["catalog_summary"].iloc[0]
    for col, want in [("titles", 8807), ("matched", 7492), ("high_rated_n", 2142)]:
        check(f"catalog_summary {col}", cs[col] == want, f"{cs[col]:,} (expected {want:,})")

    return all(results)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    found = sorted(p.stem for p in DATA.glob("*.csv"))
    if found != sorted(SHEETS):
        sys.exit(f"Expected these CSVs in {DATA}: {', '.join(SHEETS)}. Found: {', '.join(found)}")

    frames = {name: read_csv(name) for name in SHEETS}
    write(frames)
    print(f"Wrote {OUT} ({len(frames)} sheets)")
    ok = verify(frames)
    print("All checks passed." if ok else "Some checks FAILED.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
