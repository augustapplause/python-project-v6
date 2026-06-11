import io
import time
import zipfile
import requests
import pandas as pd
import geopandas as gpd
import streamlit as st
import folium
import xml.etree.ElementTree as ET

from geopy.geocoders import ArcGIS
from shapely.geometry import Point
from streamlit_folium import st_folium

st.set_page_config(page_title="Canadian Census by DA", layout="wide")

RELEASE_BASE_URL = "https://github.com/augustapplause/python-project-v6/releases/download/v1"
#RELEASE_BASE_URL = "https://github.com/augustapplause/python-project-v1/releases/download/v1"

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

BATCH_OUTPUT_COLUMNS = [
    "processing_status",
    "geocode_status",
    "geocoded_address",
    "matched_province",
    "subject_da_id",
    "da_count",
    "total_population",
    "population_0_19",
    "population_20_39",
    "population_40_64",
    "population_65_plus",
    "population_0_39",
    "non_immigrants",
    "visible_minority_population",
    "total_households",
    "owner_households",
    "renter_households",
    "average_household_income",
    "median_household_income",
    "bachelors_degree_or_higher",
    "owner_pct",
    "renter_pct",
    "bachelor_pct",
    "seniors_pct",
    "population_0_39_pct",
    "visible_minority_pct",
    "non_immigrant_pct",
    "estimated_da_income",
    "land_area_sq_km",
    "population_density",
    "household_density",
]

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
COMPARE_PAGE_TITLE_FONT_SIZE = 32
COMPARE_SECTION_TITLE_FONT_SIZE = 26
COMPARE_MAP_TITLE_FONT_SIZE = 22

COMPARE_ADDRESS_LABEL_FONT_SIZE = 16
COMPARE_ADDRESS_INPUT_FONT_SIZE = 20
COMPARE_SLIDER_LABEL_FONT_SIZE = 16
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

    /* Slider labels are rendered manually in HTML below.
       Keep this block empty to avoid fighting Streamlit's internal CSS. */

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


def geocode_address_with_retry(address: str, max_retries: int = 3, delay_seconds: float = 1.25):
    if not isinstance(address, str) or not address.strip():
        return None, "missing_address"

    geolocator = ArcGIS(timeout=20)

    for attempt in range(1, max_retries + 1):
        try:
            location = geolocator.geocode(address)

            if location is None:
                return None, "geocode_no_match"

            return {
                "address": location.address,
                "lat": location.latitude,
                "lon": location.longitude,
                "raw": location.raw,
            }, "geocode_ok"

        except Exception as exc:
            if attempt == max_retries:
                return None, f"geocode_error: {exc}"

            time.sleep(delay_seconds * attempt)

    return None, "geocode_error"


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

    land_area_sq_km = selected["LANDAREA"].fillna(0).sum()
    population_density = 0 if land_area_sq_km == 0 else total_population / land_area_sq_km
    household_density = 0 if land_area_sq_km == 0 else total_households / land_area_sq_km

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
        "land_area_sq_km": land_area_sq_km,
        "population_density": population_density,
        "household_density": household_density,
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



def summarize_selected_for_batch(selected: gpd.GeoDataFrame) -> dict:
    if selected is None or len(selected) == 0:
        return {
            "da_count": 0,
            "total_population": 0,
            "population_0_19": 0,
            "population_20_39": 0,
            "population_40_64": 0,
            "population_65_plus": 0,
            "population_0_39": 0,
            "non_immigrants": 0,
            "visible_minority_population": 0,
            "total_households": 0,
            "owner_households": 0,
            "renter_households": 0,
            "average_household_income": 0,
            "median_household_income": 0,
            "bachelors_degree_or_higher": 0,
            "owner_pct": 0,
            "renter_pct": 0,
            "bachelor_pct": 0,
            "seniors_pct": 0,
            "population_0_39_pct": 0,
            "visible_minority_pct": 0,
            "non_immigrant_pct": 0,
            "estimated_da_income": 0,
            "land_area_sq_km": 0,
            "population_density": 0,
            "household_density": 0,
        }

    total_population = selected["total_population"].fillna(0).sum()
    population_0_19 = selected["population_0_19"].fillna(0).sum()
    population_20_39 = selected["population_20_39"].fillna(0).sum()
    population_40_64 = selected["population_40_64"].fillna(0).sum()
    population_65_plus = selected["population_65_plus"].fillna(0).sum()
    population_0_39 = selected["population_0_39"].fillna(0).sum()
    non_immigrants = selected["non_immigrants"].fillna(0).sum()
    visible_minority_population = selected["visible_minority_population"].fillna(0).sum()
    total_households = selected["total_households"].fillna(0).sum()
    owner_households = selected["owner_households"].fillna(0).sum()
    renter_households = selected["renter_households"].fillna(0).sum()
    bachelors_degree_or_higher = selected["bachelors_degree_or_higher"].fillna(0).sum()
    average_household_income = household_weighted_average_income(selected)
    median_household_income = weighted_average_income(selected)
    land_area_sq_km = selected["LANDAREA"].fillna(0).sum()

    return {
        "da_count": len(selected),
        "total_population": total_population,
        "population_0_19": population_0_19,
        "population_20_39": population_20_39,
        "population_40_64": population_40_64,
        "population_65_plus": population_65_plus,
        "population_0_39": population_0_39,
        "non_immigrants": non_immigrants,
        "visible_minority_population": visible_minority_population,
        "total_households": total_households,
        "owner_households": owner_households,
        "renter_households": renter_households,
        "average_household_income": average_household_income,
        "median_household_income": median_household_income,
        "bachelors_degree_or_higher": bachelors_degree_or_higher,
        "owner_pct": 0 if total_households == 0 else owner_households / total_households * 100,
        "renter_pct": 0 if total_households == 0 else renter_households / total_households * 100,
        "bachelor_pct": 0 if total_population == 0 else bachelors_degree_or_higher / total_population * 100,
        "seniors_pct": 0 if total_population == 0 else population_65_plus / total_population * 100,
        "population_0_39_pct": 0 if total_population == 0 else population_0_39 / total_population * 100,
        "visible_minority_pct": 0 if total_population == 0 else visible_minority_population / total_population * 100,
        "non_immigrant_pct": 0 if total_population == 0 else non_immigrants / total_population * 100,
        "estimated_da_income": average_household_income * total_households,
        "land_area_sq_km": land_area_sq_km,
        "population_density": 0 if land_area_sq_km == 0 else total_population / land_area_sq_km,
        "household_density": 0 if land_area_sq_km == 0 else total_households / land_area_sq_km,
    }


def find_first_case_insensitive_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized = {str(col).strip().lower(): col for col in df.columns}

    for candidate in candidates:
        if candidate.lower() in normalized:
            return normalized[candidate.lower()]

    return None


def excel_column_letters_to_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    index = 0

    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)

    return index - 1


def read_xlsx_without_openpyxl(uploaded_file) -> pd.DataFrame:
    """
    Lightweight XLSX reader used when openpyxl is unavailable on Streamlit Cloud.
    It reads the first worksheet and supports normal values, shared strings,
    inline strings, numbers, blanks, and first-row headers.
    """
    uploaded_file.seek(0)
    file_bytes = uploaded_file.read()

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        ns = {
            "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
        }

        shared_strings = []

        if "xl/sharedStrings.xml" in z.namelist():
            shared_root = ET.fromstring(z.read("xl/sharedStrings.xml"))

            for si in shared_root.findall("main:si", ns):
                parts = []

                for t in si.findall(".//main:t", ns):
                    parts.append(t.text or "")

                shared_strings.append("".join(parts))

        workbook_root = ET.fromstring(z.read("xl/workbook.xml"))
        first_sheet = workbook_root.find("main:sheets/main:sheet", ns)

        if first_sheet is None:
            raise ValueError("No worksheets found in XLSX file.")

        rel_id = first_sheet.attrib.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )

        rels_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        sheet_target = None

        for rel in rels_root.findall("rel:Relationship", ns):
            if rel.attrib.get("Id") == rel_id:
                sheet_target = rel.attrib.get("Target")
                break

        if sheet_target is None:
            raise ValueError("Could not identify the first worksheet in the XLSX file.")

        if sheet_target.startswith("/"):
            sheet_path = sheet_target.lstrip("/")
        else:
            sheet_path = "xl/" + sheet_target

        sheet_path = sheet_path.replace("xl/xl/", "xl/")

        sheet_root = ET.fromstring(z.read(sheet_path))
        rows = []

        for row in sheet_root.findall(".//main:sheetData/main:row", ns):
            values_by_col = {}
            max_col = -1

            for cell in row.findall("main:c", ns):
                cell_ref = cell.attrib.get("r", "")
                col_idx = excel_column_letters_to_index(cell_ref)
                max_col = max(max_col, col_idx)

                cell_type = cell.attrib.get("t")
                value_node = cell.find("main:v", ns)
                inline_node = cell.find("main:is/main:t", ns)

                if cell_type == "s":
                    if value_node is None or value_node.text is None:
                        value = ""
                    else:
                        value = shared_strings[int(value_node.text)]
                elif cell_type == "inlineStr":
                    value = "" if inline_node is None or inline_node.text is None else inline_node.text
                else:
                    value = "" if value_node is None or value_node.text is None else value_node.text

                values_by_col[col_idx] = value

            if max_col >= 0:
                rows.append([values_by_col.get(i, "") for i in range(max_col + 1)])

        if len(rows) == 0:
            return pd.DataFrame()

        max_len = max(len(row) for row in rows)
        normalized_rows = [row + [""] * (max_len - len(row)) for row in rows]

        headers = [str(value).strip() for value in normalized_rows[0]]
        data_rows = normalized_rows[1:]

        # Handle duplicate or blank headers safely.
        cleaned_headers = []
        seen = {}

        for i, header in enumerate(headers):
            if header == "":
                header = f"Unnamed_{i + 1}"

            if header in seen:
                seen[header] += 1
                header = f"{header}_{seen[header]}"
            else:
                seen[header] = 0

            cleaned_headers.append(header)

        df = pd.DataFrame(data_rows, columns=cleaned_headers)

        # Convert numeric-looking columns where possible.
        # Avoid pandas errors="ignore" because some Streamlit environments reject it.
        for col in df.columns:
            converted = pd.to_numeric(df[col], errors="coerce")

            # Only replace the column if conversion did not wipe out real text values.
            non_blank_original = df[col].astype(str).str.strip().ne("")
            converted_non_null = converted.notna()

            if non_blank_original.sum() == 0:
                df[col] = converted
            elif converted_non_null.sum() == non_blank_original.sum():
                df[col] = converted

        return df


def read_uploaded_table(uploaded_file) -> pd.DataFrame:
    filename = uploaded_file.name.lower()

    if filename.endswith(".csv"):
        return pd.read_csv(uploaded_file)

    if filename.endswith(".xlsx"):
        try:
            uploaded_file.seek(0)
            return pd.read_excel(uploaded_file, engine="openpyxl")
        except ImportError:
            return read_xlsx_without_openpyxl(uploaded_file)

    if filename.endswith(".xls"):
        try:
            uploaded_file.seek(0)
            return pd.read_excel(uploaded_file)
        except ImportError as exc:
            raise ValueError(
                "Old .xls files require the xlrd package on Streamlit Cloud. "
                "Please save the file as .xlsx or .csv, or add xlrd to requirements.txt."
            ) from exc

    raise ValueError("Upload must be a CSV, XLS, or XLSX file.")


@st.cache_data(show_spinner=False)
def load_all_provinces_for_batch(release_base_url: str) -> dict:
    return {
        province_code: load_province_geojson(province_code, release_base_url)
        for province_code in PROVINCE_FILES
    }


def build_catchment_from_lat_lon(
    lat: float,
    lon: float,
    radius_km: float,
    min_overlap_pct: int,
    province_gdfs: dict,
):
    point_wgs84, point_3347, buffer_3347 = make_buffer(lat, lon, radius_km)

    for province_code, da_gdf in province_gdfs.items():
        point_match = da_gdf[da_gdf.geometry.contains(point_wgs84)]

        if len(point_match) == 0:
            continue

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

        return {
            "error": None,
            "province_code": province_code,
            "subject_da_id": subject_da_id,
            "selected": selected,
        }

    return {
        "error": "no_da_match",
        "province_code": None,
        "subject_da_id": None,
        "selected": gpd.GeoDataFrame(),
    }


def process_batch_file(
    input_df: pd.DataFrame,
    radius_km: float,
    min_overlap_pct: int,
    geocode_delay_seconds: float,
    geocode_max_retries: int,
):
    df = input_df.copy()

    lat_col = find_first_case_insensitive_column(df, ["latitude", "lat"])
    lon_col = find_first_case_insensitive_column(df, ["longitude", "lon", "long"])

    if lat_col is None:
        df["latitude"] = pd.NA
        lat_col = "latitude"

    if lon_col is None:
        df["longitude"] = pd.NA
        lon_col = "longitude"

    address_col = find_first_case_insensitive_column(
        df,
        ["address", "store_address", "full_address", "location_address", "addr"]
    )

    province_gdfs = load_all_provinces_for_batch(RELEASE_BASE_URL)

    output_rows = []
    total_rows = len(df)

    progress_bar = st.progress(0)
    status_text = st.empty()

    for row_number, (_, row) in enumerate(df.iterrows(), start=1):
        status_text.write(f"Processing row {row_number:,} of {total_rows:,}")

        output_row = row.to_dict()
        output_row.setdefault("processing_status", "ok")
        output_row.setdefault("geocode_status", "not_needed")
        output_row.setdefault("geocoded_address", "")
        output_row.setdefault("matched_province", "")
        output_row.setdefault("subject_da_id", "")

        lat = pd.to_numeric(row.get(lat_col), errors="coerce")
        lon = pd.to_numeric(row.get(lon_col), errors="coerce")

        try:
            if pd.isna(lat) or pd.isna(lon):
                if address_col is None:
                    output_row["processing_status"] = "missing_lat_lon_no_address"
                    output_row.update(summarize_selected_for_batch(gpd.GeoDataFrame()))
                    output_rows.append(output_row)
                    progress_bar.progress(row_number / total_rows)
                    continue

                geo, geocode_status = geocode_address_with_retry(
                    str(row.get(address_col, "")),
                    max_retries=geocode_max_retries,
                    delay_seconds=geocode_delay_seconds,
                )

                output_row["geocode_status"] = geocode_status

                if geo is None:
                    output_row["processing_status"] = "geocode_failed"
                    output_row.update(summarize_selected_for_batch(gpd.GeoDataFrame()))
                    output_rows.append(output_row)
                    progress_bar.progress(row_number / total_rows)
                    time.sleep(geocode_delay_seconds)
                    continue

                lat = geo["lat"]
                lon = geo["lon"]
                output_row[lat_col] = lat
                output_row[lon_col] = lon
                output_row["geocoded_address"] = geo["address"]

                time.sleep(geocode_delay_seconds)

            catchment = build_catchment_from_lat_lon(
                lat=float(lat),
                lon=float(lon),
                radius_km=radius_km,
                min_overlap_pct=min_overlap_pct,
                province_gdfs=province_gdfs,
            )

            if catchment["error"] is not None:
                output_row["processing_status"] = catchment["error"]
                output_row.update(summarize_selected_for_batch(gpd.GeoDataFrame()))
            else:
                output_row["processing_status"] = "ok"
                output_row["matched_province"] = catchment["province_code"]
                output_row["subject_da_id"] = catchment["subject_da_id"]
                output_row.update(summarize_selected_for_batch(catchment["selected"]))

        except Exception as exc:
            output_row["processing_status"] = f"error: {exc}"
            output_row.update(summarize_selected_for_batch(gpd.GeoDataFrame()))

        output_rows.append(output_row)
        progress_bar.progress(row_number / total_rows)

    progress_bar.empty()
    status_text.empty()

    output_df = pd.DataFrame(output_rows)

    original_cols = list(input_df.columns)
    appended_cols = [col for col in BATCH_OUTPUT_COLUMNS if col in output_df.columns]
    remaining_cols = [
        col for col in output_df.columns
        if col not in original_cols + appended_cols
    ]

    return output_df[original_cols + remaining_cols + appended_cols]


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
    population_density = metrics["population_density"]
    household_density = metrics["household_density"]
    owner_households = metrics["owner_households"]
    bachelors_plus = metrics["bachelors_plus"]
    seniors_pct = metrics["seniors_pct"]
    pop_039_pct = metrics["pop_039_pct"]
    nonimm_pct = metrics["nonimm_pct"]
    vm_pct = metrics["vm_pct"]
    owner_pct = metrics["owner_pct"]
    bachelors_pct = metrics["bachelors_pct"]
    estimated_da_income_millions = metrics["estimated_da_income_millions"]

    st.title(f"Canadian Census - {da_count:,} DAs")

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

    st.sidebar.markdown("#### Population Density")
    st.sidebar.markdown(
        f"<div style='font-size:28px;font-weight:bold;margin-top:-22px;'>{population_density:,.0f}<span style='font-size:20px;color:#CC0000;'>&nbsp;&nbsp;/ sq km</span></div>",
        unsafe_allow_html=True
    )

    st.sidebar.markdown("#### Household Density")
    st.sidebar.markdown(
        f"<div style='font-size:28px;font-weight:bold;margin-top:-22px;'>{household_density:,.0f}<span style='font-size:20px;color:#CC0000;'>&nbsp;&nbsp;/ sq km</span></div>",
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
    if metric_name in ["Population Density", "Household Density"]:
        return f"{value:,.0f} / sq km"
    return f"{value:,.0f}"


def comparison_difference(metric_name: str, a, b):
    diff = b - a

    if metric_name == "Avg Household Income":
        sign = "+" if diff >= 0 else "-"
        return f"{sign}${abs(diff):,.0f}"

    if metric_name == "Estimated DA Income":
        sign = "+" if diff >= 0 else "-"
        return f"{sign}${abs(diff) / 1_000_000:,.1f}M"

    if metric_name in ["Population Density", "Household Density"]:
        sign = "+" if diff >= 0 else "-"
        return f"{sign}{abs(diff):,.0f} / sq km"

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
        st.markdown(
            f"<div style='font-size:{COMPARE_ADDRESS_LABEL_FONT_SIZE}px;'>Address A</div>",
            unsafe_allow_html=True
        )
        prepare_widget("_compare_address_a", "compare_address_a_value")
        st.text_input(
            "",
            key="_compare_address_a",
            on_change=save_widget_value,
            args=("_compare_address_a", "compare_address_a_value")
        )
        address_a = st.session_state["compare_address_a_value"]

    with control_col2:
        st.markdown(
            f"<div style='font-size:{COMPARE_ADDRESS_LABEL_FONT_SIZE}px;'>Address B</div>",
            unsafe_allow_html=True
        )
        prepare_widget("_compare_address_b", "compare_address_b_value")
        st.text_input(
            "",
            key="_compare_address_b",
            on_change=save_widget_value,
            args=("_compare_address_b", "compare_address_b_value")
        )
        address_b = st.session_state["compare_address_b_value"]

    slider_col1, slider_col2 = st.columns(2)

    with slider_col1:
        st.markdown(
            f"<div style='font-size:{COMPARE_SLIDER_LABEL_FONT_SIZE}px;font-weight:400;'>Radius (km)</div>",
            unsafe_allow_html=True
        )
        prepare_widget("_compare_radius_km", "compare_radius_km_value")
        st.slider(
            label="",
            min_value=0.5,
            max_value=10.0,
            step=0.5,
            key="_compare_radius_km",
            on_change=save_widget_value,
            args=("_compare_radius_km", "compare_radius_km_value")
        )
        radius_km = st.session_state["compare_radius_km_value"]

    with slider_col2:
        st.markdown(
            f"<div style='font-size:{COMPARE_SLIDER_LABEL_FONT_SIZE}px;font-weight:400;'>Min DA overlap (0% = intersection only)</div>",
            unsafe_allow_html=True
        )
        prepare_widget("_compare_overlap_pct", "compare_overlap_pct_value")
        st.slider(
            label="",
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
            "Metric": "Population Density",
            "Address A": comparison_value("Population Density", metrics_a["population_density"]),
            "Address B": comparison_value("Population Density", metrics_b["population_density"]),
            "Difference": comparison_difference("Population Density", metrics_a["population_density"], metrics_b["population_density"]),
        },
        {
            "Metric": "Household Density",
            "Address A": comparison_value("Household Density", metrics_a["household_density"]),
            "Address B": comparison_value("Household Density", metrics_b["household_density"]),
            "Difference": comparison_difference("Household Density", metrics_a["household_density"], metrics_b["household_density"]),
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


def show_batch_processor_view():
    st.title("Batch CSV or XLS")

    st.markdown(
        "Upload a CSV, XLS, or XLSX file. The first row must contain headers. "
        "If `latitude` and/or `longitude` are blank, the app will try ArcGIS geocoding using an address column."
    )

    uploaded_file = st.file_uploader(
        "Upload address file",
        type=["csv", "xls", "xlsx"]
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        radius_km = st.number_input(
            "Radius (km)",
            min_value=0.5,
            max_value=10.0,
            value=1.0,
            step=0.5
        )

    with col2:
        min_overlap_pct = st.number_input(
            "Min DA overlap %",
            min_value=0,
            max_value=50,
            value=5,
            step=1
        )

    with col3:
        geocode_delay_seconds = st.number_input(
            "Geocode wait seconds",
            min_value=0.25,
            max_value=10.0,
            value=1.25,
            step=0.25
        )

    with col4:
        geocode_max_retries = st.number_input(
            "Geocode retries",
            min_value=1,
            max_value=5,
            value=3,
            step=1
        )

    if uploaded_file is None:
        st.info("Upload a CSV, XLS, or XLSX file to begin.")
        return

    try:
        input_df = read_uploaded_table(uploaded_file)
    except Exception as exc:
        st.error(f"Could not read uploaded file: {exc}")
        return

    st.write(f"Rows detected: {len(input_df):,}")
    st.write("Columns detected:")
    st.write(list(input_df.columns))

    lat_col = find_first_case_insensitive_column(input_df, ["latitude", "lat"])
    lon_col = find_first_case_insensitive_column(input_df, ["longitude", "lon", "long"])
    address_col = find_first_case_insensitive_column(
        input_df,
        ["address", "store_address", "full_address", "location_address", "addr"]
    )

    if lat_col is None or lon_col is None:
        if address_col is None:
            st.warning(
                "Latitude/longitude columns were not found, and no address column was found. "
                "Rows without coordinates cannot be geocoded."
            )
        else:
            st.info(
                f"Latitude/longitude not fully found. Missing coordinates will be geocoded using `{address_col}`."
            )
    else:
        st.success(f"Using latitude column `{lat_col}` and longitude column `{lon_col}`.")

    if st.button("Process uploaded file"):
        with st.spinner("Processing batch file..."):
            output_df = process_batch_file(
                input_df=input_df,
                radius_km=float(radius_km),
                min_overlap_pct=int(min_overlap_pct),
                geocode_delay_seconds=float(geocode_delay_seconds),
                geocode_max_retries=int(geocode_max_retries),
            )

        st.success("Batch processing complete.")
        st.dataframe(output_df.head(50), use_container_width=True)

        csv_bytes = output_df.to_csv(index=False).encode("utf-8-sig")

        st.download_button(
            label="Download enriched CSV",
            data=csv_bytes,
            file_name="batch_catchment_census_output.csv",
            mime="text/csv",
        )


view_mode = st.radio(
    "View",
    ["Single Address", "Compare Two Addresses", "Batch CSV or XLS"],
    horizontal=True
)

if view_mode == "Single Address":
    show_single_address_view()
elif view_mode == "Compare Two Addresses":
    show_comparison_view()
else:
    show_batch_processor_view()
