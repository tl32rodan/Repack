"""CwlEngine — generates CWL documents and runs via cwlexec."""

import logging
import os
import subprocess
from typing import Dict

import yaml

from kitdag.core.kit import Kit
from kitdag.core.target import KitTarget
from kitdag.engine.base import BaseEngine
from kitdag.pipeline import PipelineConfig, StepConfig

logger = logging.getLogger(__name__)


class CwlEngine(BaseEngine):
    """Generates CWL Workflow + CommandLineTools and executes via cwlexec."""

    def _execute_step(self, target: KitTarget, kit: Kit, step: StepConfig) -> bool:
        """Execute a single step via cwlexec.

        Generates CWL files for this step and invokes cwlexec.
        """
        workdir = os.path.join(self.pipeline.output_root, ".cwl", target.id)
        os.makedirs(workdir, exist_ok=True)

        # 1. Generate CWL CommandLineTool
        tool_path = os.path.join(workdir, f"{target.id}.cwl")
        tool_cwl = self._generate_tool_cwl(kit, step)
        with open(tool_path, "w") as f:
            f.write(tool_cwl)

        # 2. Generate CWL input.yaml
        input_path = os.path.join(workdir, "input.yaml")
        input_cwl = self._generate_cwl_inputs(kit, step, target)
        with open(input_path, "w") as f:
            f.write(input_cwl)

        # 3. Run cwlexec
        return self._run_cwlexec(workdir, tool_path, input_path, target)

    def _generate_tool_cwl(self, kit: Kit, step: StepConfig) -> str:
        """Generate CWL CommandLineTool YAML for a kit."""
        return kit.to_cwl()

    def _generate_cwl_inputs(self, kit: Kit, step: StepConfig,
                             target: KitTarget) -> str:
        """Generate CWL input.yaml for a step."""
        cwl_inputs = dict(step.inputs)
        cwl_inputs["output_dir"] = target.output_dir
        return yaml.dump(cwl_inputs, default_flow_style=False)

    def _run_cwlexec(self, workdir: str, tool_path: str,
                     input_path: str, target: KitTarget) -> bool:
        """Execute cwlexec via subprocess."""
        cmd = ["cwlexec", "-w", workdir, tool_path, input_path]
        logger.info("Running cwlexec: %s", " ".join(cmd))

        try:
            log_file = None
            if target.log_path:
                os.makedirs(os.path.dirname(target.log_path), exist_ok=True)
                log_file = open(target.log_path, "w")

            result = subprocess.run(
                cmd,
                cwd=workdir,
                stdout=log_file or subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=7200,  # 2 hour timeout for CWL workflows
            )

            if log_file:
                log_file.close()

            return result.returncode == 0

        except FileNotFoundError:
            logger.error("cwlexec not found. Is it installed?")
            if log_file and not log_file.closed:
                log_file.close()
            return False
        except subprocess.TimeoutExpired:
            logger.error("cwlexec timed out for %s", target.id)
            if log_file and not log_file.closed:
                log_file.close()
            return False
        except Exception as e:
            logger.error("cwlexec error for %s: %s", target.id, e)
            if log_file and not log_file.closed:
                log_file.close()
            return False
