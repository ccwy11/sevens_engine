import os
import streamlit as st
import pandas as pd
from database import get_conn, list_invoices, delete_invoice, update_invoice_fields
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

STATUS_OPTIONS = {
    "Active (excl. rejected)": ["pending", "approved"],
    "Pending": ["pending"],
    "Approved": ["approved"],
    "Needs Review": ["needs_review"],
    "Rejected": ["rejected"],
    "All": None,  # None = no status filter
}

with tab1:
    col1, col2 = st.columns(2)
    brand = col1.selectbox("Brand", ["all", "sevens", "kuro_kare", "unassigned"])
    status_label = col2.selectbox("Status", list(STATUS_OPTIONS.keys()), index=0)

    b_filter = None if brand == "all" else brand
    statuses = STATUS_OPTIONS[status_label]

    rows = list_invoices(brand=b_filter, statuses=statuses, limit=200)
    if rows:
        df = pd.DataFrame(rows)
        display_cols = ["id", "brand_name", "date", "vendor", "total", "category", "sub_category", "confidence", "status", "created_at"]
        st.dataframe(df[[c for c in display_cols if c in df.columns]], use_container_width=True)

        # Total excludes rejected unless explicitly viewing "Rejected" or "All"
        total_sum = sum(r["total"] or 0 for r in rows)
        st.metric("Total shown", f"HKD {total_sum:,.2f}")

        count_by_status = df.groupby("status").size().to_dict() if "status" in df.columns else {}
        if count_by_status:
            st.caption("Counts: " + " | ".join(f"{k}: {v}" for k, v in count_by_status.items()))
    else:
        st.info("No invoices found.")

with tab2:
    st.subheader("Needs Review / Low Confidence")
    review_rows = list_invoices(brand=b_filter if b_filter else None, status="needs_review", limit=100)
    if review_rows:
        for r in review_rows:
            with st.expander(f"#{r['id']} — {r['vendor'] or 'N/A'} — {r['total'] or 'N/A'} HKD — {r['confidence']}"):
                st.write(f"**Brand:** {r['brand_name']} | **Date:** {r['date']} | **File:** {r['source_file']}")
                st.write(f"**Category:** {r['category']} / {r['sub_category'] or '-'} | **Confidence:** {r['confidence']}")
                if r.get("notes"):
                    st.caption(f"Notes: {r['notes']}")

                # Action buttons
                c1, c2, c3, c4 = st.columns(4)
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
                if c3.button("Delete", key=f"del_{r['id']}"):
                    delete_invoice(r["id"])
                    st.success(f"Deleted invoice #{r['id']}")
                    st.rerun()
                if c4.button("Edit", key=f"edit_btn_{r['id']}"):
                    st.session_state[f"editing_{r['id']}"] = True
                    st.rerun()

                # Edit form
                if st.session_state.get(f"editing_{r['id']}", False):
                    st.divider()
                    st.write("**Edit Invoice**")
                    e1, e2 = st.columns(2)
                    edit_vendor = e1.text_input("Vendor", value=r.get("vendor") or "", key=f"e_vendor_{r['id']}")
                    edit_date = e2.text_input("Date (YYYY-MM-DD)", value=str(r.get("date") or ""), key=f"e_date_{r['id']}")
                    e3, e4 = st.columns(2)
                    edit_total = e3.number_input("Total", value=float(r.get("total") or 0), step=10.0, key=f"e_total_{r['id']}")
                    edit_tax = e4.number_input("Tax", value=float(r.get("tax") or 0), step=10.0, key=f"e_tax_{r['id']}")
                    e5, e6 = st.columns(2)
                    edit_cat = e5.selectbox("Category", ["Food Ingredients", "non-food Ingredients", "Operating expenses", "Utilities", "UNCATEGORIZED"],
                                            index=["Food Ingredients", "non-food Ingredients", "Operating expenses", "Utilities", "UNCATEGORIZED"].index(r.get("category", "UNCATEGORIZED")),
                                            key=f"e_cat_{r['id']}")
                    edit_sub = e6.text_input("SubCategory", value=r.get("sub_category") or "", key=f"e_sub_{r['id']}")
                    edit_notes = st.text_area("Notes", value=r.get("notes") or "", key=f"e_notes_{r['id']}")

                    c_save, c_cancel = st.columns(2)
                    if c_save.button("Save Changes", key=f"save_{r['id']}"):
                        update_fields = {
                            "vendor": edit_vendor or None,
                            "date": edit_date or None,
                            "total": edit_total if edit_total > 0 else None,
                            "tax": edit_tax if edit_tax > 0 else None,
                            "category": edit_cat,
                            "sub_category": edit_sub or None,
                            "notes": edit_notes or None,
                        }
                        update_invoice_fields(r["id"], update_fields)
                        del st.session_state[f"editing_{r['id']}"]
                        st.success("Updated")
                        st.rerun()
                    if c_cancel.button("Cancel", key=f"cancel_{r['id']}"):
                        del st.session_state[f"editing_{r['id']}"]
                        st.rerun()
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