"""The batch builder decides who gets which copy, so the language has to travel
with the address and never be invented."""

import csv

import pytest

from scripts.build_campaign_batches import (
    Contact,
    read_contacts,
    split_batches,
    write_batches,
)


def test_plain_list_takes_the_language_from_the_caller(tmp_path) -> None:
    source = tmp_path / "emails.txt"
    source.write_text("a@gmail.com\nb@gmail.com\n")

    contacts = read_contacts(source, "en")

    assert contacts == [Contact("a@gmail.com", "en"), Contact("b@gmail.com", "en")]


def test_plain_list_without_a_language_refuses_to_run(tmp_path) -> None:
    source = tmp_path / "emails.txt"
    source.write_text("a@gmail.com\n")

    with pytest.raises(SystemExit):
        read_contacts(source, None)


def test_csv_language_column_wins_per_row(tmp_path) -> None:
    source = tmp_path / "leads.csv"
    source.write_text("email,language\na@gmail.com,en\nb@gmail.com,pt\n")

    assert read_contacts(source, None) == [
        Contact("a@gmail.com", "en"),
        Contact("b@gmail.com", "pt"),
    ]


def test_language_with_no_copy_written_is_refused(tmp_path) -> None:
    source = tmp_path / "leads.csv"
    source.write_text("email,language\na@gmail.com,es\n")

    with pytest.raises(SystemExit):
        read_contacts(source, None)


def test_batches_carry_the_language_to_the_sender(tmp_path) -> None:
    contacts = [Contact("a@gmail.com", "en"), Contact("b@hotmail.com", "pt")]

    paths = write_batches(split_batches(contacts), tmp_path)

    rows = [row for path in paths for row in csv.DictReader(path.open())]
    assert {(row["email"], row["language"]) for row in rows} == set(contacts)
    # Microsoft still lands in its own (last) batch: language does not reorder.
    assert list(csv.DictReader(paths[-1].open()))[0]["email"] == "b@hotmail.com"
