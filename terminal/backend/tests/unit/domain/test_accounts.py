from decimal import Decimal

import pytest
from pydantic import ValidationError

from kterminal.domain.accounts import AccountSettings


def test_equal_settings_give_equal_documents_however_they_are_written() -> None:
    a = AccountSettings(starting_balance=Decimal(50000), risk_per_trade_pct=Decimal("0.5"))
    b = AccountSettings.model_validate({"starting_balance": "50000.00", "risk_per_trade_pct": 0.50})
    assert a == b
    assert a.document_json() == b.document_json()
    assert a.document()["starting_balance"] == "50000"


def test_a_starting_balance_must_fit_the_ledgers_four_decimals() -> None:
    AccountSettings(starting_balance=Decimal("50000.1234"))
    with pytest.raises(ValidationError, match="at most 4 decimal places"):
        AccountSettings(starting_balance=Decimal("50000.12345"))
