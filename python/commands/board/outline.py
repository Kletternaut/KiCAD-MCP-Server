"""
Board outline command implementations for KiCAD interface
"""

import logging
import math
from typing import Any, Dict, Optional

import pcbnew

logger = logging.getLogger("kicad_interface")


class BoardOutlineCommands:
    """Handles board outline operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board
        self.board_path: Optional[str] = None  # set by KiCadInterface after open_project

    def _board_is_usable(self) -> bool:
        """Return True if self.board is a real BOARD (not SwigPyObject)."""
        return self.board is not None and hasattr(self.board, "GetDrawings")

    def _add_board_outline_sexpdata(
        self,
        board_path: str,
        shape: str,
        x: float,
        y: float,
        width: float,
        height: float,
        unit: str,
    ) -> None:
        """Write Edge.Cuts outline directly to the .kicad_pcb file via sexpdata.

        Removes all existing Edge.Cuts graphic items and adds a new rectangle
        (as 4 gr_line elements).  Only rectangle shape is supported here;
        called as fallback when self.board is a SwigPyObject.
        """
        import sexpdata

        with open(board_path, encoding="utf-8") as fh:
            data = sexpdata.loads(fh.read())

        def _sym(v: Any) -> str:
            return v.value() if hasattr(v, "value") else str(v)

        def _layer_of(node: list) -> str:
            for child in node[1:]:
                if isinstance(child, list) and child and _sym(child[0]) == "layer":
                    v = child[1]
                    return v if isinstance(v, str) else _sym(v)
            return ""

        EDGE_SHAPES = {"gr_line", "gr_rect", "gr_circle", "gr_poly", "gr_arc"}

        # Remove existing Edge.Cuts drawing items
        filtered = []
        for item in data:
            if (
                isinstance(item, list)
                and item
                and _sym(item[0]) in EDGE_SHAPES
                and _layer_of(item) == "Edge.Cuts"
            ):
                continue
            filtered.append(item)

        # Build 4 gr_line items for the rectangle
        x2 = round(x + width, 6)
        y2 = round(y + height, 6)
        x = round(x, 6)
        y = round(y, 6)
        corners = [(x, y, x2, y), (x2, y, x2, y2), (x2, y2, x, y2), (x, y2, x, y)]
        for x1, y1, xe, ye in corners:
            line = [
                sexpdata.Symbol("gr_line"),
                [sexpdata.Symbol("start"), x1, y1],
                [sexpdata.Symbol("end"), xe, ye],
                [
                    sexpdata.Symbol("stroke"),
                    [sexpdata.Symbol("width"), 0.05],
                    [sexpdata.Symbol("type"), sexpdata.Symbol("solid")],
                ],
                [sexpdata.Symbol("layer"), "Edge.Cuts"],
            ]
            filtered.append(line)

        with open(board_path, "w", encoding="utf-8") as fh:
            fh.write(sexpdata.dumps(filtered))

    def add_board_outline(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a board outline to the PCB"""
        try:
            board_path = self.board_path
            if not board_path and self._board_is_usable():
                try:
                    board_path = self.board.GetFileName()
                except Exception:
                    pass
            if not board_path and not self._board_is_usable():
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Claude sends dimensions nested inside a "params" key:
            # {"shape": "rectangle", "params": {"x": 0, "y": 0, "width": 38, ...}}
            # Unwrap the inner dict if present so we read dimensions from the right level.
            inner = params.get("params", params)

            shape = params.get("shape", "rectangle")
            width = inner.get("width")
            height = inner.get("height")
            radius = inner.get("radius")
            # Accept both "cornerRadius" and "radius" regardless of shape name.
            # The AI often sends shape="rectangle" with radius=2.5 — we treat that as rounded_rectangle.
            corner_radius = inner.get("cornerRadius", inner.get("radius", 0))
            if shape == "rectangle" and corner_radius > 0:
                shape = "rounded_rectangle"
            points = inner.get("points", [])
            unit = inner.get("unit", "mm")

            # Position: accept top-left corner (x/y) or center (centerX/centerY).
            # Default: top-left at (0,0) so the board occupies positive coordinate space
            # and is consistent with component placement coordinates.
            x = inner.get("x")
            y = inner.get("y")
            if x is not None or y is not None:
                ox = x if x is not None else 0.0
                oy = y if y is not None else 0.0
                center_x = ox + (width or 0) / 2.0
                center_y = oy + (height or 0) / 2.0
            else:
                raw_cx = inner.get("centerX")
                raw_cy = inner.get("centerY")
                if raw_cx is not None or raw_cy is not None:
                    center_x = raw_cx if raw_cx is not None else 0.0
                    center_y = raw_cy if raw_cy is not None else 0.0
                else:
                    # No position given → place top-left at (0,0)
                    center_x = (width or 0) / 2.0
                    center_y = (height or 0) / 2.0

            if shape not in ["rectangle", "circle", "polygon", "rounded_rectangle"]:
                return {
                    "success": False,
                    "message": "Invalid shape",
                    "errorDetails": f"Shape '{shape}' not supported",
                }

            # --- sexpdata fallback when SWIG board is poisoned (SwigPyObject) ---
            if not self._board_is_usable():
                if shape != "rectangle" or width is None or height is None:
                    return {
                        "success": False,
                        "message": "Only rectangle shape supported without active SWIG board",
                        "errorDetails": "Reload the project to use other shapes",
                    }
                if board_path is None:
                    return {
                        "success": False,
                        "message": "Board file path unknown",
                        "errorDetails": "Open a project first",
                    }
                top_left_x = center_x - width / 2.0
                top_left_y = center_y - height / 2.0
                self._add_board_outline_sexpdata(
                    board_path, shape, top_left_x, top_left_y, width, height, unit
                )
                return {
                    "success": True,
                    "message": f"Added board outline: {shape}",
                    "outline": {
                        "shape": shape,
                        "width": width,
                        "height": height,
                        "center": {"x": center_x, "y": center_y, "unit": unit},
                        "radius": None,
                        "cornerRadius": 0,
                        "points": [],
                    },
                }

            # --- SWIG path (board is a real BOARD object) ---
            # Remove existing Edge.Cuts items before drawing the new outline
            edge_layer = self.board.GetLayerID("Edge.Cuts")
            for item in list(self.board.GetDrawings()):
                if item.GetLayer() == edge_layer:
                    self.board.Remove(item)

            # Convert to internal units (nanometers)
            scale = 1000000 if unit == "mm" else 25400000  # mm or inch to nm

            # Create drawing for edge cuts
            edge_layer = self.board.GetLayerID("Edge.Cuts")

            if shape == "rectangle":
                if width is None or height is None:
                    return {
                        "success": False,
                        "message": "Missing dimensions",
                        "errorDetails": "Both width and height are required for rectangle",
                    }

                width_nm = int(width * scale)
                height_nm = int(height * scale)
                center_x_nm = int(center_x * scale)
                center_y_nm = int(center_y * scale)

                # Create rectangle
                top_left = pcbnew.VECTOR2I(
                    center_x_nm - width_nm // 2, center_y_nm - height_nm // 2
                )
                top_right = pcbnew.VECTOR2I(
                    center_x_nm + width_nm // 2, center_y_nm - height_nm // 2
                )
                bottom_right = pcbnew.VECTOR2I(
                    center_x_nm + width_nm // 2, center_y_nm + height_nm // 2
                )
                bottom_left = pcbnew.VECTOR2I(
                    center_x_nm - width_nm // 2, center_y_nm + height_nm // 2
                )

                # Add lines for rectangle
                self._add_edge_line(top_left, top_right, edge_layer)
                self._add_edge_line(top_right, bottom_right, edge_layer)
                self._add_edge_line(bottom_right, bottom_left, edge_layer)
                self._add_edge_line(bottom_left, top_left, edge_layer)

            elif shape == "rounded_rectangle":
                if width is None or height is None:
                    return {
                        "success": False,
                        "message": "Missing dimensions",
                        "errorDetails": "Both width and height are required for rounded rectangle",
                    }

                width_nm = int(width * scale)
                height_nm = int(height * scale)
                center_x_nm = int(center_x * scale)
                center_y_nm = int(center_y * scale)
                corner_radius_nm = int(corner_radius * scale)

                # Create rounded rectangle
                self._add_rounded_rect(
                    center_x_nm,
                    center_y_nm,
                    width_nm,
                    height_nm,
                    corner_radius_nm,
                    edge_layer,
                )

            elif shape == "circle":
                if radius is None:
                    return {
                        "success": False,
                        "message": "Missing radius",
                        "errorDetails": "Radius is required for circle",
                    }

                center_x_nm = int(center_x * scale)
                center_y_nm = int(center_y * scale)
                radius_nm = int(radius * scale)

                # Create circle
                circle = pcbnew.PCB_SHAPE(self.board)
                circle.SetShape(pcbnew.SHAPE_T_CIRCLE)
                circle.SetCenter(pcbnew.VECTOR2I(center_x_nm, center_y_nm))
                circle.SetEnd(pcbnew.VECTOR2I(center_x_nm + radius_nm, center_y_nm))
                circle.SetLayer(edge_layer)
                circle.SetWidth(0)  # Zero width for edge cuts
                self.board.Add(circle)

            elif shape == "polygon":
                if not points or len(points) < 3:
                    return {
                        "success": False,
                        "message": "Missing points",
                        "errorDetails": "At least 3 points are required for polygon",
                    }

                # Convert points to nm
                polygon_points = []
                for point in points:
                    x_nm = int(point["x"] * scale)
                    y_nm = int(point["y"] * scale)
                    polygon_points.append(pcbnew.VECTOR2I(x_nm, y_nm))

                # Add lines for polygon
                for i in range(len(polygon_points)):
                    self._add_edge_line(
                        polygon_points[i],
                        polygon_points[(i + 1) % len(polygon_points)],
                        edge_layer,
                    )

            # Save board immediately so subsequent SWIG calls (e.g. Zones())
            # don't block on a dirty board object.
            board_path = self.board_path
            if not board_path:
                try:
                    board_path = self.board.GetFileName()
                except Exception:
                    pass
            if board_path:
                self.board.Save(board_path)

            return {
                "success": True,
                "message": f"Added board outline: {shape}",
                "outline": {
                    "shape": shape,
                    "width": width,
                    "height": height,
                    "center": {"x": center_x, "y": center_y, "unit": unit},
                    "radius": radius,
                    "cornerRadius": corner_radius,
                    "points": points,
                },
            }

        except Exception as e:
            logger.error(f"Error adding board outline: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add board outline",
                "errorDetails": str(e),
            }

    def add_mounting_hole(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a mounting hole to the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            position = params.get("position")
            diameter = params.get("diameter")
            pad_diameter = params.get("padDiameter")
            plated = params.get("plated", False)

            if not position or not diameter:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "position and diameter are required",
                }

            # Convert to internal units (nanometers)
            scale = 1000000 if position.get("unit", "mm") == "mm" else 25400000  # mm or inch to nm
            x_nm = int(position["x"] * scale)
            y_nm = int(position["y"] * scale)
            diameter_nm = int(diameter * scale)
            pad_diameter_nm = (
                int(pad_diameter * scale) if pad_diameter else diameter_nm + scale
            )  # 1mm larger by default

            # Create footprint for mounting hole with unique reference
            existing_mh = [
                fp.GetReference()
                for fp in self.board.GetFootprints()
                if fp.GetReference().startswith("MH")
            ]
            next_num = 1
            while f"MH{next_num}" in existing_mh:
                next_num += 1

            module = pcbnew.FOOTPRINT(self.board)
            module.SetReference(f"MH{next_num}")
            module.SetValue(f"MountingHole_{diameter}mm")

            # Create the pad for the hole
            pad = pcbnew.PAD(module)
            pad.SetNumber(1)
            pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH if plated else pcbnew.PAD_ATTRIB_NPTH)
            pad.SetSize(pcbnew.VECTOR2I(pad_diameter_nm, pad_diameter_nm))
            pad.SetDrillSize(pcbnew.VECTOR2I(diameter_nm, diameter_nm))
            pad.SetPosition(pcbnew.VECTOR2I(0, 0))  # Position relative to module
            module.Add(pad)

            # Position the mounting hole
            module.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))

            # Add to board
            self.board.Add(module)

            return {
                "success": True,
                "message": "Added mounting hole",
                "mountingHole": {
                    "position": position,
                    "diameter": diameter,
                    "padDiameter": pad_diameter or diameter + 1,
                    "plated": plated,
                },
            }

        except Exception as e:
            logger.error(f"Error adding mounting hole: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add mounting hole",
                "errorDetails": str(e),
            }

    def add_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add text annotation to the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            text = params.get("text")
            position = params.get("position")
            layer = params.get("layer", "F.SilkS")
            size = params.get("size", 1.0)
            thickness = params.get("thickness", 0.15)
            rotation = params.get("rotation", 0)
            mirror = params.get("mirror", False)

            if not text or not position:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "text and position are required",
                }

            # Convert to internal units (nanometers)
            scale = 1000000 if position.get("unit", "mm") == "mm" else 25400000  # mm or inch to nm
            x_nm = int(position["x"] * scale)
            y_nm = int(position["y"] * scale)
            size_nm = int(size * scale)
            thickness_nm = int(thickness * scale)

            # Get layer ID
            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": f"Layer '{layer}' does not exist",
                }

            # Create text
            pcb_text = pcbnew.PCB_TEXT(self.board)
            pcb_text.SetText(text)
            pcb_text.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))
            pcb_text.SetLayer(layer_id)
            pcb_text.SetTextSize(pcbnew.VECTOR2I(size_nm, size_nm))
            pcb_text.SetTextThickness(thickness_nm)

            # Set rotation angle - KiCAD 9.0 uses EDA_ANGLE
            try:
                # Try KiCAD 9.0+ API (EDA_ANGLE)
                angle = pcbnew.EDA_ANGLE(rotation, pcbnew.DEGREES_T)
                pcb_text.SetTextAngle(angle)
            except (AttributeError, TypeError):
                # Fall back to older API (decidegrees as integer)
                pcb_text.SetTextAngle(int(rotation * 10))

            pcb_text.SetMirrored(mirror)

            # Add to board
            self.board.Add(pcb_text)

            return {
                "success": True,
                "message": "Added text annotation",
                "text": {
                    "text": text,
                    "position": position,
                    "layer": layer,
                    "size": size,
                    "thickness": thickness,
                    "rotation": rotation,
                    "mirror": mirror,
                },
            }

        except Exception as e:
            logger.error(f"Error adding text: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add text",
                "errorDetails": str(e),
            }

    def _add_edge_line(self, start: pcbnew.VECTOR2I, end: pcbnew.VECTOR2I, layer: int) -> None:
        """Add a line to the edge cuts layer"""
        line = pcbnew.PCB_SHAPE(self.board)
        line.SetShape(pcbnew.SHAPE_T_SEGMENT)
        line.SetStart(start)
        line.SetEnd(end)
        line.SetLayer(layer)
        line.SetWidth(0)  # Zero width for edge cuts
        self.board.Add(line)

    def _add_rounded_rect(
        self,
        center_x_nm: int,
        center_y_nm: int,
        width_nm: int,
        height_nm: int,
        radius_nm: int,
        layer: int,
    ) -> None:
        """Add a rounded rectangle to the edge cuts layer"""
        if radius_nm <= 0:
            # If no radius, create regular rectangle
            top_left = pcbnew.VECTOR2I(center_x_nm - width_nm // 2, center_y_nm - height_nm // 2)
            top_right = pcbnew.VECTOR2I(center_x_nm + width_nm // 2, center_y_nm - height_nm // 2)
            bottom_right = pcbnew.VECTOR2I(
                center_x_nm + width_nm // 2, center_y_nm + height_nm // 2
            )
            bottom_left = pcbnew.VECTOR2I(center_x_nm - width_nm // 2, center_y_nm + height_nm // 2)

            self._add_edge_line(top_left, top_right, layer)
            self._add_edge_line(top_right, bottom_right, layer)
            self._add_edge_line(bottom_right, bottom_left, layer)
            self._add_edge_line(bottom_left, top_left, layer)
            return

        # Calculate corner centers
        half_width = width_nm // 2
        half_height = height_nm // 2

        # Ensure radius is not larger than half the smallest dimension
        max_radius = min(half_width, half_height)
        if radius_nm > max_radius:
            radius_nm = max_radius

        # Calculate corner centers
        top_left_center = pcbnew.VECTOR2I(
            center_x_nm - half_width + radius_nm, center_y_nm - half_height + radius_nm
        )
        top_right_center = pcbnew.VECTOR2I(
            center_x_nm + half_width - radius_nm, center_y_nm - half_height + radius_nm
        )
        bottom_right_center = pcbnew.VECTOR2I(
            center_x_nm + half_width - radius_nm, center_y_nm + half_height - radius_nm
        )
        bottom_left_center = pcbnew.VECTOR2I(
            center_x_nm - half_width + radius_nm, center_y_nm + half_height - radius_nm
        )

        # Add arcs for corners
        self._add_corner_arc(top_left_center, radius_nm, 180, 270, layer)
        self._add_corner_arc(top_right_center, radius_nm, 270, 0, layer)
        self._add_corner_arc(bottom_right_center, radius_nm, 0, 90, layer)
        self._add_corner_arc(bottom_left_center, radius_nm, 90, 180, layer)

        # Add lines for straight edges
        # Top edge
        self._add_edge_line(
            pcbnew.VECTOR2I(top_left_center.x, top_left_center.y - radius_nm),
            pcbnew.VECTOR2I(top_right_center.x, top_right_center.y - radius_nm),
            layer,
        )
        # Right edge
        self._add_edge_line(
            pcbnew.VECTOR2I(top_right_center.x + radius_nm, top_right_center.y),
            pcbnew.VECTOR2I(bottom_right_center.x + radius_nm, bottom_right_center.y),
            layer,
        )
        # Bottom edge
        self._add_edge_line(
            pcbnew.VECTOR2I(bottom_right_center.x, bottom_right_center.y + radius_nm),
            pcbnew.VECTOR2I(bottom_left_center.x, bottom_left_center.y + radius_nm),
            layer,
        )
        # Left edge
        self._add_edge_line(
            pcbnew.VECTOR2I(bottom_left_center.x - radius_nm, bottom_left_center.y),
            pcbnew.VECTOR2I(top_left_center.x - radius_nm, top_left_center.y),
            layer,
        )

    def _add_corner_arc(
        self,
        center: pcbnew.VECTOR2I,
        radius: int,
        start_angle: float,
        end_angle: float,
        layer: int,
    ) -> None:
        """Add an arc for a rounded corner"""
        # Create arc for corner
        arc = pcbnew.PCB_SHAPE(self.board)
        arc.SetShape(pcbnew.SHAPE_T_ARC)
        arc.SetCenter(center)

        # Calculate start and end points
        start_x = center.x + int(radius * math.cos(math.radians(start_angle)))
        start_y = center.y + int(radius * math.sin(math.radians(start_angle)))
        end_x = center.x + int(radius * math.cos(math.radians(end_angle)))
        end_y = center.y + int(radius * math.sin(math.radians(end_angle)))

        arc.SetStart(pcbnew.VECTOR2I(start_x, start_y))
        arc.SetEnd(pcbnew.VECTOR2I(end_x, end_y))
        arc.SetLayer(layer)
        arc.SetWidth(0)  # Zero width for edge cuts
        self.board.Add(arc)
