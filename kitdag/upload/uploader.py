"""Uploader - cp-based upload of kitdag outputs.

Defense against false-negative #4 (stale artifacts in upload):
  - Destination is ALWAYS rmtree'd before copytree
  - Internal directories (.specs, logs) are excluded from upload
"""

import logging
import os
import shutil
from typing import List

from kitdag.core.kit import Kit
from kitdag.config import Config

logger = logging.getLogger(__name__)

# Directories that should never be uploaded
INTERNAL_DIRS = {".specs", "logs", "__pycache__"}


def _ignore_internal(directory: str, contents: List[str]) -> List[str]:
    """shutil.copytree ignore function: skip internal directories."""
    return [c for c in contents if c in INTERNAL_DIRS]


class Uploader:
    """Uploads kit outputs to the release destination via cp.

    Always cleans the destination before copying to ensure no stale
    artifacts from previous runs remain.
    """

    def __init__(self, config: Config):
        self.config = config

    def upload_all(self, kits: List[Kit]) -> bool:
        """Upload all kit outputs to upload_dest.

        Returns:
            True if all uploads succeeded.
        """
        if not self.config.upload_dest:
            logger.warning("No upload_dest configured, skipping upload")
            return True

        success = True
        for kit in kits:
            src = kit.get_output_path(self.config)
            dst = os.path.join(self.config.upload_dest, kit.name)

            if not os.path.exists(src):
                logger.warning("Kit %s output not found at %s, skipping", kit.name, src)
                continue

            try:
                # ALWAYS clean destination first to prevent stale artifacts
                if os.path.exists(dst):
                    logger.info("Cleaning upload destination: %s", dst)
                    shutil.rmtree(dst)

                logger.info("Uploading %s -> %s", src, dst)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, ignore=_ignore_internal)
                else:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                logger.info("Upload complete: %s", kit.name)
            except Exception as e:
                logger.error("Upload failed for %s: %s", kit.name, e)
                success = False

        return success
