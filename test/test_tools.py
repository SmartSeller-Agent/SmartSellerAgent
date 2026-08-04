import requests

from src.tools import pricing, vision


def test_calculate_margin_matches_margin_check_task():
    """Tests the normal case (happy path): a standard sale with a positive profit."""
    """Mirrors the numbers from the 'margin_check' prompt task: bought for 20€, sold for 45€."""
    result = pricing.calculate_margin(purchase_price=20, selling_price=45)

    assert "Profit: 25.00 €" in result
    assert "Margin: 125.0%" in result


def test_calculate_margin_rejects_non_positive_purchase_price():
    """Checks error handling for invalid inputs (purchase price of 0)."""
    result = pricing.calculate_margin(purchase_price=0, selling_price=45)

    assert result == "Error: purchase_price must be greater than 0."


def test_calculate_margin_reports_break_even_sale():
    """Tests the business edge case: break-even (neither profit nor loss)."""
    result = pricing.calculate_margin(purchase_price=100, selling_price=100)

    assert "Profit: 0.00 €" in result
    assert "Margin: 0.0%" in result


def test_calculate_margin_reports_loss_sale():
    """Checks if negative margins (sales at a loss) are mathematically calculated correctly."""
    result = pricing.calculate_margin(purchase_price=80, selling_price=60)

    assert "Profit: -20.00 €" in result
    assert "Margin: -25.0%" in result


def test_analyze_product_image_returns_api_response_content(monkeypatch, tmp_path):
    """
    Simulates a successful API request (mocking). 
    Prevents the test from costing real money or failing without an internet connection.
    """
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "IKEA Kallax"}}]}

    def fake_post(url, json, headers, timeout):
        assert url.endswith("/chat/completions")
        assert headers["Authorization"] == "Bearer test-key"
        assert json["model"] == "test-model"
        assert json["messages"][0]["content"][1]["text"].startswith("Du bist")
        # The call must never be able to hang forever — relevant since the
        # provider can be a remote API, not just a local Ollama.
        assert timeout is not None
        return FakeResponse()

    # Replaces the real configurations with our fake data for this test
    monkeypatch.setattr(vision.requests, "post", fake_post)
    monkeypatch.setattr(vision, "VISION_MODEL_ID", "test-model")
    monkeypatch.setattr(vision, "VISION_API_BASE", "http://example.test")
    monkeypatch.setattr(vision, "VISION_API_KEY", "test-key")

    # Creates a temporary fake image file for the test
    image_path = tmp_path / "product.png"
    image_path.write_bytes(b"fake-image")

    result = vision.analyze_product_image(str(image_path))

    assert result == "IKEA Kallax"


def test_analyze_product_image_returns_error_on_http_failure(monkeypatch, tmp_path):
    """Checks if the system gracefully handles the error instead of crashing completely during API failures."""
    class FakeResponse:
        def raise_for_status(self):
            raise requests.HTTPError("boom")

    def fake_post(url, json, headers, timeout):
        return FakeResponse()

    monkeypatch.setattr(vision.requests, "post", fake_post)

    image_path = tmp_path / "product.png"
    image_path.write_bytes(b"fake-image")

    result = vision.analyze_product_image(str(image_path))

    assert "Fehler bei der Bildanalyse" in result
    assert "boom" in result


def test_analyze_product_image_handles_missing_file(monkeypatch, tmp_path):
    """Checks if missing files on the hard drive are correctly detected and reported."""
    missing_image = tmp_path / "missing.png"

    result = vision.analyze_product_image(str(missing_image))

    assert "Fehler bei der Bildanalyse" in result
    assert "No such file" in result
