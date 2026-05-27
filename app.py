import streamlit as st
import pandas as pd
import plotly.express as px
import requests

st.set_page_config(page_title="Dashboard MR & Fatturato", layout="wide")

SUPABASE_URL = st.secrets.get("SUPABASE_URL")
SUPABASE_ANON_KEY = st.secrets.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    st.error(
        "Secrets mancanti.\n\n"
        "Streamlit Cloud → Manage app → Settings → Secrets:\n"
        'SUPABASE_URL = "https://<ref>.supabase.co"\n'
        'SUPABASE_ANON_KEY = "sb_publishable_..."\n'
    )
    st.stop()

def sb_post(path: str, token: str | None = None, params=None, payload=None):
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.post(f"{SUPABASE_URL}{path}", headers=headers, params=params, json=payload, timeout=30)
    return r

def sb_get(path: str, token: str, params=None):
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {token}",
    }
    r = requests.get(f"{SUPABASE_URL}{path}", headers=headers, params=params, timeout=30)
    return r

# --- LOGIN ---
st.sidebar.header("Login")
email = st.sidebar.text_input("Email")
password = st.sidebar.text_input("Password", type="password")

if "access_token" not in st.session_state:
    st.session_state.access_token = None
    st.session_state.user = None

if st.sidebar.button("Entra"):
    # Supabase Auth: password grant
    r = sb_post(
        "/auth/v1/token",
        token=None,
        params={"grant_type": "password"},
        payload={"email": email, "password": password},
    )
    if r.status_code != 200:
        st.error(f"Login fallito ({r.status_code}): {r.text}")
        st.stop()

    data = r.json()
    st.session_state.access_token = data.get("access_token")
    st.session_state.user = email
    st.rerun()

if not st.session_state.access_token:
    st.info("Effettua login per visualizzare la dashboard.")
    st.stop()

token = st.session_state.access_token
st.sidebar.success(f"Loggato: {st.session_state.user}")

st.title("Dashboard MR & Fatturato")

# --- FILTRI: anni disponibili ---
r = sb_get("/rest/v1/facts", token, params={"select": "anno", "limit": "5000"})
if r.status_code != 200:
    st.error(f"Errore lettura anni ({r.status_code}): {r.text}")
    st.stop()

years_raw = r.json()
years = sorted({row.get("anno") for row in years_raw if row.get("anno") is not None})
if not years:
    st.warning("Nessun anno disponibile (oppure RLS ti filtra tutto).")
    st.stop()

st.sidebar.header("Filtri")
anno = st.sidebar.selectbox("Anno", years)
semestre = st.sidebar.selectbox("Semestre", ["S1", "S2"])

# --- CARICO DATI FACTS filtrati ---
select_cols = ",".join([
    "data","anno","semestre","num_mese","account","tipo",
    "valore_attuale","attuale_mese","budget_rolling_mese","valore_budget","py_mese"
])

r = sb_get(
    "/rest/v1/facts",
    token,
    params={
        "select": select_cols,
        "anno": f"eq.{int(anno)}",
        "semestre": f"eq.{semestre}",
        "limit": "100000",
    },
)

if r.status_code != 200:
    st.error(f"Errore lettura facts ({r.status_code}): {r.text}")
    st.stop()

df = pd.DataFrame(r.json())
if df.empty:
    st.warning("Nessun dato per i filtri selezionati (sales potrebbe non avere account assegnati).")
    st.stop()

df["data"] = pd.to_datetime(df["data"], errors="coerce")
for c in ["valore_attuale","attuale_mese","budget_rolling_mese","valore_budget","py_mese"]:
    df[c] = pd.to_numeric(df.get(c, 0), errors="coerce").fillna(0.0)

# --- filtro account (sales vede già solo i suoi via RLS) ---
accounts = sorted(df["account"].dropna().unique().tolist())
acc_sel = st.sidebar.multiselect("Account (opzionale)", accounts, default=[])
if acc_sel:
    df = df[df["account"].isin(acc_sel)]

# --- MR ---
df_mr = df[df["tipo"].astype(str).str.upper() == "MR"].copy()
if not df_mr.empty:
    mr_stock = (
        df_mr.groupby(["num_mese", "account"])["valore_attuale"].max()
        .groupby("num_mese").sum()
    )
    mr_target = (
        df_mr.groupby(["num_mese", "account"])["valore_budget"].max()
        .groupby("num_mese").sum()
    )
    mr = pd.DataFrame({"MR Stock": mr_stock, "MR Target": mr_target}).reset_index().sort_values("num_mese")

    last = mr.iloc[-1]
    c1, c2, c3 = st.columns(3)
    c1.metric("MR (fine periodo)", f"{last['MR Stock']:,.2f}")
    c2.metric("MR Target semestre", f"{last['MR Target']:,.2f}")
    c3.metric("Manca al target", f"{(last['MR Target'] - last['MR Stock']):,.2f}")

    fig_mr = px.line(mr, x="num_mese", y=["MR Stock", "MR Target"], markers=True, title="MR Stock vs Target")
    st.plotly_chart(fig_mr, use_container_width=True)
else:
    st.info("Nessuna riga MR nel periodo selezionato.")

# --- SOFTWARE / SERVIZI ---
def plot_tipo(label: str):
    d = df[df["tipo"].astype(str).str.lower() == label.lower()].copy()
    if d.empty:
        st.info(f"Nessun dato per {label}")
        return

    out = pd.DataFrame({
        "Attuale": d.groupby("num_mese")["attuale_mese"].sum(),
        "PY": d.groupby("num_mese")["py_mese"].sum(),
        "Rolling": d.groupby("num_mese")["budget_rolling_mese"].sum(),
    }).reset_index().sort_values("num_mese")

    fig = px.line(out, x="num_mese", y=["Attuale", "PY", "Rolling"], markers=True,
                  title=f"{label} - Attuale vs PY vs Rolling")
    st.plotly_chart(fig, use_container_width=True)

c1, c2 = st.columns(2)
with c1:
    plot_tipo("Software")
with c2:
    plot_tipo("Servizi")
