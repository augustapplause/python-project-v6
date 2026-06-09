import io
import requests
import pandas as pd
import geopandas as gpd
import streamlit as st
import folium

from geopy.geocoders import ArcGIS
from shapely.geometry import Point
from streamlit_folium import st_folium

st.set_page_config(page_title="Canadian Census by DA", layout="wide")

RELEASE_BASE_URL = "https://github.com/augustapplause/python-project-v6/releases/download/v1"

PROVINCE_FILES = {
    "AB": "AB_da_census_13vars_30m.geojson",
    "BC": "BC_da_census_13vars_30m.geojson",
    "MB": "MB_da_census_13vars_30m.geojson",
    "NB": "NB_da_census_13vars_30m.geojson",
    "NL": "NL_da_census_13vars_30m.geojson",
    "NS": "NS_da_census_13vars_30m.geojson",
    "NT": "NT_da_census_13vars_30m.geojson",
    "NU": "NU_da_census_13vars_30m.geojson",
    "ON": "ON_da_census_13vars_30m.geojson",
    "PE": "PE_da_census_13vars_30m.geojson",
    "QC": "QC_da_census_13vars_30m.geojson",
    "SK": "SK_da_census_13vars_30m.geojson",
    "YT": "YT_da_census_13vars_30m.geojson",
}

PROVINCE_NAMES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba",
    "NB": "New Brunswick", "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia", "NT": "Northwest Territories", "NU": "Nunavut",
    "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
}


@st.cache_data(show_spinner=False)
def load_province_geojson(province_code: str, release_base_url: str) -> gpd.GeoDataFrame:
    url = f"{release_base_url}/{PROVINCE_FILES[province_code]}"
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    gdf = gpd.read_file(io.BytesIO(response.content))
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    return gdf


@st.cache_data(show_spinner=False)
def geocode_address(address: str):
    geolocator = ArcGIS(timeout=20)
    location = geolocator.geocode(address)
    if location is None:
        return None
    return {
        "address": location.address,
        "lat": location.latitude,
        "lon": location.longitude,
        "raw": location.raw,
    }


def infer_province(address_text: str, geocode_result: dict) -> str | None:
    text = f"{address_text} {geocode_result.get('address', '')}".lower()
    province_aliases = {
        "ON": ["ontario", ", on", " on ", "toronto", "ottawa"],
        "QC": ["quebec", "québec", ", qc", " qc ", "montreal", "montréal", "gatineau"],
        "BC": ["british columbia", ", bc", " bc ", "vancouver"],
        "AB": ["alberta", ", ab", " ab ", "calgary", "edmonton"],
        "MB": ["manitoba", ", mb", " mb ", "winnipeg"],
        "SK": ["saskatchewan", ", sk", " sk ", "regina", "saskatoon"],
        "NS": ["nova scotia", ", ns", " ns ", "halifax"],
        "NB": ["new brunswick", ", nb", " nb "],
        "NL": ["newfoundland", "labrador", ", nl", " nl ", "st. john's"],
        "PE": ["prince edward island", ", pe", " pe ", "charlottetown"],
        "YT": ["yukon", ", yt", " yt "],
        "NT": ["northwest territories", ", nt", " nt "],
        "NU": ["nunavut", ", nu", " nu "],
    }
    for code, aliases in province_aliases.items():
        if any(alias in text for alias in aliases):
            return code
    return None


def make_buffer(lat: float, lon: float, radius_km: float):
    point_wgs84 = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326")
    point_3347 = point_wgs84.to_crs(epsg=3347)
    buffer_3347 = point_3347.buffer(radius_km * 1000)
    return point_wgs84.iloc[0], point_3347.iloc[0], buffer_3347.iloc[0]


def weighted_average_income(df: pd.DataFrame) -> float:
    valid = df[
        df["median_household_income"].notna()
        & df["total_population"].notna()
        & (df["total_population"] > 0)
    ].copy()

    if len(valid) == 0:
        return 0

    return (
        valid["median_household_income"] * valid["total_population"]
    ).sum() / valid["total_population"].sum()


def household_weighted_average_income(df: pd.DataFrame) -> float:
    valid = df[
        df["average_household_income"].notna()
        & df["total_households"].notna()
        & (df["total_households"] > 0)
    ].copy()

    if len(valid) == 0:
        return 0

    return (
        valid["average_household_income"] * valid["total_households"]
    ).sum() / valid["total_households"].sum()


st.sidebar.title("Inputs & Outputs (v5.0)")

address = st.sidebar.text_input(
    "Centre on Address or Postal Code:",
    value="50 Victoria St, Gatineau, Quebec"
)

radius_km = st.sidebar.slider(
    "Radius (km):",
    min_value=0.5,
    max_value=10.0,
    value=1.0,
    step=0.5
)

min_overlap_pct = st.sidebar.slider(
    "Min DA overlap (0% = intersection only):",
    min_value=0,
    max_value=50,
    value=5,
    step=1
)

#manual_province = st.sidebar.selectbox(
#    "Province override:",
#    ["Auto-detect"] + [f"{k} - {v}" for k, v in PROVINCE_NAMES.items()]
#)

manual_province = "Auto-detect"

if not address.strip():
    st.warning("Enter an address or postal code.")
    st.stop()

with st.spinner("Geocoding address..."):
    geo = geocode_address(address)

if geo is None:
    st.error("Address could not be geocoded.")
    st.stop()

province_code = infer_province(address, geo) if manual_province == "Auto-detect" else manual_province.split(" - ")[0]

if province_code is None:
    st.error("Could not detect province. Please use the province override.")
    st.stop()

with st.spinner(f"Loading {province_code} DA file..."):
    da_gdf = load_province_geojson(province_code, RELEASE_BASE_URL)

point_wgs84, point_3347, buffer_3347 = make_buffer(geo["lat"], geo["lon"], radius_km)

da_3347 = da_gdf.to_crs(epsg=3347).copy()

subject_da = da_3347[da_3347.geometry.contains(point_3347)].copy()
subject_da_id = None

if len(subject_da) > 0:
    subject_da_id = str(subject_da.iloc[0]["DA_ID"])

intersects_mask = da_3347.geometry.intersects(buffer_3347)
candidate_3347 = da_3347[intersects_mask].copy()

if len(candidate_3347) > 0:
    candidate_3347["intersection_area"] = candidate_3347.geometry.intersection(buffer_3347).area
    candidate_3347["da_area"] = candidate_3347.geometry.area
    candidate_3347["overlap_pct"] = candidate_3347["intersection_area"] / candidate_3347["da_area"] * 100

    selected_3347 = candidate_3347[
        (candidate_3347["overlap_pct"] >= min_overlap_pct)
        | (candidate_3347["DA_ID"].astype(str) == subject_da_id)
    ].copy()
else:
    selected_3347 = candidate_3347.copy()

selected = selected_3347.to_crs(epsg=4326)

da_count = len(selected)
total_population = selected["total_population"].fillna(0).sum()
seniors_65 = selected["population_65_plus"].fillna(0).sum()
pop_0_39 = selected["population_0_39"].fillna(0).sum()
non_immigrants = selected["non_immigrants"].fillna(0).sum()
visible_minority = selected["visible_minority_population"].fillna(0).sum()
weighted_median_income = weighted_average_income(selected)
weighted_average_household_income = household_weighted_average_income(selected)

seniors_pct = 0 if total_population == 0 else round(seniors_65 / total_population * 100)
pop_039_pct = 0 if total_population == 0 else round(pop_0_39 / total_population * 100)
nonimm_pct = 0 if total_population == 0 else round(non_immigrants / total_population * 100)
vm_pct = 0 if total_population == 0 else round(visible_minority / total_population * 100)

st.title(f"Canadian Census by DA - {da_count:,} identified")

st.sidebar.markdown("#### Total Population")
st.sidebar.markdown(
    f"<div style='font-size:32px;color:#2952CC;font-weight:bold;margin-top:-22px;'>{total_population:,.0f}</div>",
    unsafe_allow_html=True
)

#col1, col2 = st.sidebar.columns(2)

#with col1:
st.sidebar.markdown("#### Seniors 65+")
st.sidebar.markdown(
        f"<div style='font-size:28px;color:#00C853;font-weight:bold;margin-top:-22px;'>{seniors_65:,.0f}<span style='font-size:20px;color:#CC0000;'>&nbsp;&nbsp;({seniors_pct}%)</span></div>",
        unsafe_allow_html=True
    )

#with col2:
st.sidebar.markdown("#### Population 0-39")
st.sidebar.markdown(
        f"<div style='font-size:28px;font-weight:bold;margin-top:-22px;'>{pop_0_39:,.0f}<span style='font-size:20px;color:#CC0000;'>&nbsp;&nbsp;({pop_039_pct}%)</span></div>",
        unsafe_allow_html=True
    )

st.sidebar.markdown("#### Non-Immigrants")
st.sidebar.markdown(
    f"<div style='font-size:28px;font-weight:bold;margin-top:-22px;'>{non_immigrants:,.0f}<span style='font-size:20px;color:#CC0000;'>&nbsp;&nbsp;({nonimm_pct}%)</span></div>",
    unsafe_allow_html=True
)

st.sidebar.markdown("#### Visible Minority Population")
st.sidebar.markdown(
    f"<div style='font-size:28px;font-weight:bold;margin-top:-22px;'>{visible_minority:,.0f}<span style='font-size:20px;color:#CC0000;'>&nbsp;&nbsp;({vm_pct}%)</span></div>",
    unsafe_allow_html=True
)

st.sidebar.markdown("#### Median Household Income")
st.sidebar.markdown(
    f"<div style='font-size:28px;font-weight:bold;margin-top:-22px;'>${weighted_median_income:,.0f}</div>",
    unsafe_allow_html=True
)



zoom_lookup = {
    0.5: 15,
    1.0: 14,
    1.5: 14,
    2.0: 13,
    3.0: 13,
    4.0: 12,
    5.0: 12,
    5.5: 12,
    6.0: 12,
    6.5: 12,
    7.0: 11,
    7.5: 11,
    8.0: 11,
    8.5: 11,
    9.0: 11,
    9.5: 11,
    10.0: 11,
}

zoom = zoom_lookup.get(radius_km, 13)

m = folium.Map(
    location=[geo["lat"], geo["lon"]],
    zoom_start=zoom,
    tiles="OpenStreetMap",
)

folium.Marker(
    [geo["lat"], geo["lon"]],
    tooltip=geo["address"],
    icon=folium.Icon(color="red", icon="home")
).add_to(m)

folium.Circle(
    location=[geo["lat"], geo["lon"]],
    radius=radius_km * 1000,
    color="red",
    fill=False,
    weight=3,
).add_to(m)

if da_count > 0:
    folium.GeoJson(
        selected,
        name="Selected DAs",
        style_function=lambda feature: {
            "fillColor": "#4da3ff",
            "color": "#0078ff",
            "weight": 2,
            "fillOpacity": 0.35,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=[
                "DA_ID",
                "total_population",
                "population_65_plus",
                "population_0_39",
                "median_household_income",
            ],
            aliases=[
                "DA ID:",
                "Total Population:",
                "Seniors 65+:",
                "Population 0-39:",
                "Median HH Income:",
            ],
            localize=True,
            sticky=True,
        ),
    ).add_to(m)

st_folium(
    m,
    height=430,
    use_container_width=True,
    returned_objects=[]
)

st.subheader("Mapped Dissemination Areas - 2021 Census (selected)")

if da_count == 0:
    st.info("No dissemination areas meet the selected overlap threshold.")
else:
    table = selected[
        [
            "DA_ID",
            "total_population",
            "population_0_19",
            "population_20_39",
            "population_40_64",
            "population_65_plus",
            "non_immigrants",
            "visible_minority_population",
            "total_households",
            "owner_households",
            "renter_households",
            "average_household_income",
            "median_household_income",
            "bachelors_degree_or_higher",
            "LANDAREA",
            "DGUID",
        ]
    ].copy()

    table = table.rename(columns={
        "DA_ID": "DA Code",
        "DGUID": "DGUID",
        "total_population": "Total Population",
        "population_0_19": "Population 0-19",
        "population_20_39": "Population 20-39",
        "population_40_64": "Population 40-64",
        "population_65_plus": "Seniors 65+",
        "non_immigrants": "Non-Immigrants",
        "visible_minority_population": "Visible Minority Population",
        "total_households": "Total Households",
        "owner_households": "Owner Households",
        "renter_households": "Renter Households",
        "average_household_income": "Average Household Income",
        "median_household_income": "Median Household Income",
        "bachelors_degree_or_higher": "Bachelor's Degree+",
        "LANDAREA": "Land Area sq km",
    })

    table = table.sort_values("DA Code")

    total_row = pd.DataFrame([{
        "DA Code": "TOTAL",
        "DGUID": "",
        "Total Population": total_population,
        "Population 0-19": selected["population_0_19"].fillna(0).sum(),
        "Population 20-39": selected["population_20_39"].fillna(0).sum(),
        "Population 40-64": selected["population_40_64"].fillna(0).sum(),
        "Seniors 65+": seniors_65,
        "Non-Immigrants": non_immigrants,
        "Visible Minority Population": visible_minority,
        "Total Households": selected["total_households"].fillna(0).sum(),
        "Owner Households": selected["owner_households"].fillna(0).sum(),
        "Renter Households": selected["renter_households"].fillna(0).sum(),
        "Average Household Income": weighted_average_household_income,
        "Median Household Income": weighted_median_income,
        "Bachelor's Degree+": selected["bachelors_degree_or_higher"].fillna(0).sum(),
        "Land Area sq km": table["Land Area sq km"].sum(),
    }])

    display_table = pd.concat([table, total_row], ignore_index=True)

    def bold_subject_da(row):
        if subject_da_id is not None and str(row["DA Code"]) == subject_da_id:
            return ["font-weight: bold"] * len(row)
        return [""] * len(row)

    def highlight_total_row(row):
        if str(row["DA Code"]) == "TOTAL":
            return ["background-color: #FFF2CC; font-weight: bold"] * len(row)
    return [""] * len(row)

styled_table = (
    display_table.style
    .apply(bold_subject_da, axis=1)
    .apply(highlight_total_row, axis=1)
        .format({
            "Total Population": "{:,.0f}",
            "Population 0-19": "{:,.0f}",
            "Population 20-39": "{:,.0f}",
            "Population 40-64": "{:,.0f}",
            "Seniors 65+": "{:,.0f}",
            "Non-Immigrants": "{:,.0f}",
            "Visible Minority Population": "{:,.0f}",
            "Total Households": "{:,.0f}",
            "Owner Households": "{:,.0f}",
            "Renter Households": "{:,.0f}",
            "Average Household Income": "${:,.0f}",
            "Median Household Income": "${:,.0f}",
            "Bachelor's Degree+": "{:,.0f}",
            "Land Area sq km": "{:,.4f}",
        })
    )

    st.dataframe(
        styled_table,
        use_container_width=True,
        hide_index=True,
    )