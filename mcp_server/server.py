"""Repack Migration MCP Server.

Provides tools for AI coding agents to assist with migrating legacy repack
flows to the Repack v2 Python framework.

Tools:
  - analyze_legacy_command:  Parse a legacy shell command and suggest kit type
  - scaffold_kit:            Generate a complete kit class from parameters
  - validate_kit_file:       Check a kit definitions file for common mistakes
  - explain_dag:             Show the DAG for a set of kits
  - check_migration_status:  Report which kits are migrated vs TODO

Usage:
  python mcp_server/server.py                 # stdio transport (default)
  python mcp_server/server.py --port 8080     # SSE transport
"""

import argparse
import ast
import importlib.util
import json
import os
import re
import sys
import textwrap
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from mcp.server import Server
    from mcp.types import TextContent, Tool
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


# ============================================================================
# Tool implementations (pure functions — usable without MCP)
# ============================================================================

def analyze_legacy_command(command: str) -> Dict[str, Any]:
    """Parse a legacy command string and suggest kit classification.

    Args:
        command: The legacy shell command, e.g.
            "trim_liberty -ref /path -cells INV,BUF -pvt ss_100c -output /out/lib.lib"

    Returns:
        Analysis dict with executable, arguments, suggestions.
    """
    import shlex
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    if not tokens:
        return {"error": "Empty command"}

    executable = tokens[0]
    args: Dict[str, str] = {}
    positional: List[str] = []
    flags: List[str] = []

    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t.startswith("-"):
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                args[t] = tokens[i + 1]
                i += 2
            else:
                flags.append(t)
                i += 1
        else:
            positional.append(t)
            i += 1

    # Heuristics for kit type
    has_pvt = any(
        k in (" ".join(args.keys()) + " ".join(args.values())).lower()
        for k in ["pvt", "corner", "process", "voltage", "temperature"]
    )
    has_pvt_in_output = any(
        re.search(r"(ss|tt|ff|_\d+c)", v, re.IGNORECASE)
        for v in list(args.values()) + positional
    )
    is_binary_hint = any(
        k in executable.lower()
        for k in ["gen_", "generate", "compile", "build"]
    )
    has_spec = any(
        k in (" ".join(args.keys())).lower()
        for k in ["-spec", "-config", "-cfg", "-json"]
    )

    corner_based = has_pvt or has_pvt_in_output
    binary_kit = is_binary_hint or has_spec

    if binary_kit and corner_based:
        suggested_type = "BinaryKitMixin, CornerBasedKit"
    elif binary_kit:
        suggested_type = "BinaryKitMixin, Kit"
    elif corner_based:
        suggested_type = "CornerBasedKit"
    else:
        suggested_type = "Kit"

    # Guess output files
    output_args = {k: v for k, v in args.items()
                   if any(x in k.lower() for x in ["-out", "-output", "-dest", "-target"])}

    # Guess input deps
    input_args = {k: v for k, v in args.items()
                  if any(x in k.lower() for x in ["-in", "-input", "-ref", "-src", "-lib"])}

    return {
        "executable": executable,
        "arguments": args,
        "flags": flags,
        "positional": positional,
        "suggested_type": suggested_type,
        "corner_based": corner_based,
        "binary_kit": binary_kit,
        "output_args": output_args,
        "input_args": input_args,
        "hints": {
            "pvt_detected": has_pvt or has_pvt_in_output,
            "spec_arg_detected": has_spec,
            "generator_executable": is_binary_hint,
        },
    }


def scaffold_kit(
    kit_name: str,
    kit_type: str,
    dependencies: List[str],
    command_template: str,
    expected_outputs: List[str],
    corner_based: bool = True,
    binary_kit: bool = False,
    log_error_patterns: Optional[List[str]] = None,
    log_ignore_patterns: Optional[List[str]] = None,
) -> str:
    """Generate a complete kit class definition.

    Args:
        kit_name: Unique kit name (e.g. "liberty", "timing_db").
        kit_type: "Kit", "CornerBasedKit", or "BinaryKitMixin, CornerBasedKit".
        dependencies: List of kit names this depends on.
        command_template: Shell command with placeholders:
            {output_path}  — self.get_output_path(config)
            {pvt}          — target.pvt
            {lib_name}     — config.library_name
            {ref_path}     — config.ref_library_path
            {cells}        — ",".join(config.cells)
            {new_name}     — config.rename_map.get(config.library_name, config.library_name)
        expected_outputs: Relative output file paths (can use {pvt}, {lib_name}).
        corner_based: Whether to use CornerBasedKit.
        binary_kit: Whether to add BinaryKitMixin.
        log_error_patterns: Extra error patterns.
        log_ignore_patterns: Patterns to ignore.

    Returns:
        Python source code for the kit class.
    """
    # Determine base class
    if binary_kit and corner_based:
        base = "BinaryKitMixin, CornerBasedKit"
        imports = "from repack.core.kit import CornerBasedKit, BinaryKitMixin"
    elif binary_kit:
        base = "BinaryKitMixin, Kit"
        imports = "from repack.core.kit import Kit, BinaryKitMixin"
    elif corner_based:
        base = "CornerBasedKit"
        imports = "from repack.core.kit import CornerBasedKit"
    else:
        base = "Kit"
        imports = "from repack.core.kit import Kit"

    class_name = "".join(w.capitalize() for w in kit_name.split("_")) + "Kit"
    deps_str = repr(dependencies) if dependencies else "[]"

    lines = []
    lines.append(f"import os")
    lines.append(f"{imports}")
    lines.append(f"from repack.core.target import KitTarget")
    lines.append(f"from repack.config import RepackConfig")
    if binary_kit:
        lines.append(f"from typing import Any, Dict, List")
    lines.append("")
    lines.append("")
    lines.append(f"class {class_name}({base}):")
    lines.append(f'    """Repack kit: {kit_name}."""')
    lines.append("")
    lines.append(f"    def __init__(self):")
    lines.append(f'        super().__init__(name="{kit_name}", dependencies={deps_str})')
    lines.append("")

    if binary_kit:
        # BinaryKitMixin methods
        lines.append(f"    def get_trimmed_spec(self, target: KitTarget, config: RepackConfig) -> Dict[str, Any]:")
        lines.append(f'        """Return the reduced spec for this target."""')
        lines.append(f"        return {{")
        if corner_based:
            lines.append(f'            "pvt": target.pvt,')
        lines.append(f'            "cells": config.cells,')
        lines.append(f'            "lib_name": config.rename_map.get(config.library_name, config.library_name),')
        lines.append(f"        }}")
        lines.append("")
        lines.append(f"    def get_utility_command(self, target: KitTarget, config: RepackConfig, spec_path: str) -> list:")
        lines.append(f'        """Return the generation utility command."""')
        lines.append(f"        out_dir = self.get_output_path(config)")
        lines.append(f'        # TODO: Replace with actual utility command')
        lines.append(f'        return ["{command_template.split()[0] if command_template else "gen_tool"}", "--spec", spec_path, "--output", out_dir]')
    else:
        # construct_command
        lines.append(f"    def construct_command(self, target: KitTarget, config: RepackConfig) -> list:")
        lines.append(f'        """Return the shell command for this target."""')

        # Build the command from template
        if corner_based:
            lines.append(f"        out_dir = os.path.join(self.get_output_path(config), target.pvt)")
        else:
            lines.append(f"        out_dir = self.get_output_path(config)")

        if command_template:
            lines.append(f"        new_name = config.rename_map.get(config.library_name, config.library_name)")
            lines.append(f"        # TODO: Adjust command to match your tool's actual interface")
            lines.append(f"        return [")
            for part in command_template.split():
                if "{" in part:
                    lines.append(f"            f\"{part}\",")
                else:
                    lines.append(f"            \"{part}\",")
            lines.append(f"        ]")
        else:
            lines.append(f"        # TODO: Fill in the actual command")
            lines.append(f"        return [\"echo\", \"TODO\"]")

    lines.append("")

    # get_expected_outputs
    lines.append(f"    def get_expected_outputs(self, target: KitTarget, config: RepackConfig) -> list:")
    lines.append(f'        """Expected output files (relative to output_path)."""')
    if expected_outputs:
        lines.append(f"        return [")
        for out in expected_outputs:
            if "{" in out:
                lines.append(f"            f\"{out}\",")
            else:
                lines.append(f"            \"{out}\",")
        lines.append(f"        ]")
    else:
        lines.append(f"        # TODO: List expected output files")
        lines.append(f"        return []")

    # Optional methods
    if log_error_patterns:
        lines.append("")
        lines.append(f"    def get_log_error_patterns(self) -> list:")
        lines.append(f"        return {repr(log_error_patterns)}")

    if log_ignore_patterns:
        lines.append("")
        lines.append(f"    def get_log_ignore_patterns(self) -> list:")
        lines.append(f"        return {repr(log_ignore_patterns)}")

    lines.append("")
    return "\n".join(lines)


def validate_kit_file(file_path: str) -> Dict[str, Any]:
    """Check a kit definitions file for common migration mistakes.

    Args:
        file_path: Path to the Python file containing kit definitions.

    Returns:
        Dict with issues found and summary.
    """
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}

    with open(file_path) as f:
        source = f.read()

    issues: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    kit_classes: List[str] = []

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"error": f"Syntax error: {e}"}

    has_register_kits = False

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = [_ast_name(b) for b in node.bases]

            # Check if it looks like a kit class
            is_kit = any(
                b in ("Kit", "CornerBasedKit", "BinaryKitMixin")
                for b in bases
            )
            if not is_kit:
                continue

            kit_classes.append(node.name)

            # Collect method names
            methods = {
                n.name for n in ast.walk(node)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }

            # Check: get_expected_outputs must be implemented
            if "get_expected_outputs" not in methods:
                issues.append({
                    "class": node.name,
                    "line": node.lineno,
                    "issue": "Missing get_expected_outputs() — this is abstract and MUST be implemented",
                    "severity": "error",
                })

            # Check: BinaryKitMixin should not override construct_command
            if "BinaryKitMixin" in bases and "construct_command" in methods:
                issues.append({
                    "class": node.name,
                    "line": node.lineno,
                    "issue": "BinaryKitMixin provides construct_command() — override get_utility_command() instead",
                    "severity": "error",
                })

            # Check: non-BinaryKit must have construct_command
            if "BinaryKitMixin" not in bases and "construct_command" not in methods:
                issues.append({
                    "class": node.name,
                    "line": node.lineno,
                    "issue": "Missing construct_command() — this is abstract and MUST be implemented",
                    "severity": "error",
                })

            # Check: BinaryKitMixin must have get_trimmed_spec and get_utility_command
            if "BinaryKitMixin" in bases:
                if "get_trimmed_spec" not in methods:
                    issues.append({
                        "class": node.name,
                        "line": node.lineno,
                        "issue": "BinaryKitMixin requires get_trimmed_spec()",
                        "severity": "error",
                    })
                if "get_utility_command" not in methods:
                    issues.append({
                        "class": node.name,
                        "line": node.lineno,
                        "issue": "BinaryKitMixin requires get_utility_command()",
                        "severity": "error",
                    })

            # Warning: Kit used for something that might be corner-based
            if "Kit" in bases and "CornerBasedKit" not in bases:
                # Check if pvt is referenced in methods
                source_segment = ast.get_source_segment(source, node) or ""
                if "target.pvt" in source_segment and "ALL" not in source_segment:
                    warnings.append({
                        "class": node.name,
                        "line": node.lineno,
                        "issue": "Uses target.pvt but inherits from Kit (not CornerBasedKit) — should this be corner-based?",
                        "severity": "warning",
                    })

        elif isinstance(node, ast.FunctionDef) and node.name == "register_kits":
            has_register_kits = True

    if not has_register_kits:
        issues.append({
            "class": "(module)",
            "line": 0,
            "issue": "Missing register_kits(config) function — engine needs this to discover kits",
            "severity": "error",
        })

    # Check for absolute paths in get_expected_outputs
    for match in re.finditer(r'def get_expected_outputs.*?(?=\n    def |\nclass |\Z)',
                              source, re.DOTALL):
        body = match.group()
        if re.search(r'["\']/', body):
            warnings.append({
                "class": "(unknown)",
                "line": 0,
                "issue": "get_expected_outputs() may contain absolute paths — paths must be RELATIVE to output_path",
                "severity": "warning",
            })

    return {
        "file": file_path,
        "kit_classes": kit_classes,
        "has_register_kits": has_register_kits,
        "issues": issues,
        "warnings": warnings,
        "summary": (
            f"{len(kit_classes)} kit(s) found, "
            f"{len(issues)} error(s), "
            f"{len(warnings)} warning(s)"
        ),
    }


def explain_dag(kits_info: List[Dict[str, Any]]) -> str:
    """Show the DAG structure for a set of kit definitions.

    Args:
        kits_info: List of dicts, each with:
            - name: kit name
            - corner_based: bool
            - dependencies: list of kit name strings

    Returns:
        Human-readable DAG description.
    """
    from repack.core.dag import DAGBuilder
    from repack.core.target import KitTarget

    # Build mock targets
    pvts = ["ss_corner", "tt_corner", "ff_corner"]
    all_targets: List[KitTarget] = []
    for ki in kits_info:
        if ki.get("corner_based", False):
            for pvt in pvts:
                all_targets.append(KitTarget(kit_name=ki["name"], pvt=pvt))
        else:
            all_targets.append(KitTarget(kit_name=ki["name"], pvt="ALL"))

    dag = DAGBuilder()
    dag.add_targets(all_targets)
    kit_deps = {ki["name"]: ki.get("dependencies", []) for ki in kits_info}
    dag.build_edges(kit_deps)

    stages = dag.get_execution_stages()
    lines: List[str] = []
    lines.append("DAG Structure")
    lines.append("=" * 60)

    for i, stage in enumerate(stages):
        lines.append(f"\nStage {i + 1} ({len(stage)} target(s)):")
        for tid in stage:
            deps = dag.get_dependencies(tid)
            dep_str = f" ← depends on: {', '.join(sorted(deps))}" if deps else " (no dependencies)"
            lines.append(f"  {tid}{dep_str}")

    # Summary
    lines.append(f"\nTotal: {len(all_targets)} targets in {len(stages)} stage(s)")
    lines.append(f"Max parallelism (stage 1): {len(stages[0]) if stages else 0} targets")

    # Dependency chain
    lines.append("\nDependency edges:")
    for ki in kits_info:
        if ki.get("dependencies"):
            for dep in ki["dependencies"]:
                dep_info = next((k for k in kits_info if k["name"] == dep), None)
                if dep_info:
                    dep_cb = dep_info.get("corner_based", False)
                    ki_cb = ki.get("corner_based", False)
                    if dep_cb and ki_cb:
                        lines.append(f"  {dep} → {ki['name']}  (same-PVT linking)")
                    elif not dep_cb and ki_cb:
                        lines.append(f"  {dep} → {ki['name']}  (ALL → each PVT)")
                    elif dep_cb and not ki_cb:
                        lines.append(f"  {dep} → {ki['name']}  (each PVT → ALL)")
                    else:
                        lines.append(f"  {dep} → {ki['name']}  (ALL → ALL)")

    return "\n".join(lines)


def check_migration_status(file_path: str) -> Dict[str, Any]:
    """Scan a kit file and report migration status.

    Looks for TODO comments, placeholder commands, and incomplete
    implementations to determine which kits are done vs still need work.

    Args:
        file_path: Path to the kit definitions file.

    Returns:
        Migration status report.
    """
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}

    with open(file_path) as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"error": f"Syntax error: {e}"}

    kits: List[Dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        bases = [_ast_name(b) for b in node.bases]
        is_kit = any(
            b in ("Kit", "CornerBasedKit", "BinaryKitMixin")
            for b in bases
        )
        if not is_kit:
            continue

        # Extract the source for this class
        class_source = ast.get_source_segment(source, node) or ""

        todos = []
        for line_no, line in enumerate(class_source.splitlines(), node.lineno):
            stripped = line.strip()
            if "TODO" in stripped or "FIXME" in stripped or "XXX" in stripped:
                todos.append({"line": line_no, "text": stripped})

        has_placeholder = (
            'echo "TODO"' in class_source
            or "echo 'TODO'" in class_source
            or '["echo", "TODO"]' in class_source
            or "pass" in class_source.split("construct_command")[-1][:200]
            if "construct_command" in class_source else False
        )

        methods = {
            n.name for n in ast.walk(node)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        required = {"construct_command", "get_expected_outputs"}
        if "BinaryKitMixin" in bases:
            required = {"get_trimmed_spec", "get_utility_command", "get_expected_outputs"}

        missing = required - methods
        status = "TODO" if (missing or has_placeholder or todos) else "DONE"

        kits.append({
            "class": node.name,
            "line": node.lineno,
            "bases": bases,
            "status": status,
            "missing_methods": sorted(missing),
            "todos": todos,
            "has_placeholder_command": has_placeholder,
        })

    done = sum(1 for k in kits if k["status"] == "DONE")
    total = len(kits)

    return {
        "file": file_path,
        "kits": kits,
        "progress": f"{done}/{total} kits migrated",
        "done": done,
        "total": total,
    }


def _ast_name(node) -> str:
    """Extract name from an AST node (Name or Attribute)."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return node.attr
    return str(node)


# ============================================================================
# MCP Server wrapper
# ============================================================================

TOOLS = [
    {
        "name": "analyze_legacy_command",
        "description": (
            "Parse a legacy repack shell command string. "
            "Identifies the executable, arguments, and suggests whether "
            "the kit should be Kit, CornerBasedKit, or BinaryKitMixin. "
            "Detects PVT-related args, spec/config args, and output paths."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The legacy shell command to analyze",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "scaffold_kit",
        "description": (
            "Generate a complete Python kit class definition. "
            "Provide the kit name, type, dependencies, command template "
            "(with {pvt}, {lib_name}, {output_path} placeholders), and "
            "expected output files. Returns ready-to-paste Python code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kit_name": {"type": "string", "description": "Unique kit name (e.g. 'liberty')"},
                "kit_type": {
                    "type": "string",
                    "enum": ["Kit", "CornerBasedKit", "BinaryKitMixin, Kit", "BinaryKitMixin, CornerBasedKit"],
                    "description": "Kit base class type",
                },
                "dependencies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Kit names this depends on",
                },
                "command_template": {
                    "type": "string",
                    "description": "Shell command with {pvt}, {lib_name}, {output_path}, {ref_path}, {cells}, {new_name} placeholders",
                },
                "expected_outputs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Expected output files relative to output_path (can use {pvt}, {lib_name})",
                },
                "log_error_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extra regex patterns for error detection in logs",
                },
                "log_ignore_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Regex patterns to whitelist in log scanning",
                },
            },
            "required": ["kit_name", "kit_type", "dependencies", "expected_outputs"],
        },
    },
    {
        "name": "validate_kit_file",
        "description": (
            "Check a Python kit definitions file for common migration "
            "mistakes: missing abstract methods, wrong base class, "
            "absolute paths in get_expected_outputs, missing register_kits, etc."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the Python kit file"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "explain_dag",
        "description": (
            "Show the DAG structure for a set of kits. "
            "Displays execution stages, dependency edges, "
            "PVT matching type, and parallelism info."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "corner_based": {"type": "boolean"},
                            "dependencies": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["name", "corner_based", "dependencies"],
                    },
                    "description": "List of kit definitions with name, corner_based flag, and dependencies",
                },
            },
            "required": ["kits"],
        },
    },
    {
        "name": "check_migration_status",
        "description": (
            "Scan a kit definitions file and report which kits are "
            "fully migrated (DONE) vs still need work (TODO). "
            "Detects TODO comments, placeholder commands, and missing methods."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the Python kit file"},
            },
            "required": ["file_path"],
        },
    },
]


def _handle_tool_call(name: str, arguments: Dict[str, Any]) -> str:
    """Dispatch a tool call and return the result as JSON string."""
    if name == "analyze_legacy_command":
        result = analyze_legacy_command(arguments["command"])
    elif name == "scaffold_kit":
        corner_based = "CornerBasedKit" in arguments.get("kit_type", "")
        binary_kit = "BinaryKitMixin" in arguments.get("kit_type", "")
        result = scaffold_kit(
            kit_name=arguments["kit_name"],
            kit_type=arguments["kit_type"],
            dependencies=arguments.get("dependencies", []),
            command_template=arguments.get("command_template", ""),
            expected_outputs=arguments.get("expected_outputs", []),
            corner_based=corner_based,
            binary_kit=binary_kit,
            log_error_patterns=arguments.get("log_error_patterns"),
            log_ignore_patterns=arguments.get("log_ignore_patterns"),
        )
    elif name == "validate_kit_file":
        result = validate_kit_file(arguments["file_path"])
    elif name == "explain_dag":
        result = explain_dag(arguments["kits"])
    elif name == "check_migration_status":
        result = check_migration_status(arguments["file_path"])
    else:
        result = {"error": f"Unknown tool: {name}"}

    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2)


def run_stdio_server():
    """Run the MCP server using stdio transport (requires mcp package)."""
    if not HAS_MCP:
        print("Error: 'mcp' package not installed. Install with: pip install mcp", file=sys.stderr)
        print("Falling back to standalone mode. Use --help for options.", file=sys.stderr)
        sys.exit(1)

    server = Server("repack-migration")

    @server.list_tools()
    async def list_tools():
        return [Tool(**t) for t in TOOLS]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        result = _handle_tool_call(name, arguments)
        return [TextContent(type="text", text=result)]

    import asyncio
    from mcp.server.stdio import stdio_server

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream)

    asyncio.run(main())


def run_standalone(tool_name: str, args_json: str):
    """Run a tool directly from the command line (no MCP needed)."""
    try:
        arguments = json.loads(args_json)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON arguments: {e}", file=sys.stderr)
        sys.exit(1)

    result = _handle_tool_call(tool_name, arguments)
    print(result)


# ============================================================================
# Entry point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Repack Migration MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            MCP mode (default):
              python mcp_server/server.py

            Standalone mode (no MCP dependency needed):
              python mcp_server/server.py --tool analyze_legacy_command --args '{"command": "trim_liberty -pvt ss"}'
              python mcp_server/server.py --tool validate_kit_file --args '{"file_path": "kits.py"}'
              python mcp_server/server.py --tool scaffold_kit --args '{"kit_name":"lef","kit_type":"Kit","dependencies":[],"expected_outputs":["out.lef"]}'
              python mcp_server/server.py --tool explain_dag --args '{"kits":[{"name":"a","corner_based":true,"dependencies":[]},{"name":"b","corner_based":true,"dependencies":["a"]}]}'
              python mcp_server/server.py --tool check_migration_status --args '{"file_path": "kits.py"}'

            Available tools:
              analyze_legacy_command   Parse a legacy shell command and suggest kit type
              scaffold_kit             Generate a kit class from parameters
              validate_kit_file        Check a kit file for common mistakes
              explain_dag              Show DAG structure for a set of kits
              check_migration_status   Report migration progress
        """),
    )
    parser.add_argument("--tool", help="Run a tool directly (standalone mode)")
    parser.add_argument("--args", help="JSON arguments for the tool", default="{}")

    args = parser.parse_args()

    if args.tool:
        run_standalone(args.tool, args.args)
    else:
        run_stdio_server()


if __name__ == "__main__":
    main()
