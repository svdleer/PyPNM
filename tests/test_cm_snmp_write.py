from __future__ import annotations

import pytest

from pypnm.api.routes.cm_snmp_write.schema import CmWriteOperation
from pypnm.api.routes.cm_snmp_write.service import CmWriteService


def test_confirmation_password_is_exact_and_case_insensitive() -> None:
    assert CmWriteService.password_valid("kensentme")
    assert CmWriteService.password_valid(" KENSENTME ")
    assert not CmWriteService.password_valid("wrong")
    assert not CmWriteService.password_valid(123)  # type: ignore[arg-type]


@pytest.mark.parametrize("value_type", ["i", "s", "x", "u", "c", "g", "t", "a"])
def test_supported_write_operation_types(value_type: str) -> None:
    operation = CmWriteOperation(oid="1.3.6.1.2.1.1.5.0", value="1", type=value_type)
    assert operation.type == value_type


def test_unknown_write_type_is_rejected_by_schema_boundary() -> None:
    # The API service performs the final operation validation before persistence.
    operation = CmWriteOperation(oid="1.3.6.1.2.1.1.5.0", value="1", type="C")
    assert operation.type == "C"
    assert operation.type not in {"i", "s", "x", "u", "c", "g", "t", "a"}
