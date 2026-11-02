import pandas as pd
import numpy as np
import geopandas as gpd
import matplotlib.pyplot as plt

# EPSG:26910 is in meters, so buffers and areas come out right
CRS = "EPSG:26910"

COUNTY_NAMES = {"001": "Alameda", "013": "Contra Costa", "075": "San Francisco",
                "081": "San Mateo", "085": "Santa Clara"}

cleaning_log = []


def log_step(dataset, step, before, after, reason):
    cleaning_log.append({"dataset": dataset, "step": step, "rows_before": before,
                         "rows_after": after, "reason": reason})
    print(dataset, "-", step, ":", before, "->", after, "(" + reason + ")")


def load_stations():
    stops = pd.read_csv("../data/raw/bart_gtfs/stops.txt", dtype=str)
    before = len(stops)

    # parent stations have location_type 1, the other rows are platforms
    stations = stops[stops["location_type"] == "1"].copy()
    log_step("stations", "keep parent stations", before, len(stations),
             "platform rows would count each station more than once")

    before = len(stations)
    stations["stop_lat"] = pd.to_numeric(stations["stop_lat"], errors="coerce")
    stations["stop_lon"] = pd.to_numeric(stations["stop_lon"], errors="coerce")
    stations = stations.dropna(subset=["stop_lat", "stop_lon"])
    log_step("stations", "drop missing coordinates", before, len(stations),
             "cannot map a station without a location")

    points = gpd.points_from_xy(stations["stop_lon"], stations["stop_lat"])
    stations = gpd.GeoDataFrame(stations[["stop_id", "stop_name"]], geometry=points,
                                crs="EPSG:4326")
    stations = stations.to_crs(CRS)
    return stations.reset_index(drop=True)


def load_tracts():
    tracts = gpd.read_file("../data/raw/tiger_tracts/tl_2023_06_tract/tl_2023_06_tract.shp")
    before = len(tracts)

    tracts = tracts[tracts["COUNTYFP"].isin(list(COUNTY_NAMES.keys()))]
    log_step("tracts", "keep the 5 counties", before, len(tracts),
             "only the BART counties are in our study area")

    before = len(tracts)
    tracts = tracts[tracts["ALAND"] > 0]
    log_step("tracts", "drop tracts with no land", before, len(tracts),
             "water-only tracts have no jobs")

    tracts = tracts.to_crs(CRS)
    tracts["county"] = tracts["COUNTYFP"].map(COUNTY_NAMES)
    tracts = tracts[["GEOID", "county", "geometry"]]
    return tracts.reset_index(drop=True)


def load_jobs():
    jobs = pd.read_csv("../data/raw/lodes/ca_wac_S000_JT00_2023.csv.gz",
                       dtype={"w_geocode": str}, usecols=["w_geocode", "C000", "CE01"])
    before = len(jobs)

    # first 11 digits of the block code is the tract code
    jobs["GEOID"] = jobs["w_geocode"].str[:11]
    jobs = jobs[jobs["GEOID"].str[2:5].isin(list(COUNTY_NAMES.keys()))]
    log_step("jobs", "keep blocks in the 5 counties", before, len(jobs),
             "LODES covers all of California")

    before = len(jobs)
    jobs = jobs.groupby("GEOID")[["C000", "CE01"]].sum().reset_index()
    log_step("jobs", "add up blocks to tracts", before, len(jobs),
             "we join to tracts, not blocks")
    return jobs


def add_jobs_to_tracts(tracts, jobs):
    tracts = tracts.merge(jobs, on="GEOID", how="left")
    missing = tracts["C000"].isna().sum()
    tracts["C000"] = tracts["C000"].fillna(0)
    tracts["CE01"] = tracts["CE01"].fillna(0)
    log_step("tracts", "set jobs to 0 for " + str(missing) + " tracts not in LODES",
             len(tracts), len(tracts), "LODES only lists blocks that have jobs")
    return tracts


def add_county(stations, tracts):
    # spatial join: which tract is each station inside
    before = len(stations)
    joined = gpd.sjoin(stations, tracts[["county", "geometry"]], how="inner",
                       predicate="within")
    joined = joined.drop(columns="index_right")
    log_step("stations", "spatial join to tracts", before, len(joined),
             "stations outside the 5 counties would be dropped")
    return joined.reset_index(drop=True)


def run_radius(stations, tracts, meters):
    # circle around each station
    circles = stations.copy()
    circles["geometry"] = circles.buffer(meters)

    # spatial join: which tracts touch each circle
    pairs = gpd.sjoin(circles[["stop_id", "geometry"]],
                      tracts[["C000", "CE01", "geometry"]],
                      how="inner", predicate="intersects")

    # share of each tract that is inside the circle
    shares = []
    for i in range(len(pairs)):
        circle = pairs.geometry.iloc[i]
        tract = tracts.geometry.loc[pairs["index_right"].iloc[i]]
        overlap = circle.intersection(tract).area
        shares.append(overlap / tract.area)
    pairs["share"] = shares

    # assume jobs are spread evenly over a tract
    pairs["jobs_total"] = pairs["share"] * pairs["C000"]
    pairs["jobs_low"] = pairs["share"] * pairs["CE01"]

    jobs = pairs.groupby("stop_id")[["jobs_total", "jobs_low"]].sum().reset_index()
    table = stations.merge(jobs, on="stop_id", how="left")
    table["lowwage_pct"] = table["jobs_low"] / table["jobs_total"] * 100
    table["radius"] = meters
    log_step("catchments", str(meters) + " m join", len(stations), len(jobs),
             "stations whose circle touches at least one tract")
    return table


def make_map(tracts, table, meters):
    tracts = tracts.copy()
    tracts["density"] = np.log10(tracts["C000"] / (tracts.geometry.area / 1000000) + 1)

    fig, ax = plt.subplots(figsize=(8, 9))
    tracts.plot(ax=ax, column="density", cmap="Greys", legend=True,
                legend_kwds={"label": "Jobs per sq km (log10 scale)"})
    table.plot(ax=ax, color="red", markersize=table["jobs_total"] / 1000 + 5)
    ax.set_title("BART stations and jobs within " + str(meters) + " m")
    ax.set_xlabel("Easting (meters)")
    ax.set_ylabel("Northing (meters)")
    plt.savefig("../visualizations/map_" + str(meters) + "m.png", bbox_inches="tight")
    plt.show()


def chart_top_stations(all_results):
    table = all_results.pivot_table(index="stop_name", columns="radius", values="jobs_total")
    table = table.sort_values(1000).tail(10)

    ax = table.plot(kind="barh", figsize=(8, 6))
    ax.set_title("Top 10 stations by jobs within walking distance")
    ax.set_xlabel("Jobs (count)")
    ax.set_ylabel("Station")
    ax.legend(title="Radius (m)")
    plt.savefig("../visualizations/chart_top_stations.png", bbox_inches="tight")
    plt.show()


def chart_by_county(all_results):
    table = all_results.groupby(["county", "radius"])["jobs_total"].mean().unstack()
    table = table.sort_values(1000)

    ax = table.plot(kind="barh", figsize=(8, 5))
    ax.set_title("Average jobs within walking distance of a station, by county")
    ax.set_xlabel("Average jobs per station (count)")
    ax.set_ylabel("County")
    ax.legend(title="Radius (m)")
    plt.savefig("../visualizations/chart_by_county.png", bbox_inches="tight")
    plt.show()


def chart_lowwage(all_results):
    fig, ax = plt.subplots(figsize=(7, 5))
    all_results.boxplot(column="lowwage_pct", by="radius", ax=ax)
    plt.suptitle("")
    ax.set_title("Share of nearby jobs that are low wage, by radius")
    ax.set_xlabel("Radius (m)")
    ax.set_ylabel("Low wage jobs (% of jobs)")
    plt.savefig("../visualizations/chart_lowwage.png", bbox_inches="tight")
    plt.show()
