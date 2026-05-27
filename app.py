import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client

st.set_page_config(page_title="Dashboard MR & Fatturato", layout="wide")

url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_ANON_KEY"]

def client(token=None):
    sb = create_client(url, key)
    if token:
        sb.postgrest.auth(token)  # IMPORTANTISSIMO: attiva RLS con JWT utente
    return sb

st.sidebar.header("Login")
email = st.sidebar.text_input("Email")
password = st.sidebar.text_input("Password", type="password")

if "token" not in st.session_state:
    st.session_state.token = None
    st.session_state.user = None

if st.sidebar.button("Entra"):
    sb = client()
    res = sb.auth.sign_in_with_password({"email": email, "password": password})
    st.session_state.token = res.session.access_token
    st.session_state.user = res.user.email
    st.rerun()

if not st.session_state.token:
    st.info("Effettua login.")
    st.stop()

sb = client(st.session_state.token)
st.sidebar.success(f"Loggato: {st.session_state.user}")

# Filtri
years = sb.table("facts").select("anno").execute().data or []
years = sorted({r["anno"] for r in years if r.get("anno") is not None})
anno = st.sidebar.selectbox("Anno", years)
semestre = st.sidebar.selectbox("Semestre", ["S1", "S2"])

resp = (sb.table("facts")
        .select("data,anno,semestre,num_mese,account,tipo,valore_attuale,attuale_mese,budget_rolling_mese,valore_budget,py_mese")
        .eq("anno", int(anno))
        .eq("semestre", semestre)
        .execute())

df = pd.DataFrame(resp.data or [])
if df.empty:
    st.warning("Nessun dato per i filtri selezionati.")
    st.stop()

df["data"] = pd.to_datetime(df["data"])
for c in ["valore_attuale","attuale_mese","budget_rolling_mese","valore_budget","py_mese"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

# Account (sales vedono già solo i loro grazie a RLS)
accounts = sorted(df["account"].unique().tolist())
acc_sel = st.sidebar.multiselect("Account (opzionale)", accounts, default=[])
if acc_sel:
    df = df[df["account"].isin(acc_sel)]

st.title("Dashboard MR & Fatturato")

# MR
mr = df[df["tipo"].str.upper() == "MR"]
if not mr.empty:
    stock = mr.groupby(["num_mese","account"])["valore_attuale"].max().groupby("num_mese").sum()
    target = mr.groupby(["num_mese","account"])["valore_budget"].max().groupby("num_mese").sum()
    out = pd.DataFrame({"MR Stock": stock, "MR Target": target}).reset_index()
    fig = px.line(out, x="num_mese", y=["MR Stock","MR Target"], markers=True, title="MR Stock vs Target")
    st.plotly_chart(fig, use_container_width=True)

def plot_tipo(label):
    d = df[df["tipo"].str.lower() == label.lower()]
    if d.empty:
        st.info(f"Nessun dato per {label}")
        return
    out = pd.DataFrame({
        "Attuale": d.groupby("num_mese")["attuale_mese"].sum(),
        "PY": d.groupby("num_mese")["py_mese"].sum(),
        "Rolling": d.groupby("num_mese")["budget_rolling_mese"].sum(),
    }).reset_index()
    st.plotly_chart(px.line(out, x="num_mese", y=["Attuale","PY","Rolling"], markers=True,
                            title=f"{label} - Attuale vs PY vs Rolling"),
                    use_container_width=True)

c1, c2 = st.columns(2)
with c1:
    plot_tipo("Software")
with c2:
    plot_tipo("Servizi")