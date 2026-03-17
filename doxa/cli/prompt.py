"""Prompt generation command for Doxa CLI.

Generates extraction prompts from templates with KB context and schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import click

from doxa.core.branch import Branch


# Default template paths (embedded in package)
_DEFAULT_EXTRACT_TEMPLATE = Path(__file__).parent / "extract_prompt_template.md"
_DEFAULT_QUERY_TEMPLATE = Path(__file__).parent / "query_prompt_template.md"


def _detect_resource_type(resource: str, from_file: bool) -> str:
    """Auto-detect resource type: url, raw, or topic.

    Args:
        resource: The resource string
        from_file: Whether resource was loaded from --input file

    Returns:
        One of: "url", "raw", "topic"
    """
    if resource.startswith(("http://", "https://", "file://")):
        return "url"
    if from_file:
        return "raw"
    return "topic"


def _get_resource_type_description(resource_type: str) -> str:
    """Get the description text for the resource type."""
    if resource_type == "url":
        return "RESOURCE is **a URL** — fetch/read the URL first, then extract only from the retrieved content."
    elif resource_type == "raw":
        return "RESOURCE is **raw text** — extract directly from the provided content."
    else:  # topic
        return "RESOURCE is **a topic** — search the web, gather sources, then extract. Cite each source as a separate source-document object."


def _extract_kb_context(kb_path: Path) -> dict:
    """Extract predicates, entities, and types from a KB file.

    Args:
        kb_path: Path to .doxa or .json KB file

    Returns:
        Dict with "predicates" and "entities" arrays
    """
    from doxa.cli.commands import _load_file

    # Load the branch
    branch = _load_file(kb_path, fix_missing_kinds=False)

    # Extract predicates (including unary type predicates)
    predicates = []
    for pred in branch.predicates:
        pred_dict = {
            "name": pred.name,
            "arity": pred.arity,
        }
        if pred.description:
            pred_dict["description"] = pred.description
        predicates.append(pred_dict)

    # Extract entities
    entities = []
    for entity in branch.entities:
        ent_dict = {
            "name": entity.name,
        }
        description = getattr(entity, "description", None)
        if description:
            ent_dict["description"] = description
        entities.append(ent_dict)

    return {
        "predicates": predicates,
        "entities": entities,
    }


def _get_branch_schema() -> dict:
    """Get the JSON schema from Branch.llm_schema()."""
    return Branch.llm_schema()


def _generate_delta_rules(has_kb: bool) -> str:
    """Generate the delta rules section based on whether KB is present."""
    rules = []

    if has_kb:
        rules.append("0. **Delta only** — emit only new objects not already in KB.")

    rules.extend(
        [
            "1. **Schema conformance** — output must validate against SCHEMA. Schema wins over prompt if they conflict.",
            "2. **Provenance** — every emitted object gets provenance + belief fields per schema. One consistent source ID per source. ISO-8601 timestamps.",
            "3. **Entities** — emit minimum needed: type, canonical name. Aliases only if explicitly stated. Prefer existing KB types; avoid inventing new unary types.",
            '4. **Predicates** — prefer KB predicates. New predicate only if unavoidable AND it appears ≥2 times. Never create "evidential framing" predicates (reported, claimed, alleged, said) unless the reporting event itself is the target fact.',
            "5. **Facts** — grounded only. No invented arguments, dates, or relations. Don't over-specify beyond what RESOURCE supports.",
            "6. **Rules** — strongly prioritize. Every rule must be non-vacuous (head shares ≥1 variable with body). Actively look for: definitions, if-then relationships, transitivities, derived classifications, propagation patterns. Omit only if RESOURCE genuinely contains none.",
            "7. **Constraints** — strongly prioritize. Actively look for: type restrictions on predicate arguments, required components, reflexivity prohibitions, cardinality limits, domain invariants. Omit only if RESOURCE genuinely justifies none.",
            "8. **Signatures** — emit only if schema supports it, predicate is used, and arg types exist in KB or this delta.",
            "9. **Normalization** — when RESOURCE has conflict or correction, prefer representing it via (b, d) on the canonical claim. Only use separate event predicates when the event itself matters. Fewer reusable claims > many narrow one-off claims.",
        ]
    )

    return "\n".join(rules)


def generate_prompt(
    resource: str,
    template_path: Optional[Path] = None,
    kb_path: Optional[Path] = None,
    schema_dict: Optional[dict] = None,
    resource_type: Optional[str] = None,
) -> str:
    """Generate an extraction prompt from template.

    Args:
        resource: The resource text/URL/topic
        template_path: Path to template file (uses default if None)
        kb_path: Path to KB file for context (optional)
        schema_dict: JSON schema dict (uses Branch schema if None)
        resource_type: Override auto-detection ("url", "raw", or "topic")

    Returns:
        The generated prompt string
    """
    # Load template
    if template_path is None:
        template_path = _DEFAULT_EXTRACT_TEMPLATE

    template = template_path.read_text(encoding="utf-8")

    # Get schema
    if schema_dict is None:
        schema_dict = _get_branch_schema()

    schema_json = json.dumps(schema_dict, indent=2)

    # Get KB context if provided
    has_kb = kb_path is not None
    if has_kb:
        kb_context = _extract_kb_context(kb_path)
        kb_json = json.dumps(kb_context, indent=2)
    else:
        kb_json = ""

    # Detect or use provided resource type
    if resource_type is None:
        resource_type = _detect_resource_type(resource, from_file=False)

    resource_type_desc = _get_resource_type_description(resource_type)

    # Generate delta rules
    delta_rules = _generate_delta_rules(has_kb)

    # Perform substitutions
    prompt = template
    prompt = prompt.replace("{{SPEC_JSON_SCHEMA}}", schema_json)
    prompt = prompt.replace("{{RESOURCE}}", resource)
    prompt = prompt.replace("{{RESOURCE_TYPE_DESCRIPTION}}", resource_type_desc)
    prompt = prompt.replace("{{DELTA_RULES}}", delta_rules)

    # Handle KB section
    if has_kb:
        prompt = prompt.replace("{{KB_JSON}}", kb_json)
    else:
        # Remove KB section entirely
        lines = prompt.split("\n")
        filtered_lines = []
        skip_until_next_section = False

        for line in lines:
            if "## KB (reuse-first)" in line:
                skip_until_next_section = True
                continue
            if skip_until_next_section and line.startswith("## "):
                skip_until_next_section = False
            if not skip_until_next_section:
                filtered_lines.append(line)

        prompt = "\n".join(filtered_lines)

    return prompt


@click.command()
@click.argument("resource", required=False)
@click.option(
    "-i",
    "--input",
    "input_file",
    type=click.Path(exists=True, path_type=Path),
    help="Read resource from file instead of argument",
)
@click.option(
    "-o",
    "--output",
    "output_file",
    type=click.Path(path_type=Path),
    help="Write prompt to file instead of stdout",
)
@click.option(
    "-t",
    "--template",
    "template_file",
    type=click.Path(exists=True, path_type=Path),
    help="Template file (default: built-in template)",
)
@click.option(
    "-k",
    "--kb",
    "kb_file",
    type=click.Path(exists=True, path_type=Path),
    help="Knowledge base file (.doxa or .json) for reuse context",
)
@click.option(
    "-s",
    "--schema",
    "schema_file",
    type=click.Path(exists=True, path_type=Path),
    help="JSON schema file to include in prompt (default: Branch schema)",
)
@click.option(
    "--resource-type",
    type=click.Choice(["url", "raw", "topic"], case_sensitive=False),
    help="Override auto-detection of resource type",
)
def extract_prompt_command(
    resource: Optional[str],
    input_file: Optional[Path],
    output_file: Optional[Path],
    template_file: Optional[Path],
    kb_file: Optional[Path],
    schema_file: Optional[Path],
    resource_type: Optional[str],
) -> None:
    """Generate an extraction prompt from a template.

    RESOURCE is the text, URL, or topic to extract from.
    If --input is provided, RESOURCE is read from that file.
    """
    # Validate input
    if resource is None and input_file is None:
        raise click.UsageError(
            "Either RESOURCE argument or --input file must be provided"
        )

    if resource is not None and input_file is not None:
        raise click.UsageError("Cannot specify both RESOURCE argument and --input file")

    # Get resource text
    if input_file:
        resource_text = input_file.read_text(encoding="utf-8")
        from_file = True
    else:
        resource_text = resource
        from_file = False

    # Auto-detect resource type if not specified
    if resource_type is None:
        resource_type = _detect_resource_type(resource_text, from_file)

    # Load schema if provided
    schema_dict = None
    if schema_file:
        schema_dict = json.loads(schema_file.read_text(encoding="utf-8"))

    # Generate prompt
    try:
        prompt_text = generate_prompt(
            resource=resource_text,
            template_path=template_file,
            kb_path=kb_file,
            schema_dict=schema_dict,
            resource_type=resource_type,
        )
    except Exception as exc:
        raise click.ClickException(f"Failed to generate prompt: {exc}")

    # Output
    if output_file:
        output_file.write_text(prompt_text, encoding="utf-8")
        click.echo(f"Prompt written to {output_file}")
    else:
        click.echo(prompt_text)


def generate_query_prompt(
    question: str,
    template_path: Optional[Path] = None,
    kb_path: Optional[Path] = None,
) -> str:
    """Generate a query planner prompt from a template.

    Args:
        question: The natural-language question to convert into a Doxa query
        template_path: Path to template file (uses default if None)
        kb_path: Path to KB file for predicate/atom context (optional)

    Returns:
        The generated prompt string
    """
    from doxa.core.query import Query

    if template_path is None:
        template_path = _DEFAULT_QUERY_TEMPLATE

    template = template_path.read_text(encoding="utf-8")

    # Query spec from Query model
    query_spec = Query.llm_schema()
    query_spec_json = json.dumps(query_spec, indent=2)

    # KB context
    if kb_path is not None:
        kb_context = _extract_kb_context(kb_path)
        predicates_json = json.dumps(kb_context["predicates"], indent=2)
        atoms_json = json.dumps(kb_context["entities"], indent=2)
    else:
        predicates_json = "[]"
        atoms_json = "[]"

    prompt = template
    prompt = prompt.replace("{{QUERY_SPEC}}", query_spec_json)
    prompt = prompt.replace("{{PREDICATES}}", predicates_json)
    prompt = prompt.replace("{{ATOMS}}", atoms_json)
    prompt = prompt.replace("{{QUESTION}}", question)

    return prompt


@click.command()
@click.argument("question", required=False)
@click.option(
    "-i",
    "--input",
    "input_file",
    type=click.Path(exists=True, path_type=Path),
    help="Read question from file instead of argument",
)
@click.option(
    "-o",
    "--output",
    "output_file",
    type=click.Path(path_type=Path),
    help="Write prompt to file instead of stdout",
)
@click.option(
    "-t",
    "--template",
    "template_file",
    type=click.Path(exists=True, path_type=Path),
    help="Template file (default: built-in template)",
)
@click.option(
    "-k",
    "--kb",
    "kb_file",
    type=click.Path(exists=True, path_type=Path),
    help="Knowledge base file (.doxa or .json) for predicate/atom context",
)
def query_prompt_command(
    question: Optional[str],
    input_file: Optional[Path],
    output_file: Optional[Path],
    template_file: Optional[Path],
    kb_file: Optional[Path],
) -> None:
    """Generate a query planner prompt from a natural-language question.

    QUESTION is the question to convert into a Doxa query.
    If --input is provided, QUESTION is read from that file.
    """
    if question is None and input_file is None:
        raise click.UsageError(
            "Either QUESTION argument or --input file must be provided"
        )

    if question is not None and input_file is not None:
        raise click.UsageError("Cannot specify both QUESTION argument and --input file")

    if input_file:
        question_text = input_file.read_text(encoding="utf-8")
    else:
        question_text = question

    try:
        prompt_text = generate_query_prompt(
            question=question_text,
            template_path=template_file,
            kb_path=kb_file,
        )
    except Exception as exc:
        raise click.ClickException(f"Failed to generate prompt: {exc}")

    if output_file:
        output_file.write_text(prompt_text, encoding="utf-8")
        click.echo(f"Prompt written to {output_file}")
    else:
        click.echo(prompt_text)


if __name__ == "__main__":
    extract_prompt_command()
