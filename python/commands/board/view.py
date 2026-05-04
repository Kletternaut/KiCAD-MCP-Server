"""
Board view command implementations for KiCAD interface
"""

import base64
import io
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import pcbnew
from PIL import Image

logger = logging.getLogger("kicad_interface")


class BoardViewCommands:
    """Handles board viewing operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board
        self.board_path: Optional[str] = None  # set by KiCadInterface after open_project

    def _get_board_path(self) -> Optional[str]:
        """Return the board file path, preferring the cached path over SWIG call."""
        if self.board_path:
            return self.board_path
        if self.board and hasattr(self.board, "GetFileName"):
            try:
                p = self.board.GetFileName()
                if p:
                    return p
            except Exception:
                pass
        return None

    def get_board_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get information about the current board"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Get board dimensions
            board_box = self.board.GetBoardEdgesBoundingBox()
            width_nm = board_box.GetWidth()
            height_nm = board_box.GetHeight()

            # Convert to mm
            width_mm = width_nm / 1000000
            height_mm = height_nm / 1000000

            # Get layer information
            layers = []
            for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                if self.board.IsLayerEnabled(layer_id):
                    layers.append(
                        {
                            "name": self.board.GetLayerName(layer_id),
                            "type": self._get_layer_type_name(self.board.GetLayerType(layer_id)),
                            "id": layer_id,
                        }
                    )

            return {
                "success": True,
                "board": {
                    "filename": self.board.GetFileName(),
                    "size": {"width": width_mm, "height": height_mm, "unit": "mm"},
                    "layers": layers,
                    "title": self.board.GetTitleBlock().GetTitle(),
                    # Note: activeLayer removed - GetActiveLayer() doesn't exist in KiCAD 9.0
                    # Active layer is a UI concept not applicable to headless scripting
                },
            }

        except Exception as e:
            logger.error(f"Error getting board info: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get board information",
                "errorDetails": str(e),
            }

    def get_board_2d_view(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a 2D image of the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Get parameters
            width = params.get("width", 800)
            height = params.get("height", 600)
            format = params.get("format", "png")
            layers = params.get("layers", [])

            # Create plot controller
            plotter = pcbnew.PLOT_CONTROLLER(self.board)

            # Set up plot options
            plot_opts = plotter.GetPlotOptions()
            plot_opts.SetOutputDirectory(os.path.dirname(self.board.GetFileName()))
            plot_opts.SetScale(1)
            plot_opts.SetMirror(False)
            # Note: SetExcludeEdgeLayer() removed in KiCAD 9.0 - default behavior includes all layers
            plot_opts.SetPlotFrameRef(False)
            plot_opts.SetPlotValue(True)
            plot_opts.SetPlotReference(True)

            # Plot to SVG first (for vector output)
            # Note: KiCAD 9.0 prepends the project name to the filename, so we use GetPlotFileName() to get the actual path
            plotter.OpenPlotfile("temp_view", pcbnew.PLOT_FORMAT_SVG, "Temporary View")

            # Plot specified layers or all enabled layers
            # Note: In KiCAD 9.0, SetLayer() must be called before PlotLayer()
            if layers:
                for layer_name in layers:
                    layer_id = self.board.GetLayerID(layer_name)
                    if layer_id >= 0 and self.board.IsLayerEnabled(layer_id):
                        plotter.SetLayer(layer_id)
                        plotter.PlotLayer()
            else:
                for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                    if self.board.IsLayerEnabled(layer_id):
                        plotter.SetLayer(layer_id)
                        plotter.PlotLayer()

            # Get the actual filename that was created (includes project name prefix)
            temp_svg = plotter.GetPlotFileName()

            plotter.ClosePlot()

            # Convert SVG to requested format
            if format == "svg":
                with open(temp_svg, "r") as f:
                    svg_data = f.read()
                os.remove(temp_svg)
                return {"success": True, "imageData": svg_data, "format": "svg"}
            else:
                # Use PIL to convert SVG to PNG/JPG
                from cairosvg import svg2png

                png_data = svg2png(url=temp_svg, output_width=width, output_height=height)
                os.remove(temp_svg)

                if format == "jpg":
                    # Convert PNG to JPG
                    img = Image.open(io.BytesIO(png_data))
                    jpg_buffer = io.BytesIO()
                    img.convert("RGB").save(jpg_buffer, format="JPEG")
                    jpg_data = jpg_buffer.getvalue()
                    return {
                        "success": True,
                        "imageData": base64.b64encode(jpg_data).decode("utf-8"),
                        "format": "jpg",
                    }
                else:
                    return {
                        "success": True,
                        "imageData": base64.b64encode(png_data).decode("utf-8"),
                        "format": "png",
                    }

        except Exception as e:
            logger.error(f"Error getting board 2D view: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get board 2D view",
                "errorDetails": str(e),
            }

    def _get_layer_type_name(self, type_id: int) -> str:
        """Convert KiCAD layer type constant to name"""
        type_map = {
            pcbnew.LT_SIGNAL: "signal",
            pcbnew.LT_POWER: "power",
            pcbnew.LT_MIXED: "mixed",
            pcbnew.LT_JUMPER: "jumper",
        }
        # Note: LT_USER was removed in KiCAD 9.0
        return type_map.get(type_id, "unknown")

    def get_board_extents(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get the bounding box extents of the board"""
        try:
            if not self._get_board_path():
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Get unit preference (default to mm)
            unit = params.get("unit", "mm")
            scale = 1000000 if unit == "mm" else 25400000  # nm to mm or inch

            # Select bounding box source
            source = params.get("source", "edge_cuts")
            if source in ("copper", "footprints"):
                # Parse the .kicad_pcb file directly with sexpdata to avoid
                # SWIG SwigPyObject bugs after board mutations / reloads.
                import sexpdata

                board_path = self._get_board_path()
                if not board_path:
                    return {
                        "success": False,
                        "message": "Board has no file path",
                        "errorDetails": "Open a project first",
                    }

                with open(board_path, encoding="utf-8") as fh:
                    data = sexpdata.loads(fh.read())

                def _sym(v: Any) -> str:
                    return v.value() if hasattr(v, "value") else str(v)

                min_x = min_y = float("inf")
                max_x = max_y = float("-inf")

                def _upd(x: float, y: float) -> None:
                    nonlocal min_x, min_y, max_x, max_y
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)

                for item in data:
                    if not (isinstance(item, list) and item and _sym(item[0]) == "footprint"):
                        continue
                    # Collect all (at x y) and pad (at x y) positions + sizes
                    fp_x: float = 0.0
                    fp_y: float = 0.0
                    for child in item[1:]:
                        if isinstance(child, list) and child and _sym(child[0]) == "at":
                            fp_x = float(child[1])
                            fp_y = float(child[2])
                            break
                    # Walk pads and courtyard rects for a tight bound
                    for child in item[1:]:
                        if not (isinstance(child, list) and child):
                            continue
                        tag = _sym(child[0])
                        if tag == "pad":
                            # pad: (pad ... (at dx dy) (size w h) ...)
                            pad_dx = pad_dy = 0.0
                            pad_w = pad_h = 0.0
                            for pchild in child[1:]:
                                if isinstance(pchild, list) and pchild:
                                    ptag = _sym(pchild[0])
                                    if ptag == "at":
                                        pad_dx = float(pchild[1])
                                        pad_dy = float(pchild[2]) if len(pchild) > 2 else 0.0
                                    elif ptag == "size":
                                        pad_w = float(pchild[1])
                                        pad_h = (
                                            float(pchild[2])
                                            if len(pchild) > 2
                                            else float(pchild[1])
                                        )
                            px = fp_x + pad_dx
                            py = fp_y + pad_dy
                            _upd(px - pad_w / 2, py - pad_h / 2)
                            _upd(px + pad_w / 2, py + pad_h / 2)

                if min_x == float("inf"):
                    return {
                        "success": False,
                        "message": "No footprints found on the board",
                        "errorDetails": "Place components first",
                    }

                # sexpdata values are already in mm
                conv = 1.0 if unit == "mm" else 1.0 / 25.4
                left = min_x * conv
                top = min_y * conv
                right = max_x * conv
                bottom = max_y * conv
                width = right - left
                height = bottom - top
                center_x = (left + right) / 2
                center_y = (top + bottom) / 2

                return {
                    "success": True,
                    "extents": {
                        "left": left,
                        "top": top,
                        "right": right,
                        "bottom": bottom,
                        "width": width,
                        "height": height,
                        "center": {"x": center_x, "y": center_y},
                        "unit": unit,
                        "source": source,
                    },
                }
            else:
                # Default: Edge.Cuts outline — parse .kicad_pcb with sexpdata
                # to avoid GetDrawings() / GetBoardEdgesBoundingBox() SWIG bugs
                # that return SwigPyObject after board mutations.
                import sexpdata

                board_path = self._get_board_path()
                if not board_path:
                    return {
                        "success": False,
                        "message": "Board has no file path — cannot read Edge.Cuts",
                        "errorDetails": "Save the board first",
                    }

                with open(board_path, encoding="utf-8") as fh:
                    data = sexpdata.loads(fh.read())

                min_x = min_y = float("inf")
                max_x = max_y = float("-inf")

                def _sym(v: Any) -> str:
                    return v.value() if hasattr(v, "value") else str(v)

                def _update(x: float, y: float) -> None:
                    nonlocal min_x, min_y, max_x, max_y
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)

                def _xy_val(node: list) -> tuple:
                    """Return (x, y) from an (xy x y) node."""
                    return float(node[1]), float(node[2])

                for item in data:
                    if not (
                        isinstance(item, list)
                        and item
                        and _sym(item[0]) == "gr_line"
                        or isinstance(item, list)
                        and item
                        and _sym(item[0]) == "gr_rect"
                        or isinstance(item, list)
                        and item
                        and _sym(item[0]) == "gr_circle"
                        or isinstance(item, list)
                        and item
                        and _sym(item[0]) == "gr_poly"
                        or isinstance(item, list)
                        and item
                        and _sym(item[0]) == "gr_arc"
                    ):
                        continue

                    # Check layer == "Edge.Cuts"
                    layer_name = ""
                    for child in item[1:]:
                        if isinstance(child, list) and child and _sym(child[0]) == "layer":
                            v = child[1]
                            layer_name = v if isinstance(v, str) else _sym(v)
                            break
                    if layer_name != "Edge.Cuts":
                        continue

                    shape = _sym(item[0])
                    if shape in ("gr_line", "gr_arc"):
                        for child in item[1:]:
                            if (
                                isinstance(child, list)
                                and child
                                and _sym(child[0]) in ("start", "end", "mid")
                            ):
                                x, y = _xy_val(child)
                                _update(x, y)
                    elif shape == "gr_rect":
                        for child in item[1:]:
                            if (
                                isinstance(child, list)
                                and child
                                and _sym(child[0]) in ("start", "end")
                            ):
                                x, y = _xy_val(child)
                                _update(x, y)
                    elif shape == "gr_circle":
                        cx: Any = None
                        cy: Any = None
                        ex: Any = None
                        ey: Any = None
                        for child in item[1:]:
                            if isinstance(child, list) and child:
                                tag = _sym(child[0])
                                if tag == "center":
                                    cx, cy = _xy_val(child)
                                elif tag == "end":
                                    ex, ey = _xy_val(child)
                        if cx is not None and ex is not None:
                            import math

                            r = math.hypot(float(ex) - float(cx), float(ey) - float(cy))
                            _update(float(cx) - r, float(cy) - r)
                            _update(float(cx) + r, float(cy) + r)
                    elif shape == "gr_poly":
                        for child in item[1:]:
                            if isinstance(child, list) and child and _sym(child[0]) == "pts":
                                for pt in child[1:]:
                                    if isinstance(pt, list) and pt and _sym(pt[0]) == "xy":
                                        x, y = _xy_val(pt)
                                        _update(x, y)

                if min_x == float("inf"):
                    return {
                        "success": False,
                        "message": "No Edge.Cuts items found on the board",
                        "errorDetails": "Add a board outline first",
                    }

                # sexpdata values are already in mm for .kicad_pcb
                left = min_x / (1 if unit == "mm" else 25.4)
                top = min_y / (1 if unit == "mm" else 25.4)
                right = max_x / (1 if unit == "mm" else 25.4)
                bottom = max_y / (1 if unit == "mm" else 25.4)
                width = right - left
                height = bottom - top
                center_x = (left + right) / 2
                center_y = (top + bottom) / 2
                return {
                    "success": True,
                    "extents": {
                        "left": left,
                        "top": top,
                        "right": right,
                        "bottom": bottom,
                        "width": width,
                        "height": height,
                        "center": {"x": center_x, "y": center_y},
                        "unit": unit,
                        "source": source,
                    },
                }

        except Exception as e:
            logger.error(f"Error getting board extents: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get board extents",
                "errorDetails": str(e),
            }
