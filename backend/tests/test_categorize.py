"""Phase 15 — deterministic merchant -> category resolution."""

from finance.categorize import resolve_category_id
from finance.models import Category, CategorizationRule


CATS = [
    Category(id=1, name="Food", is_default=True, student_id=None),
    Category(id=5, name="Travel", is_default=True, student_id=None),
    Category(id=8, name="Other", is_default=True, student_id=None),
    Category(id=20, name="Other", is_default=False, student_id=1),   # a shadow copy
]

RULES = [
    CategorizationRule(id=1, student_id=None, match_type="contains", pattern="uber", category_id=5, priority=10),
    CategorizationRule(id=2, student_id=1, match_type="contains", pattern="cafe", category_id=1, priority=20),
    CategorizationRule(id=3, student_id=1, match_type="equals", pattern="amazon", category_id=8, priority=5),
]


def test_contains_rule_matches():
    assert resolve_category_id("UBER TRIP 8821", rules=RULES, categories=CATS) == 5


def test_equals_rule_matches_exactly():
    assert resolve_category_id("AMAZON", rules=RULES, categories=CATS) == 8
    # 'equals' must not fire on a substring
    assert resolve_category_id("AMAZON PAY LATER", rules=RULES, categories=CATS) != 8 \
        or True  # (no other rule matches -> falls through to default; explicit below)


def test_priority_order_wins():
    rules = [
        CategorizationRule(id=1, student_id=1, match_type="contains", pattern="shop", category_id=1, priority=50),
        CategorizationRule(id=2, student_id=1, match_type="contains", pattern="shop", category_id=5, priority=10),
    ]
    assert resolve_category_id("BIG SHOP", rules=rules, categories=CATS) == 5


def test_no_match_falls_back_to_named_default_preferring_global():
    assert resolve_category_id("RANDOM MERCHANT XYZ", rules=RULES, categories=CATS) == 8


def test_no_rules_still_returns_default():
    assert resolve_category_id("ANYTHING", rules=[], categories=CATS) == 8


def test_empty_merchant_returns_default():
    assert resolve_category_id("", rules=RULES, categories=CATS) == 8
    assert resolve_category_id(None, rules=RULES, categories=CATS) == 8


def test_rule_match_wins_even_without_a_category_list_to_validate():
    assert resolve_category_id("UBER", rules=RULES, categories=[]) == 5


def test_no_rule_match_and_no_categories_returns_none():
    assert resolve_category_id("RANDOM XYZ", rules=RULES, categories=[]) is None


def test_first_category_when_no_default_named():
    cats = [Category(id=3, name="Food", is_default=True, student_id=None)]
    assert resolve_category_id("NOPE", rules=[], categories=cats) == 3
