"""Repack Migration MCP Server (FastMCP).

Provides tools for AI coding agents to assist with migrating legacy repack
flows to the Repack v2 Python framework.

Usage:
  python mcp_server/server.py                     # stdio transport (default)
  python mcp_server/server.py --transport sse     # SSE transport on port 8080
  python mcp_server/server.py --tool <name> --args '<json>'  # standalone CLI
"""

import argparse
import ast
import json
import os
import re
import sys
import textwrap
from typing import Any, Dict, List, Optional

# Add project root to path so repack.* imports work
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastmcp import FastMCP
from pydantic import BaseModel

mcp = FastMCP(
    "repack-migration",
    instructions=(
        "You are assisting with migrating legacy standard cell library repack "
        "flows to Repack v2. Read SKILL.md in the repository for the full "
        "migration guide and patterns before using these tools."
    ),
)


# ============================================================================
# Pydantic model for complex inputs
# ============================================================================

class KitInfo(BaseModel):
    """A kit definition for DAG analysis."""
    name: str
    corner_based: bool
    dependencies: List[str]


# ============================================================================
# MCP tools
# ============================================================================

@mcp.tool()
def analyze_legacy_command(command: str) -> Dict[str, Any]:
    """Parse a legacy repack shell command and suggest kit classification.

    Identifies the executable, arguments, output paths, and input references.
    Suggests whether the kit should be Kit, CornerBasedKit, or BinaryKitMixin
    based on heuristics (PVT-related args, spec args, generator executable names).

    Args:
        command: The legacy shell command, e.g.
            "trim_liberty -ref /path -cells INV,BUF -pvt ss_0p75v_125c -output /out/lib.lib"

    Returns:
        Analysis dict with executable, arguments, suggested_type, hints.
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

    return {
        "executable": executable,
        "arguments": args,
        "flags": flags,
        "positional": positional,
        "suggested_type": suggested_type,
        "corner_based": corner_based,
        "binary_kit": binary_kit,
        "output_args": {k: v for k, v in args.items()
                        if any(x in k.lower() for x in ["-out", "-output", "-dest", "-target"])},
        "input_args": {k: v for k, v in args.items()
                       if any(x in k.lower() for x in ["-in", "-input", "-ref", "-src", "-lib"])},
        "hints": {
            "pvt_detected": has_pvt or has_pvt_in_output,
            "spec_arg_detected": has_spec,
            "generator_executable": is_binary_hint,
        },
    }


@mcp.tool()
def scaffold_kit(
    kit_name: str,
    kit_type: str,
    dependencies: List[str],
    expected_outputs: List[str],
    command_template: str = "",
    log_error_patterns: Optional[List[str]] = None,
    log_ignore_patterns: Optional[List[str]] = None,
) -> str:
    """Generate a complete Python kit class definition ready to paste into a kits file.

    Args:
        kit_name: Unique kit name (e.g. "liberty", "timing_db").
        kit_type: One of "Kit", "CornerBasedKit", "BinaryKitMixin, Kit",
            or "BinaryKitMixin, CornerBasedKit".
        dependencies: Kit names this depends on (e.g. ["liberty"]).
        expected_outputs: Output file paths relative to output_path.
            May use {pvt} and {lib_name} placeholders.
        command_template: Shell command with placeholders:
            {output_path}, {pvt}, {lib_name}, {ref_path}, {cells}, {new_name}.
        log_error_patterns: Extra regex patterns for error detection in logs.
        log_ignore_patterns: Regex patterns to whitelist in log scanning.

    Returns:
        Python source code for the kit class.
    """
    corner_based = "CornerBasedKit" in kit_type
    binary_kit = "BinaryKitMixin" in kit_type

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

    lines = [
        "import os",
        imports,
        "from repack.core.target import KitTarget",
        "from repack.config import RepackConfig",
    ]
    if binary_kit:
        lines.append("from typing import Any, Dict, List")
    lines += ["", "", f"class {class_name}({base}):", f'    """Repack kit: {kit_name}."""', ""]
    lines += [
        "    def __init__(self):",
        f'        super().__init__(name="{kit_name}", dependencies={deps_str})',
        "",
    ]

    if binary_kit:
        lines += [
            "    def get_trimmed_spec(self, target: KitTarget, config: RepackConfig) -> Dict[str, Any]:",
            '        """Return the reduced spec for this target."""',
            "        return {",
        ]
        if corner_based:
            lines.append('            "pvt": target.pvt,')
        lines += [
            '            "cells": config.cells,',
            '            "lib_name": config.rename_map.get(config.library_name, config.library_name),',
            "        }",
            "",
            "    def get_utility_command(self, target: KitTarget, config: RepackConfig, spec_path: str) -> list:",
            '        """Return the generation utility command."""',
            "        out_dir = self.get_output_path(config)",
            "        # TODO: Replace with actual utility command",
            f'        return ["{command_template.split()[0] if command_template else "gen_tool"}", "--spec", spec_path, "--output", out_dir]',
        ]
    else:
        lines += [
            "    def construct_command(self, target: KitTarget, config: RepackConfig) -> list:",
            '        """Return the shell command for this target."""',
        ]
        if corner_based:
            lines.append("        out_dir = os.path.join(self.get_output_path(config), target.pvt)")
        else:
            lines.append("        out_dir = self.get_output_path(config)")

        if command_template:
            lines.append("        new_name = config.rename_map.get(config.library_name, config.library_name)")
            lines.append("        # TODO: Adjust command to match your tool's actual interface")
            lines.append("        return [")
            for part in command_template.split():
                lines.append(f'            f"{part}",' if "{" in part else f'            "{part}",')
            lines.append("        ]")
        else:
            lines += ["        # TODO: Fill in the actual command", '        return ["echo", "TODO"]']

    lines += [
        "",
        "    def get_expected_outputs(self, target: KitTarget, config: RepackConfig) -> list:",
        '        """Expected output files (relative to output_path)."""',
    ]
    if expected_outputs:
        lines.append("        return [")
        for out in expected_outputs:
            lines.append(f'            f"{out}",' if "{" in out else f'            "{out}",')
        lines.append("        ]")
    else:
        lines += ["        # TODO: List expected output files", "        return []"]

    if log_error_patterns:
        lines += ["", "    def get_log_error_patterns(self) -> list:", f"        return {repr(log_error_patterns)}"]
    if log_ignore_patterns:
        lines += ["", "    def get_log_ignore_patterns(self) -> list:", f"        return {repr(log_ignore_patterns)}"]

    lines.append("")
    return "\n".join(lines)


@mcp.tool()
def validate_kit_file(file_path: str) -> Dict[str, Any]:
    """Check a Python kit definitions file for common migration mistakes.

    Performs AST-based static analysis to detect:
    - Missing abstract methods (construct_command, get_expected_outputs)
    - BinaryKitMixin overriding construct_command instead of get_utility_command
    - Missing get_trimmed_spec / get_utility_command on BinaryKitMixin subclasses
    - Kit base class used where CornerBasedKit is likely needed
    - Absolute paths in get_expected_outputs (must be relative)
    - Missing register_kits(config) function

    Args:
        file_path: Path to the Python file containing kit definitions.

    Returns:
        Dict with kit_classes, issues (errors), warnings, and summary.
    """
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}

    with open(file_path) as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"error": f"Syntax error: {e}"}

    issues: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    kit_classes: List[str] = []
    has_register_kits = False

    def ast_name(node) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return str(node)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = [ast_name(b) for b in node.bases]
            is_kit = any(b in ("Kit", "CornerBasedKit", "BinaryKitMixin") for b in bases)
            if not is_kit:
                continue

            kit_classes.append(node.name)
            methods = {
                n.name for n in ast.walk(node)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }

            if "get_expected_outputs" not in methods:
                issues.append({"class": node.name, "line": node.lineno, "severity": "error",
                                "issue": "Missing get_expected_outputs() — abstract, MUST be implemented"})

            if "BinaryKitMixin" in bases:
                if "construct_command" in methods:
                    issues.append({"class": node.name, "line": node.lineno, "severity": "error",
                                   "issue": "BinaryKitMixin provides construct_command(); implement get_utility_command() instead"})
                if "get_trimmed_spec" not in methods:
                    issues.append({"class": node.name, "line": node.lineno, "severity": "error",
                                   "issue": "BinaryKitMixin requires get_trimmed_spec()"})
                if "get_utility_command" not in methods:
                    issues.append({"class": node.name, "line": node.lineno, "severity": "error",
                                   "issue": "BinaryKitMixin requires get_utility_command()"})
            elif "construct_command" not in methods:
                issues.append({"class": node.name, "line": node.lineno, "severity": "error",
                               "issue": "Missing construct_command() — abstract, MUST be implemented"})

            if "Kit" in bases and "CornerBasedKit" not in bases:
                seg = ast.get_source_segment(source, node) or ""
                if "target.pvt" in seg and "ALL" not in seg:
                    warnings.append({"class": node.name, "line": node.lineno, "severity": "warning",
                                     "issue": "Uses target.pvt but inherits from Kit — should this be CornerBasedKit?"})

        elif isinstance(node, ast.FunctionDef) and node.name == "register_kits":
            has_register_kits = True

    if not has_register_kits:
        issues.append({"class": "(module)", "line": 0, "severity": "error",
                       "issue": "Missing register_kits(config) — engine needs this to discover kits"})

    for match in re.finditer(r'def get_expected_outputs.*?(?=\n    def |\nclass |\Z)', source, re.DOTALL):
        if re.search(r'["\']/', match.group()):
            warnings.append({"class": "(unknown)", "line": 0, "severity": "warning",
                             "issue": "get_expected_outputs() may contain absolute paths — must be RELATIVE to output_path"})

    return {
        "file": file_path,
        "kit_classes": kit_classes,
        "has_register_kits": has_register_kits,
        "issues": issues,
        "warnings": warnings,
        "summary": f"{len(kit_classes)} kit(s) found, {len(issues)} error(s), {len(warnings)} warning(s)",
    }


@mcp.tool()
def explain_dag(kits: List[KitInfo]) -> str:
    """Show the DAG execution structure for a set of kit definitions.

    Uses 3 representative PVT corners (ss, tt, ff) to expand corner-based kits.
    Displays execution stages (sets of targets that can run in parallel),
    dependency edges with PVT-matching type annotations, and parallelism info.

    Args:
        kits: List of kit definitions, each with name, corner_based flag,
            and dependencies (list of kit names).

    Returns:
        Human-readable DAG description with stages and dependency edges.
    """
    from repack.core.dag import DAGBuilder
    from repack.core.target import KitTarget

    pvts = ["ss_corner", "tt_corner", "ff_corner"]
    all_targets: List[KitTarget] = []
    for ki in kits:
        if ki.corner_based:
            for pvt in pvts:
                all_targets.append(KitTarget(kit_name=ki.name, pvt=pvt))
        else:
            all_targets.append(KitTarget(kit_name=ki.name, pvt="ALL"))

    dag = DAGBuilder()
    dag.add_targets(all_targets)
    dag.build_edges({ki.name: ki.dependencies for ki in kits})

    stages = dag.get_execution_stages()
    lines = ["DAG Structure", "=" * 60]

    for i, stage in enumerate(stages):
        lines.append(f"\nStage {i + 1} ({len(stage)} target(s)):")
        for tid in stage:
            deps = dag.get_dependencies(tid)
            dep_str = f" ← depends on: {', '.join(sorted(deps))}" if deps else " (no dependencies)"
            lines.append(f"  {tid}{dep_str}")

    lines.append(f"\nTotal: {len(all_targets)} targets in {len(stages)} stage(s)")
    lines.append(f"Max parallelism (stage 1): {len(stages[0]) if stages else 0} targets")
    lines.append("\nDependency edges:")

    kit_map = {ki.name: ki for ki in kits}
    for ki in kits:
        for dep in ki.dependencies:
            dep_info = kit_map.get(dep)
            if not dep_info:
                continue
            if dep_info.corner_based and ki.corner_based:
                label = "same-PVT linking"
            elif not dep_info.corner_based and ki.corner_based:
                label = "ALL → each PVT"
            elif dep_info.corner_based and not ki.corner_based:
                label = "each PVT → ALL"
            else:
                label = "ALL → ALL"
            lines.append(f"  {dep} → {ki.name}  ({label})")

    return "\n".join(lines)


@mcp.tool()
def check_migration_status(file_path: str) -> Dict[str, Any]:
    """Scan a kit file and report which kits are migrated (DONE) vs still need work (TODO).

    Detects TODO/FIXME/XXX comments, placeholder commands (["echo", "TODO"]),
    and missing required methods to determine migration completeness per kit.

    Args:
        file_path: Path to the Python kit definitions file.

    Returns:
        Report with per-kit status, missing methods, todos, and overall progress.
    """
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}

    with open(file_path) as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"error": f"Syntax error: {e}"}

    def ast_name(node) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return str(node)

    kits: List[Dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [ast_name(b) for b in node.bases]
        if not any(b in ("Kit", "CornerBasedKit", "BinaryKitMixin") for b in bases):
            continue

        class_source = ast.get_source_segment(source, node) or ""
        todos = [
            {"line": node.lineno + i, "text": line.strip()}
            for i, line in enumerate(class_source.splitlines())
            if any(t in line for t in ("TODO", "FIXME", "XXX"))
        ]
        has_placeholder = '["echo", "TODO"]' in class_source

        methods = {
            n.name for n in ast.walk(node)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        required = (
            {"get_trimmed_spec", "get_utility_command", "get_expected_outputs"}
            if "BinaryKitMixin" in bases
            else {"construct_command", "get_expected_outputs"}
        )
        missing = required - methods

        kits.append({
            "class": node.name,
            "line": node.lineno,
            "bases": bases,
            "status": "TODO" if (missing or has_placeholder or todos) else "DONE",
            "missing_methods": sorted(missing),
            "todos": todos,
            "has_placeholder_command": has_placeholder,
        })

    done = sum(1 for k in kits if k["status"] == "DONE")
    return {
        "file": file_path,
        "kits": kits,
        "progress": f"{done}/{len(kits)} kits migrated",
        "done": done,
        "total": len(kits),
    }


# ============================================================================
# Entry point
# ============================================================================

def _run_standalone(tool_name: str, args_json: str) -> None:
    """Call a tool directly from the CLI without MCP transport."""
    try:
        kwargs = json.loads(args_json)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON arguments: {e}", file=sys.stderr)
        sys.exit(1)

    tool_map = {
        "analyze_legacy_command": analyze_legacy_command,
        "scaffold_kit": scaffold_kit,
        "validate_kit_file": validate_kit_file,
        "explain_dag": explain_dag,
        "check_migration_status": check_migration_status,
    }
    fn = tool_map.get(tool_name)
    if fn is None:
        print(f"Unknown tool '{tool_name}'. Available: {', '.join(tool_map)}", file=sys.stderr)
        sys.exit(1)

    # explain_dag expects List[KitInfo]; coerce from raw dicts
    if tool_name == "explain_dag" and "kits" in kwargs:
        kwargs["kits"] = [KitInfo(**k) for k in kwargs["kits"]]

    result = fn(**kwargs)
    print(result if isinstance(result, str) else json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repack Migration MCP Server (FastMCP)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            MCP mode (default, stdio transport):
              python mcp_server/server.py

            MCP mode (SSE transport):
              python mcp_server/server.py --transport sse --port 8080

            Standalone CLI mode (no transport, direct function call):
              python mcp_server/server.py --tool analyze_legacy_command \\
                  --args '{"command": "trim_liberty -pvt ss -ref /path -output /out"}'

              python mcp_server/server.py --tool validate_kit_file \\
                  --args '{"file_path": "kits.py"}'

              python mcp_server/server.py --tool scaffold_kit \\
                  --args '{"kit_name":"lef","kit_type":"Kit","dependencies":[],"expected_outputs":["out.lef"]}'

              python mcp_server/server.py --tool explain_dag \\
                  --args '{"kits":[{"name":"a","corner_based":true,"dependencies":[]},{"name":"b","corner_based":true,"dependencies":["a"]}]}'

              python mcp_server/server.py --tool check_migration_status \\
                  --args '{"file_path": "kits.py"}'
        """),
    )
    parser.add_argument("--tool", help="Run a tool directly (standalone mode, no MCP)")
    parser.add_argument("--args", default="{}", help="JSON arguments for --tool")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse"],
                        help="MCP transport (default: stdio)")
    parser.add_argument("--port", type=int, default=8080, help="Port for SSE transport")
    args = parser.parse_args()

    if args.tool:
        _run_standalone(args.tool, args.args)
    else:
        mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
