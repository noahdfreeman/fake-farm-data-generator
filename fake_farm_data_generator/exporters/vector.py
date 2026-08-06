# SPDX-License-Identifier: GPL-3.0-or-later
"""Export canonical GeoPackages to open vector/tabular derivatives."""

from __future__ import annotations

import json
from pathlib import Path

from qgis.core import (
    QgsCoordinateTransformContext,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

from ..core.gpkg_consolidation import spatial_layer_names


OUTPUT_FORMAT_OPTIONS = [
    "GeoPackage",
    "ESRI Shapefile",
    "GeoJSON",
    "CSV points",
    "GeoTIFF surfaces",
]

RASTER_ATTRIBUTE_PRIORITY = (
    "dry_yield",
    "actual_rate",
    "population",
    "P",
    "K",
    "moisture_pct",
    "speed",
)


def _write(layer, destination, driver, layer_options=None):
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    options.fileEncoding = "UTF-8"
    options.layerName = Path(destination).stem
    if layer_options:
        options.layerOptions = list(layer_options)
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer,
        str(destination),
        QgsCoordinateTransformContext(),
        options,
    )
    error_code = result[0]
    if error_code != QgsVectorFileWriter.WriterError.NoError:
        message = result[1] if len(result) > 1 else "unknown writer error"
        raise RuntimeError(f"Could not export {destination}: {message}")


def _field_map(source_layer, exported_path):
    exported = QgsVectorLayer(str(exported_path), exported_path.stem, "ogr")
    if not exported.isValid():
        return {}
    source_names = source_layer.fields().names()
    exported_names = exported.fields().names()
    mapping = {
        source: exported_names[index]
        for index, source in enumerate(source_names)
        if index < len(exported_names) and source != exported_names[index]
    }
    del exported
    return mapping


def _rasterize_surface(source_path, destination, attribute, layer_name=None):
    from osgeo import gdal

    vector = gdal.OpenEx(str(source_path), gdal.OF_VECTOR)
    if vector is None:
        raise RuntimeError(f"Could not open surface for GeoTIFF export: {source_path}")
    layer = vector.GetLayerByName(layer_name) if layer_name else vector.GetLayer(0)
    if layer is None:
        raise RuntimeError(f"Could not open layer {layer_name} in {source_path}")
    x_min, x_max, y_min, y_max = layer.GetExtent()
    count = max(1, layer.GetFeatureCount())
    width_extent = max(1e-12, x_max - x_min)
    height_extent = max(1e-12, y_max - y_min)
    cell_size = (width_extent * height_extent / count) ** 0.5
    width = max(1, int(round(width_extent / cell_size)))
    height = max(1, int(round(height_extent / cell_size)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    raster = gdal.GetDriverByName("GTiff").Create(
        str(destination), width, height, 1, gdal.GDT_Float32,
        options=["COMPRESS=DEFLATE", "TILED=YES"],
    )
    raster.SetGeoTransform((x_min, width_extent / width, 0.0, y_max, 0.0, -height_extent / height))
    spatial_reference = layer.GetSpatialRef()
    if spatial_reference is not None:
        raster.SetProjection(spatial_reference.ExportToWkt())
    band = raster.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    band.Fill(-9999.0)
    result = gdal.RasterizeLayer(raster, [1], layer, options=[f"ATTRIBUTE={attribute}"])
    if result != 0:
        raise RuntimeError(f"Could not rasterize {source_path} using {attribute}")
    band.FlushCache()
    raster.FlushCache()
    band = None
    raster = None
    vector = None


def export_vector_derivatives(run_folder, manifest, selected_formats, feedback=None):
    """Create selected derivatives and append every created artifact to a manifest."""

    root = Path(run_folder)
    selected = set(selected_formats)
    if selected <= {"GeoPackage"}:
        return []
    source_outputs = [
        Path(relative)
        for relative in list(manifest.get("outputs", []))
        if Path(relative).suffix.lower() == ".gpkg"
    ]
    created = []
    field_maps = {}
    for relative in source_outputs:
        if feedback is not None and feedback.isCanceled():
            raise RuntimeError("Processing canceled during derivative export")
        source_path = root / relative
        for layer_name in spatial_layer_names(source_path):
            if feedback is not None and feedback.isCanceled():
                raise RuntimeError("Processing canceled during derivative export")
            uri = f"{source_path}|layername={layer_name}"
            layer = QgsVectorLayer(uri, layer_name, "ogr")
            if not layer.isValid():
                raise RuntimeError(
                    f"Could not open canonical layer {layer_name} in {source_path}"
                )
            year_folder = relative.parent
            if "ESRI Shapefile" in selected:
                folder = root / year_folder / "shapefile"
                folder.mkdir(parents=True, exist_ok=True)
                destination = folder / f"{layer_name}.shp"
                _write(layer, destination, "ESRI Shapefile")
                for artifact in sorted(folder.glob(f"{destination.stem}.*")):
                    relative_artifact = str(artifact.relative_to(root))
                    created.append(relative_artifact)
                mapping = _field_map(layer, destination)
                if mapping:
                    field_maps[str(destination.relative_to(root))] = mapping
            if "GeoJSON" in selected:
                folder = root / year_folder / "geojson"
                folder.mkdir(parents=True, exist_ok=True)
                destination = folder / f"{layer_name}.geojson"
                _write(layer, destination, "GeoJSON")
                created.append(str(destination.relative_to(root)))
            if (
                "CSV points" in selected
                and QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.GeometryType.PointGeometry
            ):
                folder = root / year_folder / "csv"
                folder.mkdir(parents=True, exist_ok=True)
                destination = folder / f"{layer_name}.csv"
                _write(layer, destination, "CSV", ["GEOMETRY=AS_XY"])
                created.append(str(destination.relative_to(root)))
            if (
                "GeoTIFF surfaces" in selected
                and QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.GeometryType.PolygonGeometry
            ):
                attribute = next(
                    (name for name in RASTER_ATTRIBUTE_PRIORITY if name in layer.fields().names()),
                    None,
                )
                if attribute is not None:
                    folder = root / year_folder / "geotiff"
                    destination = folder / f"{layer_name}_{attribute}.tif"
                    _rasterize_surface(source_path, destination, attribute, layer_name)
                    created.append(str(destination.relative_to(root)))
            del layer
            if feedback is not None:
                feedback.pushInfo(f"Exported selected formats for {relative}:{layer_name}")
    if field_maps:
        map_path = root / "field_name_map.json"
        map_path.write_text(json.dumps(field_maps, indent=2), encoding="utf-8")
        created.append(map_path.name)
    manifest.setdefault("outputs", []).extend(
        relative for relative in created if relative not in manifest["outputs"]
    )
    manifest["output_formats"] = sorted(selected)
    return created
