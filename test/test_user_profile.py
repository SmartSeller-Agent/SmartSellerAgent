"""
Tests für die dauerhaften Einstellungen des Anwenders.

Der Zweck des Profils: Angaben festhalten, die ein Sprachmodell nicht wissen
kann und nicht raten soll. Entsprechend streng beim Speichern und entsprechend
nachsichtig beim Lesen — eine kaputte Datei darf die Anwendung nicht aufhalten.
"""
import json

import pytest

from src import user_profile
from src.user_profile import Profile


@pytest.fixture(autouse=True)
def profile_file(monkeypatch, tmp_path):
    path = tmp_path / "profile.json"
    monkeypatch.setattr(user_profile, "PROFILE_FILE", path)
    return path


def test_a_fresh_installation_has_an_empty_profile(profile_file):
    profile = user_profile.load_profile()

    assert profile.zip_code == ""
    assert profile.complete is False


def test_saving_and_reading_back(profile_file):
    user_profile.save_profile(Profile(zip_code="78462"))

    assert user_profile.load_profile().zip_code == "78462"
    assert user_profile.load_profile().complete is True


def test_the_directory_is_created_if_it_is_missing(monkeypatch, tmp_path):
    """Beim ersten Start gibt es den Zustandsordner noch nicht."""
    monkeypatch.setattr(
        user_profile, "PROFILE_FILE", tmp_path / "gibt-es-noch-nicht" / "profile.json"
    )

    user_profile.save_profile(Profile(zip_code="10115"))

    assert user_profile.load_profile().zip_code == "10115"


@pytest.mark.parametrize("bad", ["", "784", "784629", "ABCDE", "78 46"])
def test_an_invalid_zip_code_is_refused(profile_file, bad):
    with pytest.raises(ValueError):
        user_profile.save_profile(Profile(zip_code=bad))

    assert not profile_file.exists()


def test_a_damaged_file_reads_as_empty_instead_of_raising(profile_file):
    """Sonst käme die Oberfläche wegen einer Nebensache gar nicht erst hoch."""
    profile_file.write_text("{kein json", encoding="utf-8")

    assert user_profile.load_profile().zip_code == ""


def test_unknown_fields_are_ignored(profile_file):
    """Eine Datei aus einer anderen Version darf nichts durcheinanderbringen."""
    profile_file.write_text(
        json.dumps({"zip_code": "78462", "lieblingsfarbe": "grün"}), encoding="utf-8"
    )

    assert user_profile.load_profile() == Profile(zip_code="78462")


def test_a_file_that_is_not_an_object_reads_as_empty(profile_file):
    profile_file.write_text(json.dumps(["78462"]), encoding="utf-8")

    assert user_profile.load_profile().zip_code == ""
