from pathlib import Path
import pandas as pd
import streamlit as st
import os

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="Verify Uniformity of Data",
    page_icon="🔎",
    layout="wide"
)
st.markdown("# Verify Data Uniformity")


# ============================================================
# FILE CONFIG
# ============================================================
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"

FILE_NAMES = ["master_links.xlsx","links.xlsx"]
SELECTED_FILE_NAME = st.selectbox(f"Choose File",FILE_NAMES,index=None,placeholder="Choose .xlsx File",width="stretch")


# ============================================================
# MAIN UI
# ============================================================
if SELECTED_FILE_NAME is not None:
    #set file path with the name
    SELECTED_FILE_PATH = DATA_DIR / SELECTED_FILE_NAME
    #check if file path exists
    if os.path.exists(SELECTED_FILE_PATH):

        try:
            df = pd.read_excel(SELECTED_FILE_PATH)

        except Exception as e:
            st.error(f"Could not load {SELECTED_FILE_NAME}")
            st.exception(e)
            st.stop()


        # ============================================================
        # SELECT COLUMNS
        # ============================================================
        # Exclude columns that were excluded in the original program
        excluded_columns = [
            "main_link"
        ]

        header = []
        for column in df.columns:
            if column not in excluded_columns:
                header.append(column)


        # ============================================================
        # SIDEBAR
        # ============================================================
        st.sidebar.header("Filters")

        selected_column = st.sidebar.selectbox(
            "Select Column",
            header
        )

        text_search = st.sidebar.text_input(
            "Search",
            placeholder="e.g. English"
        )

        top_n = st.sidebar.slider(
            "Number of Top Values",
            min_value=0,
            max_value=len(df[selected_column]),
            value=round(len(df[selected_column])/8),
            step=10
        )


        # ============================================================
        # PROCESS SELECTED COLUMN
        # ============================================================
        selected_data = df[selected_column]

        # Split comma-separated values
        words = (
            selected_data
            .dropna()
            .astype(str)
            .str.split(",")
            .explode()
            .str.strip()
        )

        # Remove empty values
        words = words[words != ""]

        # Frequency
        freq = (
            words
            .value_counts()
            .sort_values(ascending=False)
        )


        # ============================================================
        # DATASET INFORMATION
        # ============================================================
        with st.expander("Dataset Information", expanded=False):

            info_df = pd.DataFrame({
                "Column": df.columns,
                "Data Type": df.dtypes.astype(str),
                "Non-Null Count": df.notna().sum().values,
                "Null Count": df.isna().sum().values,
            })

            st.dataframe(
                info_df,
                width="stretch",
                hide_index=True
            )
        # ============================================================
        # DATASET OVERVIEW & COLUMN OVERVIEW
        # ============================================================
        data_overview, column_overview = st.columns(2)

        with data_overview:
            st.markdown("#### Data Overview")
            data_overview_1, data_overview_2 = st.columns(2)

            with data_overview_1:
                st.metric(
                    "Total Rows",
                    len(df)
                )

            with data_overview_2:
                st.metric(
                    "Total Columns",
                    len(df.columns)
                )
        
            data_overview_3, data_overview_4 = st.columns(2)

            with data_overview_3:
                st.metric(
                    "Missing Values",
                    int(df.isna().sum().sum())
                )

            with data_overview_4:
                st.metric(
                    "Duplicate Rows",
                    int(df.duplicated().sum())
                )

        with column_overview:
            st.markdown("#### Column Overview")
            column_overview_1, column_overview_2 = st.columns(2)

            with column_overview_1:
                st.metric(
                    "Total Rows",
                    len(selected_data)
                )

            with column_overview_2:
                st.metric(
                    "Unique Word Values",
                    len(freq)
                )
            
            column_overview_3, column_overview_4 = st.columns(2)

            with column_overview_3:
                st.metric(
                    "Not Null Values",
                    int(selected_data.notna().sum())
                )

            with column_overview_4:
                st.metric(
                    "Null Values",
                    int(selected_data.isna().sum())
                )
        
        # ============================================================
        # SEARCH
        # ============================================================
        with st.expander("Search Results",expanded=False):

            search_results = freq[
                freq.index.str.contains(
                    text_search,
                    case=False,
                    na=False
                )
            ]


            if len(search_results) == 0:
                st.warning(
                    f"No values found containing '{text_search}'."
                )

            else:

                search_df = (
                    search_results
                    .rename("Count")
                    .reset_index()
                    .rename(columns={"index": selected_column})
                )

                st.dataframe(
                    search_df,
                    width='stretch',
                    hide_index=True
                )


        # ============================================================
        # FREQUENCY TABLE + CHART
        # ============================================================


        # ------------------------------------------------------------
        # TABLE
        # ------------------------------------------------------------

        #     st.subheader("📋 Value Frequency")

        #     display_df = (
        #         freq
        #         .head(top_n)
        #         .rename("Count")
        #         .reset_index()
        #         .rename(columns={"index": selected_column})
        #     )

        #     st.dataframe(
        #         display_df,
        #         width='stretch',
        #         hide_index=True
        #     )


        # ------------------------------------------------------------
        # CHART
        # ------------------------------------------------------------
        with st.expander("Frequency Distribution",expanded=False):

            chart_df = (
                freq
                .head(top_n)
                .rename("Count")
            )

            st.bar_chart(
                chart_df,
                horizontal=True,
                width='stretch',
                sort="-Count"
            )


        # ============================================================
        # ALL VALUES
        # ============================================================
        with st.expander("View all unique values"):

            all_values_df = (
                freq
                .rename("Count")
                .reset_index()
                .rename(columns={"index": selected_column})
            )

            st.dataframe(
                all_values_df,
                width='stretch',
                hide_index=False
            )


        # ============================================================
        # DATA PREVIEW
        # ============================================================
        head_rows = 50
        with st.expander(f"Original Data - First {head_rows} Rows"):

            st.dataframe(
                df.head(head_rows),
                width='stretch',
                hide_index=True
            )


        # ============================================================
        # FOOTER
        # ============================================================

        st.divider()

    else:
        st.caption("File cannot be accessed")
else:
    st.caption("No File Selected")