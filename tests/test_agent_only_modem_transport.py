# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pypnm.api.agent import manager as agent_manager_module
from pypnm.docsis.cm_snmp_operation import CmSnmpOperation
from pypnm.lib.inet import Inet
from pypnm.snmp import agent_transport as agent_transport_module
from pypnm.snmp.agent_transport import AgentSnmpTransport


def _agent(
    *,
    agent_id: str = "cm-agent-test",
    authenticated: bool = True,
    alive: bool = True,
    capabilities: set[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        agent_id=agent_id,
        authenticated=authenticated,
        capabilities=capabilities or {"cm_reachable"},
        is_alive=lambda: alive,
    )


def test_cm_snmp_operation_fails_when_manager_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_manager_module, "get_agent_manager", lambda: None)

    with pytest.raises(RuntimeError, match="AgentManager is unavailable"):
        CmSnmpOperation(Inet("192.0.2.10"), "private")


def test_cm_snmp_operation_fails_without_cm_capable_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SimpleNamespace(get_agent_for_capability=lambda capability: None)
    monkeypatch.setattr(agent_manager_module, "get_agent_manager", lambda: manager)

    with pytest.raises(RuntimeError, match="connected cm_reachable agent"):
        CmSnmpOperation(Inet("192.0.2.10"), "private")


def test_cm_snmp_operation_pins_selected_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = _agent()
    manager = SimpleNamespace(get_agent_for_capability=lambda capability: selected)
    captured: dict[str, object] = {}

    class FakeAgentSnmpTransport:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(agent_manager_module, "get_agent_manager", lambda: manager)
    monkeypatch.setattr(
        agent_transport_module,
        "AgentSnmpTransport",
        FakeAgentSnmpTransport,
    )

    operation = CmSnmpOperation(Inet("192.0.2.10"), "private", priority="bulk")

    assert isinstance(operation._snmp, FakeAgentSnmpTransport)
    assert captured["agent_id"] == selected.agent_id
    assert captured["target_role"] == "cm"
    assert captured["priority"] == "bulk"


@pytest.mark.parametrize(
    ("agent", "message"),
    [
        (None, "not connected"),
        (_agent(authenticated=False), "not authenticated and alive"),
        (_agent(alive=False), "not authenticated and alive"),
        (_agent(capabilities={"cmts_reachable"}), "lacks 'cm_reachable'"),
    ],
)
def test_pinned_cm_agent_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    agent: SimpleNamespace | None,
    message: str,
) -> None:
    manager = SimpleNamespace(get_agent=lambda agent_id: agent)
    monkeypatch.setattr(agent_manager_module, "get_agent_manager", lambda: manager)
    transport = AgentSnmpTransport(
        Inet("192.0.2.10"),
        write_community="private",
        agent_id="cm-agent-test",
        target_role="cm",
    )

    with pytest.raises(RuntimeError, match=message):
        transport._get_manager_and_agent("cm", "cm-agent-test")
