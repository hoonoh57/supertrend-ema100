from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from supertrend_ema100.kiwoom.env import candidate_env_files


class CandidateEnvFilesTest(unittest.TestCase):
    def test_explicit_and_project_env_files_are_used_in_order(self) -> None:
        root = Path("project")
        with patch.dict(os.environ, {"SUPERTREND_ENV_FILE": "custom.env"}, clear=True):
            self.assertEqual(
                candidate_env_files(root),
                [Path("custom.env"), root / ".env"],
            )

    def test_project_env_file_is_used_without_explicit_override(self) -> None:
        root = Path("project")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(candidate_env_files(root), [root / ".env"])


if __name__ == "__main__":
    unittest.main()
