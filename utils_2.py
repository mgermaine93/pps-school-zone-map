# import json

# input_file = "new_pps_schools copy_2.jsonl"
# output_file = "cleaned_new_pps_schools.json"

# data = []

# with open(input_file, "r") as f:
#     for line in f:
#         line = line.strip()
#         if not line:
#             continue
#         data.append(json.loads(line))

# with open(output_file, "w") as f:
#     json.dump(data, f, indent=2)

# import json

# with open("schools_grouped.json") as f:
#     data = json.load(f)

# geojson = {
#     "type": "FeatureCollection",
#     "features": []
# }

# for school_id, value in data.items():
#     geojson["features"].append({
#         "type": "Feature",
#         "properties": {
#             "school_id": school_id,
#             "name": value["name"]
#         },
#         "geometry": {
#             "type": "MultiPoint",
#             "coordinates": value["points"]
#         }
#     })

# with open("school-boundaries.geojson", "w") as f:
#     json.dump(geojson, f, indent=2)


import pandas as pd
from shapely.geometry import Point
import geopandas as gpd
import alphashape
from shapely.geometry import MultiPoint
import json

def build_school_index(input_path, output_path="schools_grouped.json"):
    """
    Converts address-level records into school-level point collections.
    """

    with open(input_path, "r") as f:
        data = json.load(f)

    schools = {}

    for addr in data:
        if addr.get("lat") is None or addr.get("lng") is None:
            continue

        for school in addr.get("schools", []):
            sid = school["id"]

            if sid not in schools:
                schools[sid] = {
                    "school_id": sid,
                    "name": school.get("name"),
                    "type": school.get("type"),
                    "points": []
                }

            # convert tuple → list for JSON safety
            schools[sid]["points"].append([
                addr["lng"],
                addr["lat"]
            ])

    # OPTIONAL: write grouped result (this is what you actually want)
    with open(output_path, "w") as f:
        json.dump(schools, f)

    return schools


def to_geodataframe(schools_dict):
    records = []

    for school in schools_dict.values():
        for lon, lat in school["points"]:
            records.append({
                "school_id": school["school_id"],
                "name": school["name"],
                "type": school["type"],
                "geometry": Point(lon, lat)
            })

    return gpd.GeoDataFrame(records, crs="EPSG:4326")



def build_concave_hulls(gdf, alpha=0.01):
    """
    Builds concave hull per school.
    """

    hulls = []

    for school_id, group in gdf.groupby("school_id"):
        points = list(group.geometry)

        if len(points) < 3:
            continue

        multi = MultiPoint(points)

        hull = alphashape.alphashape(multi, alpha)

        hulls.append({
            "school_id": school_id,
            "name": group.iloc[0]["name"],
            "type": group.iloc[0]["type"],
            "geometry": hull
        })

    return gpd.GeoDataFrame(hulls, crs="EPSG:4326")


def classify_layers(hulls_gdf):
    layers = {
        "elementary": hulls_gdf[hulls_gdf["type"].str.contains("K", na=False)],
        "middle": hulls_gdf[hulls_gdf["type"].str.contains("MIDDLE", na=False)],
        "high": hulls_gdf[hulls_gdf["type"].str.contains("HIGH", na=False)],
        "other": hulls_gdf[~hulls_gdf["type"].str.contains("K|MIDDLE|HIGH", na=False)]
    }

    return layers


# build_school_index(input_path="./cleaned_new_pps_schools.json")

def to_geodataframe(schools_dict):
    records = []

    for school in schools_dict.values():
        for lon, lat in school["points"]:
            records.append({
                "school_id": school["school_id"],
                "name": school["name"],
                "type": school["type"],
                "geometry": Point(lon, lat)
            })

    gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")
    return gdf


def build_school_geodataframe(input_path):
    with open(input_path, "r") as f:
        schools_dict = json.load(f)

    return to_geodataframe(schools_dict)


def export_schools(gdf, output_path):
    if output_path.endswith(".geojson"):
        gdf.to_file(output_path, driver="GeoJSON")

    elif output_path.endswith(".shp"):
        gdf.to_file(output_path)

    elif output_path.endswith(".gpkg"):
        gdf.to_file(output_path, driver="GPKG")

    else:
        raise ValueError("Unsupported output format")


gdf = build_school_geodataframe("schools_grouped.json")

# export_schools(gdf, "schools_points.geojson")

from shapely.geometry import MultiPoint
import geopandas as gpd

groups = gdf.groupby("school_id")