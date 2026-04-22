import streamlit as st
import pandas as pd
import pdfplumber
import re
from supabase import create_client, Client

# 1. إعدادات الصفحة
st.set_page_config(page_title="GP Cloud System", layout="wide")

# 2. الربط مع Supabase
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(URL, KEY)

# --- دالة استخراج البيانات من الـ PDF (ظبط الـ Regex حسب ملفك) ---
def extract_gp_data(pdf_file):
    with pdfplumber.open(pdf_file) as pdf:
        text = pdf.pages[0].extract_text()
        gp_num = re.search(r'GP\d+', text)
        veh_no = re.search(r'[A-Z]{3}\s\d+|[A-Z]-\d+', text)
        return {
            "gp_number": gp_num.group(0) if gp_num else f"GP-{pd.Timestamp.now().strftime('%M%S')}",
            "vehicle_no": veh_no.group(0) if veh_no else "N/A",
            "status": "Pending"
        }

# --- واجهة المستخدم ---
st.title("☁️ GP Cloud System - Live Sync")

# جلب البيانات لعمل العدادات
res = supabase.table("gate_passes").select("*").execute()
df_all = pd.DataFrame(res.data) if res.data else pd.DataFrame()

# العدادات فوق الـ Tabs
if not df_all.empty:
    p_count = len(df_all[df_all['status'] == 'Pending'])
    a_count = len(df_all[df_all['status'] == 'Approved'])
    st.markdown(f"### 📊 ⏳ Pending: `{p_count}` | ✅ Approved: `{a_count}`")

# 3. تقسيم الصفحات (Tabs)
tab1, tab2, tab3 = st.tabs(["📤 Upload & Sync", "⚖️ Weighbridge", "📊 Master Report"])

# --- الصفحة الأولى: الرفع ---
with tab1:
    st.subheader("Upload PDF Gate Passes")
    files = st.file_uploader("Choose Files", type="pdf", accept_multiple_files=True)
    if st.button("Push to Cloud"):
        if files:
            for f in files:
                data = extract_gp_data(f)
                supabase.table("gate_passes").insert(data).execute()
            st.success("Data Synced!")
            st.rerun()

# --- الصفحة الثانية: الميزان (تأكيد الوصول) ---
with tab2:
    st.subheader("Live Weighbridge Arrivals")
    pending_df = df_all[df_all['status'] == 'Pending'] if not df_all.empty else pd.DataFrame()
    
    if not pending_df.empty:
        for _, row in pending_df.iterrows():
            col1, col2, col3 = st.columns([2, 2, 1])
            col1.write(f"**GP:** {row['gp_number']}")
            col2.write(f"**Vehicle:** {row['vehicle_no']}")
            if col3.button("Confirm Arrival", key=row['id']):
                # تحديث الحالة في سوبابيز
                supabase.table("gate_passes").update({
                    "status": "Approved", 
                    "arrival_time": pd.Timestamp.now().strftime('%H:%M:%S')
                }).eq("id", row['id']).execute()
                st.rerun() # دي اللي هتخفي السطر فوراً وتحدث العداد
    else:
        st.info("No pending trucks at weighbridge.")

# --- الصفحة الثالثة: الريبورت الكامل ---
with tab3:
    st.subheader("Master Records")
    if not df_all.empty:
        st.dataframe(df_all.sort_values("created_at", ascending=False), use_container_width=True)
        if st.button("Refresh Report"):
            st.rerun()
    else:
        st.write("No records found.")
