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

# Premium UI Styling
st.markdown("""
    <style>
        .main {
            background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
        }
        .stMetric {
            background: rgba(255, 255, 255, 0.7);
            padding: 15px;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(4px);
            border: 1px solid rgba(255, 255, 255, 0.3);
        }
        .stButton>button {
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.3s ease;
        }
        .stButton>button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 24px;
        }
        .stTabs [data-baseweb="tab"] {
            height: 50px;
            white-space: pre-wrap;
            background-color: transparent;
            border-radius: 4px;
            color: #64748b;
            font-weight: 500;
        }
        .stTabs [aria-selected="true"] {
            color: #2563eb !important;
            border-bottom: 2px solid #2563eb !important;
        }
    </style>
""", unsafe_allow_html=True)

# Initialize Supabase and Cloudinary
def get_secret(key, default=None):
    """Helper to get secret from st.secrets or os.environ"""
    try:
        return st.secrets[key]
    except:
        return os.environ.get(key, default)

def get_supabase() -> Client:
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_KEY")
    if not url or not key:
        st.error("Missing Supabase configuration (SUPABASE_URL/KEY)")
        st.stop()
    options = ClientOptions(schema="drawing")
    return create_client(url, key, options=options)

# Configure Cloudinary
c_name = get_secret("CLOUDINARY_NAME")
c_key = get_secret("CLOUDINARY_API_KEY")
c_secret = get_secret("CLOUDINARY_API_SECRET")

if all([c_name, c_key, c_secret]):
    cloudinary.config(
        cloud_name = c_name,
        api_key = c_key,
        api_secret = c_secret,
        secure = True
    )
else:
    st.warning("Cloudinary configuration incomplete. Media features may be limited.")

# Constants
TABLE_ALL = "dwg_iso"
TABLE_LATEST = "dwg_latest"

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
    options = ClientOptions(schema="drawing")
    return create_client(url, key, options=options)

@st.cache_data(ttl=600, show_spinner=False)
def get_cached_stats():
    """Cache statistics for 10 minutes to reduce DB load"""
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

@st.cache_data(ttl=300, show_spinner="Fetching drawing list...")
def fetch_data(search_query="", area="All", system="All", status="All", limit=150, offset=0):
    """Cache query results for 5 minutes"""
    supabase = get_supabase()
    target_table = TABLE_LATEST if status == "All" else TABLE_ALL
    
    query = supabase.table(target_table).select("*", count="exact")
    
    if search_query:
        # Optimization: prioritize exact match on drawing_no for performance
        query = query.or_(f"drawing_no.ilike.%{search_query}%,line_no.ilike.%{search_query}%,title.ilike.%{search_query}%")
    if area != "All":
        query = query.eq("area", area)
    if system != "All":
        query = query.eq("system", system)
    if status != "All":
        query = query.eq("revision", status)
        
    res = query.order("drawing_no").range(offset, offset + limit - 1).execute()
    return res.data, res.count

def get_cloudinary_url(file_key):
    """Generate optimized Cloudinary URL for PDF/Image streaming"""
    if not file_key: return None
    if file_key.startswith("http"): return file_key
    # Assuming file_key is public_id in Cloudinary
    return cloudinary.utils.cloudinary_url(file_key, resource_type="image", secure=True)[0]

def view_pdf_component(url):
    """Embed PDF viewer using an iframe for streaming-like experience"""
    st.markdown(f'<iframe src="{url}" width="100%" height="800px" style="border:none;"></iframe>', unsafe_allow_html=True)

# ==========================================
# 3. UI Components
# ==========================================
def main():
    st.title("🏗️ IPCS Drawing Management System")
    st.markdown("---")

    # --- Sidebar Filters ---
    with st.sidebar:
        st.header("Search & Filters")
        search_query = st.text_input("Search (No, Line, Title)", placeholder="Enter keywords...")
        
        area_options = ["All", "MB", "YARD", "YD BLDG"]
        area_filter = st.selectbox("Area", area_options)
        
        system_options = ["All", "AS", "ATM", "CCW", "CD", "DW", "FG", "FGH", "FO", "FW", "GT MISC", "HP", "HW", "IA", "LO", "LP", "N2", "PW", "RW", "SA", "SS", "ST MISC", "SW", "WWT"]
        system_filter = st.selectbox("System", system_options)
        
        status_options = ["All", "C01", "C01A", "C01B"]
        status_filter = st.selectbox("Revision Status", status_options)
        
        st.markdown("---")
        st.info("Cloud-synced Repository")

    # --- KPI Dashboard ---
    stats = get_cached_stats()
    cols = st.columns(4)
    cols[0].metric("Total Drawings", f"{stats['Total']:,}")
    cols[1].metric("Revision C01", f"{stats['C01']:,}")
    cols[2].metric("Revision C01A", f"{stats['C01A']:,}")
    cols[3].metric("Revision C01B", f"{stats['C01B']:,}")

    st.markdown("---")

    # --- Main Content Tabs ---
    tab_list, tab_upload, tab_export = st.tabs(["📋 Drawing List", "📤 Upload Data", "📥 Export & Reports"])

    with tab_list:
        # Pagination handling
        per_page = 50
        if 'page' not in st.session_state:
            st.session_state.page = 1
            
        data, total_count = fetch_data(search_query, area_filter, system_filter, status_filter, limit=per_page, offset=(st.session_state.page-1)*per_page)
        
        if data:
            df = pd.DataFrame(data)
            # Reorder and rename columns for readability
            display_cols = {
                "drawing_no": "Drawing No.",
                "revision": "Rev.",
                "area": "Area",
                "system": "System",
                "title": "Drawing Title",
                "issued_date": "Issued Date"
            }
            available_cols = [c for c in display_cols.keys() if c in df.columns]
            
            # Interactive Data Table with Selection
            selected_rows = st.dataframe(
                df[available_cols].rename(columns=display_cols),
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row"
            )
            
            # Action Panel for Selected Item
            if selected_rows.selection.rows:
                idx = selected_rows.selection.rows[0]
                row = df.iloc[idx]
                st.info(f"📍 Selected: {row['drawing_no']}")
                
                c1, c2 = st.columns(2)
                with c1:
                    file_link = str(row.get('file_link', '')).strip()
                    if file_link:
                        # Cloudinary PDF Streaming / Direct View
                        cloud_url = get_cloudinary_url(file_link)
                        st.markdown(f"[📂 Open Full Document]({cloud_url})")
                    else:
                        st.warning("No file link associated with this drawing.")
                
                with c2:
                    if st.button("🔄 Clear Selection"):
                        st.rerun()
            
            # Pagination UI
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
            p_cols[1].markdown(f"<center>Page {st.session_state.page} of {total_pages} ({total_count} records)</center>", unsafe_allow_html=True)
        else:
            st.warning("No data found for the given filters.")

    with tab_upload:
        st.subheader("Import Excel Data")
        uploaded_file = st.file_uploader("Choose an Excel file", type=["xlsx", "xls"])
        
        if uploaded_file is not None:
            if st.button("Process & Upload"):
                with st.spinner("Uploading to Supabase..."):
                    try:
                        df_up = pd.read_excel(uploaded_file)
                        df_up.columns = [str(c).lower().strip() for c in df_up.columns]
                        df_up = df_up.fillna("")
                        
                        records = []
                        for _, r in df_up.iterrows():
                            dr_no = str(r.get("drawing_no", r.get("drawing_n", ""))).strip()
                            if not dr_no: continue
                            records.append({
                                "drawing_no": dr_no,
                                "line_no":    str(r.get("line_no", "")).strip(),
                                "system":     str(r.get("system", "")).strip(),
                                "area":       str(r.get("area", "")).strip(),
                                "bore":       str(r.get("bore", "")).strip(),
                                "title":      str(r.get("title", "")).strip(),
                                "revision":   str(r.get("revision", "")).strip(),
                                "file_link":  str(r.get("file_link", "")).strip()
                            })
                        
                        if records:
                            supabase = get_supabase()
                            for i in range(0, len(records), 1000):
                                chunk = records[i:i+1000]
                                supabase.table(TABLE_ALL).upsert(chunk, on_conflict="drawing_no,revision").execute()
                            st.success(f"Successfully uploaded {len(records)} records!")
                        else:
                            st.error("No valid records found in the file.")
                    except Exception as e:
                        st.error(f"Error during upload: {e}")

    with tab_export:
        st.subheader("Data Export")
        if st.button("Generate Excel Master List"):
            with st.spinner("Preparing export..."):
                try:
                    supabase = get_supabase()
                    # For export, fetch everything matching filters
                    res = supabase.table(TABLE_ALL).select("*")
                    if search_query:
                        res = res.or_(f"drawing_no.ilike.%{search_query}%,line_no.ilike.%{search_query}%,title.ilike.%{search_query}%")
                    if area_filter != "All": res = res.eq("area", area_filter)
                    if status_filter != "All": res = res.eq("revision", status_filter)
                    
                    all_data = res.execute().data
                    if all_data:
                        export_df = pd.DataFrame(all_data)
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                            export_df.to_excel(writer, index=False, sheet_name='DrawingMaster')
                        processed_data = output.getvalue()
                        
                        st.download_button(
                            label="Download Excel File",
                            data=processed_data,
                            file_name=f"ISO_Drawing_Master_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    else:
                        st.warning("No data found to export.")
                except Exception as e:
                    st.error(f"Export failed: {e}")

if __name__ == "__main__":
    main()
