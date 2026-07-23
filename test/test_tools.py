from src.tools.pricing import calculate_margin


def test_calculate_margin_matches_margin_check_task():
    """Mirrors the numbers from the 'margin_check' prompt task: bought for 20€, sold for 45€."""
    result = calculate_margin(purchase_price=20, selling_price=45)

    assert "Profit: 25.00 €" in result
    assert "Margin: 125.0%" in result


def test_calculate_margin_rejects_non_positive_purchase_price():
    result = calculate_margin(purchase_price=0, selling_price=45)

    assert result == "Error: purchase_price must be greater than 0."
