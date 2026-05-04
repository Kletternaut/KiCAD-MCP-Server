"""Unit tests for resize_zones - subprocess-based implementation."""

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def _make_routing_module():
    pcbnew_stub = types.ModuleType("pcbnew")
    pcbnew_stub.VECTOR2I = lambda x, y: (x, y)
    pcbnew_stub.FromMM = lambda v: int(v * 1_000_000)
    sys.modules.setdefault("pcbnew", pcbnew_stub)

    if "commands.routing" in sys.modules:
        del sys.modules["commands.routing"]
    import commands.routing as mod

    return mod.RoutingCommands


def _make_rc():
    RoutingCommands = _make_routing_module()
    rc = RoutingCommands.__new__(RoutingCommands)
    board = MagicMock()
    board.GetFileName.return_value = "test.kicad_pcb"
    rc.board = board
    rc.board_path = "test.kicad_pcb"
    rc._find_kicad_python = MagicMock(return_value=sys.executable)
    return rc


class TestResizeZones:
    def _run_with_subprocess(self, rc, params, zones_result):
        stdout = json.dumps(zones_result)
        mock_proc = MagicMock()
        mock_proc.stdout = stdout
        mock_proc.stderr = ""
        mock_proc.returncode = 0
        with patch("subprocess.run", return_value=mock_proc):
            return rc.resize_zones(params)

    def test_resize_zones_explicit_bounds(self):
        rc = _make_rc()
        result = self._run_with_subprocess(
            rc,
            {"left": 10, "top": 20, "right": 110, "bottom": 120, "unit": "mm"},
            {"success": True, "zones": [{"layer": "F.Cu"}, {"layer": "B.Cu"}]},
        )
        assert result["success"] is True
        assert len(result["zones"]) == 2
        assert result["bounds"]["left"] == 10

    def test_resize_zones_layer_filter(self):
        rc = _make_rc()
        result = self._run_with_subprocess(
            rc,
            {"left": 5, "top": 5, "right": 50, "bottom": 50, "layers": ["F.Cu"]},
            {"success": True, "zones": [{"layer": "F.Cu"}]},
        )
        assert result["success"] is True
        assert len(result["zones"]) == 1
        assert result["zones"][0]["layer"] == "F.Cu"

    def test_resize_zones_no_zones(self):
        rc = _make_rc()
        result = self._run_with_subprocess(
            rc,
            {"left": 0, "top": 0, "right": 100, "bottom": 100},
            {
                "success": False,
                "message": "No zones found to resize",
                "errorDetails": "Check layer names or add copper pours first",
            },
        )
        assert result["success"] is False
        assert "No zones" in result["message"]
