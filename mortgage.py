"""Výpočetní logika hypoteční kalkulačky."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AdditionalCost:
    """Dodatečný náklad (pojištění, poplatky apod.)."""
    name: str
    monthly_amount: float = 0.0  # měsíční částka
    one_time_amount: float = 0.0  # jednorázová částka

    def total_over_months(self, months: int) -> float:
        return self.one_time_amount + self.monthly_amount * months


@dataclass
class MortgageParams:
    """Parametry hypotéky."""
    principal: float  # výše úvěru
    annual_rate: float  # roční úroková sazba v %
    years: int  # doba splácení v letech
    bank_name: str = ""
    # Dodatečné náklady
    additional_costs: list[AdditionalCost] = field(default_factory=list)
    # Poplatky při přechodu k jiné bance (refinancování)
    switching_costs: list[AdditionalCost] = field(default_factory=list)
    # Je to nabídka od stávající banky? (bez nákladů na přechod)
    is_current_bank: bool = False
    # Podmínky banky (textové poznámky)
    conditions: list[str] = field(default_factory=list)
    # Doba fixace v letech (0 = bez fixace / variabilní)
    fixation_years: int = 5

    @property
    def months(self) -> int:
        return self.years * 12

    @property
    def monthly_rate(self) -> float:
        return self.annual_rate / 100 / 12


@dataclass
class ScheduleRow:
    """Řádek splátkového kalendáře."""
    month: int
    payment: float
    principal_part: float
    interest_part: float
    remaining_balance: float
    cumulative_interest: float
    cumulative_principal: float


def monthly_payment(principal: float, monthly_rate: float, months: int) -> float:
    """Výpočet měsíční anuitní splátky."""
    if monthly_rate == 0:
        return principal / months if months > 0 else 0.0
    r = monthly_rate
    n = months
    return principal * r * (1 + r) ** n / ((1 + r) ** n - 1)


def amortization_schedule(params: MortgageParams) -> list[ScheduleRow]:
    """Generuje splátkový kalendář."""
    payment = monthly_payment(params.principal, params.monthly_rate, params.months)
    balance = params.principal
    cum_interest = 0.0
    cum_principal = 0.0
    schedule = []

    for month in range(1, params.months + 1):
        interest = balance * params.monthly_rate
        principal_part = payment - interest
        # Poslední splátka — dorovnání zůstatku
        if month == params.months:
            principal_part = balance
            payment = principal_part + interest
        balance -= principal_part
        cum_interest += interest
        cum_principal += principal_part
        schedule.append(ScheduleRow(
            month=month,
            payment=round(payment, 2),
            principal_part=round(principal_part, 2),
            interest_part=round(interest, 2),
            remaining_balance=round(max(balance, 0), 2),
            cumulative_interest=round(cum_interest, 2),
            cumulative_principal=round(cum_principal, 2),
        ))
    return schedule


@dataclass
class FixationSummary:
    """Souhrn nákladů za dobu fixace."""
    fixation_years: int
    fixation_months: int
    paid_in_fixation: float  # splátky za dobu fixace
    interest_in_fixation: float  # úroky za dobu fixace
    principal_in_fixation: float  # splacená jistina za dobu fixace
    additional_costs_in_fixation: float  # poplatky za dobu fixace
    switching_costs: float  # jednorázové náklady přechodu
    total_cost_in_fixation: float  # celkové náklady za fixaci
    remaining_balance: float  # zůstatek na konci fixace


def calculate_fixation_summary(params: MortgageParams) -> FixationSummary:
    """Vypočítá náklady za dobu fixace."""
    fix_months = params.fixation_years * 12
    if fix_months <= 0 or fix_months > params.months:
        fix_months = params.months

    schedule = amortization_schedule(params)
    fix_rows = schedule[:fix_months]
    last_row = fix_rows[-1]

    paid = sum(r.payment for r in fix_rows)
    interest = last_row.cumulative_interest
    principal_paid = last_row.cumulative_principal
    remaining = last_row.remaining_balance

    additional = sum(c.total_over_months(fix_months) for c in params.additional_costs)

    if params.is_current_bank:
        switching = 0.0
    else:
        switching = sum(c.one_time_amount for c in params.switching_costs)

    total = interest + additional + switching

    return FixationSummary(
        fixation_years=params.fixation_years,
        fixation_months=fix_months,
        paid_in_fixation=round(paid, 2),
        interest_in_fixation=round(interest, 2),
        principal_in_fixation=round(principal_paid, 2),
        additional_costs_in_fixation=round(additional, 2),
        switching_costs=round(switching, 2),
        total_cost_in_fixation=round(total, 2),
        remaining_balance=round(remaining, 2),
    )


@dataclass
class MortgageSummary:
    """Souhrn hypotéky pro srovnání."""
    bank_name: str
    principal: float
    annual_rate: float
    years: int
    fixation_years: int
    monthly_payment: float
    total_paid: float
    total_interest: float
    total_additional_costs: float
    total_switching_costs: float
    total_cost: float  # celkové náklady = úroky + poplatky + přechod
    monthly_total: float  # splátka + měsíční poplatky
    is_current_bank: bool
    fixation: FixationSummary | None = None


def calculate_summary(params: MortgageParams) -> MortgageSummary:
    """Vypočítá souhrn hypotéky."""
    payment = monthly_payment(params.principal, params.monthly_rate, params.months)
    total_paid = payment * params.months
    total_interest = total_paid - params.principal

    total_additional = sum(c.total_over_months(params.months) for c in params.additional_costs)
    monthly_additional = sum(c.monthly_amount for c in params.additional_costs)

    if params.is_current_bank:
        total_switching = 0.0
    else:
        total_switching = sum(c.total_over_months(params.months) for c in params.switching_costs)

    total_cost = total_interest + total_additional + total_switching

    fixation = None
    if params.fixation_years > 0:
        fixation = calculate_fixation_summary(params)

    return MortgageSummary(
        bank_name=params.bank_name or "Bez názvu",
        principal=params.principal,
        annual_rate=params.annual_rate,
        years=params.years,
        fixation_years=params.fixation_years,
        monthly_payment=round(payment, 2),
        total_paid=round(total_paid, 2),
        total_interest=round(total_interest, 2),
        total_additional_costs=round(total_additional, 2),
        total_switching_costs=round(total_switching, 2),
        total_cost=round(total_cost, 2),
        monthly_total=round(payment + monthly_additional, 2),
        is_current_bank=params.is_current_bank,
        fixation=fixation,
    )


@dataclass
class RefinancingSummary:
    """Souhrn refinancování — porovnání staré a nové hypotéky."""
    current: MortgageSummary
    new_offer: MortgageSummary
    monthly_saving: float
    total_saving: float  # kladné = ušetříte, záporné = prodělate
    fixation_saving: float | None = None  # úspora za dobu fixace nové nabídky
    common_period_saving: float | None = None  # úspora za společné období (min fixace)
    common_period_months: int | None = None


def _cost_over_months(params: MortgageParams, months: int) -> float:
    """Spočítá celkové náklady (úroky + poplatky + přechod) za daný počet měsíců."""
    schedule = amortization_schedule(params)
    rows = schedule[:months]
    interest = rows[-1].cumulative_interest if rows else 0.0
    additional = sum(c.total_over_months(months) for c in params.additional_costs)
    if params.is_current_bank:
        switching = 0.0
    else:
        switching = sum(c.one_time_amount for c in params.switching_costs)
    return interest + additional + switching


def compare_refinancing(
    current: MortgageParams,
    new_offer: MortgageParams,
) -> RefinancingSummary:
    """Porovná stávající hypotéku s novou nabídkou."""
    current_summary = calculate_summary(current)
    new_summary = calculate_summary(new_offer)

    monthly_saving = current_summary.monthly_total - new_summary.monthly_total
    total_saving = current_summary.total_cost - new_summary.total_cost

    # Úspora za dobu fixace nové nabídky
    fixation_saving = None
    if new_offer.fixation_years > 0 and new_summary.fixation:
        cur_fix = _cost_over_months(current, new_offer.fixation_years * 12)
        new_fix = new_summary.fixation.total_cost_in_fixation
        fixation_saving = round(cur_fix - new_fix, 2)

    # Srovnání přes společné období (min z obou fixací)
    common_period_saving = None
    common_period_months = None
    cur_fix_y = current.fixation_years or current.years
    new_fix_y = new_offer.fixation_years or new_offer.years
    if cur_fix_y > 0 and new_fix_y > 0:
        common_months = min(cur_fix_y, new_fix_y) * 12
        common_months = min(common_months, current.months, new_offer.months)
        cur_cost = _cost_over_months(current, common_months)
        new_cost = _cost_over_months(new_offer, common_months)
        common_period_saving = round(cur_cost - new_cost, 2)
        common_period_months = common_months

    return RefinancingSummary(
        current=current_summary,
        new_offer=new_summary,
        monthly_saving=round(monthly_saving, 2),
        total_saving=round(total_saving, 2),
        fixation_saving=fixation_saving,
        common_period_saving=common_period_saving,
        common_period_months=common_period_months,
    )


def sensitivity_analysis(
    params: MortgageParams,
    rate_range: tuple[float, float] = (-1.0, 1.0),
    rate_step: float = 0.25,
) -> list[dict]:
    """Citlivostní analýza — vliv změny sazby na splátku a celkové náklady."""
    results = []
    base_rate = params.annual_rate
    delta = rate_range[0]
    while delta <= rate_range[1] + 0.001:
        rate = base_rate + delta
        if rate < 0:
            delta += rate_step
            continue
        mr = rate / 100 / 12
        payment = monthly_payment(params.principal, mr, params.months)
        total = payment * params.months
        results.append({
            "sazba": round(rate, 2),
            "delta": round(delta, 2),
            "mesicni_splatka": round(payment, 2),
            "celkem_zaplaceno": round(total, 2),
            "celkem_uroky": round(total - params.principal, 2),
        })
        delta += rate_step
    return results
