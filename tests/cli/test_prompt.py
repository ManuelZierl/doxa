from pathlib import Path
from click.testing import CliRunner

from doxa.cli.prompt import (
    extract_prompt_command,
    generate_prompt,
    _detect_resource_type,
    _get_resource_type_description,
    _extract_kb_context,
    _generate_delta_rules,
)


def test_detect_resource_type_url() -> None:
    assert _detect_resource_type("http://example.com", from_file=False) == "url"
    assert _detect_resource_type("https://example.com", from_file=False) == "url"
    assert _detect_resource_type("file:///path/to/file", from_file=False) == "url"


def test_detect_resource_type_raw_from_file() -> None:
    assert _detect_resource_type("some text", from_file=True) == "raw"


def test_detect_resource_type_topic() -> None:
    assert _detect_resource_type("climate change", from_file=False) == "topic"
    assert _detect_resource_type("some text", from_file=False) == "topic"


def test_get_resource_type_description_url() -> None:
    desc = _get_resource_type_description("url")
    assert "URL" in desc
    assert "fetch" in desc.lower()


def test_get_resource_type_description_raw() -> None:
    desc = _get_resource_type_description("raw")
    assert "raw text" in desc.lower()
    assert "extract directly" in desc.lower()


def test_get_resource_type_description_topic() -> None:
    desc = _get_resource_type_description("topic")
    assert "topic" in desc.lower()
    assert "search" in desc.lower()


def test_extract_kb_context(tmp_path: Path) -> None:
    ax_file = tmp_path / "test.doxa"
    ax_file.write_text("""
        pred person/1 @{description:"A person entity"}.
        pred parent/2.
        
        person(alice).
        person(bob).
        parent(alice, bob).
    """)

    context = _extract_kb_context(ax_file)

    assert "predicates" in context
    assert "entities" in context
    assert len(context["predicates"]) == 2

    # Check predicate structure
    person_pred = next(p for p in context["predicates"] if p["name"] == "person")
    assert person_pred["arity"] == 1
    assert person_pred["description"] == "A person entity"


def test_extract_kb_context_with_entities(tmp_path: Path) -> None:
    ax_file = tmp_path / "test.doxa"
    ax_file.write_text("""
        pred person/1.

        person(alice).
        person(bob).
    """)

    context = _extract_kb_context(ax_file)

    assert len(context["entities"]) == 2
    alice = next(e for e in context["entities"] if e["name"] == "alice")
    assert "description" not in alice

    bob = next(e for e in context["entities"] if e["name"] == "bob")
    assert "description" not in bob


def test_generate_delta_rules_with_kb() -> None:
    rules = _generate_delta_rules(has_kb=True)

    assert "0. **Delta only**" in rules
    assert "emit only new objects not already in KB" in rules


def test_generate_delta_rules_without_kb() -> None:
    rules = _generate_delta_rules(has_kb=False)

    assert "0. **Delta only**" not in rules
    assert "1. **Schema conformance**" in rules


def test_generate_prompt_basic(tmp_path: Path) -> None:
    resource = "climate change impacts"

    prompt = generate_prompt(
        resource=resource,
        resource_type="topic",
    )

    assert "climate change impacts" in prompt
    assert "SCHEMA" in prompt
    assert "topic" in prompt.lower()


def test_generate_prompt_with_kb(tmp_path: Path) -> None:
    kb_file = tmp_path / "kb.doxa"
    kb_file.write_text("""
        pred person/1.
        person(alice).
    """)

    prompt = generate_prompt(
        resource="test resource",
        kb_path=kb_file,
        resource_type="raw",
    )

    assert "KB (reuse-first)" in prompt
    assert "person" in prompt
    assert "Delta only" in prompt


def test_generate_prompt_without_kb() -> None:
    prompt = generate_prompt(
        resource="test resource",
        kb_path=None,
        resource_type="raw",
    )

    assert "KB (reuse-first)" not in prompt
    assert "Delta only" not in prompt


def test_generate_prompt_url_type() -> None:
    prompt = generate_prompt(
        resource="https://example.com/article",
        resource_type="url",
    )

    assert "https://example.com/article" in prompt
    assert "URL" in prompt
    assert "fetch" in prompt.lower()


def test_generate_prompt_with_custom_schema() -> None:
    custom_schema = {"type": "object", "properties": {"test": {"type": "string"}}}

    prompt = generate_prompt(
        resource="test",
        schema_dict=custom_schema,
        resource_type="raw",
    )

    assert '"type": "object"' in prompt
    assert '"test"' in prompt


def test_extract_prompt_command_basic(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(extract_prompt_command, ["climate change"])

    assert result.exit_code == 0
    assert "climate change" in result.output
    assert "topic" in result.output.lower()


def test_extract_prompt_command_with_input_file(tmp_path: Path) -> None:
    input_file = tmp_path / "input.txt"
    input_file.write_text("This is raw text content.")

    runner = CliRunner()
    result = runner.invoke(extract_prompt_command, ["--input", str(input_file)])

    assert result.exit_code == 0
    assert "This is raw text content." in result.output
    assert "raw text" in result.output.lower()


def test_extract_prompt_command_with_output_file(tmp_path: Path) -> None:
    output_file = tmp_path / "output.txt"

    runner = CliRunner()
    result = runner.invoke(
        extract_prompt_command, ["test resource", "--output", str(output_file)]
    )

    assert result.exit_code == 0
    assert output_file.exists()
    content = output_file.read_text()
    assert "test resource" in content


def test_extract_prompt_command_with_kb(tmp_path: Path) -> None:
    kb_file = tmp_path / "kb.doxa"
    kb_file.write_text("pred person/1. person(alice).")

    runner = CliRunner()
    result = runner.invoke(extract_prompt_command, ["test", "--kb", str(kb_file)])

    assert result.exit_code == 0
    assert "person" in result.output
    assert "KB (reuse-first)" in result.output


def test_extract_prompt_command_with_resource_type_override(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        extract_prompt_command, ["some text", "--resource-type", "url"]
    )

    assert result.exit_code == 0
    assert "URL" in result.output


def test_extract_prompt_command_with_custom_template(tmp_path: Path) -> None:
    template_file = tmp_path / "template.md"
    template_file.write_text("Custom template: {{RESOURCE}}")

    runner = CliRunner()
    result = runner.invoke(
        extract_prompt_command, ["test", "--template", str(template_file)]
    )

    assert result.exit_code == 0
    assert "Custom template: test" in result.output


def test_extract_prompt_command_no_resource_error() -> None:
    runner = CliRunner()
    result = runner.invoke(extract_prompt_command, [])

    assert result.exit_code != 0
    assert "RESOURCE argument or --input file must be provided" in result.output


def test_extract_prompt_command_both_resource_and_input_error(tmp_path: Path) -> None:
    input_file = tmp_path / "input.txt"
    input_file.write_text("test")

    runner = CliRunner()
    result = runner.invoke(
        extract_prompt_command, ["resource", "--input", str(input_file)]
    )

    assert result.exit_code != 0
    assert "Cannot specify both" in result.output


def test_extract_prompt_command_with_schema_file(tmp_path: Path) -> None:
    schema_file = tmp_path / "schema.json"
    schema_file.write_text('{"type": "object", "custom": true}')

    runner = CliRunner()
    result = runner.invoke(
        extract_prompt_command, ["test", "--schema", str(schema_file)]
    )

    assert result.exit_code == 0
    assert '"custom": true' in result.output


def test_extract_prompt_command_url_auto_detection() -> None:
    runner = CliRunner()
    result = runner.invoke(extract_prompt_command, ["https://example.com"])

    assert result.exit_code == 0
    assert "https://example.com" in result.output
    assert "URL" in result.output


def test_generate_prompt_with_custom_template(tmp_path: Path) -> None:
    template_file = tmp_path / "custom.md"
    template_file.write_text(
        "Resource: {{RESOURCE}}\nType: {{RESOURCE_TYPE_DESCRIPTION}}"
    )

    prompt = generate_prompt(
        resource="test data",
        template_path=template_file,
        resource_type="raw",
    )

    assert "Resource: test data" in prompt
    assert "Type:" in prompt
    assert "raw text" in prompt.lower()


def test_kb_context_empty_branch(tmp_path: Path) -> None:
    kb_file = tmp_path / "empty.doxa"
    kb_file.write_text("pred test/1.")

    context = _extract_kb_context(kb_file)

    assert context["predicates"] == [{"name": "test", "arity": 1}]
    assert context["entities"] == []


def test_prompt_includes_schema_by_default() -> None:
    prompt = generate_prompt(resource="test", resource_type="raw")

    # Should include Branch schema by default
    assert "SCHEMA" in prompt
    assert '"predicates"' in prompt  # Branch schema has predicates field
