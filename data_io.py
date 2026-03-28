"""Export a import dat kalkulačky."""

import json
import csv
import io
from dataclasses import asdict
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
    )


def export_json(offers: list[MortgageParams], refinancing: dict | None = None) -> str:
    """Exportuje data do JSON řetězce (nabídky i refinancování)."""
    data: dict[str, Any] = {
        "version": 1,
    }
    if offers:
        data["offers"] = [params_to_dict(o) for o in offers]
    if refinancing:
        data["refinancing"] = {
            "current": params_to_dict(refinancing["current"]),
            "new_offers": [params_to_dict(o) for o in refinancing["new_offers"]],
        }
    return json.dumps(data, indent=2, ensure_ascii=False)


def import_json(json_str: str) -> dict[str, Any]:
    """Importuje data z JSON řetězce. Vrací dict s klíči 'offers' a/nebo 'refinancing'."""
    data = json.loads(json_str)
    version = data.get("version", 1)
    if version != 1:
        raise ValueError(f"Nepodporovaná verze formátu: {version}")

    result: dict[str, Any] = {}
    if "offers" in data:
        result["offers"] = [dict_to_params(d) for d in data["offers"]]
    if "refinancing" in data:
        ref = data["refinancing"]
        result["refinancing"] = {
            "current": dict_to_params(ref["current"]),
            "new_offers": [dict_to_params(d) for d in ref["new_offers"]],
        }
    return result


def summaries_to_csv(summaries: list[MortgageSummary]) -> str:
    """Exportuje souhrny do CSV řetězce."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Banka",
        "Jistina",
        "Sazba %",
        "Roky",
        "Měsíční splátka",
        "Měsíční celkem",
        "Celkem zaplaceno",
        "Celkem úroky",
        "Poplatky",
        "Náklady přechod",
        "Celkové náklady",
        "Stávající banka",
    ])
    for s in summaries:
        writer.writerow([
            s.bank_name,
            s.principal,
            s.annual_rate,
            s.years,
            s.monthly_payment,
            s.monthly_total,
            s.total_paid,
            s.total_interest,
            s.total_additional_costs,
            s.total_switching_costs,
            s.total_cost,
            "Ano" if s.is_current_bank else "Ne",
        ])
    return output.getvalue()
