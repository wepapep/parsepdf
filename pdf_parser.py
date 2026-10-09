#!/usr/bin/env python3
"""
pdf_parser.py - extract tables and text from PDF reports.

Two commands:

  inspect   Show how each page is structured (text, ruling lines, detected
            tables). Use this first to decide how extraction should be tuned.

  extract   Batch-extract every table to CSV and the page text to .txt,
            plus a summary.csv listing what was found in each file.

Examples:
  python pdf_parser.py inspect report.pdf --pages 1-3
  python pdf_parser.py extract ./reports -o ./out --merge-continued
  python pdf_parser.py extract ./reports -o ./out --decimal , --thousands " "

Use from your own code:
  from pdf_parser import parse_pdf
  rows = parse_pdf("report.pdf")   # every table row of the report, in order

Requires: pip install pdfplumber
(pandas is optional: only the 'extract' command and ReportParser need it;
parse_pdf and 'inspect' work without it.)
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

try:  # pandas is only needed by the 'extract' command / ReportParser
    import pandas as pd
except ImportError:
    pd = None

log = logging.getLogger("pdf_parser")


# --------------------------------------------------------------------------
# Configuration and result containers
# --------------------------------------------------------------------------

@dataclass
class ParserConfig:
    strategy: str = "lines"          # "lines" (ruled tables) or "text" (whitespace-aligned)
    table_settings: dict = field(default_factory=dict)  # extra pdfplumber settings
    header_row: bool = True          # promote the first row of each table to header
    merge_continued: bool = False    # stitch tables that continue onto the next page
    convert_numbers: bool = True
    decimal: str = "."
    thousands: str = ","
    pages: str | None = None         # e.g. "1-3,7" (1-based); None = all pages
    password: str | None = None

    def pdfplumber_table_settings(self) -> dict:
        settings = {"vertical_strategy": self.strategy, "horizontal_strategy": self.strategy}
        settings.update(self.table_settings)
        return settings


@dataclass
class ExtractedTable:
    page: int        # 1-based page where the table starts
    index: int       # 1-based position of the table on that page
    df: pd.DataFrame


@dataclass
class ParsedReport:
    path: Path
    metadata: dict
    text_by_page: dict[int, str]
    tables: list[ExtractedTable]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def parse_page_spec(spec: str | None, n_pages: int) -> list[int]:
    """Turn '1-3,7' into [1, 2, 3, 7], clipped to the document length."""
    if not spec:
        return list(range(1, n_pages + 1))
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start = int(start_s) if start_s else 1
            end = int(end_s) if end_s else n_pages
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))
    return sorted(p for p in pages if 1 <= p <= n_pages)


def clean_cell(value) -> str:
    """Normalise one raw table cell to a single-line stripped string."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def make_number_parser(decimal: str = ".", thousands: str = ","):
    """Return a function str -> float | None honouring the given separators."""
    t, d = re.escape(thousands), re.escape(decimal)
    group_sep = rf"[{t}\s]"
    pattern = re.compile(rf"^[-+]?(?:\d{{1,3}}(?:{group_sep}\d{{3}})+|\d+)(?:{d}\d+)?$")

    def parse(text: str) -> float | None:
        s = text.strip().replace("\u2212", "-")          # unicode minus
        s = re.sub(r"[\u00a0\u2009\u202f]", " ", s)       # non-breaking / thin spaces
        negative = s.startswith("(") and s.endswith(")")  # accounting negatives
        if negative:
            s = s[1:-1].strip()
        if s.endswith("%"):
            s = s[:-1].strip()
        if not pattern.match(s):
            return None
        if re.match(r"^[-+]?0\d", s):                     # keep IDs like 00123 as text
            return None
        s = re.sub(group_sep, "", s).replace(decimal, ".")
        number = float(s)
        return -number if negative else number

    return parse


def unique_headers(raw: list[str]) -> list[str]:
    """Fill blank header names and de-duplicate repeated ones."""
    seen: dict[str, int] = {}
    out = []
    for i, name in enumerate(raw, start=1):
        name = name or f"col_{i}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        out.append(name)
    return out


def iter_pdfs(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*") if p.suffix.lower() == ".pdf")


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

class ReportParser:
    """
    Generic PDF report parser.

    Subclass and override the hook methods (extract_metadata, keep_table,
    clean_table) to encode the rules for a specific report layout.
    """

    def __init__(self, config: ParserConfig | None = None):
        if pd is None:
            raise ImportError("ReportParser and the 'extract' command need pandas "
                              "(pip install pandas); parse_pdf() works without it")
        self.config = config or ParserConfig()
        self._to_number = make_number_parser(self.config.decimal, self.config.thousands)

    # ---- hooks to customise per report type -------------------------------

    def extract_metadata(self, pdf: pdfplumber.PDF, text_by_page: dict[int, str]) -> dict:
        """Pull report-level fields (title, date, site...) out of the text."""
        return dict(pdf.metadata or {})

    def keep_table(self, rows: list[list[str]], page: int, index: int) -> bool:
        """Return False to discard a detected table (e.g. layout boxes)."""
        return len(rows) >= 2 and len(rows[0]) >= 2

    def clean_table(self, df: pd.DataFrame, page: int, index: int) -> pd.DataFrame:
        """Layout-specific cleanup applied after the generic cleanup."""
        return df

    # ---- main entry point --------------------------------------------------

    def parse(self, path: Path) -> ParsedReport:
        cfg = self.config
        with pdfplumber.open(path, password=cfg.password) as pdf:
            page_numbers = parse_page_spec(cfg.pages, len(pdf.pages))
            text_by_page: dict[int, str] = {}
            raw_tables: list[tuple[int, int, list[list[str]]]] = []

            for number in page_numbers:
                page = pdf.pages[number - 1]
                text_by_page[number] = page.extract_text() or ""
                if not page.chars and page.images:
                    log.warning("%s p.%d has images but no text layer - needs OCR",
                                path.name, number)
                for index, raw in enumerate(
                        page.extract_tables(cfg.pdfplumber_table_settings()), start=1):
                    rows = self._normalise_rows(raw)
                    if rows and self.keep_table(rows, number, index):
                        raw_tables.append((number, index, rows))
                page.flush_cache()  # keep memory flat on long documents

            metadata = self.extract_metadata(pdf, text_by_page)

        if cfg.merge_continued:
            raw_tables = self._merge_continued(raw_tables)

        tables = []
        for number, index, rows in raw_tables:
            df = self._to_dataframe(rows)
            df = self.clean_table(df, number, index)
            if not df.empty:
                tables.append(ExtractedTable(number, index, df))
        return ParsedReport(path, metadata, text_by_page, tables)

    # ---- internals ---------------------------------------------------------

    @staticmethod
    def _normalise_rows(raw: list[list]) -> list[list[str]]:
        """Clean cells, pad ragged rows, drop fully empty rows and columns."""
        rows = [[clean_cell(c) for c in row] for row in raw if row]
        if not rows:
            return []
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        rows = [r for r in rows if any(r)]
        if not rows:
            return []
        keep = [i for i in range(width) if any(r[i] for r in rows)]
        return [[r[i] for i in keep] for r in rows]

    @staticmethod
    def _merge_continued(tables):
        """
        Append a table to the previous one when it is the first table on the
        next page and has the same number of columns. A repeated header row
        is dropped. This is a heuristic - check the output when enabling it.
        """
        merged: list[list] = []
        last_page_of_prev = None
        for number, index, rows in tables:
            if (merged and index == 1 and last_page_of_prev == number - 1
                    and len(rows[0]) == len(merged[-1][2][0])):
                body = rows[1:] if rows[0] == merged[-1][2][0] else rows
                merged[-1][2].extend(body)
            else:
                merged.append([number, index, list(rows)])
            last_page_of_prev = number
        return [tuple(m) for m in merged]

    def _to_dataframe(self, rows: list[list[str]]) -> pd.DataFrame:
        if self.config.header_row and len(rows) > 1:
            df = pd.DataFrame(rows[1:], columns=unique_headers(rows[0]))
        else:
            df = pd.DataFrame(rows, columns=[f"col_{i}" for i in range(1, len(rows[0]) + 1)])
        if self.config.convert_numbers:
            for column in df.columns:
                df[column] = self._convert_column(df[column])
        return df

    def _convert_column(self, series: pd.Series) -> pd.Series:
        """Convert a column to numbers only if every non-empty cell parses."""
        non_empty = series[series != ""]
        if non_empty.empty:
            return series
        parsed = non_empty.map(self._to_number)
        if parsed.isna().any():
            return series
        numeric = pd.to_numeric(series.map(lambda v: self._to_number(v) if v != "" else None))
        if (numeric.dropna() % 1 == 0).all() and not non_empty.str.contains(
                re.escape(self.config.decimal)).any():
            return numeric.astype("Int64")
        return numeric


# --------------------------------------------------------------------------
# Importable entry point
# --------------------------------------------------------------------------

def parse_pdf(path, *, strategy: str = "lines", pages: str | None = None,
              password: str | None = None, drop_empty_cells: bool = False,
              table_settings: dict | None = None) -> list[list[str]]:
    """
    Return every table row of one PDF report as a single flat list.

    All tables on all pages are merged in reading order (page by page, top
    to bottom). Each row is a list of strings exactly as found in the PDF:
    no header detection, no number conversion, no table is filtered out.
    Rows may differ in length because each table keeps its own column count.

        from pdf_parser import parse_pdf
        rows = parse_pdf("report.pdf")
        # [['Site ID', 'Region', ...], ['00000', 'Region 0', ...], ...]

    path              str or Path of the PDF file
    strategy          "lines" for ruled tables, "text" for whitespace-aligned
    pages             e.g. "1-3,7" (1-based); None means all pages
    password          for encrypted PDFs
    drop_empty_cells  True removes blank cells, so each row holds only its
                      values (positions within the row are then lost)
    table_settings    extra pdfplumber table settings, merged over defaults

    Raises FileNotFoundError if the file does not exist. Returns [] when no
    table is detected.
    """
    config = ParserConfig(strategy=strategy, table_settings=table_settings or {})
    settings = config.pdfplumber_table_settings()
    rows: list[list[str]] = []
    with pdfplumber.open(Path(path), password=password) as pdf:
        for number in parse_page_spec(pages, len(pdf.pages)):
            page = pdf.pages[number - 1]
            if not page.chars and page.images:
                log.warning("%s p.%d has images but no text layer - needs OCR",
                            Path(path).name, number)
            for raw in page.extract_tables(settings):
                for row in ReportParser._normalise_rows(raw):
                    if drop_empty_cells:
                        row = [cell for cell in row if cell]
                    rows.append(row)
            page.flush_cache()
    return rows


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_inspect(args, config: ParserConfig) -> int:
    """Print the structure of each page so extraction rules can be designed."""
    for path in iter_pdfs(args.input):
        print(f"\n{'=' * 78}\n{path}\n{'=' * 78}")
        with pdfplumber.open(path, password=config.password) as pdf:
            print(f"pages: {len(pdf.pages)}   metadata: {pdf.metadata}")
            for number in parse_page_spec(config.pages, len(pdf.pages)):
                page = pdf.pages[number - 1]
                print(f"\n--- page {number}  ({page.width:.0f} x {page.height:.0f} pt) ---")
                print(f"chars: {len(page.chars)}  lines: {len(page.lines)}  "
                      f"rects: {len(page.rects)}  curves: {len(page.curves)}  "
                      f"images: {len(page.images)}")
                if not page.chars and page.images:
                    print("!! no text layer: this page is a scan and needs OCR")
                fonts = sorted({(c["fontname"], round(c["size"], 1)) for c in page.chars})
                if fonts:
                    print("fonts:", ", ".join(f"{n}@{s}" for n, s in fonts[:8]),
                          "..." if len(fonts) > 8 else "")

                for strategy in ("lines", "text"):
                    settings = {"vertical_strategy": strategy, "horizontal_strategy": strategy}
                    found = page.find_tables(settings)
                    print(f"tables with strategy={strategy!r}: {len(found)}")
                    for i, table in enumerate(found, start=1):
                        rows = table.extract()
                        cols = max((len(r) for r in rows), default=0)
                        bbox = tuple(round(v) for v in table.bbox)
                        print(f"  [{i}] {len(rows)} rows x {cols} cols  bbox={bbox}")
                        for row in rows[:args.preview_rows]:
                            print("      ", [clean_cell(c) for c in row])

                text = page.extract_text() or ""
                lines = text.splitlines()
                print(f"text ({len(lines)} lines), first {args.text_lines}:")
                for line in lines[:args.text_lines]:
                    print("   |", line)
                page.flush_cache()
    return 0


def cmd_extract(args, config: ParserConfig) -> int:
    parser = ReportParser(config)
    out_dir: Path = args.output
    out_dir.mkdir(parents=True, exist_ok=True)
    pdfs = iter_pdfs(args.input)
    if not pdfs:
        log.error("no PDF files found at %s", args.input)
        return 1

    summary, failures = [], 0
    for path in pdfs:
        try:
            report = parser.parse(path)
        except Exception as exc:  # keep the batch going; record the failure
            failures += 1
            log.error("failed: %s (%s)", path, exc)
            summary.append({"file": str(path), "status": f"error: {exc}"})
            continue

        target = out_dir / path.stem
        target.mkdir(parents=True, exist_ok=True)
        if not args.no_text:
            (target / "text.txt").write_text(
                "\n".join(f"===== page {n} =====\n{t}\n"
                          for n, t in report.text_by_page.items()),
                encoding="utf-8")

        if not report.tables:
            summary.append({"file": str(path), "status": "no tables found"})
        for table in report.tables:
            csv_path = target / f"table_p{table.page:03d}_{table.index:02d}.csv"
            table.df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            summary.append({
                "file": str(path), "status": "ok", "page": table.page,
                "table": table.index, "rows": len(table.df),
                "columns": len(table.df.columns),
                "headers": " | ".join(map(str, table.df.columns)),
                "csv": str(csv_path),
            })
        log.info("%s: %d table(s)", path.name, len(report.tables))

    pd.DataFrame(summary).to_csv(out_dir / "summary.csv", index=False, encoding="utf-8-sig")
    log.info("done: %d file(s), %d failed, summary at %s",
             len(pdfs), failures, out_dir / "summary.csv")
    return 1 if failures else 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("input", type=Path, help="a PDF file or a folder of PDFs")
    common.add_argument("--pages", help="pages to process, e.g. '1-3,7' (default: all)")
    common.add_argument("--password", help="password for encrypted PDFs")
    common.add_argument("-v", "--verbose", action="store_true")

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", parents=[common], help="show page structure")
    p_inspect.add_argument("--preview-rows", type=int, default=3)
    p_inspect.add_argument("--text-lines", type=int, default=15)
    p_inspect.set_defaults(func=cmd_inspect)

    p_extract = sub.add_parser("extract", parents=[common], help="extract tables and text")
    p_extract.add_argument("-o", "--output", type=Path, default=Path("out"))
    p_extract.add_argument("--strategy", choices=["lines", "text"], default="lines",
                           help="'lines' for tables with ruling lines, "
                                "'text' for whitespace-aligned columns")
    p_extract.add_argument("--merge-continued", action="store_true",
                           help="stitch tables that continue across pages")
    p_extract.add_argument("--no-header", action="store_true",
                           help="do not treat the first row as the header")
    p_extract.add_argument("--no-numbers", action="store_true",
                           help="leave all cells as text")
    p_extract.add_argument("--decimal", default=".", help="decimal separator (default '.')")
    p_extract.add_argument("--thousands", default=",",
                           help="thousands separator (default ','); spaces always allowed")
    p_extract.add_argument("--no-text", action="store_true", help="skip text.txt output")
    p_extract.set_defaults(func=cmd_extract)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")
    logging.getLogger("pdfminer").setLevel(logging.ERROR)

    config = ParserConfig(pages=args.pages, password=args.password)
    if args.command == "extract":
        config.strategy = args.strategy
        config.merge_continued = args.merge_continued
        config.header_row = not args.no_header
        config.convert_numbers = not args.no_numbers
        config.decimal = args.decimal
        config.thousands = args.thousands
    return args.func(args, config)


if __name__ == "__main__":
    sys.exit(main())
