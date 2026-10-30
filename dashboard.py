import os
import streamlit as st
import pandas as pd
from database import get_conn, list_invoices
from config import DASHBOARD_PASSWORD

st.set_page_config(page_title="SEVENS Engine", layout="wide")

# Simple password gate
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    pw = st.text_input("Password", type="password")
    if pw == DASHBOARD_PASSWORD:
        st.session_state.authenticated = True
        st.rerun()
    elif pw:
        st.error("Wrong password")
    st.stop()

st.title("SEVENS Engine Dashboard")

tab1, tab2, tab3 = st.tabs(["Expenses", "Needs Review", "Manual Entry"])

with tab1:
    col1, col2 = st.columns(2)
    brand = col1.selectbox("Brand", ["all", "sevens", "kuro_kare", "unassigned"])
    status = col2.selectbox("Status", ["all", "pending", "approved", "needs_review", "rejected"])

    b_filter = None if brand == "all" else brand
    s_filter = None if status == "all" else status

    rows = list_invoices(brand=b_filter, status=s_filter, limit=200)
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df[["id", "brand_name", "date", "vendor", "total", "category", "sub_category", "confidence", "status", "created_at"]], use_container_width=True)
        total_sum = sum(r["total"] or 0 for r in rows)
        st.metric("Total shown", f"HKD {total_sum:,.2f}")
    else:
        st.info("No invoices found.")

with tab2:
    st.subheader("Needs Review / Low Confidence")
    review_rows = list_invoices(brand=b_filter if b_filter else None, status="needs_review", limit=100)
    if review_rows:
        for r in review_rows:
            with st.expander(f"#{r['id']} — {r['vendor']} — {r['total']} HKD — {r['confidence']}"):
                st.write(f"Brand: {r['brand_name']} | Date: {r['date']} | Category: {r['category']}/{r['sub_category']}")
                st.json(r.get("raw_json", {}))
                c1, c2, c3 = st.columns(3)
                if c1.button("Approve", key=f"app_{r['id']}"):
                    from database import update_invoice_status
                    update_invoice_status(r["id"], "approved")
                    st.success("Approved")
                    st.rerun()
                if c2.button("Reject", key=f"rej_{r['id']}"):
                    from database import update_invoice_status
                    update_invoice_status(r["id"], "rejected")
                    st.success("Rejected")
                    st.rerun()
                if c3.button("Re-extract", key=f"rex_{r['id']}"):
                    st.info("Re-extract queued — run extraction worker.")
    else:
        st.success("Nothing needs review right now.")

with tab3:
    st.subheader("Manual Entry (Rent / Payroll / etc.)")
    with st.form("manual"):
        m_brand = st.selectbox("Brand", ["sevens", "kuro_kare"])
        m_date = st.date_input("Date")
        m_desc = st.text_input("Description")
        m_amt = st.number_input("Amount", min_value=0.0, step=100.0)
        m_cat = st.selectbox("Category", ["Payroll", "Rent", "Utilities", "Operating expenses", "Other"])
        m_type = st.radio("Type", ["expense", "revenue"])
        m_notes = st.text_area("Notes")
        submitted = st.form_submit_button("Save")
        if submitted:
            from database import get_conn
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO manual_entries (brand_id, date, description, amount, category, entry_type, notes)
                        VALUES ((SELECT id FROM brands WHERE code=%s), %s, %s, %s, %s, %s, %s)
                    """, (m_brand, m_date, m_desc, m_amt, m_cat, m_type, m_notes))
            st.success("Saved")
