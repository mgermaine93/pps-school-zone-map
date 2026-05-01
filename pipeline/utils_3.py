import json
import geopandas as gpd
import numpy as np

from shapely.geometry import Point, MultiPoint
from shapely.ops import unary_union
from alphashape import alphashape
from scipy.spatial import Voronoi

def load_points(path):
    gdf = gpd.read_file(path)
    gdf = gdf[gdf.geometry.notnull()]
    return gdf

def split_by_type(gdf):
    return {
        "K8": gdf[gdf["type"] == "K8"],
        "HIGH": gdf[gdf["type"] == "HIGH"],
        "ELEMENTARY": gdf[gdf["type"] == "ELEM"],
        "MIDDLE": gdf[gdf["type"] == "MIDD"],
        "ONLINE": gdf[gdf["type"] == "ONLINE"]
    }

def concave_hulls(gdf, alpha=0.02):
    results = []

    for school_id, group in gdf.groupby("school_id"):
        points = [geom for geom in group.geometry]

        if len(points) < 3:
            continue  # can't build polygon

        try:
            hull = alphashape(points, alpha)
        except Exception:
            hull = MultiPoint(points).convex_hull

        results.append({
            "school_id": school_id,
            "name": group.iloc[0]["name"],
            "type": group.iloc[0]["type"],
            "geometry": hull
        })

    return gpd.GeoDataFrame(results, crs="EPSG:4326")


def voronoi_zones(gdf):
    points = []
    labels = []
    meta = []

    for _, row in gdf.iterrows():
        x, y = row.geometry.x, row.geometry.y
        points.append((x, y))
        labels.append(row["school_id"])
        meta.append((row["school_id"], row["name"], row["type"]))

    points = np.array(points)
    vor = Voronoi(points)

    # NOTE: full polygon reconstruction is complex
    # We'll store raw for now or use convex fallback

    zones = []

    for i, (sid, name, typ) in enumerate(meta):
        zones.append({
            "school_id": sid,
            "name": name,
            "type": typ,
            "geometry": Point(points[i])  # placeholder seed
        })

    return gpd.GeoDataFrame(zones, crs="EPSG:4326")


def export(gdf, path):
    gdf.to_file(path, driver="GeoJSON")


def build_all_zones(input_file):
    gdf = load_points(input_file)

    # split layers
    layers = split_by_type(gdf)

    outputs = {}

    for layer_name, layer_gdf in layers.items():

        # concave hulls (real zones)
        hulls = concave_hulls(layer_gdf)
        export(hulls, f"{layer_name}_zones_concave.geojson")

        # voronoi (idealized zones)
        vor = voronoi_zones(layer_gdf)
        export(vor, f"{layer_name}_zones_voronoi.geojson")

        outputs[layer_name] = {
            "concave": hulls,
            "voronoi": vor
        }

    return outputs


build_all_zones(input_file="schools_points.geojson")