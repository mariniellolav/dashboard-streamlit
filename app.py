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

# ---------- Helper format ITA + colori ----------
def fmt_ita(n, dec=2, eur=False):
    try:
        x = float(n)
    except Exception:
        return "0,00 €" if eur else "0,00"
    s = f"{x:,.{dec}f}"           # 1,234,567.89
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")  # 1.234.567,89
    return f"{s} €" if eur else s

def pct(x):
    try:
        v = float(x) * 100
    except Exception:
        v = 0.0
    return f"{v:.2f}".replace(".", ",") + "%"

def color_html(val):
    try:
        v = float(val)
    except Exception:
        v = 0.0
    return "#138a36" if v >= 0 else "#c1121f"

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

# ----- Filtri rapidi -----
st.sidebar.header("Filtri")
anno = st.sidebar.selectbox("Anno", years)
semestre = st.sidebar.radio("Semestre", ["S1", "S2"], index=0)

# Prendo TUTTO il semestre (serve per KPI YTD/Budget sem corretti)
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

df_full = pd.DataFrame(r.json())
if df_full.empty:
    st.warning("Nessun dato per i filtri selezionati.")
    st.stop()

df_full["data"] = pd.to_datetime(df_full["data"], errors="coerce")
for c in ["valore_attuale","attuale_mese","budget_rolling_mese","valore_budget","py_mese"]:
    df_full[c] = pd.to_numeric(df_full.get(c, 0), errors="coerce").fillna(0.0)

# ---- FILTRI MESE: dropdown + slider ----
min_m = int(df_full["num_mese"].min())
max_m = int(df_full["num_mese"].max())

months_it = {1:"Gen",2:"Feb",3:"Mar",4:"Apr",5:"Mag",6:"Giu",7:"Lug",8:"Ago",9:"Set",10:"Ott",11:"Nov",12:"Dic"}
month_options = ["Tutti"] + [f"{m:02d} - {months_it.get(m,str(m))}" for m in range(min_m, max_m+1)]
month_pick = st.sidebar.selectbox("Mese singolo (opzionale)", month_options, index=0)

if month_pick != "Tutti":
    m = int(month_pick.split(" - ")[0])
    m_from, m_to = m, m
else:
    m_from, m_to = st.sidebar.slider("Mesi (da - a)", min_m, max_m, (min_m, max_m))

# account filter
accounts_all = sorted(df_full["account"].dropna().unique().tolist())
acc_sel = st.sidebar.multiselect("Account (opzionale)", accounts_all, default=[])

def apply_acc(d):
    if acc_sel:
        return d[d["account"].isin(acc_sel)].copy()
    return d.copy()

df_full_acc = apply_acc(df_full)

# df_range per grafici/periodo
df_range = df_full_acc[(df_full_acc["num_mese"] >= m_from) & (df_full_acc["num_mese"] <= m_to)].copy()
if df_range.empty:
    st.warning("Nessun dato nel range mesi selezionato.")
    st.stop()

# ultimo mese selezionato = per YTD
last_m = m_to

# ---------- FUNZIONI KPI "stile Excel" ----------
def ytd_value(df_sem, tipo_label, last_month):
    d = df_sem[df_sem["tipo"].astype(str).str.lower() == tipo_label.lower()].copy()
    d = d[d["num_mese"] <= last_month].sort_values(["account","num_mese"])
    if d.empty:
        return 0.0
    # prendo l'ultima riga disponibile per ogni account (fotografia progressiva)
    last_rows = d.groupby("account").tail(1)
    return float(last_rows["valore_attuale"].sum())

def py_ytd_value(df_sem, tipo_label, last_month):
    d = df_sem[df_sem["tipo"].astype(str).str.lower() == tipo_label.lower()].copy()
    d = d[d["num_mese"] <= last_month]
    if d.empty:
        return 0.0
    return float(d["py_mese"].sum())

def period_value(df_period, tipo_label):
    d = df_period[df_period["tipo"].astype(str).str.lower() == tipo_label.lower()].copy()
    return float(d["attuale_mese"].sum()) if not d.empty else 0.0

def py_period_value(df_period, tipo_label):
    d = df_period[df_period["tipo"].astype(str).str.lower() == tipo_label.lower()].copy()
    return float(d["py_mese"].sum()) if not d.empty else 0.0

def rolling_period_value(df_period, tipo_label):
    d = df_period[df_period["tipo"].astype(str).str.lower() == tipo_label.lower()].copy()
    return float(d["budget_rolling_mese"].sum()) if not d.empty else 0.0

def budget_sem_value(df_sem, tipo_label):
    d = df_sem[df_sem["tipo"].astype(str).str.lower() == tipo_label.lower()].copy()
    if d.empty:
        return 0.0
    # budget semestre: prendo un solo valore per account (max), poi sommo
    b = d.groupby("account")["valore_budget"].max()
    return float(b.sum())

def safe_pct(delta, base):
    return 0.0 if base == 0 else (delta / base)

def kpi_block(title, rows):
    # rows: list of tuples (label, value_html)
    html = f"""
    <div style="border:1px solid #e6e6e6; border-radius:12px; padding:14px; background:#fff;">
      <div style="font-weight:800; font-size:18px; margin-bottom:8px;">{title}</div>
      <div>
    """
    for lbl, val_html in rows:
        html += f"""
        <div style="display:flex; justify-content:space-between; gap:10px; padding:4px 0; border-bottom:1px dashed #f0f0f0;">
          <div style="color:#333;">{lbl}</div>
          <div style="font-weight:700; text-align:right;">{val_html}</div>
        </div>
        """
    html += "</div></div>"
    st.markdown(html, unsafe_allow_html=True)

# ---------- KPI SOFTWARE / SERVIZI ----------
def build_kpi(tipo_label):
    ytd = ytd_value(df_full_acc, tipo_label, last_m)
    per = period_value(df_range, tipo_label)

    py_ytd = py_ytd_value(df_full_acc, tipo_label, last_m)
    py_per = py_period_value(df_range, tipo_label)

    roll_per = rolling_period_value(df_range, tipo_label)
    bud_sem = budget_sem_value(df_full_acc, tipo_label)

    d_py_ytd = ytd - py_ytd
    d_py_per = per - py_per

    d_roll = per - roll_per
    d_bud = ytd - bud_sem

    rows = [
        ("YTD", fmt_ita(ytd, eur=True)),
        ("Periodo selezionato", fmt_ita(per, eur=True)),
        ("vs PY (YTD) €", f"<span style='color:{color_html(d_py_ytd)}'>{fmt_ita(d_py_ytd, eur=True)}</span>"),
        ("vs PY (YTD) %", f"<span style='color:{color_html(d_py_ytd)}'>{pct(safe_pct(d_py_ytd, py_ytd))}</span>"),
        ("vs PY (Periodo) €", f"<span style='color:{color_html(d_py_per)}'>{fmt_ita(d_py_per, eur=True)}</span>"),
        ("vs PY (Periodo) %", f"<span style='color:{color_html(d_py_per)}'>{pct(safe_pct(d_py_per, py_per))}</span>"),
        ("Rolling (Periodo)", fmt_ita(roll_per, eur=True)),
        ("vs Rolling (Periodo) €", f"<span style='color:{color_html(d_roll)}'>{fmt_ita(d_roll, eur=True)}</span>"),
        ("vs Rolling (Periodo) %", f"<span style='color:{color_html(d_roll)}'>{pct(safe_pct(d_roll, roll_per))}</span>"),
        ("Budget Sem", fmt_ita(bud_sem, eur=True)),
        ("vs Budget Sem €", f"<span style='color:{color_html(d_bud)}'>{fmt_ita(d_bud, eur=True)}</span>"),
        ("Avanzamento Budget Sem %", f"<span style='color:{color_html(ytd-bud_sem)}'>{pct(safe_pct(ytd, bud_sem))}</span>"),
    ]
    return rows

# ---------- KPI MR ----------
def mr_stock(df_sem, last_month):
    d = df_sem[df_sem["tipo"].astype(str).str.upper() == "MR"].copy()
    d = d[d["num_mese"] <= last_month].sort_values(["account","num_mese"])
    if d.empty:
        return 0.0
    last_rows = d.groupby("account").tail(1)
    return float(last_rows["valore_attuale"].sum())

def mr_target_sem(df_sem):
    d = df_sem[df_sem["tipo"].astype(str).str.upper() == "MR"].copy()
    if d.empty:
        return 0.0
    return float(d.groupby("account")["valore_budget"].max().sum())

# ---------- MOSTRA KPI A 3 COLONNE ----------
st.subheader("KPI (stile Excel)")
col_sw, col_srv, col_mr = st.columns(3)

with col_sw:
    kpi_block("SOFTWARE", build_kpi("Software"))

with col_srv:
    kpi_block("SERVIZI", build_kpi("Servizi"))

with col_mr:
    stock = mr_stock(df_full_acc, last_m)
    target = mr_target_sem(df_full_acc)
    d_bud = stock - target
    prog = safe_pct(stock, target)
    rows = [
        ("MR (YTD/Stock)", fmt_ita(stock, eur=True)),
        ("MR Target Sem", fmt_ita(target, eur=True)),
        ("vs Budget Sem €", f"<span style='color:{color_html(d_bud)}'>{fmt_ita(d_bud, eur=True)}</span>"),
        ("Progress %", f"<span style='color:{color_html(d_bud)}'>{pct(prog)}</span>"),
    ]
    kpi_block("MR", rows)

# ---------- GRAFICI (sul periodo selezionato) ----------
st.subheader("Andamento mese per mese (periodo selezionato)")

# MR chart (range)
df_mr = df_range[df_range["tipo"].astype(str).str.upper() == "MR"].copy()
if not df_mr.empty:
    mr_stock_s = df_mr.groupby(["num_mese","account"])["valore_attuale"].max().groupby("num_mese").sum()
    mr_target_s = df_mr.groupby(["num_mese","account"])["valore_budget"].max().groupby("num_mese").sum()
    mr_line = pd.DataFrame({"MR Stock": mr_stock_s, "MR Target": mr_target_s}).reset_index().sort_values("num_mese")
    fig_mr = px.line(mr_line, x="num_mese", y=["MR Stock","MR Target"], markers=True, title="MR Stock vs Target")
    fig_mr.update_layout(separators=PLOTLY_SEPARATORS)
    st.plotly_chart(fig_mr, use_container_width=True)

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

c1, c2 = st.columns(2)
with c1:
    plot_tipo("Software")
with c2:
    plot_tipo("Servizi")
