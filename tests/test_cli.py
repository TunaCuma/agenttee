import pytest
from unittest.mock import patch
from pathlib import Path
from agenttee.cli import _auto_name, _get_name_arg


class TestGetNameArg:
    def test_explicit_name(self):
        assert _get_name_arg(["--name", "myservice"]) == "myservice"

    def test_name_in_middle(self):
        assert _get_name_arg(["--other", "--name", "api", "--flag"]) == "api"

    def test_missing_name_falls_back(self):
        name = _get_name_arg(["--verbose"])
        assert name  # should return something, not crash


class TestAutoName:
    def test_returns_nonempty_string(self):
        name = _auto_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_sanitizes_for_filesystem(self):
        name = _auto_name()
        assert "/" not in name
        assert " " not in name

    @patch("subprocess.run")
    def test_falls_back_to_cwd_on_ps_failure(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        name = _auto_name()
        assert isinstance(name, str)
        assert len(name) > 0
