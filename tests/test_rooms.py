"""Résolution des noms de pièces (pure, sans Home Assistant)."""
import pytest
from custom_components.neatsvor_s600.map_decoder import resolve_rooms

ROOMS = {1: "Séjour", 2: "Cuisine", 5: "Chambre Garçons", 6: "Salon", 9: "SDB"}


def test_names_ids_and_digit_strings():
    assert resolve_rooms(ROOMS, ["Cuisine", 6, "9"]) == [2, 6, 9]


def test_case_and_accents_are_ignored():
    assert resolve_rooms(ROOMS, ["sejour", "SALON"]) == [1, 6]


def test_unique_partial_name():
    assert resolve_rooms(ROOMS, ["garcons"]) == [5]


def test_duplicates_removed_keeping_order():
    assert resolve_rooms(ROOMS, ["Cuisine", 2, "cuisine", 1]) == [2, 1]


def test_unknown_name_lists_available_rooms():
    with pytest.raises(ValueError, match="unknown.*Cuisine"):
        resolve_rooms(ROOMS, ["garage"])


def test_ambiguous_partial_name():
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_rooms({1: "Salle de bain", 2: "Salle à manger"}, ["salle"])


def test_name_before_map_received():
    with pytest.raises(ValueError, match="not been received"):
        resolve_rooms({}, ["Cuisine"])


def test_ids_accepted_without_map():
    assert resolve_rooms({}, [3, "4"]) == [3, 4]
