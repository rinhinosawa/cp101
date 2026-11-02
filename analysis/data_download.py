# run from the repo root: python analysis/data_download.py
import os
import urllib.request
import zipfile

os.makedirs("data/raw/tiger_tracts", exist_ok=True)
os.makedirs("data/raw/lodes", exist_ok=True)

# census tracts for California (2023)
tract_zip = "data/raw/tiger_tracts/tl_2023_06_tract.zip"
if not os.path.exists(tract_zip):
    url = "https://www2.census.gov/geo/tiger/TIGER2023/TRACT/tl_2023_06_tract.zip"
    urllib.request.urlretrieve(url, tract_zip)
    with zipfile.ZipFile(tract_zip) as z:
        z.extractall("data/raw/tiger_tracts/tl_2023_06_tract")

# jobs by workplace block for California (2023)
jobs_file = "data/raw/lodes/ca_wac_S000_JT00_2023.csv.gz"
if not os.path.exists(jobs_file):
    url = "https://lehd.ces.census.gov/data/lodes/LODES8/ca/wac/ca_wac_S000_JT00_2023.csv.gz"
    urllib.request.urlretrieve(url, jobs_file)

# LODES od data by block group for California (2023)
od_file = "data/raw/lodes/ca_od_main_JT00_2023.csv.gz"
if not os.path.exists(od_file):
    url = "https://lehd.ces.census.gov/data/lodes/LODES8/ca/od/ca_od_main_JT00_2023.csv.gz"
    urllib.request.urlretrieve(url, od_file)

print("done")
