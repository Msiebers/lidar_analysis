"""Genotype identity mapping (Research Delivery V3A).

Attaches biological genotype identity to result rows at the delivery
aggregation layer only. Canonical pipeline results.csv files, and the
frozen per-date snapshots research_delivery.py copies from them, are never
read by this module and are never modified by anything that uses it.

Mapping key: (experiment, plot). ``side`` is deliberately NOT part of the
key -- every plot has exactly one genotype regardless of which side of the
plot a result came from; side still matters for result identity, QC, and
provenance (see RESULT_UNIQUE_FIELDS in research_delivery.py), but not for
biology. This is an explicit, established biological rule for this project,
not an inference made here.

``plot`` is treated as an opaque, case-sensitive string on both sides of the
join (this map's CSV and the pipeline's results.csv), and is never coerced
to an integer or otherwise normalized. central_runner writes results.csv
through csv.DictWriter, which never types or inspects ``plot`` -- a real run
of the current pipeline produced plot values like ``plant_1``, so nothing
here may assume plot identifiers are numeric. Coercing would risk a join
that looks successful but silently matches the wrong rows, or silently
drops rows that do not happen to parse as an integer.

No versioning (valid_from/valid_to) is implemented: a plot maps to exactly
one genotype for the life of an experiment unless a concrete requirement
for genotype changes mid-experiment is established.
"""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_GENOTYPE_MAP_COLUMNS = ("experiment", "plot", "genotype_id")
OPTIONAL_GENOTYPE_MAP_COLUMNS = ("notes",)

# Matches the SAFE_NAME_PATTERN convention already used elsewhere in
# research_delivery.py for experiment names and run_ids.
_SAFE_GENOTYPE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def sha256_file(path: Path) -> str:
    """Byte-identical to research_delivery.sha256_file; duplicated rather than
    imported so this module has no dependency on research_delivery.py."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class GenotypeMap:
    """A loaded, validated genotype map, already scoped to one experiment."""

    path: Path
    sha256: str
    experiment: str
    genotype_by_plot: dict[str, str] = field(default_factory=dict)
    notes_by_plot: dict[str, str] = field(default_factory=dict)
    total_rows: int = 0
    experiment_rows: int = 0

    def genotype_for(self, plot: object) -> str | None:
        """The genotype_id for this plot in this map's experiment, or None."""
        return self.genotype_by_plot.get(str(plot).strip())

    def unused_plots(self, observed_plots: set[str]) -> list[str]:
        """Plots this map assigns a genotype to that never appeared in the
        observed results for this experiment. Sorted for deterministic output."""
        return sorted(set(self.genotype_by_plot) - observed_plots)


def load_genotype_map(path: Path, experiment: str) -> GenotypeMap:
    """Load and strictly validate a genotype map CSV, scoped to ``experiment``.

    Raises ValueError (or FileNotFoundError if the path itself is bad) on any
    structural problem: a missing required column, a blank required field, a
    malformed genotype_id, or more than one row claiming the same
    (experiment, plot). Duplicate detection covers the whole file, not just
    rows for the active experiment, since a conflicting mapping is a data
    error regardless of which experiment happens to be active right now.

    Rows for other experiments are read (so cross-experiment duplicates can
    still be caught) but are excluded from the returned mapping -- this is
    the "rows for another experiment must not accidentally map into the
    active experiment" guarantee.
    """
    resolved = path.expanduser()
    if not resolved.is_file():
        raise FileNotFoundError(
            f"genotype_map_path does not exist or is not a file: {resolved}"
        )

    with resolved.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"genotype map has no header row: {resolved}")
        missing_columns = [
            column for column in REQUIRED_GENOTYPE_MAP_COLUMNS
            if column not in reader.fieldnames
        ]
        if missing_columns:
            raise ValueError(
                f"genotype map is missing required column(s): {', '.join(missing_columns)} "
                f"(found: {', '.join(reader.fieldnames)}): {resolved}"
            )
        rows = list(reader)

    # key -> (genotype_id, notes, line_no), across ALL experiments in the file.
    seen: dict[tuple[str, str], tuple[str, str, int]] = {}
    for line_no, row in enumerate(rows, start=2):  # header is line 1
        row_experiment = str(row.get("experiment", "")).strip()
        row_plot = str(row.get("plot", "")).strip()
        row_genotype_id = str(row.get("genotype_id", "")).strip()
        row_notes = str(row.get("notes", "")).strip()

        if not row_experiment:
            raise ValueError(f"{resolved} line {line_no}: experiment is blank")
        if not row_plot:
            raise ValueError(f"{resolved} line {line_no}: plot is blank")
        if not row_genotype_id:
            raise ValueError(f"{resolved} line {line_no}: genotype_id is blank")
        if not _SAFE_GENOTYPE_ID_PATTERN.fullmatch(row_genotype_id):
            raise ValueError(
                f"{resolved} line {line_no}: genotype_id may contain only letters, "
                f"numbers, '.', '_', and '-': {row_genotype_id!r}"
            )

        key = (row_experiment, row_plot)
        if key in seen:
            existing_genotype_id, _existing_notes, existing_line = seen[key]
            raise ValueError(
                f"{resolved}: duplicate mapping for experiment={row_experiment!r} "
                f"plot={row_plot!r} (line {existing_line}: {existing_genotype_id!r}, "
                f"line {line_no}: {row_genotype_id!r})"
            )
        seen[key] = (row_genotype_id, row_notes, line_no)

    genotype_by_plot = {
        plot_key: genotype_id
        for (row_experiment, plot_key), (genotype_id, _notes, _line) in seen.items()
        if row_experiment == experiment
    }
    notes_by_plot = {
        plot_key: notes
        for (row_experiment, plot_key), (_genotype_id, notes, _line) in seen.items()
        if row_experiment == experiment
    }

    return GenotypeMap(
        path=resolved,
        sha256=sha256_file(resolved),
        experiment=experiment,
        genotype_by_plot=genotype_by_plot,
        notes_by_plot=notes_by_plot,
        total_rows=len(rows),
        experiment_rows=len(genotype_by_plot),
    )
