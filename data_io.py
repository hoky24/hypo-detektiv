"""Export a import dat kalkulačky."""

import json
import csv
import io
from typing import Any

import datetime
import re

from mortgage import MortgageParams, AdditionalCost, FixationPeriod, MortgageSummary, TimelineRow


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
        "fixation_end_date": params.fixation_end_date,
        "original_principal": params.original_principal,
        "original_term_years": params.original_term_years,
        "start_date": params.start_date,
        "past_fixations": [
            {"annual_rate": f.annual_rate, "duration_months": f.duration_months}
            for f in params.past_fixations
        ],
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
        fixation_end_date=d.get("fixation_end_date", ""),
        original_principal=d.get("original_principal", 0.0),
        original_term_years=d.get("original_term_years", 0),
        start_date=d.get("start_date", ""),
        past_fixations=[
            FixationPeriod(**f) for f in d.get("past_fixations", [])
        ],
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


def _parse_czech_number(s: str) -> float:
    """Převede české číslo ('1 126,80') na float."""
    s = s.strip()
    if not s:
        return 0.0
    s = s.replace('\xa0', '').replace(' ', '').replace(',', '.')
    return float(s)


def _parse_czech_date(s: str) -> datetime.date:
    """Převede české datum ('25. 6. 2018') na date."""
    s = s.strip().rstrip('.')
    parts = re.split(r'[.\s]+', s)
    parts = [p for p in parts if p]
    if len(parts) == 3:
        return datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
    raise ValueError(f"Neplatný formát data: {s}")


def import_bank_csv(content: bytes | str, encoding: str = "windows-1250") -> list[TimelineRow]:
    """Importuje splátkový kalendář z CSV exportu banky (ČSOB formát).

    Formát: Datum;Čerpání Kč;Mimořádná splátka Kč;Sazba % p.a.;Splátka Kč;Úrok Kč;Jistina Kč;Nesplacená jistina Kč

    Podporuje postupné čerpání a úrokové období (bez splácení jistiny).
    """
    if isinstance(content, bytes):
        # Zkusit zadané kódování, fallback na utf-8
        for enc in [encoding, "utf-8", "utf-8-sig", "latin-1"]:
            try:
                text = content.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            text = content.decode("utf-8", errors="replace")
    else:
        text = content

    reader = csv.reader(io.StringIO(text), delimiter=';')

    # Najít řádek s hlavičkou
    header = None
    for row in reader:
        if any("datum" in c.lower() for c in row):
            header = [c.strip() for c in row]
            break
    if not header:
        raise ValueError("CSV neobsahuje rozpoznatelnou hlavičku.")

    # Mapování sloupců (flexibilní)
    col_map: dict[str, int] = {}
    for i, h in enumerate(header):
        hl = h.lower()
        if "datum" in hl:
            col_map["datum"] = i
        elif "čerpání" in hl or "cerpani" in hl:
            col_map["cerpani"] = i
        elif "mimořádná" in hl or "mimoradna" in hl:
            col_map["mimoradna"] = i
        elif "sazba" in hl:
            col_map["sazba"] = i
        elif "splátka" in hl or "splatka" in hl:
            col_map["splatka"] = i
        elif "úrok" in hl or "urok" in hl:
            col_map["urok"] = i
        elif "jistina" in hl and "nesplacen" not in hl:
            col_map["jistina"] = i
        elif "nesplacen" in hl:
            col_map["zustatek"] = i

    if "datum" not in col_map:
        raise ValueError("CSV neobsahuje sloupec 'Datum'.")

    rows: list[TimelineRow] = []
    cum_interest = 0.0
    cum_principal = 0.0
    month = 0
    last_rate = 0.0

    for row in reader:
        if not row or len(row) <= col_map["datum"]:
            continue
        date_str = row[col_map["datum"]].strip()
        if not date_str:
            continue

        try:
            _parse_czech_date(date_str)
        except ValueError:
            continue

        # Čerpání — přeskočit (jen info řádek)
        cerpani = _parse_czech_number(row[col_map.get("cerpani", 0)]) if "cerpani" in col_map and col_map["cerpani"] < len(row) else 0.0
        if cerpani > 0:
            # Zaznamenat zůstatek po čerpání
            zustatek = _parse_czech_number(row[col_map.get("zustatek", 0)]) if "zustatek" in col_map and col_map["zustatek"] < len(row) else 0.0
            sazba = _parse_czech_number(row[col_map.get("sazba", 0)]) if "sazba" in col_map and col_map["sazba"] < len(row) else last_rate
            if sazba > 0:
                last_rate = sazba
            continue

        # Splátka
        splatka = _parse_czech_number(row[col_map.get("splatka", 0)]) if "splatka" in col_map and col_map["splatka"] < len(row) else 0.0
        urok = _parse_czech_number(row[col_map.get("urok", 0)]) if "urok" in col_map and col_map["urok"] < len(row) else 0.0
        jistina = _parse_czech_number(row[col_map.get("jistina", 0)]) if "jistina" in col_map and col_map["jistina"] < len(row) else 0.0
        zustatek = _parse_czech_number(row[col_map.get("zustatek", 0)]) if "zustatek" in col_map and col_map["zustatek"] < len(row) else 0.0
        sazba = _parse_czech_number(row[col_map.get("sazba", 0)]) if "sazba" in col_map and col_map["sazba"] < len(row) else last_rate

        if sazba > 0:
            last_rate = sazba

        if splatka == 0 and urok == 0:
            continue

        month += 1
        cum_interest += urok
        cum_principal += jistina

        label = f"Fixace ({sazba:.2f} %)" if sazba > 0 else "Fixace"

        rows.append(TimelineRow(
            month=month,
            payment=round(splatka, 2),
            principal_part=round(jistina, 2),
            interest_part=round(urok, 2),
            remaining_balance=round(zustatek, 2),
            cumulative_interest=round(cum_interest, 2),
            cumulative_principal=round(cum_principal, 2),
            is_past=True,
            fixation_label=label,
        ))

    return rows


def summaries_to_csv(summaries: list[MortgageSummary]) -> str:
    """Exportuje souhrny do CSV řetězce."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Banka", "Jistina", "Sazba %", "RPSN %", "Fixace (roky)", "Roky",
        "Měsíční splátka", "Měsíční celkem",
        "Celkem zaplaceno", "Celkem úroky",
        "Poplatky", "Náklady přechod", "Bonus",
        "Celkové náklady", "Stávající banka",
    ])
    for s in summaries:
        writer.writerow([
            s.bank_name, s.principal, s.annual_rate, s.rpsn, s.fixation_years, s.years,
            s.monthly_payment, s.monthly_total,
            s.total_paid, s.total_interest,
            s.total_additional_costs, s.total_switching_costs, s.bonus,
            s.total_cost, "Ano" if s.is_current_bank else "Ne",
        ])
    return output.getvalue()
