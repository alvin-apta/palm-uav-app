from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Iterable

from app.models.all_models import Tree
from app.services.geojson import feature_collection, point_feature


def trees_to_geojson(trees: Iterable[Tree]) -> dict:
    return feature_collection(
        [
            point_feature(
                tree.lon,
                tree.lat,
                {
                    "id": tree.id,
                    "block_id": tree.block_id,
                    "health_class": tree.health_class.value,
                    "confidence": tree.confidence,
                    "equivalent_diameter_m": tree.equivalent_diameter_m,
                    "vari": tree.vari,
                    "lai_estimate": tree.lai_estimate,
                },
            )
            for tree in trees
        ]
    )


def trees_to_csv(trees: list[Tree]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "tree_id",
            "block_id",
            "lat",
            "lon",
            "health_class",
            "confidence",
            "equivalent_diameter_m",
            "vari",
            "lai_estimate",
        ],
    )
    writer.writeheader()
    for tree in trees:
        writer.writerow(
            {
                "tree_id": tree.id,
                "block_id": tree.block_id,
                "lat": tree.lat,
                "lon": tree.lon,
                "health_class": tree.health_class.value,
                "confidence": tree.confidence,
                "equivalent_diameter_m": tree.equivalent_diameter_m,
                "vari": tree.vari,
                "lai_estimate": tree.lai_estimate,
            }
        )
    return buffer.getvalue()


def trees_to_kml(trees: list[Tree], name: str = "Palm prescription") -> str:
    placemarks = []
    for tree in trees:
        placemarks.append(
            f"""
            <Placemark>
              <name>{tree.health_class.value}</name>
              <description>Tree {tree.id}; confidence {tree.confidence:.3f}</description>
              <Point><coordinates>{tree.lon},{tree.lat},0</coordinates></Point>
            </Placemark>
            """
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <name>{name}</name>
        {''.join(placemarks)}
      </Document>
    </kml>
    """


def kmz_bytes(kml_text: str, filename: str = "doc.kml") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, kml_text)
    return buffer.getvalue()


def prescription_bundle_bytes(trees: list[Tree]) -> bytes:
    geojson_text = json.dumps(trees_to_geojson(trees), ensure_ascii=False, indent=2)
    csv_text = trees_to_csv(trees)
    kml_text = trees_to_kml(trees)
    kmz = kmz_bytes(kml_text)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("prescription.geojson", geojson_text)
        archive.writestr("prescription.csv", csv_text)
        archive.writestr("prescription.kml", kml_text)
        archive.writestr("prescription.kmz", kmz)
    return buffer.getvalue()

