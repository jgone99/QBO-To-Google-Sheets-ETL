import logging

import pytest

import invoice_sheet


@pytest.fixture(autouse=True)
def text_columns(monkeypatch):
    # fixed text columns so these tests don't depend on what's configured in invoice_sheet.py
    monkeypatch.setattr(invoice_sheet, "TEXT_COLUMNS", {"DocNumber", "CustomerPO"})


def test_header_comes_from_invoice_fields():
    rows = invoice_sheet.to_rows([{"Id": "1", "DocNumber": "1001", "TotalAmt": 5.0}])

    assert rows[0] == ["Id", "DocNumber", "TotalAmt"]


def test_rows_follow_header_order():
    invoices = [
        {"Id": "1", "TotalAmt": 5.0, "CustomerPO": None},
        {"Id": "2", "TotalAmt": 7.5, "CustomerPO": None},
    ]

    rows = invoice_sheet.to_rows(invoices)

    assert rows[1:] == [["1", 5.0, None], ["2", 7.5, None]]


def test_text_columns_are_marked_as_text():
    rows = invoice_sheet.to_rows([{"Id": "1", "DocNumber": "00123", "CustomerPO": "00451", "TotalAmt": 5.0}])

    assert rows[1] == ["1", "'00123", "'00451", 5.0]


def test_blank_text_values_stay_blank():
    rows = invoice_sheet.to_rows([{"DocNumber": None, "CustomerPO": ""}])

    assert rows[1] == [None, ""]


def test_header_is_not_marked_as_text():
    rows = invoice_sheet.to_rows([{"DocNumber": "1001"}])

    assert rows[0] == ["DocNumber"]


def test_missing_text_column_warns(caplog):
    with caplog.at_level(logging.WARNING):
        invoice_sheet.to_rows([{"Id": "1", "DocNumber": "1001"}])

    assert "CustomerPO" in caplog.text


def test_no_invoices():
    assert invoice_sheet.to_rows([]) == []
