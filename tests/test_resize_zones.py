"""Unit tests for resize_zones – board.Zones() returns a tuple of pcbnew.ZONE."""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def _make_routing_module():
    """Import RoutingCommands with pcbnew stubbed out."""
    pcbnew_stub = types.ModuleType("pcbnew")
    pcbnew_stub.VECTOR2I = lambda x, y: (x, y)
    pcbnew_stub.FromMM = lambda v: int(v * 1_000_000)
    sys.modules.setdefault("pcbnew", pcbnew_stub)

    import importlib

    if "commands.routing" in sys.modules:
        del sys.modules["commands.routing"]
    import commands.routing as mod

    return mod.RoutingCommands


def _make_zone(layer_id, net_name):
    z = MagicMock()
    z.GetLayer.return_value = layer_id
    z.GetNetname.return_value = net_name
    outline = MagicMock()
    z.Outline.return_value = outline
    return z


class TestResizeZones:
    def _make_board(self, zones):
        board = MagicMock()
        board.Zones.return_value = tuple(zones)
        board.GetLayerID.return_value = 0
        board.GetLayerName.return_value = "F.Cu"
        return board

    def _make_rc(self, board):
        RoutingCommands = _make_routing_module()
        rc = RoutingCommands.__new__(RoutingCommands)
        rc.board = board
        rc.logger = MagicMock()
        return rc

    def test_resize_zones_explicit_bounds(self):
        zone = _make_zone(layer_id=0, net_name="GND")
        board = self._make_board([zone])
        rc = self._make_rc(board)

        result = rc.resize_zones({"left": 10, "top": 20, "right": 110, "bottom": 120, "unit": "mm"})

        assert result["success"] is True
        assert len(result["zones"]) == 1
        outline = zone.Outline()
        outline.RemoveAllContours.assert_called_once()
        outline.NewOutline.assert_called_once()

    def test_resize_zones_layer_filter(self):
        zone_fcu = _make_zone(layer_id=0, net_name="GND")
        zone_bcu = _make_zone(layer_id=31, net_name="GND")
        board = self._make_board([zone_fcu, zone_bcu])
        board.GetLayerID.side_effect = lambda name: 0 if name == "F.Cu" else 31
        board.GetLayerName.side_effect = lambda lid: "F.Cu" if lid == 0 else "B.Cu"
        rc = self._make_rc(board)

        result = rc.resize_zones(
            {"left": 0, "top": 0, "right": 100, "bottom": 100, "layers": ["F.Cu"], "unit": "mm"}
        )

        assert result["success"] is True
        assert len(result["zones"]) == 1
        assert result["zones"][0]["layer"] == "F.Cu"
        # B.Cu zone outline must NOT have been touched
        zone_bcu.Outline().RemoveAllContours.assert_not_called()

    def test_resize_zones_no_zones(self):
        board = self._make_board([])
        rc = self._make_rc(board)

        result = rc.resize_zones({"left": 0, "top": 0, "right": 100, "bottom": 100, "unit": "mm"})

        assert result["success"] is False
        assert "No zones" in result["message"]
