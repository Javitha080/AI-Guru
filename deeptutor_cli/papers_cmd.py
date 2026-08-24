"""
CLI Paper-Bank Command
======================

Bulk-import a folder of A/L past-paper PDFs into the local ``paper_bank``
catalog and inspect what's inside. Papers become instantly startable exams
in the Study Room — no upload needed at study time.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from rich.table import Table
import typer

from .common import console

_STATUS_STYLES = {
    "imported": "bold green",
    "skipped": "dim",
    "needs_review": "yellow",
    "failed": "bold red",
    "parsing": "cyan",
    "queued": "",
}


def _print_items(items: list[dict]) -> None:
    table = Table(title="Paper-Bank Import", show_lines=False)
    table.add_column("File", overflow="fold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    for it in items:
        style = _STATUS_STYLES.get(it["status"], "")
        table.add_row(it["filename"], f"[{style}]{it['status']}[/]", it["detail"])
    console.print(table)


def register(papers_app: typer.Typer) -> None:

    @papers_app.command("import")
    def papers_import(
        folder: str = typer.Argument(..., help="Folder containing past-paper PDFs (searched recursively)."),
        subject: str = typer.Option("ict", "--subject", help="Default subject when the filename lacks one."),
        grade: Optional[int] = typer.Option(None, "--grade", min=11, max=13, help="Default grade when filename/folder lack one."),
        medium: str = typer.Option("english", "--medium", help="Default medium: english|sinhala|tamil."),
        solve: bool = typer.Option(True, "--solve/--no-solve", help="LLM-solve answers missing from marking schemes."),
    ) -> None:
        """Import all past-paper PDFs in FOLDER into the paper bank."""
        from deeptutor.services.exams.bank_import import BankImportJob

        path = Path(folder).expanduser().resolve()
        if not path.is_dir():
            raise typer.BadParameter(f"not a folder: {path}")
        job = BankImportJob(
            path,
            subject_default=subject,
            grade_default=grade,
            medium_default=medium,
            solve_missing=solve,
        )
        console.print(f"[bold]Importing past papers from[/] {path} …")
        snap = asyncio.run(job.run())
        _print_items(snap["items"])

        counts: dict[str, int] = {}
        for it in snap["items"]:
            counts[it["status"]] = counts.get(it["status"], 0) + 1
        summary = " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "nothing to do"
        if snap.get("error"):
            console.print(f"[red]{snap['error']}[/]")
        console.print(f"[bold]Summary[/] — {summary}")

    @papers_app.command("list")
    def papers_list(
        subject: Optional[str] = typer.Option(None, "--subject"),
        grade: Optional[int] = typer.Option(None, "--grade", min=11, max=13),
        year: Optional[int] = typer.Option(None, "--year"),
        fmt: str = typer.Option("rich", "--format", "-f", help="rich | json"),
    ) -> None:
        """List papers currently in the bank."""
        import json as _json

        from deeptutor.services.exams.bank_store import BankStore

        rows = asyncio.run(
            BankStore.catalog(subject=subject, grade=grade, year=year)
        )
        if fmt == "json":
            console.print(_json.dumps(rows, indent=1))
            return
        if not rows:
            console.print("[dim]Bank is empty — run `papers import <folder>` first.[/]")
            return
        table = Table(title=f"Paper Bank ({len(rows)} papers)")
        table.add_column("Group")
        table.add_column("P#")
        table.add_column("Grade")
        table.add_column("Year", no_wrap=True)
        table.add_column("Type")
        table.add_column("Medium")
        table.add_column("Qs", justify="right")
        table.add_column("MCQ", justify="right")
        table.add_column("Essay", justify="right")
        for r in rows:
            table.add_row(
                r["group_key"], str(r["paper_no"]), str(r["grade"]), str(r["year"]),
                r["paper_type"], r["medium"],
                str(r["question_count"]), str(r["mcq_count"]), str(r["essay_count"]),
            )
        console.print(table)

    @papers_app.command("clean")
    def papers_clean(
        source: str = typer.Argument(..., help="Cleaned OCR-text folder (mirrors the PDF tree)."),
        out: str = typer.Argument(..., help="Output folder for segmentation artifacts."),
        raw_books: Optional[str] = typer.Option(None, "--raw-books", help="Folder with RAW review-book txt files (answer/keypoint source)."),
    ) -> None:
        """Normalize + segment OCR text into inspectable artifacts (JSON/txt)."""
        import json as _json

        from deeptutor.services.exams.cleaned_pipeline import build_artifacts

        report = build_artifacts(source, out, raw_books_dir=raw_books)
        table = Table(title="Paper-Corpus Clean", show_lines=False)
        table.add_column("File", overflow="fold")
        table.add_column("Yr", no_wrap=True)
        table.add_column("Gr", no_wrap=True)
        table.add_column("MCQ", justify="right")
        table.add_column("Full", justify="right")
        table.add_column("Essay", justify="right")
        table.add_column("Keys", justify="right")
        table.add_column("OK", no_wrap=True)
        for f in report["files"]:
            table.add_row(
                f["file"], str(f["year"] or "—"), str(f["grade"] or "—"),
                str(f["mcq_found"]), str(f["mcq_full_options"]), str(f["essay_found"]),
                str(f["answers"]), "[green]yes[/]" if f["quality_ok"] else "[red]no[/]",
            )
        console.print(table)
        console.print(f"[bold]Summary[/] — books processed: {report['books']} · artifacts in {out}")
        console.print(_json.dumps({k: v for k, v in report.items() if k != 'files'}, indent=1))

    @papers_app.command("import-cleaned")
    def papers_import_cleaned(artifacts: str = typer.Argument(..., help="Artifacts folder produced by `papers clean`.")) -> None:
        """Import cleaned artifacts into the paper_bank catalog."""
        from deeptutor.services.exams.cleaned_pipeline import import_artifacts

        result = import_artifacts(artifacts)
        console.print(f"[bold green]Wrote {result['rows_written']} bank rows.[/]")
        if result["skipped"]:
            console.print("[yellow]Skipped (missing year/keys/questions):[/]")
            for s in result["skipped"]:
                console.print(f"  - {s}")
