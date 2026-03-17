"""Doxa merge command - merge multiple .doxa or .json files."""

from __future__ import annotations

from pathlib import Path

import click

from doxa.cli.commands import _load_file


@click.command()
@click.argument(
    "files", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path)
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file path. If not specified, prints to stdout or overwrites the last input file.",
)
@click.option(
    "--fix",
    is_flag=True,
    default=False,
    help="Auto-fix missing 'kind' fields and other required fields in JSON files.",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["json", "doxa"], case_sensitive=False),
    default=None,
    help="Output format. If not specified, infers from output file extension or uses JSON.",
)
def merge_command(
    files: tuple[Path, ...], output: Path | None, fix: bool, format: str | None
) -> None:
    """Merge multiple .doxa or .json files into a single file.

    Examples:

        doxa merge file1.json file2.doxa -o merged.json --fix

        doxa merge temp.json temp.json --fix  (fixes a single file in-place)

        doxa merge a.doxa b.json c.json -o output.doxa
    """

    if not files:
        raise click.UsageError("At least one input file is required.")

    # Determine unique input files
    unique_files = list(dict.fromkeys(files))  # Preserve order, remove duplicates

    # Load and merge all files
    merged_branch = None
    for file_path in files:
        try:
            branch = _load_file(file_path, fix_missing_kinds=fix)
            if merged_branch is None:
                merged_branch = branch
            else:
                merged_branch = merged_branch.merge(branch)
            click.echo(
                f"Loaded {file_path} ({len(branch.belief_records)} facts, {len(branch.rules)} rules, {len(branch.constraints)} constraints)"
            )
        except Exception as exc:
            raise click.ClickException(f"Error loading {file_path}: {exc}")

    if merged_branch is None:
        raise click.ClickException("No files were successfully loaded.")

    # Determine output format
    output_format = format
    if output_format is None and output is not None:
        output_format = "json" if output.suffix.lower() == ".json" else "doxa"
    elif output_format is None:
        output_format = "json"

    # Generate output content
    if output_format.lower() == "json":
        content = merged_branch.model_dump_json(indent=2, exclude_none=True)
    else:
        # Convert to .doxa format
        lines: list[str] = []
        for p in merged_branch.predicates:
            lines.append(f"{p.to_ax()}.")
        for r in merged_branch.belief_records:
            lines.append(f"{r.to_ax()}.")
        for r in merged_branch.rules:
            lines.append(f"{r.to_ax()}.")
        for c in merged_branch.constraints:
            lines.append(f"{c.to_ax()}.")
        content = "\n".join(lines)

    # Write output
    if output is None:
        # If no output specified and only one unique file, overwrite it (useful for --fix)
        if len(unique_files) == 1:
            output = unique_files[0]
        else:
            # Print to stdout
            click.echo("\n" + content)
            return

    try:
        output.write_text(content, encoding="utf-8")
        click.echo(f"\nMerged {len(files)} file(s) -> {output}")
        click.echo(
            f"  Total: {len(merged_branch.belief_records)} facts, {len(merged_branch.rules)} rules, {len(merged_branch.constraints)} constraints, {len(merged_branch.predicates)} predicates, {len(merged_branch.entities)} entities"
        )
    except Exception as exc:
        raise click.ClickException(f"Error writing output file: {exc}")
