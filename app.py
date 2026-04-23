import streamlit as st
import pdfplumber
import re
import pandas as pd
from supabase import create_client, Client
from datetime import datetime
import io

# --- 1. Supabase Connection ---
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(URL, KEY)

# --- 2. Page Config ---
st.set_page_config(page_title="GP Cloud Optimizer", layout="wide")

# تهيئة الـ uploader key لمسح الملفات بعد الرفع
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# دالة استخراج البيانات من الـ PDF
def process_pdf_cloud(uploaded_file):
    extracted = []
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            
            gp_no = re.search(r'FZGP\d+', text).group(0) if re.search(r'FZGP\d+', text) else "N/A"
            v_match = re.search(r"Vehicle No\s*[:\.]?\s*([\w-]+)", text)
            vehicle = v_match.group(1) if v_match else "N/A"
            e_match = re.search(r"Valid Upto\s*[:\.]?\s*([\d/ :]+)", text)
            expiry = e_match.group(1).strip() if e_match else "N/A"
            
            cargo, weight = "N/A", "0"
            lines = text.split('\n')
            for i, line in enumerate(lines):
                if "BOE NO" in line:
                    if i + 1 < len(lines):
                        parts = lines[i+1].split()
                        if len(parts) >= 3 and "DPW-" in parts[0]:
                            cargo, weight = parts[1], parts[-1]

            extracted.append({
                "gp_number": gp_no, "vehicle_no": vehicle, "cargo": cargo,
                "weight": weight, "expiry_date": expiry, "status": "Pending"
            })
    return extracted

# --- 3. Statistics (العدادات اللي طلبتها) ---
# سحب الداتا مرة واحدة للعدادات والتقرير
all_res = supabase.table("gate_passes").select("*").order("created_at", desc=True).execute()
all_data = all_res.data if all_res.data else []
df_stats = pd.DataFrame(all_data)

st.title("☁️ GP Cloud System - Live Sync")

# عرض العدادات بشكل شيك وصغير فوق الـ Tabs
if not df_stats.empty:
    p_count = len(df_stats[df_stats['status'] == 'Pending'])
    a_count = len(df_stats[df_stats['status'] == 'Arrived'])
    st.markdown(f"### 📊 ⏳ Pending: `{p_count}` | ✅ Approved: `{a_count}`")

# --- 4. UI Tabs ---
tabs = st.tabs(["📤 Upload & Sync", "⚖️ Weighbridge", "📊 Master Report"])

# --- Tab 1: Upload ---
with tabs[0]:
    st.subheader("Upload to Cloud Database")
    files = st.file_uploader("Upload PDFs", accept_multiple_files=True, type=['pdf'], key=str(st.session_state.uploader_key))
    
    if st.button("Push to Cloud & Clear"):
        if files:
            added, updated = 0, 0
            for f in files:
                data_list = process_pdf_cloud(f)
                for data in data_list:
                    check = supabase.table("gate_passes").select("gp_number").eq("gp_number", data['gp_number']).execute()
                    if len(check.data) > 0:
                        supabase.table("gate_passes").update(data).eq("gp_number", data['gp_number']).execute()
                        updated += 1
                    else:
                        supabase.table("gate_passes").insert(data).execute()
                        added += 1
            st.session_state.uploader_key += 1
            st.rerun()

# --- Tab 2: Weighbridge (الـ Select Box اللي كان ناقص) ---
with tabs[1]:
    st.subheader("Live Weighbridge Arrivals")
    # فلترة البندنج فقط من الداتا اللي سحبناها
    if not df_stats.empty:
        pending_df = df_stats[df_stats['status'] == 'Pending']
        if not pending_df.empty:
            # هنا لستة العربيات والـ GP بتظهر زي ما كنت عايزها
            selection = st.selectbox("Select Arriving Truck:", pending_df['vehicle_no'] + " | GP: " + pending_df['gp_number'])
            if st.button("Confirm Check-in ✅"):
                gp_id = selection.split(" | GP: ")[1]
                now = datetime.now().strftime("%H:%M")
                supabase.table("gate_passes").update({"status": "Arrived", "arrival_time": now}).eq("gp_number", gp_id).execute()
                st.success(f"Truck {selection} Arrived!")
                st.rerun()
        else:
            st.success("No pending trucks.")
    else:
        st.info("Database is empty.")

# --- Tab 3: Master Report (Modified) ---
with tabs[2]:
    st.subheader("Full Database Log")
    if not df_stats.empty:
        # 1. إضافة فلتر فوق الجدول
        filter_status = st.multiselect("Filter by Status:", options=["Pending", "Arrived"], default=["Pending", "Arrived"])
        
        # تطبيق الفلتر
        filtered_df = df_stats[df_stats['status'].isin(filter_status)].copy()

        # 2. حساب الساعات المتبقية (Remaining Hours)
        def calc_hours(row):
            if row['status'] == 'Pending' and row['expiry_date'] != "N/A":
                try:
                    # تحويل النص لتاريخ (تأكد من مطابقة الفورمات المكتوب في الصورة)
                    expiry = datetime.strptime(row['expiry_date'], "%d/%m/%Y %H:%M")
                    now = datetime.now()
                    diff = expiry - now
                    hours = diff.total_seconds() / 3600
                    return f"{round(hours, 1)} hrs"
                except:
                    return "Date Err"
            return "-"

        filtered_df['Remaining Time'] = filtered_df.apply(calc_hours, axis=1)

        # ترتيب العرض: التوقيت المتبقي الأقل يظهر الأول في البندنج
        st.dataframe(filtered_df, use_container_width=True)
        
        # تحميل الإكسيل للبيانات المفلترة
        buffer = io.BytesIO()
        filtered_df.to_excel(buffer, index=False)
        st.download_button("📥 Download Filtered Excel", data=buffer.getvalue(), file_name="Cloud_Report.xlsx")
    else:
        st.write("No records found.")

# --- Sidebar ---
p_sidebar = len(df_stats[df_stats['status'] == 'Pending']) if not df_stats.empty else 0
st.sidebar.metric("Potential Savings", f"{p_sidebar * 35.7:.2f} AED")
