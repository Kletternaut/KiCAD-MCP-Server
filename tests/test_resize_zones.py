"""Unit tests for resize_zones – sexpdata file-based implementation."""

import sys
import textwrap
import types
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

# Minimal .kicad_pcb with two zones (F.Cu GND, B.Cu GND)
_MINIMAL_PCB = textwrap.dedent("""\
    (kicad_pcb
      (version 20221018)
      (layers
        (0 "F.Cu" signal)
        (31 "B.Cu" signal)
        (44 "Edge.Cuts" user)
      )
      (zone
        (net 1)
        (net_name "GND")
        (layer "F.Cu")
        (polygon
          (pts
            (xy 0 0) (xy 100 0) (xy 100 100) (xy 0 100)
          )
        )
      )
      (zone
        (net 1)
        (net_name "GND")
        (layer "B.Cu")
        (polygon
          (pts
            (xy 0 0) (xy 100 0) (xy 100 100) (xy 0 100)
          )
        )
      )
    )
    """)


def _make_routing_module():
    """Import RoutingCommands with pcbnew stubbed out."""
    pcbnew_stub = types.ModuleType("pcbnew")
    pcbnew_stub.VECTOR2I = lambda x, y: (x, y)
    pcbnew_stub.FromMM = lambda v: int(v * 1_000_000)
    sys.modules.setdefault("pcbnew", pcbnew_stub)

    if "commands.routing" in sys.modules:
        del sys.modules["commands.routing"]
    import commands.routing as mod

    return mod.RoutingCommands


def _make_rc(tmp_path, content=_MINIMAL_PCB):
    pcb_file = tmp_path / "test.kicad_pcb"
    pcb_file.write_text(content, encoding="utf-8")

    RoutingCommands = _make_routing_module()
    rc = RoutingCommands.__new__(RoutingCommands)

    board = MagicMock()
    board.GetFileName.return_value = str(pcb_file)
    board.GetLayerID.side_effect = lambda n: {"F.Cu": 0, "B.Cu": 31, "Edge.Cuts": 44}.get(n, -1)
    # pcbnew.LoadBoard stub returns same mock
    import pcbnew

    pcbnew.LoadBoard = MagicMock(return_value=board)
    rc.board = board
    return rc, pcb_file


class TestResizeZones:
    def test_resize_zones_explicit_bounds(self, tmp_path):
        rc, pcb_file = _make_rc(tmp_path)

        result = rc.resize_zones({"left": 10, "top": 20, "right": 110, "bottom": 120, "unit": "mm"})

        assert result["success"] is True
        assert len(result["zones"]) == 2  # both F.Cu and B.Cu resized
        content = pcb_file.read_text(encoding="utf-8")
        assert "10" in content
        assert "120" in content

    def test_resize_zones_layer_filter(self, tmp_path):
        rc, pcb_file = _make_rc(tmp_path)

        result = rc.resize_zones(
            {"left": 5, "top": 5, "right": 50, "bottom": 50, "layers": ["F.Cu"], "unit": "mm"}
        )

        assert result["success"] is True
        assert len(result["zones"]) == 1
        assert result["zones"][0]["layer"] == "F.Cu"

    def test_resize_zones_no_zones(self, tmp_path):
        empty_pcb = textwrap.dedent("""\
            (kicad_pcb
              (version 20221018)
              (layers (0 "F.Cu" signal))
            )
            """)
        rc, _ = _make_rc(tmp_path, empty_pcb)

        result = rc.resize_zones({"left": 0, "top": 0, "right": 100, "bottom": 100, "unit": "mm"})

        assert result["success"] is False
        assert "No zones" in result["message"]
