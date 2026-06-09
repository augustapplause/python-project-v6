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

DEFAULT_SINGLE_ADDRESS = "50 Victoria St, Gatineau, Quebec"
DEFAULT_COMPARE_ADDRESS_A = "50 Victoria St, Gatineau, Quebec"
DEFAULT_COMPARE_ADDRESS_B = "301 Wellington St, Ottawa, Ontario"


def init_persistent_state():
    defaults = {
        "single_address_value": DEFAULT_SINGLE_ADDRESS,
        "compare_address_a_value": DEFAULT_COMPARE_ADDRESS_A,
        "compare_address_b_value": DEFAULT_COMPARE_ADDRESS_B,
        "single_radius_km_value": 1.0,
        "single_overlap_pct_value": 5,
        "compare_radius_km_value": 1.0,
        "compare_overlap_pct_value": 5,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def prepare_widget(widget_key: str, value_key: str):
    if widget_key not in st.session_state:
        st.session_state[widget_key] = st.session_state[value_key]


def save_widget_value(widget_key: str, value_key: str):
    st.session_state[value_key] = st.session_state[widget_key]


init_persistent_state()


# -----------------------------
# Comparison view visual controls
# Change these pixel values to adjust comparison page font sizes
# -----------------------------
COMPARE_PAGE_TITLE_FONT_SIZE = 36
COMPARE_SECTION_TITLE_FONT_SIZE = 26
COMPARE_MAP_TITLE_FONT_SIZE = 22

COMPARE_ADDRESS_LABEL_FONT_SIZE = 22
COMPARE_ADDRESS_INPUT_FONT_SIZE = 24
COMPARE_SLIDER_LABEL_FONT_SIZE = 50
COMPARE_TABLE_HEADER_FONT_SIZE = 24
COMPARE_TABLE_CELL_FONT_SIZE = 20


def inject_comparison_css():
    st.markdown(f"""
    <style>
    /* View toggle text */
    div[role="radiogroup"] label {{
        font-size: {COMPARE_ADDRESS_LABEL_FONT_SIZE}px !important;
    }}

    /* Address input labels */
    div[data-testid="stTextInput"] label {{
        font-size: {COMPARE_ADDRESS_LABEL_FONT_SIZE}px !important;
        font-weight: 600 !important;
    }}

    /* Address input box text */
    div[data-testid="stTextInput"] input {{
        font-size: {COMPARE_ADDRESS_INPUT_FONT_SIZE}px !important;
    }}

    /* Slider labels */
    div[data-testid="stSlider"] label {{
        font-size: {COMPARE_SLIDER_LABEL_FONT_SIZE}px !important;
        font-weight: 600 !important;
    }}

    /* Comparison summary table */
    div[data-testid="stTable"] table {{
        font-size: {COMPARE_TABLE_CELL_FONT_SIZE}px !important;
    }}

    div[data-testid="stTable"] th {{
        font-size: {COMPARE_TABLE_HEADER_FONT_SIZE}px !important;
        font-weight: 700 !important;
    }}

    div[data-testid="stTable"] td {{
        font-size: {COMPARE_TABLE_CELL_FONT_SIZE}px !important;
    }}
    </style>
    """, unsafe_allow_html=True)



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


def get_zoom(radius_km: float) -> int:
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
    return zoom_lookup.get(radius_km, 13)


def build_catchment(address: str, radius_km: float, min_overlap_pct: int):
    if not address.strip():
        return {"error": "Enter an address or postal code."}

    geo = geocode_address(address)

    if geo is None:
        return {"error": "Address could not be geocoded."}

    province_code = infer_province(address, geo)

    if province_code is None:
        return {"error": "Could not detect province."}

    da_gdf = load_province_geojson(province_code, RELEASE_BASE_URL)

    point_wgs84, point_3347, buffer_3347 = make_buffer(
        geo["lat"],
        geo["lon"],
        radius_km
    )

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

    total_population = selected["total_population"].fillna(0).sum()
    seniors_65 = selected["population_65_plus"].fillna(0).sum()
    pop_0_39 = selected["population_0_39"].fillna(0).sum()
    non_immigrants = selected["non_immigrants"].fillna(0).sum()
    visible_minority = selected["visible_minority_population"].fillna(0).sum()
    weighted_median_income = weighted_average_income(selected)
    weighted_average_household_income = household_weighted_average_income(selected)

    total_households = selected["total_households"].fillna(0).sum()
    owner_households = selected["owner_households"].fillna(0).sum()
    bachelors_plus = selected["bachelors_degree_or_higher"].fillna(0).sum()

    metrics = {
        "da_count": len(selected),
        "total_population": total_population,
        "seniors_65": seniors_65,
        "pop_0_39": pop_0_39,
        "non_immigrants": non_immigrants,
        "visible_minority": visible_minority,
        "weighted_median_income": weighted_median_income,
        "weighted_average_household_income": weighted_average_household_income,
        "total_households": total_households,
        "owner_households": owner_households,
        "bachelors_plus": bachelors_plus,
        "seniors_pct": 0 if total_population == 0 else round(seniors_65 / total_population * 100),
        "pop_039_pct": 0 if total_population == 0 else round(pop_0_39 / total_population * 100),
        "nonimm_pct": 0 if total_population == 0 else round(non_immigrants / total_population * 100),
        "vm_pct": 0 if total_population == 0 else round(visible_minority / total_population * 100),
        "owner_pct": 0 if total_households == 0 else round(owner_households / total_households * 100),
        "bachelors_pct": 0 if total_population == 0 else round(bachelors_plus / total_population * 100),
        "estimated_da_income": weighted_average_household_income * total_households,
        "estimated_da_income_millions": (weighted_average_household_income * total_households) / 1_000_000,
    }

    return {
        "error": None,
        "geo": geo,
        "province_code": province_code,
        "selected": selected,
        "subject_da_id": subject_da_id,
        "metrics": metrics,
    }


def make_map(catchment: dict, radius_km: float, height: int = 430):
    geo = catchment["geo"]
    selected = catchment["selected"]
    da_count = catchment["metrics"]["da_count"]

    m = folium.Map(
        location=[geo["lat"], geo["lon"]],
        zoom_start=get_zoom(radius_km),
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
        height=height,
        use_container_width=True,
        returned_objects=[]
    )




def show_single_address_view():
    st.sidebar.title("Inputs & Outputs (v5.0)")

    prepare_widget("_single_address", "single_address_value")
    st.sidebar.text_input(
        "Centre on Address or Postal Code:",
        key="_single_address",
        on_change=save_widget_value,
        args=("_single_address", "single_address_value")
    )
    address = st.session_state["single_address_value"]

    prepare_widget("_single_radius_km", "single_radius_km_value")
    st.sidebar.slider(
        "Radius (km):",
        min_value=0.5,
        max_value=10.0,
        step=0.5,
        key="_single_radius_km",
        on_change=save_widget_value,
        args=("_single_radius_km", "single_radius_km_value")
    )
    radius_km = st.session_state["single_radius_km_value"]

    prepare_widget("_single_overlap_pct", "single_overlap_pct_value")
    st.sidebar.slider(
        "Min DA overlap (0% = intersection only):",
        min_value=0,
        max_value=50,
        step=1,
        key="_single_overlap_pct",
        on_change=save_widget_value,
        args=("_single_overlap_pct", "single_overlap_pct_value")
    )
    min_overlap_pct = st.session_state["single_overlap_pct_value"]

    with st.spinner("Building catchment..."):
        catchment = build_catchment(address, radius_km, min_overlap_pct)

    if catchment["error"] is not None:
        st.warning(catchment["error"])
        st.stop()

    selected = catchment["selected"]
    subject_da_id = catchment["subject_da_id"]
    metrics = catchment["metrics"]

    da_count = metrics["da_count"]
    total_population = metrics["total_population"]
    seniors_65 = metrics["seniors_65"]
    pop_0_39 = metrics["pop_0_39"]
    non_immigrants = metrics["non_immigrants"]
    visible_minority = metrics["visible_minority"]
    weighted_median_income = metrics["weighted_median_income"]
    weighted_average_household_income = metrics["weighted_average_household_income"]
    total_households = metrics["total_households"]
    owner_households = metrics["owner_households"]
    bachelors_plus = metrics["bachelors_plus"]
    seniors_pct = metrics["seniors_pct"]
    pop_039_pct = metrics["pop_039_pct"]
    nonimm_pct = metrics["nonimm_pct"]
    vm_pct = metrics["vm_pct"]
    owner_pct = metrics["owner_pct"]
    bachelors_pct = metrics["bachelors_pct"]
    estimated_da_income_millions = metrics["estimated_da_income_millions"]

    st.title(f"Canadian Census by DA - {da_count:,} identified")

    st.sidebar.markdown("#### Total Population")
    st.sidebar.markdown(
        f"<div style='font-size:32px;color:#2952CC;font-weight:bold;margin-top:-22px;'>{total_population:,.0f}</div>",
        unsafe_allow_html=True
    )

    st.sidebar.markdown("#### Seniors 65+")
    st.sidebar.markdown(
        f"<div style='font-size:28px;color:#00C853;font-weight:bold;margin-top:-22px;'>{seniors_65:,.0f}<span style='font-size:20px;color:#CC0000;'>&nbsp;&nbsp;({seniors_pct}%)</span></div>",
        unsafe_allow_html=True
    )

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

    st.sidebar.markdown("#### Visible Minority")
    st.sidebar.markdown(
        f"<div style='font-size:28px;font-weight:bold;margin-top:-22px;'>{visible_minority:,.0f}<span style='font-size:20px;color:#CC0000;'>&nbsp;&nbsp;({vm_pct}%)</span></div>",
        unsafe_allow_html=True
    )

    st.sidebar.markdown("#### Avg Household Income")
    st.sidebar.markdown(
        f"<div style='font-size:28px;font-weight:bold;margin-top:-22px;'>${weighted_average_household_income:,.0f}<span style='font-size:20px;color:#CC0000;'>&nbsp;&nbsp;(est DA income ${estimated_da_income_millions:,.1f}M)</span></div>",
        unsafe_allow_html=True
    )

    st.sidebar.markdown("#### Households")
    st.sidebar.markdown(
        f"<div style='font-size:28px;font-weight:bold;margin-top:-22px;'>{total_households:,.0f}<span style='font-size:20px;color:#CC0000;'>&nbsp;&nbsp;({owner_pct}% owned)</span></div>",
        unsafe_allow_html=True
    )

    st.sidebar.markdown("#### Bachelor deg+")
    st.sidebar.markdown(
        f"<div style='font-size:28px;font-weight:bold;margin-top:-22px;'>{bachelors_plus:,.0f}<span style='font-size:20px;color:#CC0000;'>&nbsp;&nbsp;({bachelors_pct}%)</span></div>",
        unsafe_allow_html=True
    )

    make_map(catchment, radius_km, height=430)

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
            "Total Households": total_households,
            "Owner Households": owner_households,
            "Renter Households": selected["renter_households"].fillna(0).sum(),
            "Average Household Income": weighted_average_household_income,
            "Median Household Income": weighted_median_income,
            "Bachelor's Degree+": bachelors_plus,
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


def comparison_value(metric_name: str, value):
    if metric_name == "Avg Household Income":
        return f"${value:,.0f}"
    if metric_name == "Estimated DA Income":
        return f"${value / 1_000_000:,.1f}M"
    return f"{value:,.0f}"


def comparison_difference(metric_name: str, a, b):
    diff = b - a

    if metric_name == "Avg Household Income":
        sign = "+" if diff >= 0 else "-"
        return f"{sign}${abs(diff):,.0f}"

    if metric_name == "Estimated DA Income":
        sign = "+" if diff >= 0 else "-"
        return f"{sign}${abs(diff) / 1_000_000:,.1f}M"

    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:,.0f}"


def show_comparison_view():
    inject_comparison_css()

    st.markdown(
        f"<h1 style='font-size:{COMPARE_PAGE_TITLE_FONT_SIZE}px; font-weight:700; margin-bottom:0.5rem;'>Compare Two Census Catchments</h1>",
        unsafe_allow_html=True
    )

    control_col1, control_col2 = st.columns(2)

    with control_col1:
        prepare_widget("_compare_address_a", "compare_address_a_value")
        st.text_input(
            "Address A",
            key="_compare_address_a",
            on_change=save_widget_value,
            args=("_compare_address_a", "compare_address_a_value")
        )
        address_a = st.session_state["compare_address_a_value"]

    with control_col2:
        prepare_widget("_compare_address_b", "compare_address_b_value")
        st.text_input(
            "Address B",
            key="_compare_address_b",
            on_change=save_widget_value,
            args=("_compare_address_b", "compare_address_b_value")
        )
        address_b = st.session_state["compare_address_b_value"]

    slider_col1, slider_col2 = st.columns(2)

    with slider_col1:
        prepare_widget("_compare_radius_km", "compare_radius_km_value")
        st.slider(
            "Radius (km)",
            min_value=0.5,
            max_value=10.0,
            step=0.5,
            key="_compare_radius_km",
            on_change=save_widget_value,
            args=("_compare_radius_km", "compare_radius_km_value")
        )
        radius_km = st.session_state["compare_radius_km_value"]

    with slider_col2:
        prepare_widget("_compare_overlap_pct", "compare_overlap_pct_value")
        st.slider(
            "Min DA overlap (0% = intersection only)",
            min_value=0,
            max_value=50,
            step=1,
            key="_compare_overlap_pct",
            on_change=save_widget_value,
            args=("_compare_overlap_pct", "compare_overlap_pct_value")
        )
        min_overlap_pct = st.session_state["compare_overlap_pct_value"]

    with st.spinner("Building comparison catchments..."):
        catchment_a = build_catchment(address_a, radius_km, min_overlap_pct)
        catchment_b = build_catchment(address_b, radius_km, min_overlap_pct)

    if catchment_a["error"] is not None:
        st.error(f"Address A: {catchment_a['error']}")
        st.stop()

    if catchment_b["error"] is not None:
        st.error(f"Address B: {catchment_b['error']}")
        st.stop()

    metrics_a = catchment_a["metrics"]
    metrics_b = catchment_b["metrics"]

    comparison_rows = [
        {
            "Metric": "Total Population",
            "Address A": comparison_value("Total Population", metrics_a["total_population"]),
            "Address B": comparison_value("Total Population", metrics_b["total_population"]),
            "Difference": comparison_difference("Total Population", metrics_a["total_population"], metrics_b["total_population"]),
        },
        {
            "Metric": "Population 0-19",
            "Address A": comparison_value("Population 0-19", catchment_a["selected"]["population_0_19"].fillna(0).sum()),
            "Address B": comparison_value("Population 0-19", catchment_b["selected"]["population_0_19"].fillna(0).sum()),
            "Difference": comparison_difference("Population 0-19", catchment_a["selected"]["population_0_19"].fillna(0).sum(), catchment_b["selected"]["population_0_19"].fillna(0).sum()),
        },
        {
            "Metric": "Population 65+",
            "Address A": comparison_value("Population 65+", metrics_a["seniors_65"]),
            "Address B": comparison_value("Population 65+", metrics_b["seniors_65"]),
            "Difference": comparison_difference("Population 65+", metrics_a["seniors_65"], metrics_b["seniors_65"]),
        },
        {
            "Metric": "Population 0-39",
            "Address A": comparison_value("Population 0-39", metrics_a["pop_0_39"]),
            "Address B": comparison_value("Population 0-39", metrics_b["pop_0_39"]),
            "Difference": comparison_difference("Population 0-39", metrics_a["pop_0_39"], metrics_b["pop_0_39"]),
        },
        {
            "Metric": "Number of Households",
            "Address A": f"{metrics_a['total_households']:,.0f} ({metrics_a['owner_pct']}% owned)",
            "Address B": f"{metrics_b['total_households']:,.0f} ({metrics_b['owner_pct']}% owned)",
            "Difference": comparison_difference("Number of Households", metrics_a["total_households"], metrics_b["total_households"]),
        },
        {
            "Metric": "Avg Household Income",
            "Address A": comparison_value("Avg Household Income", metrics_a["weighted_average_household_income"]),
            "Address B": comparison_value("Avg Household Income", metrics_b["weighted_average_household_income"]),
            "Difference": comparison_difference("Avg Household Income", metrics_a["weighted_average_household_income"], metrics_b["weighted_average_household_income"]),
        },
        {
            "Metric": "Estimated DA Income",
            "Address A": comparison_value("Estimated DA Income", metrics_a["estimated_da_income"]),
            "Address B": comparison_value("Estimated DA Income", metrics_b["estimated_da_income"]),
            "Difference": comparison_difference("Estimated DA Income", metrics_a["estimated_da_income"], metrics_b["estimated_da_income"]),
        },
    ]

    comparison_df = pd.DataFrame(comparison_rows)

    st.markdown(
        f"<h2 style='font-size:{COMPARE_SECTION_TITLE_FONT_SIZE}px; font-weight:700; margin-top:1rem;'>Comparison Summary</h2>",
        unsafe_allow_html=True
    )

    # Table font sizes are controlled by COMPARE_TABLE_HEADER_FONT_SIZE
    # and COMPARE_TABLE_CELL_FONT_SIZE near the top of this file.
    st.table(comparison_df)

    map_col1, map_col2 = st.columns(2)

    with map_col1:
        st.markdown(
            f"<div style='font-size:{COMPARE_MAP_TITLE_FONT_SIZE}px; font-weight:700; margin-bottom:0.5rem;'>Address A - {metrics_a['da_count']:,} DAs</div>",
            unsafe_allow_html=True
        )
        make_map(catchment_a, radius_km, height=360)

    with map_col2:
        st.markdown(
            f"<div style='font-size:{COMPARE_MAP_TITLE_FONT_SIZE}px; font-weight:700; margin-bottom:0.5rem;'>Address B - {metrics_b['da_count']:,} DAs</div>",
            unsafe_allow_html=True
        )
        make_map(catchment_b, radius_km, height=360)


view_mode = st.radio(
    "View",
    ["Single Address", "Compare Two Addresses"],
    horizontal=True
)

if view_mode == "Single Address":
    show_single_address_view()
else:
    show_comparison_view()
