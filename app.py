import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import re

st.set_page_config(page_title="Dashboard MR & Fatturato", layout="wide")

# --- CSS: evita troncamenti KPI ---
st.markdown("""
<style>
div[data-testid="stMetricValue"]{
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: clip !important;
  font-size: 1.45rem !important;
  line-height: 1.15 !important;
}
div[data-testid="stMetricLabel"]{ font-size: 0.95rem !important; }
div[data-testid="stMetricDelta"]{ font-size: 0.95rem !important; }
</style>
""", unsafe_allow_html=True)

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

# ---------- Helper format ITA ----------
def fmt_ita(n, dec=2, eur=False):
    try:
        x = float(n)
    except Exception:
        return "0,00 €" if eur else "0,00"
    s = f"{x:,.{dec}f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €" if eur else s

def pct(x):
    try:
        v = float(x) * 100
    except Exception:
        v = 0.0
    return f"{v:.2f}".replace(".", ",") + "%"

PLOTLY_SEPARATORS = ",."

# ---------- Supabase REST ----------
def sb_headers(token=None, json=True, prefer_minimal=False):
    h = {"apikey": SUPABASE_ANON_KEY}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if json:
        h["Content-Type"] = "application/json"
    if prefer_minimal:
        h["Prefer"] = "return=minimal"
    return h

def sb_post(path, token=None, params=None, payload=None):
    return requests.post(
        f"{SUPABASE_URL}{path}",
        headers=sb_headers(token, json=True),
        params=params,
        json=payload,
        timeout=60,
    )

def sb_get(path, token, params=None):
    return requests.get(
        f"{SUPABASE_URL}{path}",
        headers=sb_headers(token, json=False),
        params=params,
        timeout=60,
    )

def sb_delete(path, token, params=None):
    return requests.delete(
        f"{SUPABASE_URL}{path}",
        headers=sb_headers(token, json=False, prefer_minimal=True),
        params=params,
        timeout=60,
    )

# ---------- Auth ----------
def login_with_password(email, password):
    return sb_post(
        "/auth/v1/token",
        token=None,
        params={"grant_type": "password"},
        payload={"email": email, "password": password},
    )

def get_auth_user(token):
    return requests.get(
        f"{SUPABASE_URL}/auth/v1/user",
        headers=sb_headers(token, json=False),
        timeout=30,
    )

def get_user_role(token):
    r = get_auth_user(token)
    if r.status_code != 200:
        return None, None, "sales"
    u = r.json()
    user_id = u.get("id")
    email = u.get("email")

    r2 = sb_get(
        "/rest/v1/profiles",
        token,
        params={"select": "role", "user_id": f"eq.{user_id}", "limit": "1"},
    )
    if r2.status_code != 200:
        return user_id, email, "sales"

    rows = r2.json()
    role = (rows[0].get("role") if rows else "sales") or "sales"
    return user_id, email, role

# ---------- CSV normalize ----------
def normalize_colname(c: str) -> str:
    c = c.strip().lower()
    c = c.replace(" ", "_").replace("-", "_")
    c = re.sub(r"[^a-z0-9_]", "", c)
    return c

def parse_date_any(v):
    if pd.isna(v):
        return None
    s = str(v).strip()
    if not s:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}"
    try:
        dt = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.isna(dt):
            return None
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None

def eu_to_float(v):
    if pd.isna(v):
        return 0.0
    s = str(v).strip()
    if s == "":
        return 0.0
    s = re.sub(r"[^0-9,.\-]", "", s)
    if s == "" or s in {"-", ".", ","}:
        return 0.0

    last_comma = s.rfind(",")
    last_dot = s.rfind(".")
    if last_comma == -1 and last_dot == -1:
        try:
            return float(s)
        except Exception:
            return 0.0

    if last_comma > last_dot:
        s = s.replace(".", "")
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return 0.0

def chunk_list(lst, n=500):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

# ---------------- UI: LOGIN ----------------
st.sidebar.header("Login")

if "access_token" not in st.session_state:
    st.session_state.access_token = None
    st.session_state.user_email = None
    st.session_state.user_id = None
    st.session_state.role = None

email_in = st.sidebar.text_input("Email", value=st.session_state.user_email or "")
password_in = st.sidebar.text_input("Password", type="password")

cL1, cL2 = st.sidebar.columns(2)
with cL1:
    do_login = st.button("Entra")
with cL2:
    do_logout = st.button("Esci")

if do_logout:
    st.session_state.access_token = None
    st.session_state.user_email = None
    st.session_state.user_id = None
    st.session_state.role = None
    st.rerun()

if do_login:
    r = login_with_password(email_in, password_in)
    if r.status_code != 200:
        st.sidebar.error(f"Login fallito ({r.status_code})")
        st.sidebar.write(r.text)
        st.stop()
    tok = r.json().get("access_token")
    st.session_state.access_token = tok
    uid, em, role = get_user_role(tok)
    st.session_state.user_id = uid
    st.session_state.user_email = em
    st.session_state.role = role
    st.rerun()

if not st.session_state.access_token:
    st.info("Effettua login per visualizzare la dashboard.")
    st.stop()

token = st.session_state.access_token
user_role = st.session_state.role or "sales"
st.sidebar.success(f"Loggato: {st.session_state.user_email} ({user_role})")

# ---------------- Upload CSV (solo manager) + preview ----------------
uploaded_df_preview = None
if user_role == "manager":
    st.sidebar.divider()
    st.sidebar.subheader("Upload CSV (solo manager)")

    replace_mode = st.sidebar.checkbox("Sostituisci dati per Anno+Semestre nel CSV", value=True)
    up = st.sidebar.file_uploader("Carica CSV (Export Tabella1)", type=["csv"])

    if up is not None:
        try:
            df_up = pd.read_csv(up, sep=None, engine="python")
        except Exception:
            up.seek(0)
            df_up = pd.read_csv(up, sep=";", engine="python")

        df_up.columns = [normalize_colname(c) for c in df_up.columns]
        uploaded_df_preview = df_up.copy()

        required = ["data", "anno", "semestre", "num_mese", "account", "tipo"]
        num_cols = ["valore_attuale", "attuale_mese", "budget_rolling_mese", "valore_budget", "py_mese", "mr_base_usato"]
        missing = [c for c in required if c not in df_up.columns]

        if missing:
            st.sidebar.error(f"CSV non valido. Colonne mancanti: {missing}")
        else:
            st.sidebar.write("Righe CSV:", len(df_up))

            if st.sidebar.button("Carica nel DB"):
                with st.spinner("Normalizzo dati..."):
                    df_up["data"] = df_up["data"].apply(parse_date_any)

                    for c in num_cols:
                        if c not in df_up.columns:
                            df_up[c] = 0
                        df_up[c] = df_up[c].apply(eu_to_float)

                    def norm_tipo(t):
                        s = str(t).strip().upper()
                        if s == "MR":
                            return "MR"
                        if s == "SOFTWARE":
                            return "Software"
                        if s in {"SERVIZI", "SERVIZIO"}:
                            return "Servizi"
                        return str(t).strip()

                    df_up["tipo"] = df_up["tipo"].apply(norm_tipo)
                    df_up["account"] = df_up["account"].astype(str).str.strip().str.upper()
                    df_up["semestre"] = df_up["semestre"].astype(str).str.strip()
                    df_up["anno"] = pd.to_numeric(df_up["anno"], errors="coerce").fillna(0).astype(int)
                    df_up["num_mese"] = pd.to_numeric(df_up["num_mese"], errors="coerce").fillna(0).astype(int)

                    df_up = df_up[df_up["data"].notna()]

                if df_up.empty:
                    st.sidebar.error("Dopo normalizzazione non resta nessuna riga valida.")
                else:
                    if replace_mode:
                        pairs = sorted(set(zip(df_up["anno"].tolist(), df_up["semestre"].tolist())))
                        with st.spinner("Cancello dati esistenti (anno+semestre)..."):
                            for (a, s) in pairs:
                                rdel = sb_delete("/rest/v1/facts", token, params={"anno": f"eq.{a}", "semestre": f"eq.{s}"})
                                if rdel.status_code not in (200, 204):
                                    st.sidebar.error(f"Errore delete {a}-{s}: {rdel.status_code} {rdel.text}")
                                    st.stop()

                    records = df_up[[
                        "data","anno","semestre","num_mese","account","tipo",
                        "valore_attuale","attuale_mese","budget_rolling_mese","valore_budget",
                        "py_mese","mr_base_usato"
                    ]].to_dict(orient="records")

                    ok = 0
                    with st.spinner("Inserisco righe in facts..."):
                        for batch in chunk_list(records, 500):
                            rins = requests.post(
                                f"{SUPABASE_URL}/rest/v1/facts",
                                headers=sb_headers(token, json=True, prefer_minimal=True),
                                json=batch,
                                timeout=60,
                            )
                            if rins.status_code not in (201, 200):
                                st.sidebar.error(f"Errore insert: {rins.status_code} {rins.text}")
                                st.stop()
                            ok += len(batch)

                    st.sidebar.success(f"Caricate {ok} righe ✅")
                    st.rerun()

# ---------- MAIN ----------
st.title("Dashboard MR & Fatturato")

if user_role == "manager" and uploaded_df_preview is not None:
    with st.expander("Anteprima CSV (prima del caricamento)"):
        st.dataframe(uploaded_df_preview.head(50), use_container_width=True)

# anni disponibili
r = sb_get("/rest/v1/facts", token, params={"select": "anno", "limit": "5000"})
if r.status_code != 200:
    st.error(f"Errore lettura anni ({r.status_code}): {r.text}")
    st.stop()

years_raw = r.json()
years = sorted({row.get("anno") for row in years_raw if row.get("anno") is not None})
if not years:
    st.warning("Nessun anno disponibile.")
    st.stop()

st.sidebar.header("Filtri")
anno = st.sidebar.selectbox("Anno", years)
semestre = st.sidebar.radio("Semestre", ["S1", "S2"], index=0)

select_cols = ",".join([
    "data","anno","semestre","num_mese","account","tipo",
    "valore_attuale","attuale_mese","budget_rolling_mese","valore_budget","py_mese"
])

r = sb_get(
    "/rest/v1/facts",
    token,
    params={"select": select_cols, "anno": f"eq.{int(anno)}", "semestre": f"eq.{semestre}", "limit": "100000"},
)
if r.status_code != 200:
    st.error(f"Errore lettura facts ({r.status_code}): {r.text}")
    st.stop()

df_sem = pd.DataFrame(r.json())
if df_sem.empty:
    st.warning("Nessun dato per i filtri selezionati.")
    st.stop()

df_sem["data"] = pd.to_datetime(df_sem["data"], errors="coerce")
for c in ["valore_attuale","attuale_mese","budget_rolling_mese","valore_budget","py_mese"]:
    df_sem[c] = pd.to_numeric(df_sem.get(c, 0), errors="coerce").fillna(0.0)

# mesi + account
min_m = int(df_sem["num_mese"].min())
max_m = int(df_sem["num_mese"].max())

months_it = {1:"Gen",2:"Feb",3:"Mar",4:"Apr",5:"Mag",6:"Giu",7:"Lug",8:"Ago",9:"Set",10:"Ott",11:"Nov",12:"Dic"}
month_options = ["Tutti"] + [f"{m:02d} - {months_it.get(m,str(m))}" for m in range(min_m, max_m+1)]
month_pick = st.sidebar.selectbox("Mese singolo (opzionale)", month_options, index=0)

if month_pick != "Tutti":
    m = int(month_pick.split(" - ")[0])
    m_from, m_to = m, m
else:
    m_from, m_to = st.sidebar.slider("Mesi (da - a)", min_m, max_m, (min_m, max_m))

accounts_all = sorted(df_sem["account"].dropna().unique().tolist())
acc_sel = st.sidebar.multiselect("Account (opzionale)", accounts_all, default=[])
if acc_sel:
    df_sem = df_sem[df_sem["account"].isin(acc_sel)].copy()

df_range = df_sem[(df_sem["num_mese"] >= m_from) & (df_sem["num_mese"] <= m_to)].copy()
if df_range.empty:
    st.warning("Nessun dato nel periodo selezionato.")
    st.stop()

months_total = max(df_sem["num_mese"].nunique(), 1)
months_selected = max(df_range["num_mese"].nunique(), 1)
end_month_label = f"{int(m_to):02d}-{months_it.get(int(m_to), str(m_to))}"

def safe_pct(delta, base):
    return 0.0 if base == 0 else (delta / base)

def budget_sem(tipo_label):
    d = df_sem[df_sem["tipo"].astype(str).str.lower() == tipo_label.lower()].copy()
    if d.empty:
        return 0.0
    return float(d.groupby("account")["valore_budget"].max().sum())

# ---- KPI con Rolling mese + Rolling periodo ----
def kpi_fatt(tipo_label):
    d_period = df_range[df_range["tipo"].astype(str).str.lower() == tipo_label.lower()].copy()
    fatt_period = float(d_period["attuale_mese"].sum()) if not d_period.empty else 0.0
    py_period = float(d_period["py_mese"].sum()) if not d_period.empty else 0.0
    roll_period = float(d_period["budget_rolling_mese"].sum()) if not d_period.empty else 0.0

    d_last = df_sem[
        (df_sem["tipo"].astype(str).str.lower() == tipo_label.lower()) &
        (df_sem["num_mese"] == m_to)
    ].copy()
    fatt_last = float(d_last["attuale_mese"].sum()) if not d_last.empty else 0.0
    py_last = float(d_last["py_mese"].sum()) if not d_last.empty else 0.0
    roll_month = float(d_last["budget_rolling_mese"].sum()) if not d_last.empty else 0.0

    bud_sem_val = budget_sem(tipo_label)
    bud_period = bud_sem_val * (months_selected / months_total)

    d_py_period = fatt_period - py_period
    p_py_period = safe_pct(d_py_period, py_period)

    d_roll_period = fatt_period - roll_period
    p_roll_period = safe_pct(d_roll_period, roll_period)

    d_py_last = fatt_last - py_last
    p_py_last = safe_pct(d_py_last, py_last)

    d_roll_month = fatt_last - roll_month
    p_roll_month = safe_pct(d_roll_month, roll_month)

    d_bud = fatt_period - bud_period
    p_bud = safe_pct(d_bud, bud_period)

    return {
        "fatt_period": fatt_period,
        "py_period": py_period,
        "roll_period": roll_period,
        "fatt_last": fatt_last,
        "py_last": py_last,
        "roll_month": roll_month,
        "bud_period": bud_period,
        "bud_sem": bud_sem_val,
        "d_py_period": d_py_period,
        "p_py_period": p_py_period,
        "d_roll_period": d_roll_period,
        "p_roll_period": p_roll_period,
        "d_py_last": d_py_last,
        "p_py_last": p_py_last,
        "d_roll_month": d_roll_month,
        "p_roll_month": p_roll_month,
        "d_bud": d_bud,
        "p_bud": p_bud,
    }

def kpi_total(a, b):
    return {
        "fatt_period": a["fatt_period"] + b["fatt_period"],
        "py_period": a["py_period"] + b["py_period"],
        "roll_period": a["roll_period"] + b["roll_period"],
        "fatt_last": a["fatt_last"] + b["fatt_last"],
        "py_last": a["py_last"] + b["py_last"],
        "roll_month": a["roll_month"] + b["roll_month"],
        "bud_period": a["bud_period"] + b["bud_period"],
        "bud_sem": a["bud_sem"] + b["bud_sem"],
        "d_py_period": (a["fatt_period"] + b["fatt_period"]) - (a["py_period"] + b["py_period"]),
        "p_py_period": safe_pct(((a["fatt_period"] + b["fatt_period"]) - (a["py_period"] + b["py_period"])), (a["py_period"] + b["py_period"])),
        "d_roll_period": (a["fatt_period"] + b["fatt_period"]) - (a["roll_period"] + b["roll_period"]),
        "p_roll_period": safe_pct(((a["fatt_period"] + b["fatt_period"]) - (a["roll_period"] + b["roll_period"])), (a["roll_period"] + b["roll_period"])),
        "d_py_last": (a["fatt_last"] + b["fatt_last"]) - (a["py_last"] + b["py_last"]),
        "p_py_last": safe_pct(((a["fatt_last"] + b["fatt_last"]) - (a["py_last"] + b["py_last"])), (a["py_last"] + b["py_last"])),
        "d_roll_month": (a["fatt_last"] + b["fatt_last"]) - (a["roll_month"] + b["roll_month"]),
        "p_roll_month": safe_pct(((a["fatt_last"] + b["fatt_last"]) - (a["roll_month"] + b["roll_month"])), (a["roll_month"] + b["roll_month"])),
        "d_bud": (a["fatt_period"] + b["fatt_period"]) - (a["bud_period"] + b["bud_period"]),
        "p_bud": safe_pct(((a["fatt_period"] + b["fatt_period"]) - (a["bud_period"] + b["bud_period"])), (a["bud_period"] + b["bud_period"])),
    }

st.subheader("KPI Fatturato (periodo selezionato)")
sw = kpi_fatt("Software")
srv = kpi_fatt("Servizi")
tot = kpi_total(sw, srv)

def render_block(title, k):
    st.markdown(f"### {title}")

    r1 = st.columns(2)
    r1[0].metric("Fatturato (periodo)", fmt_ita(k["fatt_period"], eur=True))
    r1[1].metric("vs PY (periodo)", fmt_ita(k["d_py_period"], eur=True), pct(k["p_py_period"]))

    r2 = st.columns(2)
    r2[0].metric("Rolling (periodo)", fmt_ita(k["roll_period"], eur=True))
    r2[1].metric("vs Rolling (periodo)", fmt_ita(k["d_roll_period"], eur=True), pct(k["p_roll_period"]))

    r3 = st.columns(2)
    r3[0].metric(f"Fatturato ({end_month_label})", fmt_ita(k["fatt_last"], eur=True))
    r3[1].metric(f"vs PY ({end_month_label})", fmt_ita(k["d_py_last"], eur=True), pct(k["p_py_last"]))

    r4 = st.columns(2)
    r4[0].metric(f"Rolling ({end_month_label})", fmt_ita(k["roll_month"], eur=True))
    r4[1].metric(f"vs Rolling ({end_month_label})", fmt_ita(k["d_roll_month"], eur=True), pct(k["p_roll_month"]))

    r5 = st.columns(2)
    r5[0].metric("Budget (periodo)", fmt_ita(k["bud_period"], eur=True))
    r5[1].metric("vs Budget (periodo)", fmt_ita(k["d_bud"], eur=True), pct(k["p_bud"]))

    st.metric("Budget (sem)", fmt_ita(k["bud_sem"], eur=True))

cA, cB, cC = st.columns(3)
with cA:
    render_block("SOFTWARE", sw)
with cB:
    render_block("SERVIZI", srv)
with cC:
    render_block("TOTALE", tot)

# ---- MR ----
st.subheader("MR")
df_mr = df_range[df_range["tipo"].astype(str).str.upper() == "MR"].copy()
if not df_mr.empty:
    mr_stock = df_mr.groupby(["num_mese","account"])["valore_attuale"].max().groupby("num_mese").sum()
    mr_target = df_mr.groupby(["num_mese","account"])["valore_budget"].max().groupby("num_mese").sum()
    mr_line = pd.DataFrame({"MR Stock": mr_stock, "MR Target": mr_target}).reset_index().sort_values("num_mese")

    last_stock = float(mr_line.iloc[-1]["MR Stock"])
    last_target = float(mr_line.iloc[-1]["MR Target"])
    manca = last_target - last_stock
    prog = 0.0 if last_target == 0 else last_stock / last_target

    m1, m2 = st.columns(2)
    m1.metric("MR (fine periodo)", fmt_ita(last_stock, eur=True))
    m2.metric("MR Target semestre", fmt_ita(last_target, eur=True))

    m3, m4 = st.columns(2)
    m3.metric("Manca al target", fmt_ita(manca, eur=True))
    m4.metric("Progress %", pct(prog))

    fig_mr = px.line(mr_line, x="num_mese", y=["MR Stock","MR Target"], markers=True, title="MR Stock vs Target")
    fig_mr.update_layout(separators=PLOTLY_SEPARATORS)
    st.plotly_chart(fig_mr, use_container_width=True)
else:
    st.info("Nessuna riga MR nel periodo selezionato.")

# ---- Grafici fatturato ----
st.subheader("Andamento mese per mese")

def plot_tipo(label: str):
    d = df_range[df_range["tipo"].astype(str).str.lower() == label.lower()].copy()
    if d.empty:
        st.info(f"Nessun dato per {label}")
        return
    out = pd.DataFrame({
        "Attuale": d.groupby("num_mese")["attuale_mese"].sum(),
        "PY": d.groupby("num_mese")["py_mese"].sum(),
        "Rolling": d.groupby("num_mese")["budget_rolling_mese"].sum(),
    }).reset_index().sort_values("num_mese")

    fig = px.line(out, x="num_mese", y=["Attuale","PY","Rolling"], markers=True, title=f"{label} - Attuale vs PY vs Rolling")
    fig.update_layout(separators=PLOTLY_SEPARATORS)
    st.plotly_chart(fig, use_container_width=True)

cc1, cc2 = st.columns(2)
with cc1:
    plot_tipo("Software")
with cc2:
    plot_tipo("Servizi")
