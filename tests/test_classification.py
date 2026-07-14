from classification import canonical_category_id, category_matches, classify_market
from position_tracker import american_odds_from_probability, probability_from_american_odds


def test_sports_classification_uses_multiple_fields():
    position = {"title": "Spread: France (-1.5)", "eventSlug": "fifwc-fra-esp-2026-07-14"}
    event = {"tags": [{"label": "Sports"}, {"label": "Soccer"}], "sport": {"sport": "fifwc"}, "title": "France vs. Spain"}
    result = classify_market(position, event)
    assert result.category == "Soccer"
    assert result.is_sports is True


def test_non_sports_classification():
    position = {"title": "Will BTC close above $150k?", "eventSlug": "bitcoin-price"}
    event = {"tags": [{"label": "Crypto"}], "title": "Bitcoin"}
    result = classify_market(position, event)
    assert result.category == "Crypto"
    assert result.is_sports is False


def test_american_odds_conversion():
    assert american_odds_from_probability(0.6) == "-150"
    assert american_odds_from_probability(0.4) == "+150"
    assert round(probability_from_american_odds(-150), 2) == 0.6


def test_canonical_category_taxonomy_normalizes_required_sports_hierarchies():
    assert canonical_category_id("baseball") == "mlb"
    assert canonical_category_id("MLB") == "mlb"
    assert canonical_category_id("ATP Challenger") == "tennis"
    assert canonical_category_id("WTA") == "tennis"
    assert canonical_category_id("FIFA World Cup") == "soccer"
    assert canonical_category_id("Hockey") == "nhl"
    assert category_matches("NBA", ["Basketball"]) is True
    assert category_matches("MLB", ["Sports"]) is False
    assert category_matches("Tennis", ["Games"]) is False
    assert canonical_category_id("Football") is None
