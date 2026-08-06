"""
Tests der Agenten-Verdrahtung.

Kein Modell wird befragt — geprüft wird nur, dass die Teile richtig
zusammengesteckt sind. Das sind die Fehler, die sonst erst nach Minuten
Laufzeit und echten Modellkosten auffallen.
"""
import pytest

from src import app as app_module


def test_the_orchestrator_manages_both_subagents():
    assert set(app_module.orchestrator.managed_agents) == {
        "vision_agent",
        "publisher_agent",
    }


def test_the_publisher_can_check_the_login_before_it_publishes():
    """Ohne das Prüf-Tool bliebe ihm nur, ins Leere zu laufen."""
    assert "check_marketplace_session" in app_module.publisher_agent.tools
    assert "publish_listing" in app_module.publisher_agent.tools


def test_only_the_publisher_can_create_an_ad():
    """Der Orchestrator soll nicht am Subagenten vorbei veröffentlichen."""
    assert "publish_listing" not in app_module.orchestrator.tools
    assert "publish_listing" not in app_module.vision_agent.tools


def test_the_model_is_never_offered_the_publish_switch():
    """dry_run gehört der Anwendung, nicht dem Sprachmodell."""
    inputs = app_module.publisher_agent.tools["publish_listing"].inputs

    assert "dry_run" not in inputs
    assert "allow_publish" not in inputs
    # Den Standort liefert das Profil des Anwenders.
    assert "zip_code" not in inputs


@pytest.mark.parametrize(
    "task_name", ["create_and_publish_listing", "create_listing", "margin_check"]
)
def test_the_known_tasks_are_still_there(task_name):
    """create_listing bleibt erhalten: nur Text, ohne den Marktplatz anzufassen."""
    assert task_name in app_module._prompts["orchestrator"]["tasks"]


def test_the_publishing_task_passes_the_image_path_through():
    template = app_module._prompts["orchestrator"]["tasks"]["create_and_publish_listing"]

    filled = template.format(image_path="/app/test/images/uploads/regal.jpg", purchase_price=0)

    assert filled.count("/app/test/images/uploads/regal.jpg") == 2
    assert "publisher_agent" in filled


def test_the_publisher_is_told_not_to_publish_twice():
    """Ein zweiter Aufruf erzeugte eine zweite Anzeige."""
    instructions = app_module._prompts["publisher_agent"]["instructions"]

    assert "Never call publish_listing a second time" in instructions
    assert "check_marketplace_session first" in instructions
