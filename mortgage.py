"""Výpočetní logika hypoteční kalkulačky."""

from dataclasses import dataclass, field


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
    additional_costs: list[AdditionalCost] = field(default_factory=list)
    switching_costs: list[AdditionalCost] = field(default_factory=list)
    is_current_bank: bool = False
    conditions: list[str] = field(default_factory=list)
    fixation_years: int = 5
    bonus: float = 0.0  # jednorázový bonus/odměna od banky (snižuje náklady)

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
    paid_in_fixation: float
    interest_in_fixation: float
    principal_in_fixation: float
    additional_costs_in_fixation: float
    switching_costs: float
    total_cost_in_fixation: float
    remaining_balance: float


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

    total = interest + additional + switching - params.bonus

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
    bonus: float
    total_cost: float  # úroky + poplatky + přechod − bonus
    monthly_total: float
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

    total_cost = total_interest + total_additional + total_switching - params.bonus

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
        bonus=params.bonus,
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
    total_saving: float
    fixation_saving: float | None = None
    common_period_saving: float | None = None
    common_period_months: int | None = None
    breakeven_month: int | None = None


# --- Kumulativní náklady pro grafy ---

@dataclass
class CumulativeCostRow:
    """Řádek kumulativních nákladů v čase."""
    month: int
    cumulative_interest: float
    cumulative_additional: float
    cumulative_switching: float
    cumulative_total_cost: float
    remaining_balance: float


def cumulative_cost_schedule(params: MortgageParams) -> list[CumulativeCostRow]:
    """Měsíc po měsíci kumulativní náklady — pro grafy refinancování."""
    schedule = amortization_schedule(params)
    monthly_additional = sum(c.monthly_amount for c in params.additional_costs)

    if params.is_current_bank:
        switching_total = 0.0
    else:
        switching_total = sum(c.one_time_amount for c in params.switching_costs)

    cum_additional = sum(c.one_time_amount for c in params.additional_costs)
    rows = []

    for row in schedule:
        cum_additional += monthly_additional
        total = row.cumulative_interest + cum_additional + switching_total - params.bonus
        rows.append(CumulativeCostRow(
            month=row.month,
            cumulative_interest=round(row.cumulative_interest, 2),
            cumulative_additional=round(cum_additional, 2),
            cumulative_switching=round(switching_total, 2),
            cumulative_total_cost=round(total, 2),
            remaining_balance=row.remaining_balance,
        ))
    return rows


def find_breakeven_month(current: MortgageParams, new_offer: MortgageParams) -> int | None:
    """Najde měsíc, kdy se náklady přechodu vrátí díky měsíční úspoře.

    Porovnává měsíc po měsíci: kolik ušetřím na úrocích a poplatcích
    vs. kolik mě stál přechod (switching costs - bonus).
    Vrací None pokud se přechod nikdy nezaplatí.
    """
    # Jednorázové náklady přechodu (to, co musím "splatit" úsporou)
    if new_offer.is_current_bank:
        upfront_cost = -new_offer.bonus  # jen bonus, žádné switching costs
    else:
        upfront_cost = (
            sum(c.one_time_amount for c in new_offer.switching_costs)
            - new_offer.bonus
        )

    # Pokud je upfront_cost <= 0 (bonus >= přechod), vyplatí se hned
    if upfront_cost <= 0:
        return 0

    # Měsíční úspora = rozdíl v úrocích + rozdíl v měsíčních poplatcích
    cur_sched = amortization_schedule(current)
    new_sched = amortization_schedule(new_offer)
    cur_monthly_fees = sum(c.monthly_amount for c in current.additional_costs)
    new_monthly_fees = sum(c.monthly_amount for c in new_offer.additional_costs)

    cumulative_saving = 0.0
    max_months = min(len(cur_sched), len(new_sched))

    for i in range(max_months):
        # Úspora na úrocích tento měsíc
        interest_saving = cur_sched[i].interest_part - new_sched[i].interest_part
        # Úspora na poplatcích tento měsíc
        fee_saving = cur_monthly_fees - new_monthly_fees
        cumulative_saving += interest_saving + fee_saving

        if cumulative_saving >= upfront_cost:
            return i + 1  # měsíc (1-based)

    return None


def fixation_comparison_matrix(
    current: MortgageParams | None,
    offers: list[MortgageParams],
) -> list[dict]:
    """Porovná náklady všech nabídek pro všechny délky fixací.

    Vrací list[dict] kde každý dict je řádek matice:
    {"fixace": N, "Banka A": náklady, "Banka B": náklady, ...}
    """
    # Sesbírat všechny unikátní délky fixace
    fixation_years_set = set()
    all_params = list(offers)
    if current:
        all_params = [current] + all_params
        if current.fixation_years > 0:
            fixation_years_set.add(current.fixation_years)

    for o in offers:
        if o.fixation_years > 0:
            fixation_years_set.add(o.fixation_years)

    # Přidat standardní fixace pro úplnost
    for std in [1, 2, 3, 5, 7, 10]:
        if any(abs(f - std) <= 1 for f in fixation_years_set):
            fixation_years_set.add(std)

    fixation_years = sorted(fixation_years_set)
    if not fixation_years:
        fixation_years = [3, 5, 7]

    rows = []
    for fy in fixation_years:
        months = fy * 12
        row: dict = {"Fixace (let)": fy}
        for p in all_params:
            if months > p.months:
                continue
            label = p.bank_name
            if p.is_current_bank and p is (current if current else None):
                label += " (stávající)"
            cost = _cost_over_months(p, months)
            row[label] = round(cost, 0)
        rows.append(row)
    return rows


def _cost_over_months(params: MortgageParams, months: int) -> float:
    """Spočítá celkové náklady za daný počet měsíců."""
    schedule = amortization_schedule(params)
    rows = schedule[:months]
    interest = rows[-1].cumulative_interest if rows else 0.0
    additional = sum(c.total_over_months(months) for c in params.additional_costs)
    if params.is_current_bank:
        switching = 0.0
    else:
        switching = sum(c.one_time_amount for c in params.switching_costs)
    return interest + additional + switching - params.bonus


def compare_refinancing(
    current: MortgageParams,
    new_offer: MortgageParams,
) -> RefinancingSummary:
    """Porovná stávající hypotéku s novou nabídkou."""
    current_summary = calculate_summary(current)
    new_summary = calculate_summary(new_offer)

    monthly_saving = current_summary.monthly_total - new_summary.monthly_total
    total_saving = current_summary.total_cost - new_summary.total_cost

    fixation_saving = None
    if new_offer.fixation_years > 0 and new_summary.fixation:
        cur_fix = _cost_over_months(current, new_offer.fixation_years * 12)
        new_fix = new_summary.fixation.total_cost_in_fixation
        fixation_saving = round(cur_fix - new_fix, 2)

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

    breakeven = find_breakeven_month(current, new_offer)

    return RefinancingSummary(
        current=current_summary,
        new_offer=new_summary,
        monthly_saving=round(monthly_saving, 2),
        total_saving=round(total_saving, 2),
        fixation_saving=fixation_saving,
        common_period_saving=common_period_saving,
        common_period_months=common_period_months,
        breakeven_month=breakeven,
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


# --- Optimální splátka ---

@dataclass
class PaymentStrategyResult:
    """Výsledek simulace jedné platební strategie."""
    strategy_name: str
    monthly_mortgage_payment: float
    monthly_extra: float
    monthly_investment: float
    months_to_payoff: int
    total_interest_paid: float
    investment_value_at_end: float
    net_wealth_at_end: float  # investice - zaplacené úroky
    timeline: list[dict]  # month, mortgage_balance, investment_value, net_wealth


def optimal_payment_analysis(
    params: MortgageParams,
    total_monthly_budget: float,
    investment_annual_return: float,
    inflation_annual: float = 0.0,
) -> list[PaymentStrategyResult]:
    """Simuluje různé strategie splácení vs. investování.

    Args:
        params: Parametry hypotéky
        total_monthly_budget: Celkový měsíční budget (splátka + investice)
        investment_annual_return: Očekávaný roční výnos investice v %
        inflation_annual: Roční inflace v % (pro reálný výnos)
    """
    base_payment = monthly_payment(params.principal, params.monthly_rate, params.months)
    available_extra = max(0, total_monthly_budget - base_payment)

    real_return = investment_annual_return - inflation_annual
    monthly_inv_rate = real_return / 100 / 12

    # Strategie: 0%, 25%, 50%, 75%, 100% z extra jde na hypotéku
    strategies = [
        ("Minimum (vše investovat)", 0.0),
        ("25 % extra na hypotéku", 0.25),
        ("50 % extra na hypotéku", 0.50),
        ("75 % extra na hypotéku", 0.75),
        ("Maximum (vše na hypotéku)", 1.0),
    ]

    results = []
    for name, extra_ratio in strategies:
        monthly_extra = available_extra * extra_ratio
        monthly_invest_contrib = available_extra - monthly_extra

        balance = params.principal
        investment = 0.0
        total_interest = 0.0
        months_to_payoff = params.months
        timeline = []

        for month in range(1, params.months + 1):
            interest = balance * params.monthly_rate
            total_interest += interest

            if balance <= 0:
                # Hypotéka splacena — vše jde do investice
                investment = investment * (1 + monthly_inv_rate) + total_monthly_budget
            else:
                principal_part = base_payment - interest + monthly_extra
                if principal_part >= balance:
                    principal_part = balance
                    months_to_payoff = month
                    leftover = base_payment + monthly_extra - interest - balance
                    balance = 0.0
                    investment = investment * (1 + monthly_inv_rate) + monthly_invest_contrib + leftover
                else:
                    balance -= principal_part
                    investment = investment * (1 + monthly_inv_rate) + monthly_invest_contrib

            net_wealth = investment - total_interest

            if month % 12 == 0 or month == params.months or month == months_to_payoff:
                timeline.append({
                    "month": month,
                    "mortgage_balance": round(max(balance, 0), 0),
                    "investment_value": round(investment, 0),
                    "net_wealth": round(net_wealth, 0),
                    "total_interest": round(total_interest, 0),
                })

        results.append(PaymentStrategyResult(
            strategy_name=name,
            monthly_mortgage_payment=round(base_payment + monthly_extra, 2),
            monthly_extra=round(monthly_extra, 2),
            monthly_investment=round(monthly_invest_contrib, 2),
            months_to_payoff=months_to_payoff,
            total_interest_paid=round(total_interest, 2),
            investment_value_at_end=round(investment, 2),
            net_wealth_at_end=round(investment - total_interest, 2),
            timeline=timeline,
        ))

    return results


def find_breakeven_investment_rate(
    params: MortgageParams,
    total_monthly_budget: float,
    tolerance: float = 0.01,
) -> float:
    """Najde sazbu investice, při které je jedno jestli splácíte navíc nebo investujete.

    Binární vyhledávání: hledá sazbu kde min-payment a max-payment strategie
    dávají stejný čistý majetek na konci.
    """
    lo, hi = 0.0, 30.0

    for _ in range(100):
        mid = (lo + hi) / 2
        results = optimal_payment_analysis(params, total_monthly_budget, mid)
        min_payment_wealth = results[0].net_wealth_at_end  # vše investovat
        max_payment_wealth = results[-1].net_wealth_at_end  # vše na hypotéku

        if abs(min_payment_wealth - max_payment_wealth) < 100:
            return round(mid, 2)

        if min_payment_wealth > max_payment_wealth:
            hi = mid  # investice je moc výhodná, snížit sazbu
        else:
            lo = mid  # investice je málo výhodná, zvýšit sazbu

    return round((lo + hi) / 2, 2)
