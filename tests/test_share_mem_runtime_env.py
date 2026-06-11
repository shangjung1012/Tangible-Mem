from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from share_mem.l1 import io_utils


class ShareMemRuntimeEnvTests(unittest.TestCase):
    def tearDown(self) -> None:
        io_utils._ENV_LOADED = False

    def test_ensure_env_loaded_preserves_shell_project_by_default(self) -> None:
        def fake_load_dotenv(_path=None, *, override=False):
            if override or "GOOGLE_CLOUD_PROJECT" not in os.environ:
                os.environ["GOOGLE_CLOUD_PROJECT"] = "dotenv-project"
            return True

        with (
            patch.object(io_utils, "load_dotenv", side_effect=fake_load_dotenv),
            patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "shell-project"}, clear=True),
        ):
            io_utils._ENV_LOADED = False
            io_utils.ensure_env_loaded()

            self.assertEqual(os.environ["GOOGLE_CLOUD_PROJECT"], "shell-project")

    def test_ensure_env_loaded_can_fill_project_from_dotenv_when_shell_is_empty(self) -> None:
        def fake_load_dotenv(_path=None, *, override=False):
            if override or "GOOGLE_CLOUD_PROJECT" not in os.environ:
                os.environ["GOOGLE_CLOUD_PROJECT"] = "dotenv-project"
            return True

        with (
            patch.object(io_utils, "load_dotenv", side_effect=fake_load_dotenv),
            patch.dict(os.environ, {}, clear=True),
        ):
            io_utils._ENV_LOADED = False
            io_utils.ensure_env_loaded()

            self.assertEqual(os.environ["GOOGLE_CLOUD_PROJECT"], "dotenv-project")


if __name__ == "__main__":
    unittest.main()
