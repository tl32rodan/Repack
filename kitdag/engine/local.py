"""LocalEngine — runs kits locally using subprocess."""

import logging
import os
import subprocess
from typing import Dict, List

from kitdag.core.kit import Kit
from kitdag.core.target import KitTarget
from kitdag.engine.base import BaseEngine
from kitdag.pipeline import PipelineConfig, StepConfig

logger = logging.getLogger(__name__)


class LocalEngine(BaseEngine):
    """Executes kits as local subprocesses."""

    def _execute_step(self, target: KitTarget, kit: Kit, step: StepConfig) -> bool:
        """Execute a single kit step as a local subprocess."""
        # Build merged inputs (step inputs + output_dir)
        merged_inputs = dict(step.inputs)
        merged_inputs["output_dir"] = target.output_dir

        command = kit.get_command(merged_inputs)
        if not command:
            logger.error("Kit %s produced empty command", kit.name)
            return False

        logger.info("Executing %s: %s", target.id, " ".join(command))

        try:
            log_file = None
            if target.log_path:
                os.makedirs(os.path.dirname(target.log_path), exist_ok=True)
                log_file = open(target.log_path, "w")

            result = subprocess.run(
                command,
                cwd=target.output_dir or None,
                stdout=log_file or subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=3600,  # 1 hour default timeout
            )

            if log_file:
                log_file.close()

            return result.returncode == 0

        except subprocess.TimeoutExpired:
            logger.error("Target %s timed out", target.id)
            if log_file and not log_file.closed:
                log_file.close()
            return False
        except FileNotFoundError:
            logger.error("Command not found: %s", command[0])
            if log_file and not log_file.closed:
                log_file.close()
            return False
        except Exception as e:
            logger.error("Target %s execution error: %s", target.id, e)
            if log_file and not log_file.closed:
                log_file.close()
            return False
