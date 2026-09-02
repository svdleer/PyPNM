
from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia
import logging
from pypnm.docsis.cm_snmp_operation import CmSnmpOperation
from pypnm.lib.inet import Inet, InetAddressStr
from pypnm.lib.mac_address import MacAddress


class CableModem(CmSnmpOperation):
    """
    Represents a Cable Modem device that extends SNMP operations.

    Provides access to the modem's MAC and IP addresses plus agent-backed
    SNMP responsiveness checks.
    """

    inet: Inet

    def __init__(self, mac_address: MacAddress,
                 inet: Inet,
                 write_community: str | None = None,
                 priority: str = 'interactive') -> None:
        """
        Initialize the CableModem instance.

        Args:
            mac_address (MacAddress): The MAC address of the cable modem.
            inet (Inet): The IP address of the cable modem.
            write_community (str, optional): SNMP write community passed to the agent.
            priority (str, optional): Agent task priority ('interactive' for GUI, 'bulk' for background jobs).
        """
        super().__init__(inet=inet, write_community=write_community, priority=priority)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._mac_address: MacAddress = mac_address

    @property
    def get_mac_address(self) -> MacAddress:
        """
        Returns the MAC address of the cable modem.

        Returns:
            MacAddress: The cable modem's MAC address.
        """
        return self._mac_address

    @property
    def get_inet_address(self) -> InetAddressStr:
        """
        Returns the IP address of the cable modem as a string.

        Returns:
            str: The cable modem's IP address.
        """
        return InetAddressStr(self._inet.__str__())

    async def is_snmp_reachable(self) -> bool:
        """
        Checks whether the cable modem is reachable via SNMP by requesting sysDescr.

        Returns:
            bool: True if SNMP communication is successful, False otherwise.
        """
        system_description = await self.getSysDescr(timeout=10, retries=2)

        self.logger.debug(f"SNMP.is_snmp_reachable: System Description for {system_description}, is_empty: {system_description.is_empty()}")

        if system_description.is_empty():
            self.logger.debug(f"{self.__repr__()}- SNMP access failed")
            return False

        return True

    async def isCableModemMacCorrect(self) -> bool:
        "Checks to see if mac address is cable modem mac-address (docsCableMaclayer)"
        try:
            mac = await self.getIfPhysAddress()
            self.logger.debug(f"CableModem MAC Address: {self.get_mac_address}, SNMP Retrieved MAC Address: {mac}, types: {type(self.get_mac_address)}, {type(mac)}")
            result = self.get_mac_address.is_equal(mac)
            self.logger.debug(f"MAC comparison result: {result}")
            return result
        except Exception as e:
            self.logger.error(f"Error in isCableModemMacCorrect: {e}", exc_info=True)
            raise

    def same_inet_version(self, other: Inet) -> bool:
        """
        Determines whether this modem's IP address and another Inet address are the same IP version.

        Args:
            other (Inet): Another Inet instance to compare.

        Returns:
            bool: True if both are either IPv4 or IPv6, False otherwise.

        Raises:
            TypeError: If 'other' is not an instance of Inet.
        """
        if not isinstance(other, Inet):
            raise TypeError(f"Expected 'Inet' instance, got {type(other).__name__}")
        return self._inet.same_inet_version(other)

    def __str__(self) -> str:
        """
        String representation of the cable modem.

        Returns:
            str: MAC and IP address representation.
        """
        return f"{self.get_mac_address}"

    def __repr__(self) -> str:
        """
        String representation of the cable modem.

        Returns:
            str: MAC and IP address representation.
        """
        return f"Mac: {self.__str__()} - Inet: {self.get_inet_address}"

    def __hash__(self) -> int:
        """
        Hash based on the normalized raw MAC address string (12 lowercase hex chars).

        This ensures that any MacAddress instance with the same underlying
        normalized MAC value will be treated as equal in sets and dicts.
        """
        return hash(self._mac_address.mac_address)

    def __eq__(self, other: object) -> bool:
        """
        Equality check based on normalized MAC string.
        """
        return isinstance(other, MacAddress) and self._mac_address == other._mac
