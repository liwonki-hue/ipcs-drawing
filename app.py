import os
import re
import io
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_file
from supabase import create_client, Client

# ── [.env 파일을 직접 읽어오는 로직] ──
def load_env_manually():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(base_dir, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"): continue
                if "=" in line:
                    try:
                        key, val = line.split("=", 1)
                        os.environ[key.strip()] = val.strip()
                    except: continue

load_env_manually()

template_dir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__, template_folder=template_dir, static_folder=template_dir)

from jinja2 import ChoiceLoader, FileSystemLoader
app.jinja_loader = ChoiceLoader([
    FileSystemLoader(template_dir),
    FileSystemLoader(os.path.join(template_dir, "templates"))
])
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
TABLE = "dwg_iso"

def get_client() -> Client:
    # Render 환경변수 우선 사용
    url = os.environ.get("SUPABASE_URL") or SUPABASE_URL
    key = os.environ.get("SUPABASE_KEY") or SUPABASE_KEY
    if not url or not key:
        raise ValueError("SUPABASE_URL, SUPABASE_KEY를 확인하세요.")
    return create_client(url, key)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/drawings")
def get_drawings():
    try:
        search = request.args.get("search", "").strip()
        area = request.args.get("area", "")
        system = request.args.get("system", "")
        status = request.args.get("status", "")
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 150))
        offset = (page - 1) * per_page

        supabase = get_client()
        target_table = "dwg_latest" if not status else TABLE
        query = supabase.table(target_table).select("*", count="exact")
        
        if search:
            query = query.or_(f"drawing_no.ilike.%{search}%,line_no.ilike.%{search}%,title.ilike.%{search}%")
        if area: query = query.eq("area", area)
        if system: query = query.eq("system", system)
        if status: query = query.eq("revision", status)

        res = query.order("drawing_no").range(offset, offset + per_page - 1).execute()
        return jsonify({"data": res.data, "total": res.count, "page": page})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stats")
def get_stats():
    try:
        supabase = get_client()
        total_res = supabase.table(TABLE).select("id", count="exact").limit(1).execute()
        c01_res   = supabase.table(TABLE).select("id", count="exact").eq("revision", "C01").execute()
        c01a_res  = supabase.table(TABLE).select("id", count="exact").eq("revision", "C01A").execute()
        c01b_res  = supabase.table(TABLE).select("id", count="exact").eq("revision", "C01B").execute()
        return jsonify({
            "total": total_res.count if hasattr(total_res, 'count') else 0, 
            "C01":   c01_res.count if hasattr(c01_res, 'count') else 0,
            "C01A":  c01a_res.count if hasattr(c01a_res, 'count') else 0,
            "C01B":  c01b_res.count if hasattr(c01b_res, 'count') else 0
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/filters")
def get_filters():
    return jsonify({
        "areas": ["MB", "YARD", "YD BLDG"],
        "systems": ["AS", "ATM", "CCW", "CD", "DW", "FG", "FGH", "FO", "FW", "GT MISC", "HP", "HW", "IA", "LO", "LP", "N2", "PW", "RW", "SA", "SS", "ST MISC", "SW", "WWT"],
        "statuses": ["C01", "C01A", "C01B"]
    })

@app.route("/api/upload", methods=["POST"])
def upload_excel():
    try:
        file = request.files["file"]
        if not file: return jsonify({"error": "No file shared"}), 400
        df = pd.read_excel(io.BytesIO(file.read()), sheet_name=0)
        df.columns = [str(c).lower().strip() for c in df.columns]
        df = df.fillna("")
        records = df.to_dict("records")
        supabase = get_client()
        batch = []
        for r in records:
            dr_no = str(r.get("drawing_no", r.get("drawing_n", ""))).strip()
            if not dr_no: continue
            batch.append({
                "drawing_no": dr_no,
                "line_no":    str(r.get("line_no", "")).strip(),
                "system":     str(r.get("system", "")).strip(),
                "area":       str(r.get("area", "")).strip(),
                "bore":       str(r.get("bore", "")).strip(),
                "title":      str(r.get("title", "")).strip(),
                "revision":   str(r.get("revision", "")).strip(),
                "file_link":  str(r.get("file_link", "")).strip()
            })
        inserted_count = 0
        if batch:
            for i in range(0, len(batch), 1000):
                chunk = batch[i:i+1000]
                supabase.table(TABLE).upsert(chunk, on_conflict="drawing_no,revision").execute()
                inserted_count += len(chunk)
        return jsonify({"success": True, "inserted": inserted_count, "processed": len(batch)})
    except Exception as e:
        print(f"UPLOAD ERROR: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/export")
def export_excel():
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "")
    try:
        from concurrent.futures import ThreadPoolExecutor
        supabase = get_client()
        cols = "area,system,drawing_no,line_no,title,revision,issued_date,bore"
        count_res = supabase.table(TABLE).select("id", count="exact").limit(1).execute()
        total_count = count_res.count if hasattr(count_res, 'count') else 0
        page_size = 1000
        offsets = list(range(0, total_count, page_size))
        def fetch_batch(offset):
            q = supabase.table(TABLE).select(cols)
            if search: q = q.or_(f"drawing_no.ilike.%{search}%,line_no.ilike.%{search}%,title.ilike.%{search}%")
            if status: q = q.eq("revision", status)
            return q.order("drawing_no").range(offset, offset + page_size - 1).execute().data
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(fetch_batch, offsets))
        all_data = [item for sublist in results for item in sublist]
        if not all_data: return jsonify({"error": "No data to export"}), 404
        df = pd.DataFrame(all_data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='DrawingMaster')
        output.seek(0)
        filename = f"ISO_Drawing_Master_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return send_file(output, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        return jsonify({"error": f"Export failed: {str(e)}"}), 500

@app.route('/api/print')
def print_drawings():
    try:
        from concurrent.futures import ThreadPoolExecutor
        supabase = get_client()
        
        search = request.args.get('search', '').strip()
        area = request.args.get('area', '').strip()
        system = request.args.get('system', '').strip()
        status = request.args.get('status', '').strip()

        target_table = "dwg_latest" if not status else TABLE

        def build_print_query(base_q):
            q = base_q
            if search:
                q = q.or_(f"drawing_no.ilike.%{search}%,line_no.ilike.%{search}%,title.ilike.%{search}%")
            if area: q = q.eq('area', area)
            if system: q = q.eq('system', system)
            if status: q = q.eq('revision', status)
            return q

        count_q = build_print_query(supabase.table(target_table).select("id", count="exact"))
        count_res = count_q.limit(1).execute()
        total_count = count_res.count if hasattr(count_res, 'count') else 0

        batch_size = 1000
        offsets = [i * batch_size for i in range((total_count + batch_size - 1) // batch_size)]
        def fetch_batch(offset):
            q = build_print_query(supabase.table(target_table).select("area,system,drawing_no,line_no,title,revision,issued_date"))
            return q.order('drawing_no').range(offset, offset + batch_size - 1).execute().data

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(fetch_batch, offsets))
        all_data = [item for sublist in results for item in sublist]

        html = f"""
        <html>
        <head>
            <title>IPCS Print Report</title>
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
                @page {{ size: landscape; margin: 8mm !important; }}
                * {{ -webkit-print-color-adjust: exact !important; }}
                body {{ font-family: 'Inter', sans-serif; margin: 15px 0; background: #f8fafc; font-size: 8px !important; }}
                #print-main {{ background: #fff; padding: 20px; width: 96%; margin: 0 auto; box-shadow: 0 0 15px rgba(0,0,0,0.05); }}
                h2 {{ text-align: center; margin-bottom: 10px; font-size: 15px; font-weight: 600; color: #1e293b; }}
                .meta {{ text-align: right; margin-bottom: 5px; font-size: 7px; color: #64748b; }}
                <table> {{ width: 100%; border-collapse: collapse; border: 0.5px solid #94a3b8; }}
                th, td {{ border: 0.4px solid #cbd5e1; padding: 4px 6px; text-align: center !important; }}
                th {{ background-color: #f1f5f9; font-weight: 600; text-transform: uppercase; }}
                .col-dwg {{ color: #2563eb; font-weight: 500; text-decoration: none; }}
                .badge-rev {{ padding: 1px 5px; border-radius: 3px; font-weight: 600; background-color: #f0fdf4; color: #16a34a; border: 0.2px solid #dcfce7; }}
                #top-ctrl {{ width: 96%; margin: 10px auto; display: flex; justify-content: flex-end; align-items: center; gap: 15px; }}
                #print-btn {{ background: #2563eb; color: #fff; border: none; padding: 6px 15px; border-radius: 4px; font-size: 11px; cursor: pointer; }}
                @media print {{
                    body {{ background: #fff; margin: 0; }}
                    #print-main {{ width: 100%; padding: 0; box-shadow: none; }}
                    #top-ctrl {{ display: none !important; }}
                }}
            </style>
        </head>
        <body>
            <div id="top-ctrl">
                <div style="font-size: 9px; color: #dc2626; font-weight: 500;">
                    ⌛ 필터 적용 데이터({len(all_data)}건) 준비 중... 3.5초 후 인쇄창이 자동으로 뜹니다.
                </div>
                <button id="print-btn" onclick="window.print()">🖨️ 수동 인쇄 호출 (Force Print)</button>
            </div>
            <div id="print-main">
                <h2>IPCS ISO Drawing Master List ({len(all_data)} Records)</h2>
                <div class="meta">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
                <table>
                    <thead>
                        <tr>
                            <th style="width:35px;">NO.</th>
                            <th>AREA</th>
                            <th>SYSTEM</th>
                            <th class="col-dwg">DWG. NO.</th>
                            <th style="white-space:nowrap;">LINE. NO.</th>
                            <th style="min-width:180px;">DRAWING TITLE</th>
                            <th>REV.</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        for i, d in enumerate(all_data):
            rev = d.get('revision','')
            html += f"""
                <tr>
                    <td>{i+1}</td>
                    <td>{d.get('area','')}</td>
                    <td>{d.get('system','')}</td>
                    <td class="col-dwg">{d.get('drawing_no','')}</td>
                    <td style="white-space:nowrap;">{d.get('line_no','')}</td>
                    <td style="white-space:normal; text-align:left !important;">{d.get('title','')}</td>
                    <td><span class="badge-rev">{rev}</span></td>
                </tr>
            """
        html += f"""
                    </tbody>
                </table>
            </div>
            <script>
                function runPrint() {{
                    window.print();
                    window.onafterprint = function() {{ window.close(); }};
                }}
                window.onload = function() {{
                    const wait = Math.max(3500, Math.min(6000, {len(all_data)} * 1.5));
                    setTimeout(runPrint, wait);
                }};
            </script>
        </body>
        </html>"""
        return html
    except Exception as e:
        return f"Print failed: {str(e)}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5100))
    app.run(host="0.0.0.0", port=port)
