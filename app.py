"""Hypoteční kalkulačka — Streamlit aplikace."""

import datetime
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from mortgage import (
    MortgageParams,
    AdditionalCost,
    FixationPeriod,
    amortization_schedule,
    calculate_summary,
    combined_timeline,
    compare_refinancing,
    cumulative_cost_schedule,
    fixation_comparison_matrix,
    generate_verdict,
    monthly_payment,
    sensitivity_analysis,
    optimal_payment_analysis,
    find_breakeven_investment_rate,
    validate_mortgage_history,
)
from data_io import export_json, import_json, import_bank_csv, summaries_to_csv

st.set_page_config(page_title="Hypoteční kalkulačka", page_icon="🏠", layout="wide")
st.title("Hypoteční kalkulačka")


# ============================================================
# SESSION STATE & IMPORT
# ============================================================

def _init(key, default):
    """Inicializuje session state klíč jen jednou."""
    if key not in st.session_state:
        st.session_state[key] = default


def _populate_widget_keys(current_mortgage, offers_list):
    """Nastaví widgetové klíče podle importovaných dat."""
    if current_mortgage:
        st.session_state["has_current"] = True
        st.session_state["cur_bank"] = current_mortgage.bank_name
        st.session_state["cur_principal"] = current_mortgage.principal
        st.session_state["cur_rate"] = current_mortgage.annual_rate
        st.session_state["cur_years"] = current_mortgage.years
        st.session_state["cur_fix"] = current_mortgage.fixation_years
        if current_mortgage.fixation_end_date:
            st.session_state["cur_fix_date"] = datetime.date.fromisoformat(current_mortgage.fixation_end_date)
        if current_mortgage.original_principal > 0:
            st.session_state["cur_orig_principal"] = current_mortgage.original_principal
            st.session_state["cur_orig_years"] = current_mortgage.original_term_years
            if current_mortgage.start_date:
                st.session_state["cur_start_date"] = datetime.date.fromisoformat(current_mortgage.start_date)
            st.session_state["cur_n_past_fix"] = len(current_mortgage.past_fixations)
            for j, fp in enumerate(current_mortgage.past_fixations):
                st.session_state[f"cur_pf_{j}_rate"] = fp.annual_rate
                st.session_state[f"cur_pf_{j}_years"] = fp.duration_months // 12
    else:
        st.session_state["has_current"] = False
    st.session_state["n_offers"] = len(offers_list)
    for i, o in enumerate(offers_list):
        st.session_state[f"o{i}_bank"] = o.bank_name
        st.session_state[f"o{i}_principal"] = o.principal
        st.session_state[f"o{i}_rate"] = o.annual_rate
        st.session_state[f"o{i}_years"] = o.years
        st.session_state[f"o{i}_fix"] = o.fixation_years
        st.session_state[f"o{i}_is_cur"] = o.is_current_bank
        st.session_state[f"o{i}_bonus"] = o.bonus


_init("current_mortgage", None)
_init("offers", [])

# Zpracování čekajícího importu (PŘED widgety)
if "_pending_import" in st.session_state:
    imported = st.session_state.pop("_pending_import")
    _populate_widget_keys(imported.get("current_mortgage"), imported.get("offers", []))
    st.session_state.current_mortgage = imported.get("current_mortgage")
    st.session_state.offers = imported.get("offers", [])
    st.rerun()

# Zpracování čekajícího CSV importu (PŘED widgety)
if "_pending_csv" in st.session_state:
    _csv = st.session_state.pop("_pending_csv")
    st.session_state["_csv_all_rows"] = _csv["all_rows"]
    st.session_state["_csv_periods"] = _csv["periods"]

    # Historické řádky (minulost)
    _past = [r for r in _csv["all_rows"] if r.is_past]
    st.session_state["_past_schedule"] = _past

    _periods = _csv["periods"]
    _cur = _csv["current"]

    # Předvyplnit stávající hypotéku
    if _cur.get("rate"):
        st.session_state["cur_rate"] = _cur["rate"]
    if _cur.get("balance"):
        st.session_state["cur_principal"] = _cur["balance"]
    if _cur.get("remaining_years"):
        st.session_state["cur_years"] = _cur["remaining_years"]

    # Zajistit checkbox "Mám stávající hypotéku"
    st.session_state["has_current"] = True
    st.session_state["cur_bank"] = "ČSOB"
    # Smazat výsledky, aby se expander rozbalil a uživatel viděl předvyplněná data
    st.session_state["offers"] = []

    # Pokud jsou 2+ fixační období → poslední = nová nabídka ČSOB
    if len(_periods) >= 2:
        _last_p = _periods[-1]
        _balance = _cur.get("balance", 0)
        _rem_years = _cur.get("remaining_years", _last_p["months"] // 12)

        st.session_state["o0_bank"] = "ČSOB"
        st.session_state["o0_rate"] = _last_p["rate"]
        st.session_state["o0_years"] = _rem_years
        st.session_state["o0_principal"] = _balance
        st.session_state["o0_is_cur"] = True
        _fy = _last_p["months"] // 12 or 3
        for _std in [3, 5, 7, 10]:
            if _std <= _fy:
                _fy = _std
                break
        st.session_state["o0_fix"] = _fy

    st.rerun()


# ============================================================
# FORMULÁŘE
# ============================================================

def render_additional_costs(prefix, label="Dodatečné náklady"):
    """Editor měsíčních/jednorázových nákladů."""
    costs = []
    st.markdown(f"**{label}**")
    presets = {
        "Pojištění nemovitosti": (200, 0),
        "Životní pojištění": (300, 0),
        "Poplatek za vedení účtu": (100, 0),
        "Poplatek za správu úvěru": (150, 0),
    }
    selected = st.multiselect("Rychlý výběr", list(presets.keys()), key=f"{prefix}_pre")
    for name in selected:
        m_def, o_def = presets[name]
        c1, c2 = st.columns(2)
        with c1:
            m = st.number_input(f"{name} — měsíčně (Kč)", min_value=0.0, value=float(m_def), step=50.0, key=f"{prefix}_{name}_m")
        with c2:
            o = st.number_input(f"{name} — jednorázově (Kč)", min_value=0.0, value=float(o_def), step=500.0, key=f"{prefix}_{name}_o")
        costs.append(AdditionalCost(name=name, monthly_amount=m, one_time_amount=o))
    n = st.number_input("Vlastní položky", min_value=0, max_value=10, value=0, key=f"{prefix}_n")
    for i in range(n):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            name = st.text_input(f"Název #{i+1}", key=f"{prefix}_cn_{i}")
        with c2:
            m = st.number_input(f"Měsíčně #{i+1}", min_value=0.0, step=50.0, key=f"{prefix}_cm_{i}")
        with c3:
            o = st.number_input(f"Jednorázově #{i+1}", min_value=0.0, step=500.0, key=f"{prefix}_co_{i}")
        if name:
            costs.append(AdditionalCost(name=name, monthly_amount=m, one_time_amount=o))
    return costs


def render_switching_costs(prefix):
    """Editor nákladů na přechod k jiné bance."""
    costs = []
    st.markdown("**Náklady na přechod**")
    presets = {
        "Posouzení vhodnosti zástavy (odhad)": 3000,
        "Zápis zástavního práva — el. podání (ČÚZK)": 1600,
        "Zpracování el. podpisů zástavní smlouvy": 400,
        "Ověření podpisu na zástavní smlouvě": 50,
        "Výmaz zástavního práva — el. podání (ČÚZK)": 1600,
        "Poplatek za předčasné splacení (stará banka)": 0,
    }
    # Inicializovat default jen jednou
    sw_key = f"{prefix}_sw_pre"
    _init(sw_key, list(presets.keys()))
    selected = st.multiselect("Náklady přechodu", list(presets.keys()), key=sw_key)
    for name in selected:
        val = st.number_input(f"{name} (Kč)", min_value=0.0, value=float(presets[name]), step=500.0, key=f"{prefix}_sw_{name}")
        costs.append(AdditionalCost(name=name, one_time_amount=val))
    return costs


def render_conditions(prefix):
    """Editor podmínek banky."""
    conditions = []
    presets = {
        "Běžný účet u banky s min. příjmem": "Splácení z běžného účtu, min. kreditní příjem 15 000 Kč/měsíc",
        "Pojištění nemovitosti": "Nemovitost musí být pojištěna po celou dobu trvání úvěru",
        "Životní pojištění": "Banka vyžaduje/doporučuje životní pojištění (sleva na sazbě)",
    }
    sel = st.multiselect("Běžné podmínky", list(presets.keys()), key=f"{prefix}_cpre")
    for c in sel:
        text = st.text_input(c, value=presets[c], key=f"{prefix}_c_{c}")
        conditions.append(text)
    custom = st.text_area("Další podmínky", key=f"{prefix}_ctxt")
    if custom.strip():
        conditions.append(custom.strip())
    return conditions


def _find_offer_by_name(name, summaries_list, offers_list, current_mortgage):
    """Najde parametry a souhrn nabídky podle názvu z selectboxu."""
    if current_mortgage and name == f"{current_mortgage.bank_name} (stávající)":
        return current_mortgage, calculate_summary(current_mortgage)
    idx = next(i for i, s in enumerate(summaries_list) if s.bank_name == name)
    return offers_list[idx], summaries_list[idx]


# ============================================================
# VSTUPNÍ DATA
# ============================================================

with st.expander("Vstupní data", expanded=not st.session_state.offers):

    # --- Import CSV z ČSOB ---
    st.subheader("Import splátkového plánu z ČSOB")
    st.caption("Nahrajte CSV splátkového plánu z ČSOB — automaticky předvyplní stávající hypotéku, historii i novou nabídku ČSOB.")
    csv_file = st.file_uploader(
        "CSV splátkový kalendář (ČSOB)", type=["csv"],
        key="cur_history_csv",
        help="Splátkový plán z ČSOB ve formátu: Datum;Čerpání;Sazba;Splátka;Úrok;Jistina;Nesplacená jistina (kódování Windows-1250)")

    if csv_file is not None and "_past_schedule" not in st.session_state:
        try:
            result = import_bank_csv(csv_file.read())
            st.session_state["_pending_csv"] = result
            st.rerun()
        except Exception as e:
            st.error(f"Chyba při importu CSV: {e}")

    if st.session_state.get("_past_schedule"):
        past = st.session_state["_past_schedule"]
        periods = st.session_state.get("_csv_periods", [])

        if periods:
            st.markdown("**Detekovaná fixační období:**")
            for pi, p in enumerate(periods):
                years = p["months"] / 12
                st.caption(
                    f"{pi+1}. Sazba **{p['rate']:.2f} %** — "
                    f"{p['months']} měs. ({years:.1f} let), "
                    f"{p['first_date']} – {p['last_date']}")

            if len(periods) >= 2:
                _init("_csv_last_is_offer", True)
                st.checkbox(
                    f"Poslední sazba ({periods[-1]['rate']:.2f} %) je nová nabídka od banky",
                    key="_csv_last_is_offer",
                    help="Zaškrtněte, pokud CSV obsahuje modelaci nové nabídky. "
                         "Odškrtněte, pokud celé CSV je průběh stávající hypotéky.")

                if not st.session_state["_csv_last_is_offer"]:
                    all_rows = st.session_state.get("_csv_all_rows", [])
                    st.session_state["_past_schedule"] = all_rows

        st.caption(
            f"Historie: {len(past)} měsíců, "
            f"zůstatek {past[-1].remaining_balance:,.0f} Kč, "
            f"zaplaceno úroky {past[-1].cumulative_interest:,.0f} Kč")

        if st.button("Smazat import", key="clear_history"):
            for k in ("_past_schedule", "_csv_all_rows", "_csv_periods"):
                st.session_state.pop(k, None)
            st.rerun()

    st.divider()

    # --- Stávající hypotéka ---
    _init("has_current", False)
    has_current = st.checkbox("Mám stávající hypotéku", key="has_current")

    if has_current:
        st.subheader("Stávající hypotéka")
        _init("cur_bank", "Moje banka")
        cur_bank = st.text_input("Stávající banka", key="cur_bank")
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        with c1:
            _init("cur_principal", 2_000_000.0)
            cur_principal = st.number_input("Zbývající jistina (Kč)", min_value=100_000.0, max_value=50_000_000.0, step=100_000.0, key="cur_principal")
        with c2:
            _init("cur_rate", 5.5)
            cur_rate = st.number_input("Aktuální sazba (%)", min_value=0.0, max_value=20.0, step=0.1, format="%.2f", key="cur_rate")
        with c3:
            _init("cur_years", 20)
            cur_years = st.number_input("Zbývající doba (roky)", min_value=1, max_value=40, key="cur_years")
        with c4:
            _init("cur_fix", 0)
            cur_fix = st.number_input("Zbývající fixace (roky)", min_value=0, max_value=15, key="cur_fix")

        _init("cur_fix_date", datetime.date.today() + datetime.timedelta(days=90))
        cur_fix_date = st.date_input("Datum konce fixace", key="cur_fix_date",
                                      help="Datum, kdy končí fixace stávající hypotéky.")
        today = datetime.date.today()
        days_to_end = (cur_fix_date - today).days
        date_str = cur_fix_date.strftime("%d. %m. %Y").lstrip("0").replace(". 0", ". ")
        if days_to_end > 0:
            import calendar
            m = (cur_fix_date.year - today.year) * 12 + cur_fix_date.month - today.month
            if cur_fix_date.day < today.day:
                m -= 1
                prev_m = cur_fix_date.month - 1 if cur_fix_date.month > 1 else 12
                prev_y = cur_fix_date.year if cur_fix_date.month > 1 else cur_fix_date.year - 1
                d = calendar.monthrange(prev_y, prev_m)[1] - today.day + cur_fix_date.day
            else:
                d = cur_fix_date.day - today.day
            parts = []
            if m > 0:
                parts.append(f"{m} měsíců")
            if d > 0:
                parts.append(f"{d} dní")
            st.info(f"Do konce fixace zbývá **{' a '.join(parts)}** ({date_str})")
        elif days_to_end == 0:
            st.warning("Fixace končí dnes.")
        else:
            st.warning(f"Fixace skončila {date_str} (před {abs(days_to_end)} dny).")

        with st.expander("Poplatky stávající hypotéky"):
            cur_costs = render_additional_costs("cur_ac", "Stávající poplatky/pojištění")

        st.session_state.current_mortgage = MortgageParams(
            principal=cur_principal, annual_rate=cur_rate, years=cur_years,
            bank_name=cur_bank, additional_costs=cur_costs,
            is_current_bank=True, fixation_years=cur_fix,
            fixation_end_date=cur_fix_date.isoformat(),
        )
    else:
        st.session_state.current_mortgage = None

    st.divider()

    # --- Nabídky bank ---
    st.subheader("Nabídky bank")
    _init("n_offers", 2)
    n_offers = st.number_input("Počet nabídek", min_value=1, max_value=10, key="n_offers")

    offers = []
    for i in range(n_offers):
        with st.expander(f"Nabídka {i+1}", expanded=(i < 2)):
            bank = st.text_input("Banka", key=f"o{i}_bank")
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            with c1:
                _default_principal = st.session_state.get("cur_principal", 3_000_000.0) if has_current else 3_000_000.0
                _init(f"o{i}_principal", _default_principal)
                principal = st.number_input("Výše úvěru (Kč)", min_value=100_000.0, max_value=50_000_000.0,
                                            step=100_000.0, key=f"o{i}_principal")
            with c2:
                _init(f"o{i}_rate", 5.0)
                rate = st.number_input("Sazba (%)", min_value=0.0, max_value=20.0, step=0.1, format="%.2f", key=f"o{i}_rate")
            with c3:
                _default_years = st.session_state.get("cur_years", 25) if has_current else 25
                _init(f"o{i}_years", _default_years)
                years = st.number_input("Splácení (roky)", min_value=1, max_value=40, key=f"o{i}_years")
            with c4:
                _init(f"o{i}_fix", 5)
                fix = st.number_input("Fixace (roky)", min_value=0, max_value=15, key=f"o{i}_fix")

            is_cur_bank = False
            switching = []
            if has_current:
                is_cur_bank = st.checkbox("Nabídka od stávající banky", key=f"o{i}_is_cur")
                if not is_cur_bank:
                    switching = render_switching_costs(f"o{i}")

            additional = render_additional_costs(f"o{i}_ac")
            _init(f"o{i}_bonus", 0.0)
            bonus = st.number_input("Bonus / odměna od banky (Kč)", min_value=0.0, step=1000.0,
                                    key=f"o{i}_bonus", help="Jednorázová odměna za sjednání hypotéky")

            with st.expander("Podmínky banky"):
                conditions = render_conditions(f"o{i}")

            offers.append(MortgageParams(
                principal=principal, annual_rate=rate, years=years,
                bank_name=bank, additional_costs=additional,
                switching_costs=switching, is_current_bank=is_cur_bank,
                conditions=conditions, fixation_years=fix, bonus=bonus,
            ))

    st.session_state.offers = offers


# ============================================================
# ANALYTICKÉ ZÁLOŽKY
# ============================================================

current = st.session_state.current_mortgage
offers = st.session_state.offers

if not offers:
    st.info("Zadejte nabídky bank v sekci 'Vstupní data' výše.")
    st.stop()

summaries = [calculate_summary(p) for p in offers]

tab_names = ["Srovnání nabídek", "Detail nabídky", "Časová osa", "Citlivostní analýza", "Optimální splátka", "Export / Import"]
_tab = dict(zip(tab_names, st.tabs(tab_names)))


# ──────────────────────────────────────────────────────────────
# TAB 1: SROVNÁNÍ NABÍDEK
# ──────────────────────────────────────────────────────────────
with _tab["Srovnání nabídek"]:
    st.header("Srovnání nabídek")

    # Verdikt
    verdict = generate_verdict(summaries)
    {"green": st.success, "yellow": st.warning, "red": st.error}[verdict.color](verdict.message)

    # Referenční řádek stávající hypotéky
    if current:
        st.caption(f"Stávající hypotéka ({current.bank_name}) je uvedena jako reference — "
                   f"fixace končí, stávající sazba {current.annual_rate:.2f} % přestane platit.")

    # Hlavní tabulka
    def _summary_row(s, label=None):
        row = {
            "Nabídka": label or s.bank_name,
            "Sazba %": s.annual_rate,
            "RPSN %": s.rpsn,
            "Fixace": f"{s.fixation_years} let" if s.fixation_years else "—",
            "Splátka": f"{s.monthly_payment:,.0f}",
            "Měsíčně celkem": f"{s.monthly_total:,.0f}",
        }
        if s.fixation:
            row["Efekt. měs. náklady"] = f"{s.fixation.effective_monthly_cost:,.0f}"
            row["Náklady za fixaci"] = f"{s.fixation.total_cost_in_fixation:,.0f}"
            row["Zůstatek po fixaci"] = f"{s.fixation.remaining_balance:,.0f}"
            row["Splaceno jistiny"] = f"{s.fixation.principal_in_fixation:,.0f}"
        row["Přechod"] = f"{s.total_switching_costs:,.0f}" if s.total_switching_costs > 0 else "—"
        row["Bonus"] = f"−{s.bonus:,.0f}" if s.bonus > 0 else "—"
        return row

    table = []
    if current:
        table.append(_summary_row(calculate_summary(current), f"📌 {current.bank_name} (stávající — ref.)"))
    for s in summaries:
        table.append(_summary_row(s))
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)

    # Detailní srovnání za dobu fixace
    fix_summaries = [(s, s.fixation) for s in summaries if s.fixation]
    if fix_summaries:
        st.subheader("Srovnání za dobu fixace")

        # Najít nejlevnější nabídku
        best_idx = min(range(len(fix_summaries)), key=lambda i: fix_summaries[i][1].total_cost_in_fixation)
        best_s, best_f = fix_summaries[best_idx]

        fix_table = []
        for s, f in fix_summaries:
            diff_total = f.total_cost_in_fixation - best_f.total_cost_in_fixation
            diff_monthly = f.effective_monthly_cost - best_f.effective_monthly_cost
            fix_table.append({
                "Nabídka": s.bank_name,
                "Sazba %": s.annual_rate,
                "Fixace": f"{f.fixation_years} let",
                "Splátka": f"{s.monthly_payment:,.0f} Kč",
                "Úroky za fixaci": f"{f.interest_in_fixation:,.0f} Kč",
                "Poplatky za fixaci": f"{f.additional_costs_in_fixation:,.0f} Kč",
                "Přechod": f"{f.switching_costs:,.0f} Kč" if f.switching_costs > 0 else "—",
                "Bonus": f"−{s.bonus:,.0f} Kč" if s.bonus > 0 else "—",
                "Celk. náklady fixace": f"{f.total_cost_in_fixation:,.0f} Kč",
                "Splaceno jistiny": f"{f.principal_in_fixation:,.0f} Kč",
                "Zůstatek": f"{f.remaining_balance:,.0f} Kč",
                "Rozdíl": "Nejlevnější" if diff_total == 0 else f"+{diff_total:,.0f} Kč",
            })

        st.dataframe(pd.DataFrame(fix_table), use_container_width=True, hide_index=True)

        # Metriky nejlevnější vs ostatní
        if len(fix_summaries) >= 2:
            cols = st.columns(len(fix_summaries))
            for col, (s, f) in zip(cols, fix_summaries):
                diff = f.total_cost_in_fixation - best_f.total_cost_in_fixation
                with col:
                    st.metric(
                        s.bank_name,
                        f"{f.total_cost_in_fixation:,.0f} Kč",
                        delta=f"{diff:+,.0f} Kč" if diff != 0 else "Nejlevnější",
                        delta_color="inverse" if diff != 0 else "off",
                    )
                    st.caption(
                        f"Splátka {s.monthly_payment:,.0f} Kč/měs\n\n"
                        f"Úroky {f.interest_in_fixation:,.0f} Kč\n\n"
                        f"Splaceno jistiny {f.principal_in_fixation:,.0f} Kč"
                    )

            # Měsíční rozdíl
            worst_s, worst_f = max(fix_summaries, key=lambda x: x[1].total_cost_in_fixation)
            if worst_f.total_cost_in_fixation > best_f.total_cost_in_fixation:
                monthly_diff = worst_f.effective_monthly_cost - best_f.effective_monthly_cost
                total_diff = worst_f.total_cost_in_fixation - best_f.total_cost_in_fixation
                st.info(
                    f"**{best_s.bank_name}** ušetří oproti **{worst_s.bank_name}** "
                    f"celkem **{total_diff:,.0f} Kč** za fixaci "
                    f"(~{monthly_diff:,.0f} Kč/měsíc)."
                )

    # Porovnání s referenční stávající hypotékou
    if current and fix_summaries:
        from mortgage import _cost_over_months as _com
        st.subheader("Úspora oproti stávající hypotéce")
        st.caption(f"Kolik ušetříte za dobu fixace oproti pokračování se stávající sazbou {current.annual_rate:.2f} %.")
        ref_cols = st.columns(len(fix_summaries))
        for col, (s, f) in zip(ref_cols, fix_summaries):
            cur_cost = _com(current, f.fixation_months)
            saving = cur_cost - f.total_cost_in_fixation
            monthly_saving = s.monthly_total - calculate_summary(current).monthly_total
            with col:
                st.metric(
                    s.bank_name,
                    f"{saving:+,.0f} Kč",
                    delta=f"{-monthly_saving:+,.0f} Kč/měs" if monthly_saving != 0 else "Stejná splátka",
                    delta_color="normal",
                )
                st.caption(
                    f"Stávající: {cur_cost:,.0f} Kč za {f.fixation_months} měs.\n\n"
                    f"Nová: {f.total_cost_in_fixation:,.0f} Kč za {f.fixation_months} měs."
                )

    # Matice fixací
    st.subheader("Náklady pro různé délky fixace")
    st.caption("Celkové náklady (úroky + poplatky + přechod − bonus) za danou dobu.")
    fix_matrix = fixation_comparison_matrix(current, offers)
    if fix_matrix:
        df_fix = pd.DataFrame(fix_matrix)
        for col in df_fix.columns:
            if col != "Fixace (let)":
                df_fix[col] = df_fix[col].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "—")
        st.dataframe(df_fix, use_container_width=True, hide_index=True)

    # Grafy
    st.subheader("Grafy")

    fig_cum = go.Figure()
    if current:
        cc = cumulative_cost_schedule(current)
        fig_cum.add_trace(go.Scatter(x=[r.month for r in cc], y=[r.cumulative_total_cost for r in cc],
                                     name=f"{current.bank_name} (stávající)", line=dict(dash="dash", color="gray")))
    for p, s in zip(offers, summaries):
        cc = cumulative_cost_schedule(p)
        fig_cum.add_trace(go.Scatter(x=[r.month for r in cc], y=[r.cumulative_total_cost for r in cc], name=s.bank_name))
    fig_cum.update_layout(title="Kumulativní náklady v čase", xaxis_title="Měsíc", yaxis_title="Kč", hovermode="x")
    fig_cum.update_traces(hovertemplate="%{fullData.name}: %{y:,.0f} Kč<extra></extra>")
    st.plotly_chart(fig_cum, use_container_width=True)

    fig_bal = go.Figure()
    if current:
        sc = amortization_schedule(current)
        fig_bal.add_trace(go.Scatter(x=[r.month for r in sc], y=[r.remaining_balance for r in sc],
                                     name=f"{current.bank_name} (stávající)", line=dict(dash="dash", color="gray")))
    for p, s in zip(offers, summaries):
        sc = amortization_schedule(p)
        fig_bal.add_trace(go.Scatter(x=[r.month for r in sc], y=[r.remaining_balance for r in sc], name=s.bank_name))
    fig_bal.update_layout(title="Vývoj zůstatku úvěru", xaxis_title="Měsíc", yaxis_title="Kč", hovermode="x")
    fig_bal.update_traces(hovertemplate="%{fullData.name}: %{y:,.0f} Kč<extra></extra>")
    st.plotly_chart(fig_bal, use_container_width=True)

    if len(summaries) >= 2:
        fig_sav = go.Figure()
        names = [s.bank_name for s in summaries]
        diffs = [s.monthly_total - best.monthly_total for s in summaries]
        fig_sav.add_trace(go.Bar(x=names, y=diffs, marker_color=["#2ecc71" if d == 0 else "#e74c3c" for d in diffs]))
        fig_sav.update_layout(title=f"Měsíční přeplatek oproti {best.bank_name}", yaxis_title="Kč/měsíc")
        st.plotly_chart(fig_sav, use_container_width=True)

    # Podmínky
    all_with_conds = ([current] if current and current.conditions else []) + [p for p in offers if p.conditions]
    if all_with_conds:
        with st.expander("Podmínky bank"):
            for p in all_with_conds:
                label = f"{p.bank_name} (stávající)" if p is current else p.bank_name
                st.markdown(f"**{label}**")
                for c in p.conditions:
                    st.markdown(f"- {c}")


# ──────────────────────────────────────────────────────────────
# TAB 2: DETAIL NABÍDKY
# ──────────────────────────────────────────────────────────────
with _tab["Detail nabídky"]:
    st.header("Detail nabídky")

    opts = [s.bank_name for s in summaries]
    if current:
        opts.append(f"{current.bank_name} (stávající)")
    selected = st.selectbox("Vyberte nabídku", opts, key="detail_select")
    det_params, det_summary = _find_offer_by_name(selected, summaries, offers, current)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Měsíční splátka", f"{det_summary.monthly_payment:,.0f} Kč")
    c2.metric("RPSN", f"{det_summary.rpsn:.2f} %")
    c3.metric("Celkem úroky", f"{det_summary.total_interest:,.0f} Kč")
    if det_summary.fixation:
        c4.metric("Zůstatek po fixaci", f"{det_summary.fixation.remaining_balance:,.0f} Kč")

    sched = amortization_schedule(det_params)
    with st.expander("Splátkový kalendář"):
        df = pd.DataFrame([{"Měsíc": r.month, "Splátka": r.payment, "Jistina": r.principal_part,
                            "Úrok": r.interest_part, "Zůstatek": r.remaining_balance} for r in sched])
        st.dataframe(df, use_container_width=True, hide_index=True)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[r.month for r in sched], y=[r.principal_part for r in sched], name="Jistina", stackgroup="one"))
    fig.add_trace(go.Scatter(x=[r.month for r in sched], y=[r.interest_part for r in sched], name="Úrok", stackgroup="one"))
    fig.update_layout(title="Rozpad splátky v čase", xaxis_title="Měsíc", yaxis_title="Kč")
    st.plotly_chart(fig, use_container_width=True)

    dc = cumulative_cost_schedule(det_params)
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=[r.month for r in dc], y=[r.cumulative_interest for r in dc], name="Úroky", stackgroup="one"))
    fig2.add_trace(go.Scatter(x=[r.month for r in dc], y=[r.cumulative_additional for r in dc], name="Poplatky", stackgroup="one"))
    fig2.add_trace(go.Scatter(x=[r.month for r in dc], y=[r.cumulative_switching for r in dc], name="Přechod", stackgroup="one"))
    fig2.update_layout(title="Kumulativní náklady — rozpad", xaxis_title="Měsíc", yaxis_title="Kč")
    st.plotly_chart(fig2, use_container_width=True)

    # Porovnání se stávající
    if current and det_params is not current:
        st.subheader(f"Porovnání se stávající hypotékou ({current.bank_name})")
        ref = compare_refinancing(current, det_params)

        c1, c2, c3 = st.columns(3)
        for col, label_text, value, saving in [
            (c1, "Měsíčně", ref.monthly_saving, ref.monthly_saving),
            (c2, "Celkem", ref.total_saving, ref.total_saving),
        ]:
            tag = "úspora" if saving > 0 else "ztráta"
            col.metric(label_text, f"{abs(saving):,.0f} Kč {tag}",
                       delta=f"{saving:,.0f} Kč", delta_color="normal")
        if ref.fixation_saving is not None:
            tag = "úspora" if ref.fixation_saving > 0 else "ztráta"
            c3.metric(f"Za fixaci ({ref.new_offer.fixation_years} let)",
                      f"{abs(ref.fixation_saving):,.0f} Kč {tag}",
                      delta=f"{ref.fixation_saving:,.0f} Kč", delta_color="normal")

        if not det_params.is_current_bank:
            if ref.breakeven_month is not None and ref.breakeven_month > 0:
                y, m = divmod(ref.breakeven_month, 12)
                st.info(f"Náklady přechodu se vrátí za **{y} let {m} měsíců**.")
            elif ref.breakeven_month == 0:
                st.success("Bonus pokryje náklady přechodu — vyplatí se hned.")
            elif ref.total_saving > 0:
                st.info("Přechod se vyplatí, náklady jsou minimální.")
            else:
                st.warning("Přechod k jiné bance se nevyplatí.")


# ──────────────────────────────────────────────────────────────
# TAB 3: ČASOVÁ OSA
# ──────────────────────────────────────────────────────────────
with _tab["Časová osa"]:
    st.header("Průběh hypotéky v čase")

    past_schedule = st.session_state.get("_past_schedule", [])

    if not past_schedule:
        st.info(
            "Pro zobrazení časové osy nahrajte CSV splátkový kalendář z banky "
            "v sekci **Stávající hypotéka → Historie hypotéky**."
        )
    elif not offers:
        st.info("Zadejte alespoň jednu nabídku pro porovnání.")
    else:
        # Výběr nabídky pro budoucnost
        tl_opts = [s.bank_name for s in summaries]
        tl_sel = st.selectbox("Budoucí nabídka", tl_opts, key="tl_offer")
        tl_idx = tl_opts.index(tl_sel)
        tl_future_params = offers[tl_idx]

        # Budoucí splátky
        future_schedule = amortization_schedule(tl_future_params)
        month_offset = past_schedule[-1].month
        cum_interest_offset = past_schedule[-1].cumulative_interest
        cum_principal_offset = past_schedule[-1].cumulative_principal

        label = f"{tl_future_params.bank_name} ({tl_future_params.annual_rate:.2f} %)"
        from mortgage import TimelineRow as _TLR
        future_rows = []
        for row in future_schedule:
            future_rows.append(_TLR(
                month=month_offset + row.month,
                payment=row.payment,
                principal_part=row.principal_part,
                interest_part=row.interest_part,
                remaining_balance=row.remaining_balance,
                cumulative_interest=round(cum_interest_offset + row.cumulative_interest, 2),
                cumulative_principal=round(cum_principal_offset + row.cumulative_principal, 2),
                is_past=False,
                fixation_label=label,
            ))

        timeline = past_schedule + future_rows

        # Data pro grafy
        tl_data = []
        for row in timeline:
            tl_data.append({
                "Měsíc": row.month,
                "Zůstatek": row.remaining_balance,
                "Splátka": row.payment,
                "Úrok": row.interest_part,
                "Jistina": row.principal_part,
                "Kum. úroky": row.cumulative_interest,
                "Fixace": row.fixation_label,
                "Období": "Minulost" if row.is_past else "Budoucnost",
            })

        df_tl = pd.DataFrame(tl_data)
        now_month = past_schedule[-1].month

        # Graf zůstatku
        fig_bal = px.area(
            df_tl, x="Měsíc", y="Zůstatek", color="Fixace",
            title="Zůstatek jistiny v čase",
            labels={"Zůstatek": "Kč", "Měsíc": "Měsíc od začátku"},
        )
        fig_bal.add_vline(
            x=now_month, line_dash="dash", line_color="red",
            annotation_text="Teď")
        fig_bal.update_layout(height=400)
        st.plotly_chart(fig_bal, use_container_width=True)

        # Graf splátky
        fig_pmt = px.line(
            df_tl, x="Měsíc", y="Splátka", color="Fixace",
            title="Měsíční splátka v čase",
            labels={"Splátka": "Kč", "Měsíc": "Měsíc od začátku"},
        )
        fig_pmt.add_vline(
            x=now_month, line_dash="dash", line_color="red",
            annotation_text="Teď")
        fig_pmt.update_layout(height=300)
        st.plotly_chart(fig_pmt, use_container_width=True)

        # Souhrn fixací
        st.subheader("Přehled fixací")
        fix_labels = []
        seen = set()
        for row in timeline:
            if row.fixation_label not in seen:
                seen.add(row.fixation_label)
                fix_labels.append(row.fixation_label)

        fix_summary = []
        for fl in fix_labels:
            rows_in_fix = [r for r in timeline if r.fixation_label == fl]
            months = len(rows_in_fix)
            interest = sum(r.interest_part for r in rows_in_fix)
            principal = sum(r.principal_part for r in rows_in_fix)
            fix_summary.append({
                "Fixace": fl,
                "Měsíců": months,
                "Let": f"{months / 12:.1f}",
                "Zaplaceno úroky": f"{interest:,.0f} Kč",
                "Splaceno jistiny": f"{principal:,.0f} Kč",
            })

        st.table(pd.DataFrame(fix_summary))

        # Celkové souhrny
        total_interest = timeline[-1].cumulative_interest
        total_principal = timeline[-1].cumulative_principal
        c1, c2, c3 = st.columns(3)
        c1.metric("Celkem úroky", f"{total_interest:,.0f} Kč")
        c2.metric("Celkem splaceno jistiny", f"{total_principal:,.0f} Kč")
        c3.metric("Celkem zaplaceno", f"{total_interest + total_principal:,.0f} Kč")


# ──────────────────────────────────────────────────────────────
# TAB 4: CITLIVOSTNÍ ANALÝZA
# ──────────────────────────────────────────────────────────────
with _tab["Citlivostní analýza"]:
    st.header("Citlivostní analýza")

    sa_opts = [s.bank_name for s in summaries]
    if current:
        sa_opts.append(f"{current.bank_name} (stávající)")
    selected_sa = st.selectbox("Vyberte nabídku", sa_opts, key="sa_select")
    sa_params, _ = _find_offer_by_name(selected_sa, summaries, offers, current)

    st.caption(f"Jistina: {sa_params.principal:,.0f} Kč | Sazba: {sa_params.annual_rate:.2f} % | "
               f"Splácení: {sa_params.years} let | Fixace: {sa_params.fixation_years} let")

    c1, c2 = st.columns(2)
    with c1:
        sa_dmin = st.number_input("Odchylka sazby od (pp)", value=-2.0, step=0.5, key="sa_dmin")
    with c2:
        sa_dmax = st.number_input("Odchylka sazby do (pp)", value=2.0, step=0.5, key="sa_dmax")

    sa_results = sensitivity_analysis(sa_params, rate_range=(sa_dmin, sa_dmax))
    df_sa = pd.DataFrame(sa_results)
    df_sa.columns = ["Sazba %", "Delta (pp)", "Měsíční splátka", "Celkem zaplaceno", "Celkem úroky"]
    st.dataframe(df_sa, use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(px.line(df_sa, x="Sazba %", y="Měsíční splátka", title="Vliv sazby na splátku", markers=True)
                        .update_layout(yaxis_title="Kč"), use_container_width=True)
    with c2:
        st.plotly_chart(px.line(df_sa, x="Sazba %", y="Celkem úroky", title="Vliv sazby na úroky", markers=True)
                        .update_layout(yaxis_title="Kč"), use_container_width=True)

    st.subheader("Vliv doby splácení")
    yr_data = [{"Roky": y,
                "Měsíční splátka": round(monthly_payment(sa_params.principal, sa_params.annual_rate / 100 / 12, y * 12), 0),
                "Celkem úroky": round(monthly_payment(sa_params.principal, sa_params.annual_rate / 100 / 12, y * 12) * y * 12 - sa_params.principal, 0)}
               for y in range(5, 36)]
    df_yr = pd.DataFrame(yr_data)
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(px.line(df_yr, x="Roky", y="Měsíční splátka", title="Vliv doby na splátku", markers=True)
                        .update_layout(yaxis_title="Kč"), use_container_width=True)
    with c2:
        st.plotly_chart(px.line(df_yr, x="Roky", y="Celkem úroky", title="Vliv doby na úroky", markers=True)
                        .update_layout(yaxis_title="Kč"), use_container_width=True)


# ──────────────────────────────────────────────────────────────
# TAB 4: OPTIMÁLNÍ SPLÁTKA
# ──────────────────────────────────────────────────────────────
with _tab["Optimální splátka"]:
    st.header("Optimální splátka — splácet navíc, nebo investovat?")
    st.info("Pokud můžete investovat s vyšším výnosem než je sazba hypotéky, vyplatí se platit minimum a zbytek investovat.")

    opt_opts = [s.bank_name for s in summaries]
    if current:
        opt_opts.append(f"{current.bank_name} (stávající)")
    selected_opt = st.selectbox("Vyberte nabídku", opt_opts, key="opt_select")
    opt_params, _ = _find_offer_by_name(selected_opt, summaries, offers, current)

    base_pay = monthly_payment(opt_params.principal, opt_params.monthly_rate, opt_params.months)

    budget = st.number_input("Celkový měsíční budget (Kč)", min_value=0.0, value=round(base_pay * 1.5, 0),
                              step=1000.0, key="opt_budget", help=f"Minimální splátka: {base_pay:,.0f} Kč")
    if budget < base_pay:
        st.warning(f"Budget musí být alespoň {base_pay:,.0f} Kč. Používám minimum.")
        budget = base_pay

    c1, c2 = st.columns(2)
    with c1:
        inv_return = st.slider("Očekávaný výnos investice (% p.a.)", 0.0, 20.0, 7.0, 0.25, key="opt_return")
    with c2:
        inflation = st.slider("Inflace (% p.a.)", 0.0, 10.0, 2.5, 0.25, key="opt_inflation")

    try:
        be_rate = find_breakeven_investment_rate(opt_params, budget)
        st.metric("Break-even sazba investice", f"{be_rate:.2f} %",
                  help="Nad touto sazbou se vyplatí investovat místo splácet navíc.")

        if inv_return > be_rate:
            st.success(f"Při výnosu {inv_return:.1f} % se vyplatí **investovat** a platit minimum.")
        elif inv_return < be_rate:
            st.warning(f"Při výnosu {inv_return:.1f} % se vyplatí **splácet navíc**.")
        else:
            st.info("Výnos investice je na hraně.")

        results_opt = optimal_payment_analysis(opt_params, budget, inv_return, inflation)

        st.dataframe(pd.DataFrame([{
            "Strategie": r.strategy_name,
            "Splátka": f"{r.monthly_mortgage_payment:,.0f}",
            "Investice": f"{r.monthly_investment:,.0f}",
            "Splaceno za": f"{r.months_to_payoff // 12} let {r.months_to_payoff % 12} měs.",
            "Úroky celkem": f"{r.total_interest_paid:,.0f}",
            "Hodnota investice": f"{r.investment_value_at_end:,.0f}",
            "Čistý majetek": f"{r.net_wealth_at_end:,.0f}",
        } for r in results_opt]), use_container_width=True, hide_index=True)

        fig_w = go.Figure()
        for r in results_opt:
            fig_w.add_trace(go.Scatter(x=[t["month"] for t in r.timeline], y=[t["net_wealth"] for t in r.timeline],
                                       name=r.strategy_name, mode="lines+markers"))
        fig_w.update_layout(title="Vývoj čistého majetku", xaxis_title="Měsíc", yaxis_title="Kč")
        st.plotly_chart(fig_w, use_container_width=True)

        best_w = max(r.net_wealth_at_end for r in results_opt)
        fig_b = go.Figure()
        fig_b.add_trace(go.Bar(x=[r.strategy_name for r in results_opt], y=[r.net_wealth_at_end for r in results_opt],
                               marker_color=["#2ecc71" if r.net_wealth_at_end == best_w else "#3498db" for r in results_opt]))
        fig_b.update_layout(title="Čistý majetek na konci", yaxis_title="Kč")
        st.plotly_chart(fig_b, use_container_width=True)

    except Exception as e:
        st.error(f"Chyba při výpočtu: {e}")


# ──────────────────────────────────────────────────────────────
# TAB 5: EXPORT / IMPORT
# ──────────────────────────────────────────────────────────────
with _tab["Export / Import"]:
    st.header("Export / Import dat")

    st.subheader("Export")
    json_data = export_json(st.session_state.current_mortgage, st.session_state.offers)
    st.download_button("Stáhnout JSON", data=json_data, file_name="hypoteka_data.json", mime="application/json")

    all_sums = ([calculate_summary(current)] if current else []) + summaries
    st.download_button("Stáhnout CSV", data=summaries_to_csv(all_sums), file_name="hypoteka_srovnani.csv", mime="text/csv")

    with st.expander("Náhled JSON"):
        st.json(json_data)

    st.subheader("Import")
    uploaded = st.file_uploader("Nahrát JSON soubor", type=["json"], key="import_file")
    if uploaded is not None:
        try:
            st.session_state["_pending_import"] = import_json(uploaded.read().decode("utf-8"))
            st.rerun()
        except Exception as e:
            st.error(f"Chyba při importu: {e}")
