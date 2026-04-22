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

# --- دالة استخراج البيانات من الـ PDF ---
def extract_gp_data(pdf_file):
    with pdfplumber.open(pdf_file) as pdf:
        text = pdf.pages[0].extract_text()
        # معادلات البحث عن البيانات (Regex)
        gp_match = re.search(r'GP\d+', text)
        veh_match = re.search(r'[A-Z]-\d+', text) # بيجيب رقم السيارة لو فيه حرف وشرطة
        
        return {
            "gp_number": gp_match.group(0) if gp_match else f"Manual-{pd.Timestamp.now().strftime('%M%S')}",
            "vehicle_no": veh_match.group(0) if veh_match else "N/A",
            "status": "Pending"
        }

# --- واجهة المستخدم ---
st.title("☁️ GP Cloud System - Live Sync")

# 3. قسم العدادات والتقرير (بيحدث نفسه)
res = supabase.table("gate_passes").select("*").order("created_at", desc=True).execute()
data = res.data

if data:
    df = pd.DataFrame(data)
    p_count = len(df[df['status'] == 'Pending'])
    a_count = len(df[df['status'] == 'Approved'])
    
    # العدادات في سطر واحد
    st.markdown(f"### 📊 Statistics: ⏳ Pending: `{p_count}` | ✅ Approved: `{a_count}`")
    st.dataframe(df, use_container_width=True)
else:
    st.info("No data in cloud yet.")

st.divider()

# 4. رفع الملفات والـ Push
st.subheader("📤 Upload & Sync")
uploaded_files = st.file_uploader("Choose PDF files", type="pdf", accept_multiple_files=True)

if st.button("🚀 Push to Cloud"):
    if uploaded_files:
        with st.spinner("Processing..."):
            for f in uploaded_files:
                extracted = extract_gp_data(f)
                try:
                    supabase.table("gate_passes").insert(extracted).execute()
                except:
                    pass # عشان لو الرقم مكرر ميعملش Crash
            
        st.success("Synced Successfully!")
        st.rerun() # دي اللي بتخفي السطور من الـ Pending وتحدث الجدول فوراً
    else:
        st.warning("Please upload files first.")

if st.button("🔄 Manual Refresh"):
    st.rerun()
