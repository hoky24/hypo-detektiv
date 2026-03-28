"""Hypoteční kalkulačka — Streamlit aplikace."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from mortgage import (
    MortgageParams,
    AdditionalCost,
    amortization_schedule,
    calculate_fixation_summary,
    calculate_summary,
    compare_refinancing,
    monthly_payment,
    sensitivity_analysis,
)
from data_io import (
    export_json,
    import_json,
    params_to_dict,
    summaries_to_csv,
)

st.set_page_config(
    page_title="Hypoteční kalkulačka",
    page_icon="🏠",
    layout="wide",
)

st.title("Hypoteční kalkulačka")

# --- Session state inicializace ---
if "offers" not in st.session_state:
    st.session_state.offers = []
if "refinancing" not in st.session_state:
    st.session_state.refinancing = {}  # {"current": params, "new_offers": [params, ...]}


# === Pomocné funkce pro UI ===

def render_additional_costs(key_prefix: str, label: str = "Dodatečné náklady") -> list[AdditionalCost]:
    """Renderuje editor dodatečných nákladů."""
    costs = []
    st.markdown(f"**{label}**")
    presets = {
        "Pojištění nemovitosti": (200, 0),
        "Životní pojištění": (300, 0),
        "Poplatek za vedení účtu": (100, 0),
        "Poplatek za správu úvěru": (150, 0),
    }
    selected = st.multiselect(
        "Rychlý výběr nákladů",
        options=list(presets.keys()),
        key=f"{key_prefix}_presets",
    )
    for name in selected:
        monthly_default, onetime_default = presets[name]
        col1, col2 = st.columns(2)
        with col1:
            m = st.number_input(
                f"{name} — měsíčně (Kč)",
                min_value=0.0, value=float(monthly_default), step=50.0,
                key=f"{key_prefix}_{name}_m",
            )
        with col2:
            o = st.number_input(
                f"{name} — jednorázově (Kč)",
                min_value=0.0, value=float(onetime_default), step=500.0,
                key=f"{key_prefix}_{name}_o",
            )
        costs.append(AdditionalCost(name=name, monthly_amount=m, one_time_amount=o))

    # Vlastní náklady
    n_custom = st.number_input(
        "Počet vlastních položek nákladů", min_value=0, max_value=10, value=0,
        key=f"{key_prefix}_n_custom",
    )
    for i in range(n_custom):
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            name = st.text_input(f"Název #{i+1}", key=f"{key_prefix}_custom_name_{i}")
        with col2:
            m = st.number_input(
                f"Měsíčně #{i+1} (Kč)", min_value=0.0, step=50.0,
                key=f"{key_prefix}_custom_m_{i}",
            )
        with col3:
            o = st.number_input(
                f"Jednorázově #{i+1} (Kč)", min_value=0.0, step=500.0,
                key=f"{key_prefix}_custom_o_{i}",
            )
        if name:
            costs.append(AdditionalCost(name=name, monthly_amount=m, one_time_amount=o))

    return costs


def render_switching_costs(key_prefix: str) -> list[AdditionalCost]:
    """Renderuje editor nákladů na přechod k jiné bance."""
    costs = []
    st.markdown("**Náklady na přechod k jiné bance**")
    presets = {
        "Posouzení vhodnosti zástavy (odhad)": (0, 3000),
        "Zápis zástavního práva — el. podání (ČÚZK)": (0, 1600),
        "Zpracování el. podpisů zástavní smlouvy": (0, 400),
        "Ověření podpisu na zástavní smlouvě": (0, 50),
        "Výmaz zástavního práva — el. podání (ČÚZK)": (0, 1600),
        "Poplatek za předčasné splacení (stará banka)": (0, 0),
    }
    selected = st.multiselect(
        "Náklady přechodu",
        options=list(presets.keys()),
        default=list(presets.keys()),
        key=f"{key_prefix}_sw_presets",
    )
    for name in selected:
        monthly_default, onetime_default = presets[name]
        val = st.number_input(
            f"{name} (Kč)",
            min_value=0.0, value=float(onetime_default), step=500.0,
            key=f"{key_prefix}_sw_{name}",
        )
        costs.append(AdditionalCost(name=name, monthly_amount=monthly_default, one_time_amount=val))

    return costs


def render_mortgage_form(key_prefix: str, title: str, show_switching: bool = False, default_bank: str = "") -> MortgageParams | None:
    """Renderuje formulář jedné hypotéky."""
    st.subheader(title)
    bank = st.text_input("Název banky", value=default_bank, key=f"{key_prefix}_bank")
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1:
        principal = st.number_input(
            "Výše úvěru (Kč)", min_value=100_000.0, max_value=50_000_000.0,
            value=3_000_000.0, step=100_000.0, key=f"{key_prefix}_principal",
        )
    with col2:
        rate = st.number_input(
            "Roční úroková sazba (%)", min_value=0.0, max_value=20.0,
            value=5.0, step=0.1, format="%.2f", key=f"{key_prefix}_rate",
        )
    with col3:
        years = st.number_input(
            "Doba splácení (roky)", min_value=1, max_value=40,
            value=25, key=f"{key_prefix}_years",
        )
    with col4:
        fixation = st.number_input(
            "Fixace (roky)", min_value=0, max_value=15,
            value=5, key=f"{key_prefix}_fixation",
        )

    is_current = False
    if show_switching:
        is_current = st.checkbox("Nabídka od stávající banky (bez nákladů na přechod)", key=f"{key_prefix}_is_current")

    additional = render_additional_costs(f"{key_prefix}_ac")

    switching = []
    if show_switching and not is_current:
        switching = render_switching_costs(f"{key_prefix}_sc")

    # Podmínky banky
    conditions = []
    with st.expander("Podmínky banky (poznámky)"):
        cond_presets = {
            "Běžný účet u banky s min. příjmem": "Splácení z běžného účtu u banky, min. kreditní příjem 15 000 Kč/měsíc",
            "Pojištění nemovitosti": "Nemovitost musí být pojištěna po celou dobu trvání úvěru",
            "Životní pojištění": "Banka vyžaduje/doporučuje životní pojištění (sleva na sazbě)",
        }
        sel_conds = st.multiselect(
            "Běžné podmínky",
            options=list(cond_presets.keys()),
            key=f"{key_prefix}_cond_presets",
        )
        for c in sel_conds:
            text = st.text_input(c, value=cond_presets[c], key=f"{key_prefix}_cond_{c}")
            conditions.append(text)
        custom_cond = st.text_area(
            "Další podmínky (volný text)",
            key=f"{key_prefix}_cond_custom",
        )
        if custom_cond.strip():
            conditions.append(custom_cond.strip())

    return MortgageParams(
        principal=principal,
        annual_rate=rate,
        years=years,
        bank_name=bank,
        additional_costs=additional,
        switching_costs=switching,
        is_current_bank=is_current,
        conditions=conditions,
        fixation_years=fixation,
    )


# === Záložky ===

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Kalkulačka",
    "Srovnání nabídek",
    "Refinancování",
    "Citlivostní analýza",
    "Export / Import",
])

# --- Tab 1: Kalkulačka ---
with tab1:
    st.header("Výpočet splátky")

    col1, col2, col3 = st.columns(3)
    with col1:
        calc_principal = st.number_input(
            "Výše úvěru (Kč)", min_value=100_000.0, max_value=50_000_000.0,
            value=3_000_000.0, step=100_000.0, key="calc_principal",
        )
    with col2:
        calc_rate = st.number_input(
            "Roční úroková sazba (%)", min_value=0.0, max_value=20.0,
            value=5.0, step=0.1, format="%.2f", key="calc_rate",
        )
    with col3:
        calc_years = st.number_input(
            "Doba splácení (roky)", min_value=1, max_value=40,
            value=25, key="calc_years",
        )

    params = MortgageParams(principal=calc_principal, annual_rate=calc_rate, years=calc_years)
    payment = monthly_payment(params.principal, params.monthly_rate, params.months)
    total_paid = payment * params.months
    total_interest = total_paid - params.principal

    col1, col2, col3 = st.columns(3)
    col1.metric("Měsíční splátka", f"{payment:,.0f} Kč")
    col2.metric("Celkem zaplaceno", f"{total_paid:,.0f} Kč")
    col3.metric("Celkem úroky", f"{total_interest:,.0f} Kč")

    # Splátkový kalendář
    with st.expander("Splátkový kalendář"):
        schedule = amortization_schedule(params)
        df = pd.DataFrame([
            {
                "Měsíc": r.month,
                "Splátka": r.payment,
                "Jistina": r.principal_part,
                "Úrok": r.interest_part,
                "Zůstatek": r.remaining_balance,
            }
            for r in schedule
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Graf
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["Měsíc"], y=df["Jistina"], name="Jistina", stackgroup="one"))
        fig.add_trace(go.Scatter(x=df["Měsíc"], y=df["Úrok"], name="Úrok", stackgroup="one"))
        fig.update_layout(title="Rozpad splátky v čase", xaxis_title="Měsíc", yaxis_title="Kč")
        st.plotly_chart(fig, use_container_width=True)

        # Graf zůstatku
        fig2 = px.line(df, x="Měsíc", y="Zůstatek", title="Vývoj zůstatku úvěru")
        fig2.update_layout(yaxis_title="Kč")
        st.plotly_chart(fig2, use_container_width=True)


# --- Tab 2: Srovnání nabídek ---
with tab2:
    st.header("Srovnání nabídek bank")

    n_offers = st.number_input("Počet nabídek k porovnání", min_value=2, max_value=10, value=3, key="n_offers")

    offers_params = []
    cols = st.columns(min(n_offers, 3))
    for i in range(n_offers):
        col_idx = i % min(n_offers, 3)
        with cols[col_idx]:
            p = render_mortgage_form(f"offer_{i}", f"Nabídka {i+1}", show_switching=False)
            if p:
                offers_params.append(p)

    if st.button("Porovnat nabídky", key="compare_btn"):
        if len(offers_params) >= 2:
            summaries = [calculate_summary(p) for p in offers_params]
            st.session_state.offers = offers_params

            # Tabulka srovnání
            comparison_data = []
            for s in summaries:
                comparison_data.append({
                    "Banka": s.bank_name,
                    "Sazba %": s.annual_rate,
                    "Fixace": f"{s.fixation_years} let",
                    "Měsíční splátka": f"{s.monthly_payment:,.0f}",
                    "Měsíční celkem": f"{s.monthly_total:,.0f}",
                    "Celkem úroky": f"{s.total_interest:,.0f}",
                    "Poplatky": f"{s.total_additional_costs:,.0f}",
                    "Celkové náklady": f"{s.total_cost:,.0f}",
                    "Náklady za fixaci": f"{s.fixation.total_cost_in_fixation:,.0f}" if s.fixation else "—",
                })
            st.dataframe(pd.DataFrame(comparison_data), use_container_width=True, hide_index=True)

            # Graf srovnání
            chart_data = pd.DataFrame([
                {"Banka": s.bank_name, "Typ": "Úroky", "Částka": s.total_interest}
                for s in summaries
            ] + [
                {"Banka": s.bank_name, "Typ": "Poplatky", "Částka": s.total_additional_costs}
                for s in summaries
            ])
            fig = px.bar(chart_data, x="Banka", y="Částka", color="Typ", barmode="stack",
                         title="Celkové náklady podle banky")
            fig.update_layout(yaxis_title="Kč")
            st.plotly_chart(fig, use_container_width=True)

            # Graf vývoje zůstatku
            fig2 = go.Figure()
            for p, s in zip(offers_params, summaries):
                sched = amortization_schedule(p)
                months = [r.month for r in sched]
                balances = [r.remaining_balance for r in sched]
                fig2.add_trace(go.Scatter(x=months, y=balances, name=s.bank_name))
            fig2.update_layout(
                title="Vývoj zůstatku úvěru",
                xaxis_title="Měsíc", yaxis_title="Kč",
            )
            st.plotly_chart(fig2, use_container_width=True)

            # Podmínky bank
            has_conditions = any(p.conditions for p in offers_params)
            if has_conditions:
                st.subheader("Podmínky bank")
                for p in offers_params:
                    if p.conditions:
                        st.markdown(f"**{p.bank_name}**")
                        for cond in p.conditions:
                            st.markdown(f"- {cond}")


# --- Tab 3: Refinancování ---
with tab3:
    st.header("Refinancování hypotéky")
    st.info("Porovnejte stávající hypotéku s novými nabídkami — od stávající banky i od konkurence.")

    col_current, col_divider = st.columns([1, 2])

    with col_current:
        st.subheader("Stávající hypotéka")
        cur_bank = st.text_input("Stávající banka", value="Moje banka", key="ref_cur_bank")
        cur_balance = st.number_input(
            "Zbývající jistina (Kč)", min_value=0.0, max_value=50_000_000.0,
            value=2_000_000.0, step=100_000.0, key="ref_cur_balance",
        )
        cur_rate = st.number_input(
            "Aktuální sazba (%)", min_value=0.0, max_value=20.0,
            value=5.5, step=0.1, format="%.2f", key="ref_cur_rate",
        )
        col_y, col_f = st.columns(2)
        with col_y:
            cur_remaining = st.number_input(
                "Zbývající doba (roky)", min_value=1, max_value=40,
                value=20, key="ref_cur_remaining",
            )
        with col_f:
            cur_fixation = st.number_input(
                "Zbývající fixace (roky)", min_value=0, max_value=15,
                value=0, key="ref_cur_fixation",
                help="Kolik let zbývá do konce fixace. 0 = fixace už skončila.",
            )
        cur_costs = render_additional_costs("ref_cur", "Stávající poplatky/pojištění")

    current_params = MortgageParams(
        principal=cur_balance,
        annual_rate=cur_rate,
        years=cur_remaining,
        bank_name=cur_bank,
        additional_costs=cur_costs,
        is_current_bank=True,
        fixation_years=cur_fixation,
    )

    with col_divider:
        n_new = st.number_input("Počet nových nabídek", min_value=1, max_value=8, value=2, key="ref_n_new")

    new_offers = []
    for i in range(n_new):
        with st.expander(f"Nová nabídka {i+1}", expanded=(i < 2)):
            p = render_mortgage_form(
                f"ref_new_{i}", f"Nabídka {i+1}",
                show_switching=True,
                default_bank=cur_bank if i == 0 else "",
            )
            # Přepíšeme jistinu na zbývající zůstatek
            if p:
                p.principal = cur_balance
                new_offers.append(p)

    if st.button("Porovnat refinancování", key="ref_compare"):
        st.session_state.refinancing = {
            "current": current_params,
            "new_offers": new_offers,
        }
        all_summaries = [calculate_summary(current_params)]
        refinancing_results = []

        for offer in new_offers:
            result = compare_refinancing(current_params, offer)
            refinancing_results.append(result)
            all_summaries.append(result.new_offer)

        # Tabulka
        table_data = []
        for s in all_summaries:
            label = s.bank_name
            if s is all_summaries[0]:
                label += " (stávající)"
            row = {
                "Nabídka": label,
                "Sazba %": s.annual_rate,
                "Fixace": f"{s.fixation_years} let" if s.fixation_years else "—",
                "Měsíční splátka": f"{s.monthly_payment:,.0f}",
                "Měsíční celkem": f"{s.monthly_total:,.0f}",
                "Celkem úroky": f"{s.total_interest:,.0f}",
                "Poplatky": f"{s.total_additional_costs:,.0f}",
                "Náklady přechod": f"{s.total_switching_costs:,.0f}",
                "Náklady za fixaci": f"{s.fixation.total_cost_in_fixation:,.0f}" if s.fixation else "—",
                "Celkové náklady": f"{s.total_cost:,.0f}",
            }
            table_data.append(row)
        st.subheader("Srovnání")
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)

        # Úspora
        st.subheader("Úspora oproti stávající hypotéce")
        for i, result in enumerate(refinancing_results):
            label = result.new_offer.bank_name
            if result.new_offer.is_current_bank:
                label += " (stávající banka, nová sazba)"

            col1, col2, col3 = st.columns(3)
            col1.metric(
                f"{label} — měsíční úspora",
                f"{result.monthly_saving:,.0f} Kč",
                delta=f"{result.monthly_saving:,.0f} Kč/měsíc",
                delta_color="normal",
            )
            col2.metric(
                f"{label} — celková úspora",
                f"{result.total_saving:,.0f} Kč",
                delta=f"{result.total_saving:,.0f} Kč celkem",
                delta_color="normal",
            )
            # Úspora za fixaci
            if result.fixation_saving is not None:
                fix_y = result.new_offer.fixation_years
                col3.metric(
                    f"{label} — úspora za fixaci ({fix_y} let)",
                    f"{result.fixation_saving:,.0f} Kč",
                    delta=f"{result.fixation_saving:,.0f} Kč za {fix_y} let",
                    delta_color="normal",
                )

            # Srovnání přes společné období (pokud se fixace liší)
            if result.common_period_months and result.common_period_saving is not None:
                common_y = result.common_period_months // 12
                remaining_m = result.common_period_months % 12
                period_label = f"{common_y} let" + (f" {remaining_m} měs." if remaining_m else "")
                st.caption(
                    f"Srovnání přes společné období ({period_label}): "
                    f"úspora **{result.common_period_saving:,.0f} Kč**"
                )

        # Graf
        fig = go.Figure()
        for s in all_summaries:
            fig.add_trace(go.Bar(
                name=s.bank_name,
                x=["Úroky", "Poplatky", "Přechod"],
                y=[s.total_interest, s.total_additional_costs, s.total_switching_costs],
            ))
        fig.update_layout(
            title="Rozpad celkových nákladů",
            barmode="group", yaxis_title="Kč",
        )
        st.plotly_chart(fig, use_container_width=True)

        # Podmínky bank
        all_offers = [current_params] + new_offers
        has_conditions = any(p.conditions for p in all_offers)
        if has_conditions:
            st.subheader("Podmínky bank")
            for p in all_offers:
                if p.conditions:
                    st.markdown(f"**{p.bank_name}**")
                    for cond in p.conditions:
                        st.markdown(f"- {cond}")


# --- Tab 4: Citlivostní analýza ---
with tab4:
    st.header("Citlivostní analýza")

    col1, col2, col3 = st.columns(3)
    with col1:
        sa_principal = st.number_input(
            "Výše úvěru (Kč)", min_value=100_000.0, max_value=50_000_000.0,
            value=3_000_000.0, step=100_000.0, key="sa_principal",
        )
    with col2:
        sa_rate = st.number_input(
            "Základní sazba (%)", min_value=0.0, max_value=20.0,
            value=5.0, step=0.1, format="%.2f", key="sa_rate",
        )
    with col3:
        sa_years = st.number_input(
            "Doba splácení (roky)", min_value=1, max_value=40,
            value=25, key="sa_years",
        )

    col1, col2 = st.columns(2)
    with col1:
        sa_delta_min = st.number_input("Odchylka sazby od (pp)", value=-2.0, step=0.5, key="sa_dmin")
    with col2:
        sa_delta_max = st.number_input("Odchylka sazby do (pp)", value=2.0, step=0.5, key="sa_dmax")

    sa_params = MortgageParams(principal=sa_principal, annual_rate=sa_rate, years=sa_years)
    results = sensitivity_analysis(sa_params, rate_range=(sa_delta_min, sa_delta_max))

    df = pd.DataFrame(results)
    df.columns = ["Sazba %", "Delta (pp)", "Měsíční splátka", "Celkem zaplaceno", "Celkem úroky"]

    st.dataframe(df, use_container_width=True, hide_index=True)

    fig = px.line(df, x="Sazba %", y="Měsíční splátka", title="Vliv sazby na měsíční splátku",
                  markers=True)
    fig.update_layout(yaxis_title="Kč")
    st.plotly_chart(fig, use_container_width=True)

    fig2 = px.line(df, x="Sazba %", y="Celkem úroky", title="Vliv sazby na celkové úroky",
                   markers=True)
    fig2.update_layout(yaxis_title="Kč")
    st.plotly_chart(fig2, use_container_width=True)

    # Vliv doby splácení
    st.subheader("Vliv doby splácení")
    years_range = list(range(5, 36))
    year_data = []
    for y in years_range:
        months = y * 12
        mr = sa_rate / 100 / 12
        p = monthly_payment(sa_principal, mr, months)
        total = p * months
        year_data.append({
            "Roky": y,
            "Měsíční splátka": round(p, 0),
            "Celkem úroky": round(total - sa_principal, 0),
        })
    df_years = pd.DataFrame(year_data)

    col1, col2 = st.columns(2)
    with col1:
        fig3 = px.line(df_years, x="Roky", y="Měsíční splátka",
                       title="Vliv doby splácení na měsíční splátku", markers=True)
        fig3.update_layout(yaxis_title="Kč")
        st.plotly_chart(fig3, use_container_width=True)
    with col2:
        fig4 = px.line(df_years, x="Roky", y="Celkem úroky",
                       title="Vliv doby splácení na celkové úroky", markers=True)
        fig4.update_layout(yaxis_title="Kč")
        st.plotly_chart(fig4, use_container_width=True)


# --- Tab 5: Export / Import ---
with tab5:
    st.header("Export / Import dat")

    has_offers = bool(st.session_state.offers)
    has_refinancing = bool(st.session_state.refinancing)

    st.subheader("Export")
    if has_offers or has_refinancing:
        # JSON export — vše dohromady
        ref_data = st.session_state.refinancing if has_refinancing else None
        json_data = export_json(st.session_state.offers, refinancing=ref_data)
        st.download_button(
            "Stáhnout JSON (vše)",
            data=json_data,
            file_name="hypoteka_data.json",
            mime="application/json",
        )

        # CSV export — srovnání nabídek
        if has_offers:
            summaries = [calculate_summary(p) for p in st.session_state.offers]
            csv_data = summaries_to_csv(summaries)
            st.download_button(
                "Stáhnout CSV — srovnání nabídek",
                data=csv_data,
                file_name="hypoteka_srovnani.csv",
                mime="text/csv",
            )

        # CSV export — refinancování
        if has_refinancing:
            ref = st.session_state.refinancing
            all_params = [ref["current"]] + ref["new_offers"]
            ref_summaries = [calculate_summary(p) for p in all_params]
            csv_ref = summaries_to_csv(ref_summaries)
            st.download_button(
                "Stáhnout CSV — refinancování",
                data=csv_ref,
                file_name="hypoteka_refinancovani.csv",
                mime="text/csv",
            )

        # Přehled co se exportuje
        with st.expander("Náhled exportovaných dat"):
            if has_offers:
                st.caption(f"Srovnání nabídek: {len(st.session_state.offers)} nabídek")
            if has_refinancing:
                ref = st.session_state.refinancing
                st.caption(f"Refinancování: stávající + {len(ref['new_offers'])} nových nabídek")
            st.json(json_data)
    else:
        st.info("Nejprve vyplňte data v záložce 'Srovnání nabídek' nebo 'Refinancování' a klikněte na příslušné tlačítko.")

    st.subheader("Import")
    uploaded = st.file_uploader("Nahrát JSON soubor", type=["json"], key="import_file")
    if uploaded is not None:
        try:
            content = uploaded.read().decode("utf-8")
            imported = import_json(content)
            parts = []
            if "offers" in imported:
                st.session_state.offers = imported["offers"]
                parts.append(f"{len(imported['offers'])} nabídek (srovnání)")
            if "refinancing" in imported:
                st.session_state.refinancing = imported["refinancing"]
                n = len(imported["refinancing"]["new_offers"])
                parts.append(f"refinancování (stávající + {n} nabídek)")
            st.success(f"Naimportováno: {', '.join(parts)}")
            st.json(content)
        except Exception as e:
            st.error(f"Chyba při importu: {e}")
