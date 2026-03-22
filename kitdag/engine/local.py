"""LocalEngine — runs tasks locally using subprocess."""

import logging
import os
import subprocess
from typing import Any, Dict

from kitdag.core.step import Step
from kitdag.core.task import Task
from kitdag.engine.base import BaseEngine

logger = logging.getLogger(__name__)


class LocalEngine(BaseEngine):
    """Executes tasks as local subprocesses."""

    def _execute_task(self, task: Task, step: Step, inputs: Dict[str, Any]) -> bool:
        """Execute a single task as a local subprocess."""
        command = step.get_command(inputs)
        if not command:
            logger.error("Step %s produced empty command", step.name)
            return False

        logger.info("Executing %s: %s", task.id, " ".join(command))

        try:
            log_file = None
            if task.log_path:
                os.makedirs(os.path.dirname(task.log_path), exist_ok=True)
                log_file = open(task.log_path, "w")

            result = subprocess.run(
                command,
                cwd=task.output_dir or None,
                stdout=log_file or subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=3600,
            )

            if log_file:
                log_file.close()

            return result.returncode == 0

        except subprocess.TimeoutExpired:
            logger.error("Task %s timed out", task.id)
            if log_file and not log_file.closed:
                log_file.close()
            return False
        except FileNotFoundError:
            logger.error("Command not found: %s", command[0])
            if log_file and not log_file.closed:
                log_file.close()
            return False
        except Exception as e:
            logger.error("Task %s execution error: %s", task.id, e)
            if log_file and not log_file.closed:
                log_file.close()
            return False
