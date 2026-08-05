# SPDX-License-Identifier: GPL-3.0-or-later
"""Sample categorical CDL values inside a field polygon with QGIS raster APIs."""

from __future__ import annotations

import math

from qgis.core import (
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
)


def raster_histogram(raster, field_geometry, field_crs, transform_context=None):
    """Return class counts and nominal resolution for one field geometry."""

    layer = raster if isinstance(raster, QgsRasterLayer) else QgsRasterLayer(str(raster), "CDL")
    if not layer.isValid():
        raise ValueError(f"Could not open CDL raster: {raster}")
    geometry = QgsGeometry(field_geometry)
    context = transform_context or QgsProject.instance().transformContext()
    if field_crs != layer.crs():
        geometry.transform(QgsCoordinateTransform(field_crs, layer.crs(), context))
    if geometry.isEmpty():
        return {}, max(abs(layer.rasterUnitsPerPixelX()), abs(layer.rasterUnitsPerPixelY()))

    raster_extent = layer.extent()
    field_extent = geometry.boundingBox()
    sample_extent = QgsRectangle(
        max(raster_extent.xMinimum(), field_extent.xMinimum()),
        max(raster_extent.yMinimum(), field_extent.yMinimum()),
        min(raster_extent.xMaximum(), field_extent.xMaximum()),
        min(raster_extent.yMaximum(), field_extent.yMaximum()),
    )
    if sample_extent.isEmpty() or sample_extent.width() <= 0 or sample_extent.height() <= 0:
        return {}, max(abs(layer.rasterUnitsPerPixelX()), abs(layer.rasterUnitsPerPixelY()))

    pixel_x = max(1e-9, abs(layer.rasterUnitsPerPixelX()))
    pixel_y = max(1e-9, abs(layer.rasterUnitsPerPixelY()))
    width = max(1, int(math.ceil(sample_extent.width() / pixel_x)))
    height = max(1, int(math.ceil(sample_extent.height() / pixel_y)))
    block = layer.dataProvider().block(1, sample_extent, width, height)
    if block is None or not block.isValid():
        raise ValueError(f"Could not read CDL raster values: {layer.source()}")

    step_x = sample_extent.width() / width
    step_y = sample_extent.height() / height
    histogram = {}
    for row in range(height):
        y = sample_extent.yMaximum() - (row + 0.5) * step_y
        for column in range(width):
            if block.isNoData(row, column):
                continue
            x = sample_extent.xMinimum() + (column + 0.5) * step_x
            if not geometry.contains(QgsGeometry.fromPointXY(QgsPointXY(x, y))):
                continue
            value = int(round(float(block.value(row, column))))
            histogram[value] = histogram.get(value, 0) + 1
    return histogram, max(pixel_x, pixel_y)
