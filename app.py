import streamlit as st
import pandas as pd
import io
import os
import cloudinary
import cloudinary.uploader
from datetime import datetime
from supabase import create_client, Client, ClientOptions
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 1. Configuration & Secrets
# ==========================================
st.set_page_config(
    page_title="IPCS Drawing Management",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Refined Professional Compact UI
st.markdown("""
    <style>
        /* Adjust Top Padding to prevent clipping with Streamlit header */
        .block-container {
            padding-top: 3.5rem !important;
            padding-bottom: 1rem !important;
        }
        
        /* Professional Compact Title */
        h1 {
            font-size: 1.8rem !important;
            font-weight: 700 !important;
            margin-bottom: 0.8rem !important;
            color: #1e293b;
        }
        
        .main {
            background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
        }
        
        /* Dashboard KPI Cards - Compact with narrow line spacing */
        [data-testid="stMetric"] {
            background: rgba(255, 255, 255, 0.7);
            padding: 8px 12px !important;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
            backdrop-filter: blur(4px);
            border: 1px solid rgba(255, 255, 255, 0.3);
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.7rem !important;
            color: #64748b !important;
            margin-bottom: -10px !important;
            line-height: 1 !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.3rem !important;
            font-weight: 700 !important;
            color: #0f172a !important;
            line-height: 1.1 !important;
        }
        
        /* Sidebar Polish */
        .sidebar .sidebar-content {
            background: #f1f5f9;
        }
        
        .stButton>button {
            border-radius: 4px;
            font-weight: 600;
        }
    </style>
""", unsafe_allow_html=True)

# Initialize Secrets Helper
def get_secret(key, default=None):
    """Helper to get secret from st.secrets or os.environ"""
    try:
        return st.secrets[key]
    except:
        return os.environ.get(key, default)

# ==========================================
# 2. Data Logic & Caching
# ==========================================
@st.cache_resource
def get_supabase() -> Client:
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_KEY")
    if not url or not key:
        st.error("Missing Supabase configuration (SUPABASE_URL/KEY)")
        st.stop()
    options = ClientOptions(schema="public")
    return create_client(url, key, options=options)

# Configure Cloudinary
c_name = get_secret("CLOUDINARY_NAME")
c_key = get_secret("CLOUDINARY_API_KEY")
c_secret = get_secret("CLOUDINARY_API_SECRET")

if all([c_name, c_key, c_secret]):
    cloudinary.config(cloud_name=c_name, api_key=c_key, api_secret=c_secret, secure=True)

# Constants
TABLE_ALL = "dwg_iso"
TABLE_LATEST = "dwg_latest"

@st.cache_data(ttl=600, show_spinner=False)
def get_cached_stats():
    supabase = get_supabase()
    total_res = supabase.table(TABLE_ALL).select("id", count="exact").limit(1).execute()
    c01_res   = supabase.table(TABLE_ALL).select("id", count="exact").eq("revision", "C01").execute()
    c01a_res  = supabase.table(TABLE_ALL).select("id", count="exact").eq("revision", "C01A").execute()
    c01b_res  = supabase.table(TABLE_ALL).select("id", count="exact").eq("revision", "C01B").execute()
    return {
        "Total": total_res.count if hasattr(total_res, 'count') else 0,
        "C01": c01_res.count if hasattr(c01_res, 'count') else 0,
        "C01A": c01a_res.count if hasattr(c01a_res, 'count') else 0,
        "C01B": c01b_res.count if hasattr(c01b_res, 'count') else 0
    }

@st.cache_data(ttl=300, show_spinner="Fetching...")
def fetch_data(search_query="", area="All", system="All", status="All", limit=150, offset=0):
    supabase = get_supabase()
    target_table = TABLE_LATEST if status == "All" else TABLE_ALL
    query = supabase.table(target_table).select("*", count="exact")
    if search_query:
        query = query.or_(f"drawing_no.ilike.%{search_query}%,line_no.ilike.%{search_query}%,title.ilike.%{search_query}%")
    if area != "All": query = query.eq("area", area)
    if system != "All": query = query.eq("system", system)
    if status != "All": query = query.eq("revision", status)
    res = query.order("drawing_no").range(offset, offset + limit - 1).execute()
    return res.data, res.count

def get_cloudinary_url(file_key):
    if not file_key: return None
    if file_key.startswith("http"): return file_key
    return cloudinary.utils.cloudinary_url(file_key, resource_type="image", secure=True)[0]

# ==========================================
# 3. UI Components
# ==========================================
def main():
    st.title("🏗️ IPCS Drawing Management System")

    # --- Sidebar Filters (Restored as requested) ---
    with st.sidebar:
        st.header("Search & Filters")
        search_query = st.text_input("🔍 Keyword Search", placeholder="Drawing No, Title...", label_visibility="visible")
        area_filter = st.selectbox("Area", ["All", "MB", "YARD", "YD BLDG"])
        system_filter = st.selectbox("System", ["All", "AS", "ATM", "CCW", "CD", "DW", "FG", "FGH", "FO", "FW", "GT MISC", "HP", "HW", "IA", "LO", "LP", "N2", "PW", "RW", "SA", "SS", "ST MISC", "SW", "WWT"])
        status_filter = st.selectbox("Revision", ["All", "C01", "C01A", "C01B"])
        st.markdown("---")
        st.info("IPCS Cloud draws data from Supabase.")

    # --- KPI Dashboard ---
    stats = get_cached_stats()
    cols = st.columns(4)
    cols[0].metric("Total Drawings", f"{stats['Total']:,}")
    cols[1].metric("Revision C01", f"{stats['C01']:,}")
    cols[2].metric("Revision C01A", f"{stats['C01A']:,}")
    cols[3].metric("Revision C01B", f"{stats['C01B']:,}")

    # --- Main Content Tabs ---
    tab_list, tab_upload, tab_export = st.tabs(["📋 Drawing List", "📤 Upload Data", "📥 Export & Reports"])

    with tab_list:
        per_page = 50
        if 'page' not in st.session_state: st.session_state.page = 1
            
        data, total_count = fetch_data(search_query, area_filter, system_filter, status_filter, limit=per_page, offset=(st.session_state.page - 1) * per_page)
        
        if data:
            df = pd.DataFrame(data)
            display_cols = {"drawing_no": "Drawing No.", "revision": "Rev.", "area": "Area", "system": "System", "title": "Drawing Title", "issued_date": "Issued Date"}
            available_cols = [c for c in display_cols.keys() if c in df.columns]
            
            selected_rows = st.dataframe(df[available_cols].rename(columns=display_cols), use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
            
            if selected_rows.selection.rows:
                idx = selected_rows.selection.rows[0]
                row = df.iloc[idx]
                st.info(f"📍 Selected: {row['drawing_no']}")
                file_link = str(row.get('file_link', '')).strip()
                if file_link:
                    cloud_url = get_cloudinary_url(file_link)
                    st.link_button("📂 View Drawing (Cloudinary)", cloud_url, type="primary")

            # Pagination
            total_pages = (total_count + per_page - 1) // per_page
            p_cols = st.columns([1, 2, 1])
            if st.session_state.page > 1:
                if p_cols[0].button("Previous"):
                    st.session_state.page -= 1
                    st.rerun()
            if st.session_state.page < total_pages:
                if p_cols[2].button("Next"):
                    st.session_state.page += 1
                    st.rerun()
            p_cols[1].markdown(f"<center><small>Page {st.session_state.page} of {total_pages} ({total_count} records)</small></center>", unsafe_allow_html=True)
        else:
            st.warning("No data found.")

    with tab_upload:
        st.subheader("Import Excel Data")
        uploaded_file = st.file_uploader("Choose an Excel file", type=["xlsx", "xls"])
        if uploaded_file is not None and st.button("Process & Upload"):
            with st.spinner("Processing..."):
                try:
                    df_up = pd.read_excel(uploaded_file)
                    df_up.columns = [str(c).lower().strip() for c in df_up.columns]
                    records = []
                    for _, r in df_up.iterrows():
                        dr_no = str(r.get("drawing_no", r.get("drawing_n", ""))).strip()
                        if dr_no:
                            records.append({"drawing_no": dr_no, "line_no": str(r.get("line_no", "")).strip(), "system": str(r.get("system", "")).strip(), "area": str(r.get("area", "")).strip(), "bore": str(r.get("bore", "")).strip(), "title": str(r.get("title", "")).strip(), "revision": str(r.get("revision", "")).strip(), "file_link": str(r.get("file_link", "")).strip()})
                    if records:
                        supabase = get_supabase()
                        for i in range(0, len(records), 1000):
                            supabase.table(TABLE_ALL).upsert(records[i:i+1000], on_conflict="drawing_no,revision").execute()
                        st.success(f"Success: {len(records)} records.")
                except Exception as e: st.error(f"Error: {e}")

    with tab_export:
        st.subheader("Data Export")
        if st.button("Generate Excel Master List"):
            with st.spinner("Preparing..."):
                try:
                    supabase = get_supabase()
                    res = supabase.table(TABLE_ALL).select("*")
                    all_data = res.execute().data
                    if all_data:
                        export_df = pd.DataFrame(all_data)
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                            export_df.to_excel(writer, index=False, sheet_name='DrawingMaster')
                        st.download_button(label="Download Excel File", data=output.getvalue(), file_name=f"ISO_Master_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                except Exception as e: st.error(f"Failed: {e}")

if __name__ == "__main__":
    main()
