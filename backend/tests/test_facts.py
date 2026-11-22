"""Deterministic fact checking of reports against the computed facts."""

from __future__ import annotations

from backend.facts import build_facts, extract_numbers, verify_report

# What the sandbox extracted from the product-catalog run in the bug report.
INDICATORS = {
    "price": {"Electronics": 94.0, "Home": 63.25, "Sports": 24.25},
    "rating": {"Electronics": 4.375, "Home": 4.375, "Sports": 4.325},
}
STDOUT = (
    "             price  rating\n"
    "category\n"
    "Electronics  94.00   4.375\n"
    "Home         63.25   4.375\n"
    "Sports       24.25   4.325\n"
    "      sku               name     category  stock\n"
    "2  EL-102  Bluetooth Speaker  Electronics      0\n"
    "5  HO-201          Desk Lamp         Home      8\n"
    "7  HO-203       Air Purifier         Home      0\n"
    "9  SP-301       Running Belt       Sports      5\n"
)
FILE_DATA = {"row_count": 12, "columns": ["sku", "name", "category", "price", "stock", "rating"]}

FACTS = build_facts(INDICATORS, STDOUT, FILE_DATA)

CORRECT = """# Summary
The product catalog contains 12 items across three categories: Electronics, Home, and Sports.
Average prices are 94.00, 63.25, and 24.25 respectively, while average ratings are 4.375, 4.375, and 4.325.

## Key Findings
* Electronics have the highest average price (94.00) and share the highest average rating (4.375) with Home.
* Sports products have the lowest average price (24.25) and rating (4.325).
* Four items are at risk of stock shortage.
"""


# --- Facts JSON ---------------------------------------------------------------


def test_facts_rank_each_indicator_with_ties() -> None:
    price = FACTS["indicators"]["price"]
    assert price["max"] == "Electronics" and price["min"] == "Sports"
    assert price["values"] == {"Electronics": 94.0, "Home": 63.25, "Sports": 24.25}

    rating = FACTS["indicators"]["rating"]
    assert rating["max"] == "Electronics"
    assert rating["max_all"] == ["Electronics", "Home"]  # tie at 4.375
    assert rating["min_all"] == ["Sports"]


def test_facts_numbers_include_values_output_and_dataset_size() -> None:
    numbers = set(FACTS["numbers"])
    assert {94.0, 63.25, 24.25, 4.375, 4.325} <= numbers  # indicators
    assert {8.0, 5.0} <= numbers  # printed by the code
    assert 12.0 in numbers  # dataset rows


def test_extract_numbers_reads_separators_decimals_and_percents() -> None:
    text = "Revenue 157,250 then 94.00 and 50% in 2026; see ![c](/uploads/chart_9f3a12.png)\n1. first item"
    assert extract_numbers(text) == [(157250.0, 0, False), (94.0, 2, False), (50.0, 0, True), (2026.0, 0, False)]


# --- Verifier -----------------------------------------------------------------


def test_correct_report_passes() -> None:
    assert verify_report(CORRECT, FACTS) == []


def test_invented_number_is_reported() -> None:
    errors = verify_report(CORRECT + "\nTotal revenue reached 1,234.50.\n", FACTS)
    assert errors == ["The number 1,234.50 does not appear in the computed results."]


def test_rounded_numbers_are_accepted_at_their_precision() -> None:
    assert verify_report("Electronics average about 94 and Sports 24.3.", FACTS) == []


def test_wrong_superlative_from_the_bug_report_is_caught() -> None:
    report = CORRECT + "* Home products have the highest average price among the three categories.\n"
    errors = verify_report(report, FACTS)
    assert "'Home' is not the highest for price: the highest is Electronics." in errors


def test_internal_contradiction_is_caught() -> None:
    report = (
        "Electronics have the highest average price (94.00).\n"
        "Later on, Sports have the highest average price.\n"
    )
    errors = verify_report(report, FACTS)
    assert any("Contradiction on price" in error for error in errors)


def test_label_claimed_highest_and_lowest_is_a_contradiction() -> None:
    errors = verify_report("Home has the highest price. Home has the lowest price.", FACTS)
    assert any("Contradiction on price" in error for error in errors)


def test_french_superlatives_are_checked() -> None:
    assert verify_report("Les Electronics ont le prix le plus élevé (94.00).", FACTS) == []
    errors = verify_report("Le price le plus bas est celui de Home.", FACTS)
    assert "'Home' is not the lowest for price: the lowest is Sports." in errors


def test_quantifier_most_without_a_category_is_ignored() -> None:
    assert verify_report("Most items keep a healthy price level.", FACTS) == []


def test_no_facts_means_nothing_to_check() -> None:
    assert verify_report("Revenue was 123 456.", {"indicators": {}, "numbers": []}) == []


def test_grouping_words_in_variable_names_do_not_hide_claims() -> None:
    facts = build_facts({"stock_by_cat": {"Electronics": 187.0, "Home": 413.0, "Sports": 432.0}})
    assert verify_report("Highest total stock: Sports (432.0).", facts) == []
    errors = verify_report("Highest total stock: Home (413.0).", facts)
    assert "'Home' is not the highest for stock_by_cat: the highest is Sports." in errors


# --- Several breakdowns of the same measure (Monthly sales example) -----------

SALES_FACTS = build_facts(
    {
        "revenue_by_region": {"North": 157250.0, "South": 81319.0},
        "revenue_by_category": {"Electronics": 161583.0, "Home": 76986.0},
        "revenue_by_month": {"2026-01": 87295.0, "2026-02": 93444.0, "2026-06": 119499.0},
    }
)


def test_superlatives_are_checked_against_the_breakdown_of_their_categories() -> None:
    report = (
        "North has the highest revenue (157,250) and South the lowest (81,319).\n"
        "Electronics generates the highest revenue (161,583).\n"
        "2026-06 had the highest revenue (119,499), while 2026-01 had the lowest.\n"
    )
    assert verify_report(report, SALES_FACTS) == []


def test_a_wrong_claim_is_still_caught_within_its_breakdown() -> None:
    errors = verify_report("South has the highest revenue.", SALES_FACTS)
    assert errors == ["'South' is not the highest for revenue_by_region: the highest is North."]


# The exact Monthly sales report that produced a false warning in production.
SALES_RUN = build_facts(
    {
        "revenue_by_region": {"North": 341102.0, "South": 277092.0},
        "revenue_by_category": {"Electronics": 458068.0, "Home": 160126.0},
        "revenue_by_month": {
            "2026-01": 87295.0, "2026-02": 93444.0, "2026-03": 98302.0,
            "2026-04": 104105.0, "2026-05": 115549.0, "2026-06": 119499.0,
        },
    },
    "",
    {"row_count": 24, "columns": ["month", "region", "category", "units", "revenue"]},
)
SALES_REPORT = """Summary
The dataset contains monthly sales for two regions (North, South) and two product categories (Electronics, Home) from January to June 2026. Total revenue is highest in the North region and for Electronics, while the South region and Home category generate the lowest revenue. Monthly revenue has increased steadily, reaching its peak in June.
Data Analysis
* Revenue per region
   * North: 341102
   * South: 277092
* Month‑over‑month revenue
   * 2026‑01: 87295
   * 2026‑06: 119499
Key Findings
* The North region leads in total revenue with 341102, while the South region trails with 277092.
* Electronics dominates sales, generating 458068, compared to 160126 from Home.
* Revenue grew each month, peaking at 119499 in 2026‑06 and starting at 87295 in 2026‑01.
"""


def test_monthly_sales_report_from_production_passes() -> None:
    assert verify_report(SALES_REPORT, SALES_RUN) == []


def test_non_breaking_hyphens_in_dates_are_understood() -> None:
    errors = verify_report("2026\u201101 had the highest revenue.", SALES_RUN)
    assert errors == ["'2026-01' is not the highest for revenue_by_month: the highest is 2026-06."]
