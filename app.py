import json
import re
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd
import streamlit as st

# -------------------------------------------------------------------
# App setup
# -------------------------------------------------------------------
st.set_page_config(
    page_title="Links Explorer",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BASE_DIR = Path(__file__).resolve().parent


def first_existing(*paths: Path) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


DATA_PATH = first_existing(
    BASE_DIR / "data" / "links.json",
    BASE_DIR / "links.json",
)
META_PATH = first_existing(
    BASE_DIR / "data" / "metadata.json",
    BASE_DIR / "metadata.json",
)


# -------------------------------------------------------------------
# Metadata helpers
# -------------------------------------------------------------------
def canonical_url(url: str) -> str:
    """Normalize URL keys so harmless slash/case differences do not break metadata lookup."""
    value = str(url or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    return f"{scheme}://{netloc}{path}" + (f"?{parsed.query}" if parsed.query else "")


def fallback_title(url: str) -> str:
    path = unquote(urlparse(url).path).rstrip("/")
    slug = path.split("/")[-1] if path else urlparse(url).netloc
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()
    return slug.title() if slug else urlparse(url).netloc


def build_metadata_index(raw_metadata):
    """Index metadata.json by both the original URL and a normalized URL."""
    if not isinstance(raw_metadata, dict):
        return {}
    index = {}
    for key, value in raw_metadata.items():
        if not isinstance(value, dict):
            continue
        url = str(key or "").strip()
        if url:
            index[url] = value
            normalized = canonical_url(url)
            if normalized:
                index[normalized] = value
        page_url = value.get("playback", {}).get("page_url") if isinstance(value.get("playback"), dict) else None
        if page_url:
            index[str(page_url).strip()] = value
            normalized = canonical_url(page_url)
            if normalized:
                index[normalized] = value
    return index


def metadata_for_url(url: str):
    if not isinstance(metadata, dict):
        return {}
    return (
        metadata.get(url)
        or metadata.get(str(url).strip())
        or metadata.get(canonical_url(url))
        or {}
    )

# -------------------------------------------------------------------
# Data
# -------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_json(path: str, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


@st.cache_data(show_spinner=False)
def prepare_data(data):
    rows = []
    for item in data if isinstance(data, list) else []:
        row = dict(item)

        for field in ("stars", "categories", "positions"):
            value = row.get(field, [])
            if not isinstance(value, list):
                value = [value] if value else []
            row[field] = [
                str(x).strip() for x in value if str(x).strip()
            ]

        row["_stars"] = " | ".join(row["stars"]).lower()
        row["_categories"] = " | ".join(row["categories"]).lower()
        row["_positions"] = " | ".join(row["positions"]).lower()
        row["_tags"] = str(row.get("general_tags", "") or "").lower()
        row["_studio"] = str(row.get("studio", "") or "")
        row["_core_cat"] = str(row.get("core_cat", "") or "")
        row["_url"] = str(row.get("main_link", "") or "")

        try:
            row["duration_num"] = float(row.get("duration", 0) or 0)
        except (TypeError, ValueError):
            row["duration_num"] = 0.0

        try:
            row["rate_num"] = float(row.get("rate", 0) or 0)
        except (TypeError, ValueError):
            row["rate_num"] = 0.0

        rows.append(row)

    return pd.DataFrame(rows)


raw_data = load_json(str(DATA_PATH), [])
metadata_raw = load_json(str(META_PATH), {})
metadata = build_metadata_index(metadata_raw)
df = prepare_data(raw_data)

if df.empty:
    st.error(f"No data found. Expected a JSON file at `{DATA_PATH}`.")
    st.stop()

metadata_entries = len(metadata_raw) if isinstance(metadata_raw, dict) else 0
metadata_matches = sum(
    1 for url in df["_url"]
    if metadata_for_url(str(url))
)

if metadata_entries == 0:
    st.sidebar.error(f"metadata.json not found or empty: `{META_PATH}`")
elif metadata_matches == 0:
    st.sidebar.warning(
        f"metadata.json loaded ({metadata_entries:,} entries), but none match the URLs in links.json."
    )


def unique_values(column):
    values = set()
    for value in df[column].dropna():
        if isinstance(value, list):
            values.update(str(x).strip() for x in value if str(x).strip())
    return sorted(values, key=str.casefold)


core_categories = sorted(
    {x for x in df["_core_cat"] if x},
    key=str.casefold,
)
studios = sorted(
    {x for x in df["_studio"] if x},
    key=str.casefold,
)
actors = unique_values("stars")
categories = unique_values("categories")
positions = unique_values("positions")

min_duration = int(df["duration_num"].min())
max_duration = max(int(df["duration_num"].max()), min_duration + 1)

# -------------------------------------------------------------------
# Compact styling
# -------------------------------------------------------------------
st.markdown(
    """
    <style>
        .block-container {
            max-width: 1920px;
            padding-top: 3rem;
            padding-bottom: 3rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }

        [data-testid="stSidebar"] {
            width: 300px;
        }

        [data-testid="stSidebarContent"] {
            padding-top: 1rem;
        }

        .card-title {
            font-size: 1.10rem;
            font-weight: 650;
            line-height: 1.3;
            margin-bottom: .35rem;
        }

        .muted {
            color: var(--text-color-secondary);
            font-size: 1rem;
        }

        div[data-testid="stHorizontalBlock"] {
            gap: 1rem;
        }

        .thumb-placeholder {
            aspect-ratio: 16/10;
            min-height: 130px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 9px;
            background: rgba(128,128,128,.10);
            color: var(--text-color-secondary);
            font-size: .8rem;
        }

        @media (max-width: 800px) {
            .block-container {
                padding-left: 1rem;
                padding-right: 1rem;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------------------------------------------------------
# App / filter sidebar
# -------------------------------------------------------------------
st.sidebar.markdown("# 🎬 Links Explorer")
count_left, count_right = st.sidebar.columns(2)
with count_left:
    st.caption(f"Total: {len(df):,}")
with count_right:
    visible_count_placeholder = st.empty()

# -------------------------------------------------------------------
# Filters — persistent left sidebar
# -------------------------------------------------------------------
st.sidebar.markdown("## 🔎 Filters")


def reset_filters():
    for key in (
        "search", "tag_search", "duration_range", "rating_range",
        "selected_core", "selected_studio", "selected_actors",
        "selected_categories", "selected_positions",
        "sort_by", "sort_order",
    ):
        st.session_state.pop(key, None)


st.sidebar.button(
    "Reset filters",
    type="secondary",
    width='stretch',
    on_click=reset_filters,
)

# -------------------------------------------------------------------
# Sidebar sorting
# -------------------------------------------------------------------
st.sidebar.markdown("### Sort")
sort_by = st.sidebar.selectbox(
    "Sort by",
    ["Default", "Rating", "Duration", "Studio", "Core category"],
    key="sort_by",
)

if sort_by in ("Rating", "Duration"):
    sort_order = st.sidebar.segmented_control(
        "Order",
        ["Highest", "Lowest"],
        default="Highest",
        key="sort_order",
    )
else:
    sort_order = "Highest"

search = st.sidebar.text_input(
    "Search",
    placeholder="Title, actor, studio, category, tag…",
    key="search",
)
tag_search = st.sidebar.text_input(
    "Tags",
    placeholder="Tags: comma-separated",
    key="tag_search",
)

duration_range = st.sidebar.slider(
    "Duration (minutes)",
    min_duration,
    max_duration,
    (min_duration+1, max_duration),
    key="duration_range",
)
rating_range = st.sidebar.slider(
    "Rating",
    1,
    10,
    (1, 10),
    step=1,
    key="rating_range",
)

selected_core = st.sidebar.multiselect(
    "Core Categories", core_categories, placeholder="Any", key="selected_core"
)
selected_studio = st.sidebar.multiselect(
    "Studios", studios, placeholder="Any", key="selected_studio"
)
selected_actors = st.sidebar.multiselect(
    "Actors", actors, placeholder="Any", key="selected_actors"
)
selected_categories = st.sidebar.multiselect(
    "Categories", categories, placeholder="Any", key="selected_categories"
)
selected_positions = st.sidebar.multiselect(
    "Positions", positions, placeholder="Any", key="selected_positions"
)


# -------------------------------------------------------------------
# Filtering
# -------------------------------------------------------------------
mask = (
    df["duration_num"].between(*duration_range)
    & df["rate_num"].between(*rating_range)
)

if selected_core:
    mask &= df["_core_cat"].isin(selected_core)

if selected_studio:
    mask &= df["_studio"].isin(selected_studio)

if selected_actors:
    actor_terms = [x.casefold() for x in selected_actors]
    mask &= df["_stars"].apply(
        lambda s: any(x in s for x in actor_terms)
    )

if selected_categories:
    category_terms = [x.casefold() for x in selected_categories]
    mask &= df["_categories"].apply(
        lambda s: any(x in s for x in category_terms)
    )

if selected_positions:
    position_terms = [x.casefold() for x in selected_positions]
    mask &= df["_positions"].apply(
        lambda s: any(x in s for x in position_terms)
    )

if tag_search.strip():
    tag_terms = [
        x.strip().casefold()
        for x in tag_search.split(",")
        if x.strip()
    ]
    mask &= df["_tags"].apply(
        lambda s: all(term in s for term in tag_terms)
    )

if search.strip():
    terms = [x for x in search.casefold().split() if x]

    def searchable(row):
        meta = metadata_for_url(str(row.get("_url", "")))
        title = str(meta.get("title") or "")
        text = " ".join(
            [
                title,
                str(row.get("_stars", "")),
                str(row.get("_categories", "")),
                str(row.get("_positions", "")),
                str(row.get("_studio", "")),
                str(row.get("_core_cat", "")),
                str(row.get("_tags", "")),
            ]
        )
        return all(term in text for term in terms)

    mask &= df.apply(searchable, axis=1)

result = df.loc[mask].copy()

with visible_count_placeholder:
    st.caption(f"Visible: {len(result):,}")
# -------------------------------------------------------------------
# Sort results
# -------------------------------------------------------------------
if sort_by == "Rating":
    result = result.sort_values(
        "rate_num", ascending=(sort_order == "Lowest")
    )
elif sort_by == "Duration":
    result = result.sort_values(
        "duration_num", ascending=(sort_order == "Lowest")
    )
elif sort_by == "Studio":
    result = result.sort_values("_studio", key=lambda s: s.str.casefold())
elif sort_by == "Core category":
    result = result.sort_values("_core_cat", key=lambda s: s.str.casefold())

# -------------------------------------------------------------------
# Cards — two-column result grid, no pagination
# -------------------------------------------------------------------
if result.empty:
    st.info("No links match the current filters.")
else:
    rows = result.to_dict("records")
    for i in range(0, len(rows), 2):
        card_row = rows[i:i + 2]
        cols = st.columns(2, gap="medium")

        for col, row in zip(cols, card_row):
            with col:
                with st.expander(label="Link",expanded=True):
                    with st.container(height=680):
                        url = str(row.get("_url", "") or "").strip()
                        meta = metadata_for_url(url)

                        # metadata.json is the only source for title and thumbnail.
                        title = str(meta.get("title") or "").strip() or fallback_title(url)
                        thumbnail = str(meta.get("thumbnail") or "").strip()

                        stars = list(row.get("stars", []) or [])
                        cats = list(row.get("categories", []) or [])
                        positions_list = list(row.get("positions", []) or [])

                        # st.markdown('<div class="card">', unsafe_allow_html=True)

                        if thumbnail:
                            st.image(thumbnail, width='stretch')
                        else:
                            st.markdown(
                                '<div class="thumb-placeholder">No thumbnail in metadata.json</div>',
                                unsafe_allow_html=True,
                            )

                        st.markdown(
                            f'<div class="card-title">{escape(title)}</div>',
                            unsafe_allow_html=True,
                        )

                        duration = row.get("duration", "?")
                        rating = row.get("rate", "?")
                        studio = row.get("studio", "") or "—"
                        core = row.get("core_cat", "") or "—"

                        st.markdown(
                            f'<div class="muted">⏱ {duration} min &nbsp; · &nbsp; ⭐ {rating}'
                            f' &nbsp; · &nbsp; {studio} &nbsp; · &nbsp; {core} &nbsp; · &nbsp;</div>',
                            unsafe_allow_html=True,
                        )
            
                        if stars:
                            st.write("**Stars:** " + ", ".join(stars))
                        if cats:
                            st.write("**Categories:** " + ", ".join(cats))
                        if positions_list:
                            st.write("**Positions:** " + ", ".join(positions_list))
                        tags = row.get("general_tags", "")
                        if tags:
                            st.write("**Tags:** " + str(tags))

                        if url:
                            st.link_button(
                                "Open source ↗",
                                url,
                                type="secondary",
                                width='stretch',
                            )

                        st.markdown('</div>', unsafe_allow_html=True)
