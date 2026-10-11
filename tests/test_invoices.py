import logging
from datetime import date, timedelta

import pytest

import config
from qbo_client import invoices
from qbo_client.client import QBOAPIError


def custom_field(name, value=None, type_="StringType", definition_id="1"):
    field = {"DefinitionId": definition_id, "Name": name, "Type": type_}
    if value is not None:
        field[invoices.CUSTOM_FIELD_VALUE_KEYS.get(type_, "StringValue")] = value
    return field


def raw_invoice(**overrides):
    invoice = {
        "Id": "101",
        "DocNumber": "1001",
        "TxnDate": "2026-07-15",
        "DueDate": "2026-08-14",
        "TotalAmt": 250.0,
        "Balance": 100.0,
        "CustomerRef": {"value": "5", "name": "Acme Co"},
        "MetaData": {"CreateTime": "2026-07-15T09:00:00-07:00", "LastUpdatedTime": "2026-07-16T10:00:00-07:00"},
        "CustomField": [custom_field("Customer PO", "00451"), custom_field("Payment Type", "1", definition_id="2")],
    }
    invoice.update(overrides)
    return invoice


@pytest.fixture
def payment_type_on(monkeypatch):
    monkeypatch.setattr(config, "INCLUDE_PAYMENT_TYPE_COLUMN", True)


@pytest.fixture
def payment_type_off(monkeypatch):
    monkeypatch.setattr(config, "INCLUDE_PAYMENT_TYPE_COLUMN", False)


# --- _clean_invoices

def test_clean_invoice_fields(payment_type_on):
    [clean] = invoices._clean_invoices([raw_invoice()])

    assert clean["Id"] == "101"
    assert clean["DocNumber"] == "1001"
    assert clean["TxnDate"] == "2026-07-15"
    assert clean["DueDate"] == "2026-08-14"
    assert clean["TotalAmt"] == 250.0
    assert clean["Balance"] == 100.0
    assert clean["CustomerName"] == "Acme Co"
    assert clean["LastUpdatedTime"] == "2026-07-16T10:00:00-07:00"
    assert clean["CustomerPO"] == "00451"
    assert clean["PaymentType"] == "Check"


def test_clean_invoice_column_order(payment_type_on):
    # the sheet's column order comes from this key order, so new fields must go at the end
    [clean] = invoices._clean_invoices([raw_invoice()])

    assert list(clean) == [
        "Id", "DocNumber", "TxnDate", "DueDate", "TotalAmt", "Balance",
        "CustomerName", "LastUpdatedTime", "DaysUntilDue", "CustomerPO", "PaymentType",
    ]


def test_payment_type_column_left_out_when_disabled(payment_type_off):
    [clean] = invoices._clean_invoices([raw_invoice()])

    assert "PaymentType" not in clean
    assert list(clean)[-1] == "CustomerPO"


def test_days_until_due_counts_from_today(payment_type_off):
    due = date.today() + timedelta(days=10)
    overdue = date.today() - timedelta(days=3)

    cleaned = invoices._clean_invoices([
        raw_invoice(DueDate=due.isoformat()),
        raw_invoice(DueDate=overdue.isoformat()),
    ])

    assert [c["DaysUntilDue"] for c in cleaned] == [10, -3]


def test_missing_optional_fields_become_none(payment_type_on):
    bare = {"Id": "7"}

    [clean] = invoices._clean_invoices([bare])

    assert clean["Id"] == "7"
    assert clean["DueDate"] is None
    assert clean["DaysUntilDue"] is None
    assert clean["CustomerName"] is None
    assert clean["LastUpdatedTime"] is None
    assert clean["CustomerPO"] is None
    assert clean["PaymentType"] is None


def test_clean_empty_list():
    assert invoices._clean_invoices([]) == []


# --- _get_custom_field

@pytest.mark.parametrize("type_, value", [
    ("StringType", "PO-1"),
    ("NumberType", 42.0),
    ("DateType", "2026-09-01"),
])
def test_custom_field_value_read_by_type(type_, value):
    invoice = {"CustomField": [custom_field("Customer PO", value, type_=type_)]}

    assert invoices._get_custom_field(invoice, "Customer PO") == value


def test_custom_field_falsy_values_are_kept():
    invoice = {"CustomField": [
        custom_field("Count", 0, type_="NumberType"),
        custom_field("Note", "", definition_id="2"),
    ]}

    assert invoices._get_custom_field(invoice, "Count") == 0
    assert invoices._get_custom_field(invoice, "Note") == ""


def test_custom_field_picks_the_named_field():
    invoice = {"CustomField": [custom_field("Customer PO", "PO-1"), custom_field("Payment Type", "2", definition_id="2")]}

    assert invoices._get_custom_field(invoice, "Payment Type") == "2"


def test_custom_field_blank_on_invoice():
    invoice = {"CustomField": [custom_field("Customer PO")]}

    assert invoices._get_custom_field(invoice, "Customer PO") is None


def test_custom_field_not_on_invoice():
    assert invoices._get_custom_field({"CustomField": []}, "Customer PO") is None
    assert invoices._get_custom_field({}, "Customer PO") is None


def test_custom_field_unsupported_type_warns(caplog):
    invoice = {"DocNumber": "1001", "CustomField": [custom_field("Payment Type", type_="DropDownType")]}

    with caplog.at_level(logging.WARNING):
        assert invoices._get_custom_field(invoice, "Payment Type") is None

    assert "Unsupported type 'DropDownType'" in caplog.text
    assert "1001" in caplog.text


# --- _payment_type_label

@pytest.mark.parametrize("value, label", [("1", "Check"), ("2", "CC")])
def test_payment_type_label(value, label):
    assert invoices._payment_type_label(value, "1001") == label


@pytest.mark.parametrize("value", [None, ""])
def test_payment_type_blank(value):
    assert invoices._payment_type_label(value, "1001") is None


def test_payment_type_unknown_kept_and_warned(caplog):
    with caplog.at_level(logging.WARNING):
        assert invoices._payment_type_label("9", "1001") == "9"

    assert "Unknown Payment Type '9' on invoice 1001" in caplog.text


# --- get_all_invoices_since

@pytest.fixture
def fake_query(monkeypatch):
    """
    Replaces QBO with scripted responses: a COUNT response, then one response per page.
    Returns the list of (query_string, extra_params) calls made.
    """
    calls = []

    def setup(total_count, pages):
        responses = iter(
            [{"QueryResponse": {"totalCount": total_count}}]
            + [{"QueryResponse": {"Invoice": page} if page else {}} for page in pages]
        )

        def query(realm_id, access_token, query_string, extra_params=None):
            calls.append((query_string, extra_params))
            return next(responses)

        monkeypatch.setattr(invoices, "query", query)
        monkeypatch.setattr(invoices, "get_access_token", lambda: "token")
        return calls

    return setup


def test_fetch_pages_until_empty(fake_query, payment_type_off):
    page_1 = [raw_invoice(Id=str(i)) for i in range(1000)]
    page_2 = [raw_invoice(Id=str(i)) for i in range(1000, 1005)]
    calls = fake_query(1005, [page_1, page_2, []])

    result = invoices.get_all_invoices_since("2026-07-01")

    assert len(result) == 1005
    assert [c["Id"] for c in result[:2]] == ["0", "1"]
    page_queries = [q for q, _ in calls[1:]]
    assert "STARTPOSITION 1 " in page_queries[0]
    assert "STARTPOSITION 1001 " in page_queries[1]
    assert "STARTPOSITION 1006 " in page_queries[2]


def test_fetch_filters_by_date_and_requests_custom_fields(fake_query, payment_type_off):
    calls = fake_query(1, [[raw_invoice()], []])

    invoices.get_all_invoices_since("2026-07-01")

    count_query, _ = calls[0]
    page_query, page_params = calls[1]
    assert "SELECT COUNT(*) FROM Invoice WHERE TxnDate >= '2026-07-01'" in count_query
    assert "WHERE TxnDate >= '2026-07-01'" in page_query
    assert page_params == {"include": "enhancedAllCustomFields"}


def test_fetch_with_no_invoices(fake_query):
    fake_query(0, [[]])

    assert invoices.get_all_invoices_since("2026-07-01") == []


def test_fetch_fewer_than_counted_raises(fake_query):
    fake_query(3, [[raw_invoice(Id="1"), raw_invoice(Id="2")], []])

    with pytest.raises(QBOAPIError, match="QBO counted 3 invoices but only 2 were returned"):
        invoices.get_all_invoices_since("2026-07-01")


def test_fetch_more_than_counted_warns(fake_query, payment_type_off, caplog):
    fake_query(1, [[raw_invoice(Id="1"), raw_invoice(Id="2")], []])

    with caplog.at_level(logging.WARNING):
        result = invoices.get_all_invoices_since("2026-07-01")

    assert len(result) == 2
    assert "QBO counted 1" in caplog.text
