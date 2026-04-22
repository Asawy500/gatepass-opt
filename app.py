import streamlit as st
import pdfplumber
import re
import pandas as pd
from supabase import create_client, Client
from datetime import datetime
import io

# --- 1. Supabase Connection ---
# بنسحب المفاتيح من Streamlit Secrets للأمان
URL = st.secrets["https://uuzpretbqegrpuownltm.supabase.co/rest/v1/"]
KEY = st.secrets["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InV1enByZXRicWVncnB1b3dubHRtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY4NjI4NjgsImV4cCI6MjA5MjQzODg2OH0.bW79vCfGpHCoobzrvh5CZMdxQBl-4Zx_7PCB7pxhCDI"]
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

# --- 3. UI Tabs ---
st.title("☁️ GP Cloud System - Live Sync")
tabs = st.tabs(["📤 Upload & Sync", "⚖️ Weighbridge", "📊 Master Report"])

# --- Tab 1: Upload (With Auto-Clear) ---
with tabs[0]:
    st.subheader("Upload to Cloud Database")
    files = st.file_uploader("Upload PDFs", accept_multiple_files=True, type=['pdf'], key=str(st.session_state.uploader_key))
    
    if st.button("Push to Cloud & Clear"):
        if files:
            added, updated = 0, 0
            for f in files:
                data_list = process_pdf_cloud(f)
                for data in data_list:
                    # فحص هل الجيت باص موجود؟ (للـ Amendment)
                    check = supabase.table("gate_passes").select("gp_number").eq("gp_number", data['gp_number']).execute()
                    
                    if len(check.data) > 0:
                        supabase.table("gate_passes").update(data).eq("gp_number", data['gp_number']).execute()
                        updated += 1
                    else:
                        supabase.table("gate_passes").insert(data).execute()
                        added += 1
            
            st.session_state.uploader_key += 1 # مسح الخانة
            if added > 0: st.success(f"✅ {added} New records synced.")
            if updated > 0: st.info(f"🔄 {updated} Records updated (Amended).")
            st.rerun()

# --- Tab 2: Weighbridge (Live Filtered) ---
with tabs[1]:
    st.subheader("Live Weighbridge Arrivals")
    # سحب البندنج فقط من السحاب
    res = supabase.table("gate_passes").select("*").eq("status", "Pending").execute()
    pending_df = pd.DataFrame(res.data)
    
    if not pending_df.empty:
        selection = st.selectbox("Select Arriving Truck:", pending_df['vehicle_no'] + " | GP: " + pending_df['gp_number'])
        if st.button("Confirm Check-in ✅"):
            gp_id = selection.split(" | GP: ")[1]
            now = datetime.now().strftime("%H:%M")
            supabase.table("gate_passes").update({"status": "Arrived", "arrival_time": now}).eq("gp_number", gp_id).execute()
            st.success("Cloud Updated!")
            st.rerun()
    else:
        st.success("No pending trucks.")

# --- Tab 3: Master Report (Auto-Sorted) ---
with tabs[2]:
    st.subheader("Full Database Log")
    # سحب كل البيانات وترتيبها: البندنج فوق
    all_res = supabase.table("gate_passes").select("*").order("created_at", desc=True).execute()
    if all_res.data:
        full_df = pd.DataFrame(all_res.data)
        # الترتيب: Pending أولاً
        full_df['status'] = pd.Categorical(full_df['status'], categories=["Pending", "Arrived"], ordered=True)
        full_df = full_df.sort_values(by="status")
        
        st.dataframe(full_df, use_container_width=True)
        
        buffer = io.BytesIO()
        full_df.to_excel(buffer, index=False)
        st.download_button("📥 Download Excel Report", data=buffer.getvalue(), file_name="Cloud_Report.xlsx")

# --- Sidebar ---
pending_count = len(supabase.table("gate_passes").select("id").eq("status", "Pending").execute().data)
st.sidebar.metric("Potential Savings", f"{pending_count * 35.7:.2f} AED")
