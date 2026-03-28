"""Export a import dat kalkulačky."""

import json
import csv
import io
from typing import Any

from mortgage import MortgageParams, AdditionalCost, MortgageSummary


def params_to_dict(params: MortgageParams) -> dict[str, Any]:
    """Převede MortgageParams na serializovatelný slovník."""
    return {
        "principal": params.principal,
        "annual_rate": params.annual_rate,
        "years": params.years,
        "bank_name": params.bank_name,
        "is_current_bank": params.is_current_bank,
        "additional_costs": [
            {"name": c.name, "monthly_amount": c.monthly_amount, "one_time_amount": c.one_time_amount}
            for c in params.additional_costs
        ],
        "switching_costs": [
            {"name": c.name, "monthly_amount": c.monthly_amount, "one_time_amount": c.one_time_amount}
            for c in params.switching_costs
        ],
        "conditions": params.conditions,
        "fixation_years": params.fixation_years,
        "bonus": params.bonus,
    }


def dict_to_params(d: dict[str, Any]) -> MortgageParams:
    """Převede slovník zpět na MortgageParams."""
    return MortgageParams(
        principal=d["principal"],
        annual_rate=d["annual_rate"],
        years=d["years"],
        bank_name=d.get("bank_name", ""),
        is_current_bank=d.get("is_current_bank", False),
        additional_costs=[
            AdditionalCost(**c) for c in d.get("additional_costs", [])
        ],
        switching_costs=[
            AdditionalCost(**c) for c in d.get("switching_costs", [])
        ],
        conditions=d.get("conditions", []),
        fixation_years=d.get("fixation_years", 5),
        bonus=d.get("bonus", 0.0),
    )


def export_json(
    current_mortgage: MortgageParams | None,
    offers: list[MortgageParams],
) -> str:
    """Exportuje data do JSON (verze 2)."""
    data: dict[str, Any] = {"version": 2}
    if current_mortgage:
        data["current_mortgage"] = params_to_dict(current_mortgage)
    data["offers"] = [params_to_dict(o) for o in offers]
    return json.dumps(data, indent=2, ensure_ascii=False)


def import_json(json_str: str) -> dict[str, Any]:
    """Importuje data z JSON. Podporuje verzi 1 i 2."""
    data = json.loads(json_str)
    version = data.get("version", 1)

    if version == 2:
        return {
            "current_mortgage": dict_to_params(data["current_mortgage"]) if data.get("current_mortgage") else None,
            "offers": [dict_to_params(d) for d in data.get("offers", [])],
        }
    elif version == 1:
        # Zpětná kompatibilita
        result: dict[str, Any] = {"current_mortgage": None, "offers": []}
        if "refinancing" in data:
            result["current_mortgage"] = dict_to_params(data["refinancing"]["current"])
            result["offers"] = [dict_to_params(d) for d in data["refinancing"]["new_offers"]]
        elif "offers" in data:
            result["offers"] = [dict_to_params(d) for d in data["offers"]]
        return result
    else:
        raise ValueError(f"Nepodporovaná verze formátu: {version}")


def summaries_to_csv(summaries: list[MortgageSummary]) -> str:
    """Exportuje souhrny do CSV řetězce."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Banka", "Jistina", "Sazba %", "Fixace (roky)", "Roky",
        "Měsíční splátka", "Měsíční celkem",
        "Celkem zaplaceno", "Celkem úroky",
        "Poplatky", "Náklady přechod", "Bonus",
        "Celkové náklady", "Stávající banka",
    ])
    for s in summaries:
        writer.writerow([
            s.bank_name, s.principal, s.annual_rate, s.fixation_years, s.years,
            s.monthly_payment, s.monthly_total,
            s.total_paid, s.total_interest,
            s.total_additional_costs, s.total_switching_costs, s.bonus,
            s.total_cost, "Ano" if s.is_current_bank else "Ne",
        ])
    return output.getvalue()
