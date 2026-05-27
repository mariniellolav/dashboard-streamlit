import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client

# Alcune installazioni hanno postgrest separato, ma in genere arriva con supabase
try:
    from postgrest.exceptions import APIError
except Exception:
    APIError = Exception  # fallback

st.set_page_config(page_title="Dashboard MR & Fatturato", layout="wide")

# --- SECRETS ---
SUPABASE_URL = st.secrets.get("SUPABASE_URL")
SUPABASE_ANON_KEY = st.secrets.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    st.error(
        "Secrets mancanti su Streamlit Cloud.\n\n"
        "Vai su: Manage app → Settings → Secrets e inserisci:\n"
        'SUPABASE_URL = "https://<ref>.supabase.co"\n'
        'SUPABASE_ANON_KEY = "sb_publishable_..."\n'
    )
    st.stop()

def get_client(token: str | None = None):
    sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    # IMPORTANTISSIMO: assegnazione, altrimenti non si applica davvero alle query
    if token:
        sb.postgrest = sb.postgrest.auth(token)
    return sb

# --- SIDEBAR: LOGIN ---
st.sidebar.header("Login")
email = st.sidebar.text_input("Email")
password = st.sidebar.text_input("Password", type="password")

if "token" not in st.session_state:
    st.session_state.token = None
    st.session_state.user = None

if st.sidebar.button("Entra"):
    try:
        sb0 = get_client()
        res = sb0.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.token = res.session.access_token
        st.session_state.user = res.user.email
        st.rerun()
    except Exception as e:
        st.error(f"Login fallito: {e}")
        st.stop()

if not st.session_state.token:
    st.info("Effettua login per visualizzare la dashboard.")
    st.stop()

sb = get_client(st.session_state.token)
st.sidebar.success(f"Loggato: {st.session_state.user}")

st.title("Dashboard MR & Fatturato")

# --- FILTRI (anni) con debug errori ---
st.sidebar.header("Filtri")

try:
    years_resp = sb.table("facts").select("anno").limit(5000).execute()
    years_raw = years_resp.data or []
except APIError as e:
    # Qui vedi l’errore vero di PostgREST (permessi, schema cache, ecc.)
    st.error(f"POSTGREST APIError (facts/anno): {e.args[0]}")
    st.info(
        "Tip: se vedi 'permission denied', servono GRANT SELECT su public.facts.\n"
        "Se vedi 'schema cache' o 'not found', verifica Data API → Exposed schemas include 'public'."
    )
    st.stop()
except Exception as e:
    st.error(f"Errore generico leggendo gli anni: {e}")
    st.stop()

years = sorted({r.get("anno") for r in years_raw if r.get("anno") is not None})
if not years:
    st.warning("Non risultano anni disponibili in facts (o RLS ti sta filtrando tutto).")
    st.stop()

anno = st.sidebar.selectbox("Anno", years)
semestre = st.sidebar.selectbox("Semestre", ["S1", "S2"])

# --- CARICO DATI FILTRATI (RLS applicata per utente) ---
try:
    resp = (
        sb.table("facts")
        .select(
            "data,anno,semestre,num_mese,account,tipo,"
            "valore_attuale,attuale_mese,budget_rolling_mese,valore_budget,py_mese"
        )
        .eq("anno", int(anno))
        .eq("semestre", semestre)
        .limit(100000)
        .execute()
    )
except APIError as e:
    st.error(f"POSTGREST APIError (facts/select): {e.args[0]}")
    st.stop()
except Exception as e:
    st.error(f"Errore generico caricando i dati: {e}")
    st.stop()

df = pd.DataFrame(resp.data or [])
if df.empty:
    st.warning("Nessun dato per i filtri selezionati (o nessun account assegnato per l’utente sales).")
    st.stop()

# tipi
df["data"] = pd.to_datetime(df["data"])
for c in ["valore_attuale", "attuale_mese", "budget_rolling_mese", "valore_budget", "py_mese"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

# filtro account (sales vedono già solo i loro account via RLS)
accounts = sorted(df["account"].dropna().unique().tolist())
acc_sel = st.sidebar.multiselect("Account (opzionale)", accounts, default=[])
if acc_sel:
    df = df[df["account"].isin(acc_sel)]

# --- MR ---
df_mr = df[df["tipo"].astype(str).str.upper() == "MR"].copy()
if not df_mr.empty:
    # stock/target "as-of" per account e mese: prendo MAX per account/mese e sommo
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
    manca = last["MR Target"] - last["MR Stock"]
    c3.metric("Manca al target", f"{manca:,.2f}")

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
