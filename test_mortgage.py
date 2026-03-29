"""Testy výpočetní logiky hypoteční kalkulačky."""

import math
import unittest

from mortgage import (
    AdditionalCost,
    FixationPeriod,
    MortgageParams,
    monthly_payment,
    amortization_schedule,
    calculate_rpsn,
    calculate_fixation_summary,
    calculate_summary,
    combined_timeline,
    compare_refinancing,
    cumulative_cost_schedule,
    find_breakeven_month,
    generate_verdict,
    historical_amortization_schedule,
    sensitivity_analysis,
    optimal_payment_analysis,
    find_breakeven_investment_rate,
    validate_mortgage_history,
    _cost_over_months,
    fixation_comparison_matrix,
)
from data_io import params_to_dict, dict_to_params, export_json, import_json, import_bank_csv, summaries_to_csv


# ============================================================
# Pomocné factory funkce
# ============================================================

def _params(
    principal=2_000_000, rate=4.0, years=20, fixation=5,
    bank="Banka", is_current=False, bonus=0.0,
    additional_costs=None, switching_costs=None,
):
    return MortgageParams(
        principal=principal,
        annual_rate=rate,
        years=years,
        bank_name=bank,
        fixation_years=fixation,
        is_current_bank=is_current,
        bonus=bonus,
        additional_costs=additional_costs or [],
        switching_costs=switching_costs or [],
    )


# ============================================================
# MortgageParams
# ============================================================

class TestMortgageParams(unittest.TestCase):
    def test_months(self):
        p = _params(years=20)
        self.assertEqual(p.months, 240)

    def test_monthly_rate(self):
        p = _params(rate=6.0)
        self.assertAlmostEqual(p.monthly_rate, 0.005, places=6)

    def test_monthly_rate_zero(self):
        p = _params(rate=0.0)
        self.assertEqual(p.monthly_rate, 0.0)


# ============================================================
# monthly_payment
# ============================================================

class TestMonthlyPayment(unittest.TestCase):
    def test_known_value(self):
        """2 000 000 Kč, 4 %, 20 let → ~12 120 Kč."""
        pmt = monthly_payment(2_000_000, 4.0 / 100 / 12, 240)
        self.assertAlmostEqual(pmt, 12_119.61, delta=1.0)

    def test_zero_rate(self):
        pmt = monthly_payment(1_200_000, 0.0, 120)
        self.assertAlmostEqual(pmt, 10_000.0, delta=0.01)

    def test_high_rate(self):
        """Splátka roste s vyšší sazbou."""
        low = monthly_payment(1_000_000, 3.0 / 100 / 12, 360)
        high = monthly_payment(1_000_000, 6.0 / 100 / 12, 360)
        self.assertGreater(high, low)

    def test_shorter_term_higher_payment(self):
        short = monthly_payment(1_000_000, 4.0 / 100 / 12, 120)
        long = monthly_payment(1_000_000, 4.0 / 100 / 12, 360)
        self.assertGreater(short, long)

    def test_moneta_example(self):
        """Ověření proti Moneta kalkulačce: 2 500 000, 3.99 %, 30 let."""
        pmt = monthly_payment(2_500_000, 3.99 / 100 / 12, 360)
        self.assertAlmostEqual(pmt, 11_921, delta=1.0)


# ============================================================
# amortization_schedule
# ============================================================

class TestAmortizationSchedule(unittest.TestCase):
    def test_length(self):
        p = _params(years=10)
        sched = amortization_schedule(p)
        self.assertEqual(len(sched), 120)

    def test_balance_reaches_zero(self):
        p = _params()
        sched = amortization_schedule(p)
        self.assertEqual(sched[-1].remaining_balance, 0.0)

    def test_cumulative_principal_equals_loan(self):
        p = _params(principal=1_500_000, rate=5.0, years=15)
        sched = amortization_schedule(p)
        self.assertAlmostEqual(sched[-1].cumulative_principal, 1_500_000, delta=1.0)

    def test_first_month_interest(self):
        p = _params(principal=1_000_000, rate=6.0, years=10)
        sched = amortization_schedule(p)
        expected = 1_000_000 * 6.0 / 100 / 12
        self.assertAlmostEqual(sched[0].interest_part, expected, delta=0.01)

    def test_payment_constant(self):
        """Splátka je konstantní (kromě posledního měsíce)."""
        p = _params()
        sched = amortization_schedule(p)
        payments = [r.payment for r in sched[:-1]]
        self.assertTrue(all(p == payments[0] for p in payments))

    def test_interest_decreasing(self):
        """Úroková část klesá v čase."""
        p = _params()
        sched = amortization_schedule(p)
        for i in range(len(sched) - 2):
            self.assertGreaterEqual(sched[i].interest_part, sched[i + 1].interest_part)

    def test_principal_part_increasing(self):
        """Splátka jistiny roste v čase (kromě posledního měsíce)."""
        p = _params()
        sched = amortization_schedule(p)
        for i in range(len(sched) - 3):
            self.assertLessEqual(sched[i].principal_part, sched[i + 1].principal_part)


# ============================================================
# RPSN
# ============================================================

class TestRPSN(unittest.TestCase):
    def test_no_fees_equals_nominal(self):
        """Bez poplatků RPSN == nominální sazba."""
        p = _params(rate=4.0, is_current=True)
        rpsn = calculate_rpsn(p)
        self.assertAlmostEqual(rpsn, 4.0, delta=0.01)

    def test_fees_increase_rpsn(self):
        """S měsíčními poplatky je RPSN vyšší než sazba."""
        p = _params(
            rate=4.0,
            additional_costs=[AdditionalCost("Pojištění", monthly_amount=200)],
        )
        rpsn = calculate_rpsn(p)
        self.assertGreater(rpsn, 4.0)

    def test_onetime_fees_increase_rpsn(self):
        """S jednorázovými poplatky je RPSN vyšší než sazba."""
        p = _params(
            rate=4.0,
            switching_costs=[AdditionalCost("Odhad", one_time_amount=5000)],
        )
        rpsn = calculate_rpsn(p)
        self.assertGreater(rpsn, 4.0)

    def test_bonus_decreases_rpsn(self):
        """Bonus snižuje RPSN."""
        sw = [AdditionalCost("Odhad", one_time_amount=5000)]
        p_no = _params(rate=4.0, switching_costs=sw, bonus=0)
        p_yes = _params(rate=4.0, switching_costs=sw, bonus=3000)
        self.assertLess(calculate_rpsn(p_yes), calculate_rpsn(p_no))

    def test_bonus_exceeds_fees(self):
        """Bonus > poplatky → RPSN pod nominální sazbou."""
        sw = [AdditionalCost("Odhad", one_time_amount=3000)]
        p = _params(rate=4.0, switching_costs=sw, bonus=7000)
        self.assertLess(calculate_rpsn(p), 4.0)

    def test_current_bank_ignores_switching(self):
        """Stávající banka — switching costs se nezapočítávají do RPSN."""
        sw = [AdditionalCost("ČÚZK", one_time_amount=5000)]
        p = _params(rate=4.0, is_current=True, switching_costs=sw)
        self.assertAlmostEqual(calculate_rpsn(p), 4.0, delta=0.01)

    def test_moneta_no_bonus(self):
        """Moneta: 2 500 000, 3.99 %, 30 let, poplatky 6 650 Kč → RPSN > 3.99."""
        sw = [
            AdditionalCost("Odhad", one_time_amount=3000),
            AdditionalCost("ČÚZK vklad", one_time_amount=2000),
            AdditionalCost("ČÚZK výmaz", one_time_amount=1600),
            AdditionalCost("Ověření", one_time_amount=50),
        ]
        p = _params(principal=2_500_000, rate=3.99, years=30, fixation=3,
                    switching_costs=sw, bonus=0)
        rpsn = calculate_rpsn(p)
        self.assertGreater(rpsn, 4.0)
        self.assertLess(rpsn, 4.10)


# ============================================================
# FixationSummary
# ============================================================

class TestFixationSummary(unittest.TestCase):
    def test_fixation_months(self):
        p = _params(fixation=5)
        fs = calculate_fixation_summary(p)
        self.assertEqual(fs.fixation_months, 60)

    def test_fixation_within_total(self):
        p = _params(years=20, fixation=5)
        fs = calculate_fixation_summary(p)
        self.assertLessEqual(fs.fixation_months, p.months)

    def test_remaining_balance_positive(self):
        p = _params(years=20, fixation=3)
        fs = calculate_fixation_summary(p)
        self.assertGreater(fs.remaining_balance, 0)

    def test_paid_equals_interest_plus_principal(self):
        p = _params(fixation=5)
        fs = calculate_fixation_summary(p)
        self.assertAlmostEqual(
            fs.paid_in_fixation,
            fs.interest_in_fixation + fs.principal_in_fixation, delta=1.0)

    def test_switching_costs_included(self):
        sw = [AdditionalCost("Odhad", one_time_amount=5000)]
        p = _params(fixation=3, switching_costs=sw)
        fs = calculate_fixation_summary(p)
        self.assertEqual(fs.switching_costs, 5000.0)

    def test_switching_zero_for_current_bank(self):
        sw = [AdditionalCost("Odhad", one_time_amount=5000)]
        p = _params(fixation=3, switching_costs=sw, is_current=True)
        fs = calculate_fixation_summary(p)
        self.assertEqual(fs.switching_costs, 0.0)

    def test_effective_monthly_cost(self):
        p = _params(fixation=5)
        fs = calculate_fixation_summary(p)
        expected = fs.total_cost_in_fixation / fs.fixation_months
        self.assertAlmostEqual(fs.effective_monthly_cost, expected, delta=0.01)

    def test_bonus_reduces_total_cost(self):
        p_no = _params(fixation=3, bonus=0)
        p_yes = _params(fixation=3, bonus=5000)
        fs_no = calculate_fixation_summary(p_no)
        fs_yes = calculate_fixation_summary(p_yes)
        self.assertLess(fs_yes.total_cost_in_fixation, fs_no.total_cost_in_fixation)

    def test_fixation_exceeds_term(self):
        """Fixace delší než celková doba → ořízne na celou dobu."""
        p = _params(years=3, fixation=10)
        fs = calculate_fixation_summary(p)
        self.assertEqual(fs.fixation_months, 36)


# ============================================================
# MortgageSummary
# ============================================================

class TestMortgageSummary(unittest.TestCase):
    def test_total_interest(self):
        p = _params()
        s = calculate_summary(p)
        self.assertAlmostEqual(s.total_interest, s.total_paid - s.principal, delta=1.0)

    def test_monthly_total_includes_fees(self):
        costs = [AdditionalCost("Pojištění", monthly_amount=300)]
        p = _params(additional_costs=costs)
        s = calculate_summary(p)
        self.assertAlmostEqual(s.monthly_total, s.monthly_payment + 300, delta=0.01)

    def test_total_cost_formula(self):
        sw = [AdditionalCost("Odhad", one_time_amount=3000)]
        costs = [AdditionalCost("Pojištění", monthly_amount=200)]
        p = _params(additional_costs=costs, switching_costs=sw, bonus=1000)
        s = calculate_summary(p)
        expected = s.total_interest + s.total_additional_costs + s.total_switching_costs - s.bonus
        self.assertAlmostEqual(s.total_cost, expected, delta=1.0)

    def test_fixation_present(self):
        p = _params(fixation=5)
        s = calculate_summary(p)
        self.assertIsNotNone(s.fixation)
        self.assertEqual(s.fixation.fixation_years, 5)

    def test_no_fixation(self):
        p = _params(fixation=0)
        s = calculate_summary(p)
        self.assertIsNone(s.fixation)


# ============================================================
# Verdict
# ============================================================

class TestVerdict(unittest.TestCase):
    def test_no_offers(self):
        v = generate_verdict([])
        self.assertEqual(v.color, "red")

    def test_single_offer(self):
        s = calculate_summary(_params(bank="Jediná"))
        v = generate_verdict([s])
        self.assertEqual(v.color, "green")
        self.assertEqual(v.best_offer_name, "Jediná")
        self.assertEqual(len(v.ranking), 1)

    def test_clear_winner(self):
        """Nabídka s nižší sazbou musí vyhrát."""
        cheap = calculate_summary(_params(bank="Levná", rate=3.0))
        expensive = calculate_summary(_params(bank="Drahá", rate=6.0))
        v = generate_verdict([expensive, cheap])
        self.assertEqual(v.best_offer_name, "Levná")
        self.assertEqual(v.ranking[0]["rank"], 1)

    def test_close_offers_yellow(self):
        """Téměř stejné nabídky → yellow."""
        a = calculate_summary(_params(bank="A", rate=4.00))
        b = calculate_summary(_params(bank="B", rate=4.01))
        v = generate_verdict([a, b])
        self.assertEqual(v.color, "yellow")


# ============================================================
# Refinancování
# ============================================================

class TestRefinancing(unittest.TestCase):
    def _current(self):
        return _params(rate=5.5, years=20, fixation=3, is_current=True, bank="Stávající")

    def _offer(self):
        return _params(
            rate=3.99, years=20, fixation=3, bank="Nová",
            switching_costs=[AdditionalCost("Odhad", one_time_amount=3000)],
        )

    def test_monthly_saving_positive(self):
        ref = compare_refinancing(self._current(), self._offer())
        self.assertGreater(ref.monthly_saving, 0)

    def test_total_saving_positive(self):
        ref = compare_refinancing(self._current(), self._offer())
        self.assertGreater(ref.total_saving, 0)

    def test_fixation_saving(self):
        ref = compare_refinancing(self._current(), self._offer())
        self.assertIsNotNone(ref.fixation_saving)
        self.assertGreater(ref.fixation_saving, 0)

    def test_common_period(self):
        ref = compare_refinancing(self._current(), self._offer())
        self.assertEqual(ref.common_period_months, 36)
        self.assertIsNotNone(ref.common_period_saving)

    def test_breakeven_exists(self):
        ref = compare_refinancing(self._current(), self._offer())
        self.assertIsNotNone(ref.breakeven_month)
        self.assertGreater(ref.breakeven_month, 0)

    def test_breakeven_zero_if_no_switching_cost(self):
        offer = _params(rate=3.99, years=20, fixation=3, bank="Nová", bonus=5000)
        be = find_breakeven_month(self._current(), offer)
        self.assertEqual(be, 0)

    def test_no_saving_when_same_rate(self):
        same = _params(rate=5.5, years=20, fixation=3, bank="Nová")
        ref = compare_refinancing(self._current(), same)
        self.assertAlmostEqual(ref.monthly_saving, 0, delta=1.0)


# ============================================================
# Kumulativní náklady
# ============================================================

class TestCumulativeCosts(unittest.TestCase):
    def test_length(self):
        p = _params(years=10)
        rows = cumulative_cost_schedule(p)
        self.assertEqual(len(rows), 120)

    def test_monotonically_increasing(self):
        p = _params()
        rows = cumulative_cost_schedule(p)
        for i in range(len(rows) - 1):
            self.assertGreaterEqual(
                rows[i + 1].cumulative_total_cost, rows[i].cumulative_total_cost)

    def test_includes_switching_costs(self):
        sw = [AdditionalCost("Odhad", one_time_amount=5000)]
        p = _params(switching_costs=sw)
        rows = cumulative_cost_schedule(p)
        self.assertEqual(rows[0].cumulative_switching, 5000.0)

    def test_no_switching_for_current(self):
        sw = [AdditionalCost("Odhad", one_time_amount=5000)]
        p = _params(switching_costs=sw, is_current=True)
        rows = cumulative_cost_schedule(p)
        self.assertEqual(rows[0].cumulative_switching, 0.0)


# ============================================================
# cost_over_months a fixation_comparison_matrix
# ============================================================

class TestCostOverMonths(unittest.TestCase):
    def test_cost_positive(self):
        p = _params()
        cost = _cost_over_months(p, 60)
        self.assertGreater(cost, 0)

    def test_cost_grows_with_time(self):
        p = _params()
        c1 = _cost_over_months(p, 36)
        c2 = _cost_over_months(p, 60)
        self.assertGreater(c2, c1)

    def test_matrix_has_rows(self):
        a = _params(bank="A", fixation=3)
        b = _params(bank="B", fixation=5)
        rows = fixation_comparison_matrix(None, [a, b])
        self.assertGreater(len(rows), 0)
        self.assertIn("Fixace (let)", rows[0])


# ============================================================
# Citlivostní analýza
# ============================================================

class TestSensitivityAnalysis(unittest.TestCase):
    def test_contains_base_rate(self):
        p = _params(rate=4.0)
        results = sensitivity_analysis(p)
        rates = [r["sazba"] for r in results]
        self.assertIn(4.0, rates)

    def test_delta_zero_matches_base(self):
        p = _params(rate=4.0)
        results = sensitivity_analysis(p)
        base = [r for r in results if r["delta"] == 0.0][0]
        expected = monthly_payment(p.principal, p.monthly_rate, p.months)
        self.assertAlmostEqual(base["mesicni_splatka"], expected, delta=0.01)

    def test_higher_rate_higher_payment(self):
        p = _params(rate=4.0)
        results = sensitivity_analysis(p)
        base = [r for r in results if r["delta"] == 0.0][0]
        higher = [r for r in results if r["delta"] > 0][0]
        self.assertGreater(higher["mesicni_splatka"], base["mesicni_splatka"])


# ============================================================
# Optimální splátka
# ============================================================

class TestOptimalPayment(unittest.TestCase):
    def test_five_strategies(self):
        p = _params(rate=4.0, years=20)
        pmt = monthly_payment(p.principal, p.monthly_rate, p.months)
        results = optimal_payment_analysis(p, pmt + 5000, 7.0)
        self.assertEqual(len(results), 5)

    def test_max_extra_fastest_payoff(self):
        p = _params(rate=4.0, years=20)
        pmt = monthly_payment(p.principal, p.monthly_rate, p.months)
        results = optimal_payment_analysis(p, pmt + 5000, 7.0)
        self.assertLess(results[-1].months_to_payoff, results[0].months_to_payoff)

    def test_min_extra_most_interest(self):
        p = _params(rate=4.0, years=20)
        pmt = monthly_payment(p.principal, p.monthly_rate, p.months)
        results = optimal_payment_analysis(p, pmt + 5000, 7.0)
        self.assertGreater(results[0].total_interest_paid, results[-1].total_interest_paid)

    def test_breakeven_rate_positive(self):
        p = _params(rate=4.0, years=20)
        pmt = monthly_payment(p.principal, p.monthly_rate, p.months)
        rate = find_breakeven_investment_rate(p, pmt + 5000)
        self.assertGreater(rate, 0)


# ============================================================
# Data IO
# ============================================================

class TestDataIO(unittest.TestCase):
    def test_roundtrip(self):
        p = _params(
            bank="Test",
            additional_costs=[AdditionalCost("Poj", monthly_amount=200)],
            switching_costs=[AdditionalCost("Odhad", one_time_amount=3000)],
            bonus=5000,
        )
        d = params_to_dict(p)
        p2 = dict_to_params(d)
        self.assertEqual(p2.principal, p.principal)
        self.assertEqual(p2.annual_rate, p.annual_rate)
        self.assertEqual(p2.bank_name, p.bank_name)
        self.assertEqual(p2.bonus, p.bonus)
        self.assertEqual(len(p2.additional_costs), 1)
        self.assertEqual(p2.additional_costs[0].monthly_amount, 200)
        self.assertEqual(len(p2.switching_costs), 1)

    def test_export_import_json(self):
        cur = _params(bank="Stávající", is_current=True)
        offers = [_params(bank="Nová A"), _params(bank="Nová B")]
        json_str = export_json(cur, offers)
        imported = import_json(json_str)
        self.assertEqual(imported["current_mortgage"].bank_name, "Stávající")
        self.assertEqual(len(imported["offers"]), 2)
        self.assertEqual(imported["offers"][0].bank_name, "Nová A")

    def test_export_no_current(self):
        offers = [_params(bank="A")]
        json_str = export_json(None, offers)
        imported = import_json(json_str)
        self.assertIsNone(imported["current_mortgage"])
        self.assertEqual(len(imported["offers"]), 1)

    def test_csv_export(self):
        s = calculate_summary(_params(bank="Test"))
        csv_str = summaries_to_csv([s])
        self.assertIn("Test", csv_str)
        self.assertIn("Banka", csv_str)


# ============================================================
# AdditionalCost
# ============================================================

class TestAdditionalCost(unittest.TestCase):
    def test_total_over_months_monthly(self):
        c = AdditionalCost("Poj", monthly_amount=200)
        self.assertEqual(c.total_over_months(12), 2400)

    def test_total_over_months_onetime(self):
        c = AdditionalCost("Odhad", one_time_amount=3000)
        self.assertEqual(c.total_over_months(12), 3000)

    def test_total_over_months_combined(self):
        c = AdditionalCost("Mix", monthly_amount=100, one_time_amount=500)
        self.assertEqual(c.total_over_months(10), 1500)


# ============================================================
# Historie hypotéky
# ============================================================

class TestHistoricalSchedule(unittest.TestCase):
    def _fixations(self):
        return [
            FixationPeriod(annual_rate=2.5, duration_months=60),   # 5 let
            FixationPeriod(annual_rate=5.5, duration_months=36),   # 3 roky
        ]

    def test_length(self):
        rows = historical_amortization_schedule(2_000_000, 20, self._fixations())
        self.assertEqual(len(rows), 96)  # 60 + 36

    def test_balance_decreasing(self):
        rows = historical_amortization_schedule(2_000_000, 20, self._fixations())
        for i in range(len(rows) - 1):
            self.assertGreaterEqual(rows[i].remaining_balance, rows[i + 1].remaining_balance)

    def test_all_past(self):
        rows = historical_amortization_schedule(2_000_000, 20, self._fixations())
        self.assertTrue(all(r.is_past for r in rows))

    def test_month_numbering(self):
        rows = historical_amortization_schedule(2_000_000, 20, self._fixations())
        months = [r.month for r in rows]
        self.assertEqual(months, list(range(1, 97)))

    def test_cumulative_principal_positive(self):
        rows = historical_amortization_schedule(2_000_000, 20, self._fixations())
        self.assertGreater(rows[-1].cumulative_principal, 0)

    def test_balance_less_than_original(self):
        rows = historical_amortization_schedule(2_000_000, 20, self._fixations())
        self.assertLess(rows[-1].remaining_balance, 2_000_000)

    def test_fixation_labels(self):
        rows = historical_amortization_schedule(2_000_000, 20, self._fixations())
        labels = set(r.fixation_label for r in rows)
        self.assertEqual(len(labels), 2)

    def test_payment_changes_between_fixations(self):
        """Splátka se změní při nové fixaci (jiná sazba)."""
        rows = historical_amortization_schedule(2_000_000, 20, self._fixations())
        pmt_fix1 = rows[0].payment
        pmt_fix2 = rows[60].payment
        self.assertNotAlmostEqual(pmt_fix1, pmt_fix2, delta=1.0)

    def test_single_fixation(self):
        rows = historical_amortization_schedule(
            1_000_000, 10, [FixationPeriod(3.0, 24)])
        self.assertEqual(len(rows), 24)

    def test_empty_fixations(self):
        rows = historical_amortization_schedule(1_000_000, 10, [])
        self.assertEqual(len(rows), 0)


class TestValidateMortgageHistory(unittest.TestCase):
    def test_no_history(self):
        p = _params()
        ok, msg = validate_mortgage_history(p)
        self.assertTrue(ok)

    def test_matching_balance(self):
        """Historie by měla odpovídat zbývající jistině."""
        # Spočítáme zbývající jistinu po 60 měsících fixace 2.5%
        rows = historical_amortization_schedule(
            2_000_000, 20, [FixationPeriod(2.5, 60)])
        remaining = rows[-1].remaining_balance

        p = _params(
            principal=remaining, years=15, rate=5.5,
            additional_costs=[], switching_costs=[])
        p = MortgageParams(
            principal=remaining, annual_rate=5.5, years=15,
            original_principal=2_000_000, original_term_years=20,
            past_fixations=[FixationPeriod(2.5, 60)])
        ok, msg = validate_mortgage_history(p)
        self.assertTrue(ok)

    def test_mismatched_balance(self):
        p = MortgageParams(
            principal=500_000, annual_rate=5.5, years=15,
            original_principal=2_000_000, original_term_years=20,
            past_fixations=[FixationPeriod(2.5, 60)])
        ok, msg = validate_mortgage_history(p)
        self.assertFalse(ok)


class TestCombinedTimeline(unittest.TestCase):
    def test_past_plus_future(self):
        current = MortgageParams(
            principal=1_500_000, annual_rate=5.5, years=15,
            original_principal=2_000_000, original_term_years=20,
            past_fixations=[FixationPeriod(2.5, 60)],
            is_current_bank=True)
        future = _params(principal=1_500_000, rate=3.99, years=15, bank="Nová")
        tl = combined_timeline(current, future)
        past = [r for r in tl if r.is_past]
        fut = [r for r in tl if not r.is_past]
        self.assertEqual(len(past), 60)
        self.assertEqual(len(fut), 180)

    def test_month_continuity(self):
        current = MortgageParams(
            principal=1_500_000, annual_rate=5.5, years=15,
            original_principal=2_000_000, original_term_years=20,
            past_fixations=[FixationPeriod(2.5, 60)],
            is_current_bank=True)
        future = _params(principal=1_500_000, rate=3.99, years=15, bank="Nová")
        tl = combined_timeline(current, future)
        months = [r.month for r in tl]
        self.assertEqual(months, list(range(1, len(tl) + 1)))

    def test_cumulative_interest_continuous(self):
        current = MortgageParams(
            principal=1_500_000, annual_rate=5.5, years=15,
            original_principal=2_000_000, original_term_years=20,
            past_fixations=[FixationPeriod(2.5, 60)],
            is_current_bank=True)
        future = _params(principal=1_500_000, rate=3.99, years=15, bank="Nová")
        tl = combined_timeline(current, future)
        # Kumulativní úroky by neměly klesnout na hranici minulost/budoucnost
        past_last = [r for r in tl if r.is_past][-1]
        fut_first = [r for r in tl if not r.is_past][0]
        self.assertGreater(fut_first.cumulative_interest, past_last.cumulative_interest)

    def test_no_history(self):
        """Bez historie — jen budoucí řádky."""
        current = _params(principal=2_000_000, rate=5.5, years=20, is_current=True)
        future = _params(principal=2_000_000, rate=3.99, years=20, bank="Nová")
        tl = combined_timeline(current, future)
        self.assertTrue(all(not r.is_past for r in tl))
        self.assertEqual(len(tl), 240)


class TestBankCSVImport(unittest.TestCase):
    SAMPLE_CSV = """\
Datum;Čerpání Kč;Mimořádná splátka Kč;Sazba % p. a.;Splátka Kč;Úrok Kč;Jistina Kč;Nesplacená jistina Kč
24. 2. 2017;800 000;;1.690;;;;800 000
25. 2. 2017;;;1.690;37,56;37,56;0;800 000
25. 3. 2017;;;1.690;1 126,80;1 126,80;0;800 000
25. 4. 2017;;;1.690;1 126,80;1 126,80;0;800 000
11. 6. 2018;750 000;;1.690;;;;1 550 000
20. 6. 2018;340 000;;1.690;;;;1 890 000
25. 6. 2018;;;1.690;1 699,45;1 699,45;0;1 890 000
25. 7. 2018;;;1.690;6 696,50;2 661,90;4 034,60;1 885 965,40
25. 8. 2018;;;1.690;6 696,50;2 656,20;4 040,30;1 881 925,10
"""

    def test_parse_rows(self):
        rows = import_bank_csv(self.SAMPLE_CSV)
        # 3 interest-only + 1 interest after last drawdown + 2 regular = 6
        self.assertEqual(len(rows), 6)

    def test_drawdowns_skipped(self):
        rows = import_bank_csv(self.SAMPLE_CSV)
        # No row should have is_past=False
        self.assertTrue(all(r.is_past for r in rows))

    def test_balance_decreasing_after_drawdown(self):
        rows = import_bank_csv(self.SAMPLE_CSV)
        # After all drawdowns, balance should decrease
        regular = [r for r in rows if r.principal_part > 0]
        if len(regular) >= 2:
            self.assertGreater(regular[0].remaining_balance, regular[-1].remaining_balance)

    def test_cumulative_interest(self):
        rows = import_bank_csv(self.SAMPLE_CSV)
        total = sum(r.interest_part for r in rows)
        self.assertAlmostEqual(rows[-1].cumulative_interest, total, delta=0.01)

    def test_fixation_label(self):
        rows = import_bank_csv(self.SAMPLE_CSV)
        self.assertIn("1.69", rows[0].fixation_label)

    def test_czech_number_parsing(self):
        """Čísla s mezerami a čárkou se správně parsují."""
        rows = import_bank_csv(self.SAMPLE_CSV)
        regular = [r for r in rows if r.payment > 6000]
        self.assertGreater(len(regular), 0)
        self.assertAlmostEqual(regular[0].payment, 6696.50, delta=0.01)

    def test_bytes_windows1250(self):
        encoded = self.SAMPLE_CSV.encode("windows-1250")
        rows = import_bank_csv(encoded)
        self.assertGreater(len(rows), 0)

    def test_bytes_utf8(self):
        encoded = self.SAMPLE_CSV.encode("utf-8")
        rows = import_bank_csv(encoded, encoding="utf-8")
        self.assertGreater(len(rows), 0)


class TestDataIOHistory(unittest.TestCase):
    def test_roundtrip_with_history(self):
        p = MortgageParams(
            principal=1_500_000, annual_rate=5.5, years=15,
            bank_name="Test", original_principal=2_000_000,
            original_term_years=20, start_date="2021-06-15",
            past_fixations=[
                FixationPeriod(2.5, 60),
                FixationPeriod(5.5, 36),
            ])
        d = params_to_dict(p)
        p2 = dict_to_params(d)
        self.assertAlmostEqual(p2.original_principal, 2_000_000)
        self.assertEqual(p2.original_term_years, 20)
        self.assertEqual(p2.start_date, "2021-06-15")
        self.assertEqual(len(p2.past_fixations), 2)
        self.assertEqual(p2.past_fixations[0].duration_months, 60)
        self.assertAlmostEqual(p2.past_fixations[1].annual_rate, 5.5)

    def test_backward_compat_no_history(self):
        """Import bez historie — výchozí hodnoty."""
        d = {"principal": 1_000_000, "annual_rate": 4.0, "years": 20,
             "bank_name": "X", "additional_costs": [], "switching_costs": [],
             "is_current_bank": False, "fixation_years": 5, "bonus": 0}
        p = dict_to_params(d)
        self.assertEqual(p.original_principal, 0.0)
        self.assertEqual(p.past_fixations, [])


if __name__ == "__main__":
    unittest.main()
