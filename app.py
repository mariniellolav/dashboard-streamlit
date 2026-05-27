import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import re

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

# ---------- Helper format ITA ----------
def fmt_ita(n, dec=2, eur=False):
    try:
        x = float(n)
    except Exception:
        return "0,00 €" if eur else "0,00"
    s = f"{x:,.{dec}f}"           # 1,234,567.89
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")  # 1.234.567,89
    return f"{s} €" if eur else s

def fmt_pct(x, dec=2):
    try:
        v = float(x) * 100
    except Exception:
        v = 0.0
    s = f"{v:.{dec}f}".replace(".", ",")
    return f"{s}%"

PLOTLY_SEPARATORS = ",."  # decimale=',' migliaia='.'

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

col_login1, col_login2 = st.sidebar.columns(2)
with col_login1:
    do_login = st.button("Entra")
with col_login2:
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

# ---------------- Upload CSV (solo manager) + ANTEPRIMA ----------------
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
        allowed = set(required + num_cols)

        missing = [c for c in required if c not in df_up.columns]
        unknown = sorted([c for c in df_up.columns if c not in allowed])

        if missing:
            st.sidebar.error(f"CSV non valido. Colonne mancanti: {missing}")
        else:
            if unknown:
                st.sidebar.warning(f"Colonne non usate (ok): {unknown}")
            st.sidebar.write("Righe CSV:", len(df_up))
            try:
                yrs = sorted(df_up["anno"].dropna().unique().tolist())
                sems = sorted(df_up["semestre"].dropna().unique().tolist())
                st.sidebar.caption(f"Anni nel CSV: {yrs}")
                st.sidebar.caption(f"Semestri nel CSV: {sems}")
            except Exception:
                pass

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
                    st.sidebar.error("Dopo normalizzazione non resta nessuna riga valida (controlla la colonna data).")
                else:
                    if replace_mode:
                        pairs = sorted(set(zip(df_up["anno"].tolist(), df_up["semestre"].tolist())))
                        with st.spinner("Cancello dati esistenti (anno+semestre)..."):
                            for (a, s) in pairs:
                                rdel = sb_delete(
                                    "/rest/v1/facts",
                                    token,
                                    params={"anno": f"eq.{a}", "semestre": f"eq.{s}"},
                                )
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

# Anteprima CSV (solo se manager ha caricato un file)
if user_role == "manager" and uploaded_df_preview is not None:
    with st.expander("Anteprima CSV (prima del caricamento)"):
        st.write("Colonne:", list(uploaded_df_preview.columns))
        st.dataframe(uploaded_df_preview.head(50), use_container_width=True)

# anni disponibili (RLS)
r = sb_get("/rest/v1/facts", token, params={"select": "anno", "limit": "5000"})
if r.status_code != 200:
    st.error(f"Errore lettura anni ({r.status_code}): {r.text}")
    st.stop()

years_raw = r.json()
years = sorted({row.get("anno") for row in years_raw if row.get("anno") is not None})
if not years:
    st.warning("Nessun anno disponibile (oppure RLS filtra tutto).")
    st.stop()

# ----- Filtri rapidi (anno + semestre) -----
st.sidebar.header("Filtri")
anno = st.sidebar.selectbox("Anno", years)

# radio è più rapido del selectbox
semestre = st.sidebar.radio("Semestre", ["S1", "S2"], index=0)

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
    st.warning("Nessun dato per i filtri selezionati.")
    st.stop()

df["data"] = pd.to_datetime(df["data"], errors="coerce")
for c in ["valore_attuale","attuale_mese","budget_rolling_mese","valore_budget","py_mese"]:
    df[c] = pd.to_numeric(df.get(c, 0), errors="coerce").fillna(0.0)

# ---- FILTRI MESE: dropdown + slider ----
min_m = int(df["num_mese"].min())
max_m = int(df["num_mese"].max())

months_it = {
    1:"Gen",2:"Feb",3:"Mar",4:"Apr",5:"Mag",6:"Giu",
    7:"Lug",8:"Ago",9:"Set",10:"Ott",11:"Nov",12:"Dic"
}
month_options = ["Tutti"] + [f"{m:02d} - {months_it.get(m,str(m))}" for m in range(min_m, max_m+1)]
month_pick = st.sidebar.selectbox("Mese singolo (opzionale)", month_options, index=0)

if month_pick != "Tutti":
    m = int(month_pick.split(" - ")[0])
    m_from, m_to = m, m
else:
    m_from, m_to = st.sidebar.slider("Mesi (da - a)", min_m, max_m, (min_m, max_m))

df = df[(df["num_mese"] >= m_from) & (df["num_mese"] <= m_to)]
if df.empty:
    st.warning("Nessun dato nel range mesi selezionato.")
    st.stop()

accounts = sorted(df["account"].dropna().unique().tolist())
acc_sel = st.sidebar.multiselect("Account (opzionale)", accounts, default=[])
if acc_sel:
    df = df[df["account"].isin(acc_sel)]

# ---------- KPI fatturato ----------
def kpi_fatturato(tipo_label: str):
    d = df[df["tipo"].astype(str).str.lower() == tipo_label.lower()].copy()
    att = float(d["attuale_mese"].sum()) if not d.empty else 0.0
    py = float(d["py_mese"].sum()) if not d.empty else 0.0
    roll = float(d["budget_rolling_mese"].sum()) if not d.empty else 0.0

    vs_py = att - py
    vs_py_pct = 0.0 if py == 0 else vs_py / py

    vs_roll = att - roll
    vs_roll_pct = 0.0 if roll == 0 else vs_roll / roll

    return att, py, roll, vs_py, vs_py_pct, vs_roll, vs_roll_pct

sw_att, sw_py, sw_roll, sw_dpy, sw_dpy_pct, sw_drl, sw_drl_pct = kpi_fatturato("Software")
srv_att, srv_py, srv_roll, srv_dpy, srv_dpy_pct, srv_drl, srv_drl_pct = kpi_fatturato("Servizi")

st.subheader("KPI Fatturato (periodo selezionato)")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Software €", fmt_ita(sw_att, eur=True))
c2.metric("Software vs PY €", fmt_ita(sw_dpy, eur=True), fmt_pct(sw_dpy_pct))
c3.metric("Software vs Rolling €", fmt_ita(sw_drl, eur=True), fmt_pct(sw_drl_pct))
c4.metric("Software PY / Rolling", f"{fmt_ita(sw_py, eur=True)} / {fmt_ita(sw_roll, eur=True)}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Servizi €", fmt_ita(srv_att, eur=True))
c2.metric("Servizi vs PY €", fmt_ita(srv_dpy, eur=True), fmt_pct(srv_dpy_pct))
c3.metric("Servizi vs Rolling €", fmt_ita(srv_drl, eur=True), fmt_pct(srv_drl_pct))
c4.metric("Servizi PY / Rolling", f"{fmt_ita(srv_py, eur=True)} / {fmt_ita(srv_roll, eur=True)}")

# --- MR KPI + chart ---
df_mr = df[df["tipo"].astype(str).str.upper() == "MR"].copy()
st.subheader("MR")
if not df_mr.empty:
    mr_stock = (
        df_mr.groupby(["num_mese","account"])["valore_attuale"].max()
        .groupby("num_mese").sum()
    )
    mr_target = (
        df_mr.groupby(["num_mese","account"])["valore_budget"].max()
        .groupby("num_mese").sum()
    )
    mr = pd.DataFrame({"MR Stock": mr_stock, "MR Target": mr_target}).reset_index().sort_values("num_mese")
    last = mr.iloc[-1]

    c1, c2, c3 = st.columns(3)
    c1.metric("MR (fine periodo)", fmt_ita(last["MR Stock"], eur=True))
    c2.metric("MR Target semestre", fmt_ita(last["MR Target"], eur=True))
    c3.metric("Manca al target", fmt_ita(last["MR Target"] - last["MR Stock"], eur=True))

    fig_mr = px.line(mr, x="num_mese", y=["MR Stock","MR Target"], markers=True, title="MR Stock vs Target")
    fig_mr.update_layout(separators=PLOTLY_SEPARATORS)
    st.plotly_chart(fig_mr, use_container_width=True)
else:
    st.info("Nessuna riga MR nel periodo selezionato.")

# --- SW/SRV charts ---
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

    fig = px.line(out, x="num_mese", y=["Attuale","PY","Rolling"], markers=True,
                  title=f"{label} - Attuale vs PY vs Rolling")
    fig.update_layout(separators=PLOTLY_SEPARATORS)
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Andamento mese per mese")
c1, c2 = st.columns(2)
with c1:
    plot_tipo("Software")
with c2:
    plot_tipo("Servizi")
