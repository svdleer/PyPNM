# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from pydantic import BaseModel, Field

from pypnm.lib.types import ChannelId, PowerdB, PowerdBmV


class DwrChannelPowerModel(BaseModel):
    channel_id: ChannelId = Field(..., description="DOCSIS upstream channel ID.")
    tx_power_dbmv: PowerdBmV = Field(..., description="Upstream transmit power in dBmV.")

    model_config = {"frozen": True}


class DwrWindowCheckModel(BaseModel):
    dwr_warning_db: PowerdB = Field(..., description="Warning threshold for DWR spread (dB).")
    dwr_violation_db: PowerdB = Field(..., description="Violation threshold for DWR spread (dB).")
    channel_count: int = Field(..., description="Number of channels evaluated.")

    min_power_dbmv: PowerdBmV = Field(..., description="Minimum TX power across channels (dBmV).")
    max_power_dbmv: PowerdBmV = Field(..., description="Maximum TX power across channels (dBmV).")
    spread_db: PowerdB = Field(..., description="Power spread across channels (max-min) in dB.")

    is_warning: bool = Field(..., description="True when warning_db < spread_db <= violation_db.")
    is_violation: bool = Field(..., description="True when spread_db > violation_db.")
    extreme_channel_ids: list[ChannelId] = Field(
        ...,
        description="Channels at the extremes (min/max) that define the spread.",
    )

    model_config = {"frozen": True}


@dataclass(frozen=True, slots=True, init=False)
class DwrDynamicWindowRangeChecker:
    """
    Check DOCSIS ATDMA Upstream Transmit-Power Dynamic Window Range (DWR) compliance.

    What This Checker Does
    - Evaluates whether a set of upstream ATDMA channels (N >= 2) are “clustered” in transmit power
      tightly enough to satisfy a configured DWR window.
    - The check is performed using the simplest deterministic rule: the *min/max spread*.

    Inputs
    - Each channel contributes a single transmit power sample p_i (in dBmV).

    Core Math (Min/Max Spread Rule)
    - For powers p_i across N channels:
        p_min     = min(p_i)
        p_max     = max(p_i)
        spread_db = p_max - p_min
      The DWR constraint is satisfied when:
        spread_db <= W
      and is a violation when:
        spread_db > W

    Thresholding With Warning + Violation Triggers
    - Two thresholds are evaluated independently:
      - W_warning:
          If spread_db > W_warning but spread_db <= W_violation then the condition is a WARNING.
      - W_violation:
          If spread_db > W_violation then the condition is a HARD violation.
      - Otherwise:
          spread_db <= W_warning is considered OK.

      Example (defaults):
      - W_warning = 6.0 dB, W_violation = 12.0 dB
        * spread_db <= 6.0 dB                -> OK
        * 6.0 dB < spread_db <= 12.0 dB      -> WARNING
        * spread_db > 12.0 dB                -> VIOLATION

    Output Field Meanings (DwrWindowCheckModel)
    - channel_count:
        Number of channels included in the evaluation.

    - min_power_dbmv / max_power_dbmv:
        The smallest and largest transmit powers observed across the channels (in dBmV).

    - spread_db:
        The computed power spread across channels:
            spread_db = max_power_dbmv - min_power_dbmv

    - extreme_channel_ids (or violating_channel_ids, depending on your model naming):
        Channel IDs at the power extremes that *define* the spread.
        Specifically:
        - All channel IDs whose tx_power_dbmv == min_power_dbmv
        - All channel IDs whose tx_power_dbmv == max_power_dbmv
        Notes:
        - If multiple channels tie for the minimum or maximum, all tied IDs are included.
        - These IDs are useful for pinpointing which channels anchor the DWR spread.

    - is_warning / is_violation:
        Booleans indicating the threshold state based on the trigger tuple.
        (You may choose a single enum-like status instead; the meaning is the same.)

    Notes / Scope
    - This checker implements the min/max spread rule only.
    - A “± window around a reference” (mean/median/anchor channel) is a different policy
      and should be implemented as a separate evaluation mode to avoid ambiguity.
    """

    dwr_warning_db: PowerdB
    dwr_violation_db: PowerdB

    MIN_CHANNELS: ClassVar[Final[int]] = 2
    DEFAULT_WARNING_DB: ClassVar[Final[PowerdB]] = PowerdB(6.0)
    DEFAULT_VIOLATION_DB: ClassVar[Final[PowerdB]] = PowerdB(12.0)

    def __init__(
        self,
        *,
        dwr_violation_db: PowerdB = DEFAULT_VIOLATION_DB,
        dwr_warning_db: PowerdB = DEFAULT_WARNING_DB,
    ) -> None:
        """
        Initialize a DWR checker with explicit thresholds.

        Args:
            dwr_violation_db: Violation threshold in dB. Default 12.0 dB.
            dwr_warning_db: Warning threshold in dB. Default 6.0 dB.

        Raises:
            ValueError: When dwr_warning_db > dwr_violation_db.
        """
        warn = float(dwr_warning_db)
        violation = float(dwr_violation_db)

        if warn > violation:
            raise ValueError("dwr_warning_db must be <= dwr_violation_db.")

        object.__setattr__(self, "dwr_warning_db", PowerdB(warn))
        object.__setattr__(self, "dwr_violation_db", PowerdB(violation))

    def evaluate(self, channels: list[DwrChannelPowerModel]) -> DwrWindowCheckModel:
        """
        Evaluate DWR compliance over a set of upstream channel powers.

        Args:
            channels: Channel power samples used to compute the min/max spread.

        Returns:
            DwrWindowCheckModel with spread, bounds, warning/violation status, and extreme channel IDs.
        """
        if len(channels) < self.MIN_CHANNELS:
            raise ValueError(f"Need at least {self.MIN_CHANNELS} channels to evaluate DWR.")

        samples: list[tuple[ChannelId, float]] = [(c.channel_id, float(c.tx_power_dbmv)) for c in channels]
        powers = [p for _, p in samples]

        p_min = min(powers)
        p_max = max(powers)
        spread = p_max - p_min

        min_ids = [cid for cid, p in samples if p == p_min]
        max_ids = [cid for cid, p in samples if p == p_max]

        extreme_ids: list[ChannelId] = []
        extreme_ids.extend(min_ids)
        for cid in max_ids:
            if cid not in extreme_ids:
                extreme_ids.append(cid)

        is_violation = spread > float(self.dwr_violation_db)
        is_warning = (spread > float(self.dwr_warning_db)) and (not is_violation)

        return DwrWindowCheckModel(
            dwr_warning_db=self.dwr_warning_db,
            dwr_violation_db=self.dwr_violation_db,
            channel_count=len(channels),
            min_power_dbmv=PowerdBmV(p_min),
            max_power_dbmv=PowerdBmV(p_max),
            spread_db=PowerdB(spread),
            is_warning=is_warning,
            is_violation=is_violation,
            extreme_channel_ids=extreme_ids,
        )
