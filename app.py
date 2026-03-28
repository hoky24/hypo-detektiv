"""Hypoteční kalkulačka — Streamlit aplikace."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from mortgage import (
    MortgageParams,
    AdditionalCost,
    amortization_schedule,
    calculate_summary,
    compare_refinancing,
    cumulative_cost_schedule,
    fixation_comparison_matrix,
    monthly_payment,
    sensitivity_analysis,
    optimal_payment_analysis,
    find_breakeven_investment_rate,
)
from data_io import export_json, import_json, summaries_to_csv

st.set_page_config(page_title="Hypoteční kalkulačka", page_icon="🏠", layout="wide")
st.title("Hypoteční kalkulačka")

# --- Pomocná funkce pro import (musí být před session state blokem) ---

def _populate_widget_keys(current_mortgage, offers_list):
    """Nastaví widgetové klíče v session state podle importovaných dat."""
    if current_mortgage:
        st.session_state["has_current"] = True
        st.session_state["cur_bank"] = current_mortgage.bank_name
        st.session_state["cur_principal"] = current_mortgage.principal
        st.session_state["cur_rate"] = current_mortgage.annual_rate
        st.session_state["cur_years"] = current_mortgage.years
        st.session_state["cur_fix"] = current_mortgage.fixation_years
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


# --- Session state ---
if "current_mortgage" not in st.session_state:
    st.session_state.current_mortgage = None
if "offers" not in st.session_state:
    st.session_state.offers = []

# --- Zpracování čekajícího importu (PŘED vykreslením widgetů) ---
if "_pending_import" in st.session_state:
    imported = st.session_state.pop("_pending_import")
    cur = imported.get("current_mortgage")
    off = imported.get("offers", [])
    _populate_widget_keys(cur, off)
    st.session_state.current_mortgage = cur
    st.session_state.offers = off
    st.rerun()


# ============================================================
# POMOCNÉ FUNKCE PRO FORMULÁŘE
# ============================================================

def render_additional_costs(key_prefix: str, label: str = "Dodatečné náklady") -> list[AdditionalCost]:
    """Editor dodatečných nákladů."""
    costs = []
    st.markdown(f"**{label}**")
    presets = {
        "Pojištění nemovitosti": (200, 0),
        "Životní pojištění": (300, 0),
        "Poplatek za vedení účtu": (100, 0),
        "Poplatek za správu úvěru": (150, 0),
    }
    selected = st.multiselect(
        "Rychlý výběr", options=list(presets.keys()), key=f"{key_prefix}_presets",
    )
    for name in selected:
        m_def, o_def = presets[name]
        c1, c2 = st.columns(2)
        with c1:
            m = st.number_input(f"{name} — měsíčně (Kč)", min_value=0.0, value=float(m_def), step=50.0, key=f"{key_prefix}_{name}_m")
        with c2:
            o = st.number_input(f"{name} — jednorázově (Kč)", min_value=0.0, value=float(o_def), step=500.0, key=f"{key_prefix}_{name}_o")
        costs.append(AdditionalCost(name=name, monthly_amount=m, one_time_amount=o))

    n_custom = st.number_input("Vlastní položky", min_value=0, max_value=10, value=0, key=f"{key_prefix}_n_custom")
    for i in range(n_custom):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            name = st.text_input(f"Název #{i+1}", key=f"{key_prefix}_cname_{i}")
        with c2:
            m = st.number_input(f"Měsíčně #{i+1}", min_value=0.0, step=50.0, key=f"{key_prefix}_cm_{i}")
        with c3:
            o = st.number_input(f"Jednorázově #{i+1}", min_value=0.0, step=500.0, key=f"{key_prefix}_co_{i}")
        if name:
            costs.append(AdditionalCost(name=name, monthly_amount=m, one_time_amount=o))
    return costs


def render_switching_costs(key_prefix: str) -> list[AdditionalCost]:
    """Editor nákladů na přechod k jiné bance."""
    costs = []
    st.markdown("**Náklady na přechod**")
    presets = {
        "Posouzení vhodnosti zástavy (odhad)": (0, 3000),
        "Zápis zástavního práva — el. podání (ČÚZK)": (0, 1600),
        "Zpracování el. podpisů zástavní smlouvy": (0, 400),
        "Ověření podpisu na zástavní smlouvě": (0, 50),
        "Výmaz zástavního práva — el. podání (ČÚZK)": (0, 1600),
        "Poplatek za předčasné splacení (stará banka)": (0, 0),
    }
    selected = st.multiselect(
        "Náklady přechodu", options=list(presets.keys()), default=list(presets.keys()),
        key=f"{key_prefix}_sw_presets",
    )
    for name in selected:
        _, o_def = presets[name]
        val = st.number_input(f"{name} (Kč)", min_value=0.0, value=float(o_def), step=500.0, key=f"{key_prefix}_sw_{name}")
        costs.append(AdditionalCost(name=name, one_time_amount=val))
    return costs


def render_conditions(key_prefix: str) -> list[str]:
    """Editor podmínek banky."""
    conditions = []
    cond_presets = {
        "Běžný účet u banky s min. příjmem": "Splácení z běžného účtu u banky, min. kreditní příjem 15 000 Kč/měsíc",
        "Pojištění nemovitosti": "Nemovitost musí být pojištěna po celou dobu trvání úvěru",
        "Životní pojištění": "Banka vyžaduje/doporučuje životní pojištění (sleva na sazbě)",
    }
    sel = st.multiselect("Běžné podmínky", options=list(cond_presets.keys()), key=f"{key_prefix}_cond_pre")
    for c in sel:
        text = st.text_input(c, value=cond_presets[c], key=f"{key_prefix}_cond_{c}")
        conditions.append(text)
    custom = st.text_area("Další podmínky", key=f"{key_prefix}_cond_txt")
    if custom.strip():
        conditions.append(custom.strip())
    return conditions




# ============================================================
# VSTUPNÍ DATA (HORNÍ SEKCE)
# ============================================================

with st.expander("Vstupní data", expanded=not st.session_state.offers):
    has_current = st.checkbox("Mám stávající hypotéku", key="has_current")

    if has_current:
        st.subheader("Stávající hypotéka")
        cur_bank = st.text_input("Stávající banka", value="Moje banka", key="cur_bank")
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        with c1:
            cur_principal = st.number_input("Zbývající jistina (Kč)", min_value=100_000.0, max_value=50_000_000.0, value=2_000_000.0, step=100_000.0, key="cur_principal")
        with c2:
            cur_rate = st.number_input("Aktuální sazba (%)", min_value=0.0, max_value=20.0, value=5.5, step=0.1, format="%.2f", key="cur_rate")
        with c3:
            cur_years = st.number_input("Zbývající doba (roky)", min_value=1, max_value=40, value=20, key="cur_years")
        with c4:
            cur_fix = st.number_input("Zbývající fixace (roky)", min_value=0, max_value=15, value=0, key="cur_fix")

        with st.expander("Poplatky stávající hypotéky"):
            cur_costs = render_additional_costs("cur_ac", "Stávající poplatky/pojištění")

        st.session_state.current_mortgage = MortgageParams(
            principal=cur_principal, annual_rate=cur_rate, years=cur_years,
            bank_name=cur_bank, additional_costs=cur_costs,
            is_current_bank=True, fixation_years=cur_fix,
        )
    else:
        st.session_state.current_mortgage = None

    st.divider()
    st.subheader("Nabídky bank")
    n_offers = st.number_input("Počet nabídek", min_value=1, max_value=10, value=2, key="n_offers")

    offers = []
    for i in range(n_offers):
        with st.expander(f"Nabídka {i+1}", expanded=(i < 2)):
            bank = st.text_input("Banka", key=f"o{i}_bank")
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            with c1:
                principal = st.number_input("Výše úvěru (Kč)", min_value=100_000.0, max_value=50_000_000.0,
                    value=cur_principal if has_current else 3_000_000.0,
                    step=100_000.0, key=f"o{i}_principal")
            with c2:
                rate = st.number_input("Sazba (%)", min_value=0.0, max_value=20.0, value=5.0, step=0.1, format="%.2f", key=f"o{i}_rate")
            with c3:
                years = st.number_input("Splácení (roky)", min_value=1, max_value=40, value=cur_years if has_current else 25, key=f"o{i}_years")
            with c4:
                fix = st.number_input("Fixace (roky)", min_value=0, max_value=15, value=5, key=f"o{i}_fix")

            is_cur_bank = False
            switching = []
            if has_current:
                is_cur_bank = st.checkbox("Nabídka od stávající banky", key=f"o{i}_is_cur")
                if not is_cur_bank:
                    switching = render_switching_costs(f"o{i}")

            additional = render_additional_costs(f"o{i}_ac")

            bonus = st.number_input("Bonus / odměna od banky (Kč)", min_value=0.0, value=0.0, step=1000.0, key=f"o{i}_bonus",
                                    help="Jednorázová odměna za sjednání hypotéky (snižuje celkové náklady)")

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

# Připravit souhrny
summaries = [calculate_summary(p) for p in offers]

tab_names = ["Přehled"]
if current:
    tab_names.append("Refinancování")
tab_names += ["Citlivostní analýza", "Optimální splátka", "Export / Import"]
all_tabs = st.tabs(tab_names)
_tab = {name: tab for name, tab in zip(tab_names, all_tabs)}


# --- TAB: Přehled ---
with _tab["Přehled"]:
    st.header("Srovnání nabídek")

    comparison = []
    for s in summaries:
        row = {
            "Banka": s.bank_name,
            "Sazba %": s.annual_rate,
            "Fixace": f"{s.fixation_years} let",
            "Splácení": f"{s.years} let",
            "Měsíční splátka": f"{s.monthly_payment:,.0f}",
            "Měsíční celkem": f"{s.monthly_total:,.0f}",
            "Celkem úroky": f"{s.total_interest:,.0f}",
            "Poplatky": f"{s.total_additional_costs:,.0f}",
        }
        if any(s.total_switching_costs > 0 for s in summaries):
            row["Přechod"] = f"{s.total_switching_costs:,.0f}"
        if any(s.bonus > 0 for s in summaries):
            row["Bonus"] = f"−{s.bonus:,.0f}" if s.bonus else "—"
        row["Celkové náklady"] = f"{s.total_cost:,.0f}"
        if s.fixation:
            row["Náklady za fixaci"] = f"{s.fixation.total_cost_in_fixation:,.0f}"
        comparison.append(row)
    st.dataframe(pd.DataFrame(comparison), use_container_width=True, hide_index=True)

    # Grafy
    col1, col2 = st.columns(2)
    with col1:
        chart_data = pd.DataFrame(
            [{"Banka": s.bank_name, "Typ": "Úroky", "Kč": s.total_interest} for s in summaries] +
            [{"Banka": s.bank_name, "Typ": "Poplatky", "Kč": s.total_additional_costs} for s in summaries] +
            [{"Banka": s.bank_name, "Typ": "Přechod", "Kč": s.total_switching_costs} for s in summaries if s.total_switching_costs > 0]
        )
        fig = px.bar(chart_data, x="Banka", y="Kč", color="Typ", barmode="stack", title="Celkové náklady")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig2 = go.Figure()
        for p, s in zip(offers, summaries):
            sched = amortization_schedule(p)
            fig2.add_trace(go.Scatter(
                x=[r.month for r in sched], y=[r.remaining_balance for r in sched],
                name=s.bank_name,
            ))
        fig2.update_layout(title="Vývoj zůstatku", xaxis_title="Měsíc", yaxis_title="Kč")
        st.plotly_chart(fig2, use_container_width=True)

    # Splátkový kalendář pro vybranou nabídku
    selected_name = st.selectbox("Splátkový kalendář", [s.bank_name for s in summaries], key="overview_sched")
    idx = next(i for i, s in enumerate(summaries) if s.bank_name == selected_name)
    sched = amortization_schedule(offers[idx])
    with st.expander("Zobrazit splátkový kalendář"):
        df = pd.DataFrame([{
            "Měsíc": r.month, "Splátka": r.payment, "Jistina": r.principal_part,
            "Úrok": r.interest_part, "Zůstatek": r.remaining_balance,
        } for r in sched])
        st.dataframe(df, use_container_width=True, hide_index=True)
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=df["Měsíc"], y=df["Jistina"], name="Jistina", stackgroup="one"))
        fig3.add_trace(go.Scatter(x=df["Měsíc"], y=df["Úrok"], name="Úrok", stackgroup="one"))
        fig3.update_layout(title="Rozpad splátky", xaxis_title="Měsíc", yaxis_title="Kč")
        st.plotly_chart(fig3, use_container_width=True)

    # Podmínky
    has_conds = any(p.conditions for p in offers)
    if has_conds:
        with st.expander("Podmínky bank"):
            for p in offers:
                if p.conditions:
                    st.markdown(f"**{p.bank_name}**")
                    for c in p.conditions:
                        st.markdown(f"- {c}")



# --- TAB: Refinancování ---
if current:
    with _tab["Refinancování"]:
        st.header("Refinancování hypotéky")

        cur_summary = calculate_summary(current)
        ref_results = [compare_refinancing(current, o) for o in offers]

        # Srovnávací tabulka
        table = []
        all_summaries_ref = [cur_summary] + [r.new_offer for r in ref_results]
        for i, s in enumerate(all_summaries_ref):
            label = s.bank_name + (" (stávající)" if i == 0 else "")
            table.append({
                "Nabídka": label,
                "Sazba %": s.annual_rate,
                "Fixace": f"{s.fixation_years} let" if s.fixation_years else "—",
                "Měsíční splátka": f"{s.monthly_payment:,.0f}",
                "Měsíční celkem": f"{s.monthly_total:,.0f}",
                "Celkem úroky": f"{s.total_interest:,.0f}",
                "Poplatky": f"{s.total_additional_costs:,.0f}",
                "Přechod": f"{s.total_switching_costs:,.0f}",
                "Bonus": f"−{s.bonus:,.0f}" if s.bonus else "—",
                "Celkové náklady": f"{s.total_cost:,.0f}",
            })
        st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)

        # === ÚSPORY OPROTI STÁVAJÍCÍ ===
        any_positive = any(r.total_saving > 0 for r in ref_results)
        any_negative = any(r.total_saving < 0 for r in ref_results)

        if any_negative and not any_positive:
            st.error("Refinancování se u žádné nabídky nevyplatí — stávající hypotéka je levnější.")
        elif any_positive and not any_negative:
            st.success("Refinancování se vyplatí u všech nabídek.")

        st.subheader("Porovnání s aktuální hypotékou")
        for r in ref_results:
            label = r.new_offer.bank_name
            if r.new_offer.is_current_bank:
                label += " (nová sazba)"

            profitable = r.total_saving > 0
            saving_label = "úspora" if profitable else "ztráta"

            cols = st.columns(4)
            cols[0].metric(
                f"{label} — měsíčně",
                f"{abs(r.monthly_saving):,.0f} Kč {saving_label}",
                delta=f"{r.monthly_saving:,.0f} Kč/měs",
                delta_color="normal",
            )
            cols[1].metric(
                "Celkem za dobu splácení",
                f"{abs(r.total_saving):,.0f} Kč {saving_label}",
                delta=f"{r.total_saving:,.0f} Kč",
                delta_color="normal",
            )

            if r.fixation_saving is not None:
                fix_label = "úspora" if r.fixation_saving > 0 else "ztráta"
                cols[2].metric(
                    f"Za fixaci ({r.new_offer.fixation_years} let)",
                    f"{abs(r.fixation_saving):,.0f} Kč {fix_label}",
                    delta=f"{r.fixation_saving:,.0f} Kč",
                    delta_color="normal",
                )

            # Bod zvratu — jen pro nabídky od jiné banky s kladnou úsporou
            if not r.new_offer.is_current_bank:
                if not profitable:
                    cols[3].metric("Přechod k jiné bance", "Nevyplatí se")
                elif r.breakeven_month is not None and r.breakeven_month > 0:
                    y = r.breakeven_month // 12
                    m = r.breakeven_month % 12
                    cols[3].metric(
                        "Náklady přechodu se vrátí za",
                        f"{y} let {m} měs.",
                        help="Za kolik měsíců se náklady na přechod zaplatí z úspory na úrocích a poplatcích",
                    )
                elif r.breakeven_month == 0:
                    cols[3].metric("Náklady přechodu", "Pokryje bonus")

        # === SROVNÁNÍ NOVÝCH NABÍDEK MEZI SEBOU ===
        if len(offers) >= 2:
            st.subheader("Srovnání nových nabídek mezi sebou")
            st.caption("Bez ohledu na stávající hypotéku — která z nových nabídek je nejlevnější?")

            best_idx = min(range(len(summaries)), key=lambda i: summaries[i].total_cost)
            best = summaries[best_idx]

            diff_table = []
            for i, s in enumerate(summaries):
                diff_total = s.total_cost - best.total_cost
                diff_monthly = s.monthly_total - best.monthly_total
                row = {
                    "Nabídka": s.bank_name,
                    "Sazba %": s.annual_rate,
                    "Fixace": f"{s.fixation_years} let" if s.fixation_years else "—",
                    "Měsíční celkem": f"{s.monthly_total:,.0f}",
                    "Celkové náklady": f"{s.total_cost:,.0f}",
                }
                if i == best_idx:
                    row["Hodnocení"] = "Nejlevnější"
                else:
                    row["Hodnocení"] = f"+{diff_total:,.0f} Kč celkem (+{diff_monthly:,.0f} Kč/měs)"
                diff_table.append(row)
            st.dataframe(pd.DataFrame(diff_table), use_container_width=True, hide_index=True)

        # === MATICE FIXACÍ ===
        st.subheader("Srovnání nákladů pro různé délky fixace")
        st.caption("Celkové náklady (úroky + poplatky + přechod − bonus) za danou dobu fixace. "
                   "Umožňuje férové srovnání nabídek s různou délkou fixace.")
        fix_matrix = fixation_comparison_matrix(current, offers)
        if fix_matrix:
            df_fix = pd.DataFrame(fix_matrix)
            # Formátovat čísla
            for col in df_fix.columns:
                if col != "Fixace (let)":
                    df_fix[col] = df_fix[col].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "—")
            st.dataframe(df_fix, use_container_width=True, hide_index=True)

        # --- GRAFY ---
        st.subheader("Grafy")

        # Graf 1: Kumulativní náklady v čase
        fig_cum = go.Figure()
        cur_costs_sched = cumulative_cost_schedule(current)
        fig_cum.add_trace(go.Scatter(
            x=[r.month for r in cur_costs_sched],
            y=[r.cumulative_total_cost for r in cur_costs_sched],
            name=f"{current.bank_name} (stávající)",
            line=dict(dash="dash"),
        ))
        for o, r in zip(offers, ref_results):
            new_costs_sched = cumulative_cost_schedule(o)
            fig_cum.add_trace(go.Scatter(
                x=[r2.month for r2 in new_costs_sched],
                y=[r2.cumulative_total_cost for r2 in new_costs_sched],
                name=o.bank_name,
            ))
            if r.breakeven_month and r.breakeven_month > 0:
                fig_cum.add_vline(x=r.breakeven_month, line_dash="dot",
                                  annotation_text=f"{o.bank_name}: {r.breakeven_month} měs.",
                                  annotation_position="top left")
        fig_cum.update_layout(
            title="Kumulativní náklady v čase",
            xaxis_title="Měsíc", yaxis_title="Kč", hovermode="x",
        )
        fig_cum.update_traces(hovertemplate="%{fullData.name}: %{y:,.0f} Kč<extra></extra>")
        st.plotly_chart(fig_cum, use_container_width=True)

        # Graf 2: Vývoj zůstatku
        fig_bal = go.Figure()
        cur_sched = amortization_schedule(current)
        fig_bal.add_trace(go.Scatter(
            x=[r.month for r in cur_sched], y=[r.remaining_balance for r in cur_sched],
            name=f"{current.bank_name} (stávající)", line=dict(dash="dash"),
        ))
        for p, s in zip(offers, summaries):
            sched = amortization_schedule(p)
            fig_bal.add_trace(go.Scatter(
                x=[r.month for r in sched], y=[r.remaining_balance for r in sched],
                name=s.bank_name,
            ))
        fig_bal.update_layout(title="Vývoj zůstatku úvěru", xaxis_title="Měsíc", yaxis_title="Kč", hovermode="x")
        fig_bal.update_traces(hovertemplate="%{fullData.name}: %{y:,.0f} Kč<extra></extra>")
        st.plotly_chart(fig_bal, use_container_width=True)

        # Graf 3: Rozpad nákladů
        sel_ref = st.selectbox("Rozpad nákladů pro nabídku", [s.bank_name for s in summaries], key="ref_detail")
        idx_ref = next(i for i, s in enumerate(summaries) if s.bank_name == sel_ref)
        detail_costs = cumulative_cost_schedule(offers[idx_ref])
        df_detail = pd.DataFrame([{
            "Měsíc": r.month,
            "Úroky": r.cumulative_interest,
            "Poplatky": r.cumulative_additional,
            "Přechod": r.cumulative_switching,
        } for r in detail_costs])

        fig_stack = go.Figure()
        fig_stack.add_trace(go.Scatter(x=df_detail["Měsíc"], y=df_detail["Úroky"], name="Úroky", stackgroup="one"))
        fig_stack.add_trace(go.Scatter(x=df_detail["Měsíc"], y=df_detail["Poplatky"], name="Poplatky", stackgroup="one"))
        fig_stack.add_trace(go.Scatter(x=df_detail["Měsíc"], y=df_detail["Přechod"], name="Přechod", stackgroup="one"))
        fig_stack.update_layout(title=f"Rozpad nákladů — {sel_ref}", xaxis_title="Měsíc", yaxis_title="Kč")
        st.plotly_chart(fig_stack, use_container_width=True)

        # Graf 4: Měsíční úspora
        fig_savings = go.Figure()
        saving_names = []
        saving_values = []
        for r in ref_results:
            label = r.new_offer.bank_name
            if r.new_offer.is_current_bank:
                label += " (nová sazba)"
            saving_names.append(label)
            saving_values.append(r.monthly_saving)
        colors = ["green" if v > 0 else "red" for v in saving_values]
        fig_savings.add_trace(go.Bar(x=saving_names, y=saving_values, marker_color=colors))
        fig_savings.update_layout(title="Měsíční úspora oproti stávající hypotéce", yaxis_title="Kč/měsíc")
        st.plotly_chart(fig_savings, use_container_width=True)

        # Podmínky
        all_params = [current] + offers
        has_conds = any(p.conditions for p in all_params)
        if has_conds:
            with st.expander("Podmínky bank"):
                for p in all_params:
                    if p.conditions:
                        st.markdown(f"**{p.bank_name}**")
                        for c in p.conditions:
                            st.markdown(f"- {c}")



# --- TAB: Citlivostní analýza ---
with _tab["Citlivostní analýza"]:
    st.header("Citlivostní analýza")

    # Výběr nabídky
    all_options = []
    if current:
        all_options.append(f"{current.bank_name} (stávající)")
    all_options += [s.bank_name for s in summaries]

    selected_sa = st.selectbox("Vyberte nabídku", all_options, key="sa_select")

    if current and selected_sa == f"{current.bank_name} (stávající)":
        sa_params = current
    else:
        idx_sa = next(i for i, s in enumerate(summaries) if s.bank_name == selected_sa)
        sa_params = offers[idx_sa]

    st.caption(f"Jistina: {sa_params.principal:,.0f} Kč | Sazba: {sa_params.annual_rate:.2f} % | "
               f"Splácení: {sa_params.years} let | Fixace: {sa_params.fixation_years} let")

    c1, c2 = st.columns(2)
    with c1:
        sa_delta_min = st.number_input("Odchylka sazby od (pp)", value=-2.0, step=0.5, key="sa_dmin")
    with c2:
        sa_delta_max = st.number_input("Odchylka sazby do (pp)", value=2.0, step=0.5, key="sa_dmax")

    results = sensitivity_analysis(sa_params, rate_range=(sa_delta_min, sa_delta_max))
    df = pd.DataFrame(results)
    df.columns = ["Sazba %", "Delta (pp)", "Měsíční splátka", "Celkem zaplaceno", "Celkem úroky"]
    st.dataframe(df, use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        fig = px.line(df, x="Sazba %", y="Měsíční splátka", title="Vliv sazby na splátku", markers=True)
        fig.update_layout(yaxis_title="Kč")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig2 = px.line(df, x="Sazba %", y="Celkem úroky", title="Vliv sazby na celkové úroky", markers=True)
        fig2.update_layout(yaxis_title="Kč")
        st.plotly_chart(fig2, use_container_width=True)

    # Vliv doby splácení
    st.subheader("Vliv doby splácení")
    year_data = []
    for y in range(5, 36):
        months = y * 12
        mr = sa_params.annual_rate / 100 / 12
        p = monthly_payment(sa_params.principal, mr, months)
        total = p * months
        year_data.append({"Roky": y, "Měsíční splátka": round(p, 0), "Celkem úroky": round(total - sa_params.principal, 0)})
    df_years = pd.DataFrame(year_data)

    c1, c2 = st.columns(2)
    with c1:
        fig3 = px.line(df_years, x="Roky", y="Měsíční splátka", title="Vliv doby na splátku", markers=True)
        fig3.update_layout(yaxis_title="Kč")
        st.plotly_chart(fig3, use_container_width=True)
    with c2:
        fig4 = px.line(df_years, x="Roky", y="Celkem úroky", title="Vliv doby na úroky", markers=True)
        fig4.update_layout(yaxis_title="Kč")
        st.plotly_chart(fig4, use_container_width=True)



# --- TAB: Optimální splátka ---
with _tab["Optimální splátka"]:
    st.header("Optimální splátka — splácet navíc, nebo investovat?")

    st.info(
        "Pokud můžete investovat s vyšším výnosem než je sazba hypotéky, vyplatí se platit minimum "
        "a zbytek investovat. Tento model porovnává různé strategie."
    )

    # Výběr nabídky
    opt_options = []
    if current:
        opt_options.append(f"{current.bank_name} (stávající)")
    opt_options += [s.bank_name for s in summaries]
    selected_opt = st.selectbox("Vyberte nabídku", opt_options, key="opt_select")

    if current and selected_opt == f"{current.bank_name} (stávající)":
        opt_params = current
    else:
        idx_opt = next(i for i, s in enumerate(summaries) if s.bank_name == selected_opt)
        opt_params = offers[idx_opt]

    base_pay = monthly_payment(opt_params.principal, opt_params.monthly_rate, opt_params.months)

    budget = st.number_input(
        "Celkový měsíční budget (Kč)",
        min_value=0.0,
        value=round(base_pay * 1.5, 0),
        step=1000.0, key="opt_budget",
        help=f"Minimální splátka: {base_pay:,.0f} Kč. Zadejte kolik celkem můžete měsíčně alokovat.",
    )
    # Zajistit, že budget >= minimální splátka
    if budget < base_pay:
        st.warning(f"Budget musí být alespoň {base_pay:,.0f} Kč (minimální splátka). Používám minimum.")
        budget = base_pay

    c1, c2 = st.columns(2)
    with c1:
        inv_return = st.slider("Očekávaný výnos investice (% p.a.)", min_value=0.0, max_value=20.0, value=7.0, step=0.25, key="opt_return")
    with c2:
        inflation = st.slider("Inflace (% p.a.)", min_value=0.0, max_value=10.0, value=2.5, step=0.25, key="opt_inflation")

    try:
        # Break-even sazba
        breakeven_rate = find_breakeven_investment_rate(opt_params, budget)
        st.metric("Break-even sazba investice", f"{breakeven_rate:.2f} %",
                  help="Nad touto sazbou se vyplatí investovat místo splácet navíc.")

        if inv_return > breakeven_rate:
            st.success(f"Při výnosu {inv_return:.1f} % se vyplatí **investovat** a platit minimum na hypotéce.")
        elif inv_return < breakeven_rate:
            st.warning(f"Při výnosu {inv_return:.1f} % se vyplatí **splácet navíc** na hypotéce.")
        else:
            st.info("Výnos investice je na hraně — obě strategie vycházejí podobně.")

        # Simulace
        results_opt = optimal_payment_analysis(opt_params, budget, inv_return, inflation)

        # Tabulka strategií
        strat_table = []
        for r in results_opt:
            strat_table.append({
                "Strategie": r.strategy_name,
                "Splátka hypotéky": f"{r.monthly_mortgage_payment:,.0f}",
                "Investice měsíčně": f"{r.monthly_investment:,.0f}",
                "Splaceno za": f"{r.months_to_payoff // 12} let {r.months_to_payoff % 12} měs.",
                "Zaplaceno úroky": f"{r.total_interest_paid:,.0f}",
                "Hodnota investice": f"{r.investment_value_at_end:,.0f}",
                "Čistý majetek": f"{r.net_wealth_at_end:,.0f}",
            })
        st.dataframe(pd.DataFrame(strat_table), use_container_width=True, hide_index=True)

        # Graf: čistý majetek v čase
        fig_wealth = go.Figure()
        for r in results_opt:
            fig_wealth.add_trace(go.Scatter(
                x=[t["month"] for t in r.timeline],
                y=[t["net_wealth"] for t in r.timeline],
                name=r.strategy_name,
                mode="lines+markers",
            ))
        fig_wealth.update_layout(
            title="Vývoj čistého majetku (investice − zaplacené úroky)",
            xaxis_title="Měsíc", yaxis_title="Kč",
        )
        st.plotly_chart(fig_wealth, use_container_width=True)

        # Graf: porovnání konečného majetku
        fig_bar = go.Figure()
        best_wealth = max(r.net_wealth_at_end for r in results_opt)
        fig_bar.add_trace(go.Bar(
            x=[r.strategy_name for r in results_opt],
            y=[r.net_wealth_at_end for r in results_opt],
            marker_color=["#2ecc71" if r.net_wealth_at_end == best_wealth else "#3498db" for r in results_opt],
        ))
        fig_bar.update_layout(title="Čistý majetek na konci", yaxis_title="Kč")
        st.plotly_chart(fig_bar, use_container_width=True)

    except Exception as e:
        st.error(f"Chyba při výpočtu: {e}")



# --- TAB: Export / Import ---
with _tab["Export / Import"]:
    st.header("Export / Import dat")

    st.subheader("Export")
    json_data = export_json(st.session_state.current_mortgage, st.session_state.offers)
    st.download_button(
        "Stáhnout JSON", data=json_data, file_name="hypoteka_data.json", mime="application/json",
    )

    all_sums = []
    if current:
        all_sums.append(calculate_summary(current))
    all_sums += summaries
    csv_data = summaries_to_csv(all_sums)
    st.download_button(
        "Stáhnout CSV", data=csv_data, file_name="hypoteka_srovnani.csv", mime="text/csv",
    )

    with st.expander("Náhled JSON"):
        st.json(json_data)

    st.subheader("Import")
    uploaded = st.file_uploader("Nahrát JSON soubor", type=["json"], key="import_file")
    if uploaded is not None:
        try:
            content = uploaded.read().decode("utf-8")
            imported = import_json(content)
            # Uložit do pending — zpracuje se na začátku dalšího rerunu,
            # PŘED vykreslením widgetů (jinak Streamlit zahlásí chybu)
            st.session_state["_pending_import"] = imported
            st.rerun()
        except Exception as e:
            st.error(f"Chyba při importu: {e}")
