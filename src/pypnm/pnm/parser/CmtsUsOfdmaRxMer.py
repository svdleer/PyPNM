# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

import logging
import struct
from typing import cast

from pypnm.lib.constants import KHZ
from pypnm.lib.mac_address import MacAddress, MacAddressFormat
from pypnm.lib.signal_processing.shan.series import ShannonSeries
from pypnm.lib.types import (
    FloatSeries,
    FrequencyHz,
    FrequencySeriesHz,
    MacAddressStr,
)
from pypnm.pnm.lib.signal_statistics import SignalStatistics
from pypnm.pnm.parser.model.parser_rtn_models import CmtsUsOfdmaRxMerModel
from pypnm.pnm.parser.pnm_file_type import PnmFileType
from pypnm.pnm.parser.pnm_header import PnmHeader


class CmtsUsOfdmaRxMer(PnmHeader):
    """
    Parser for CMTS Upstream OFDMA RxMER Per Subcarrier binary data.
    
    File type: PNN105 (0x69 = 'i')
    
    Per Table 7-108 - RxMER File Format:
        - File type (504E4D69) - 4 bytes
        - Capture Time - 4 bytes  
        - IfIndex - 4 bytes
        - Unique CCAP ID - 256 bytes
        - CM MAC Address - 6 bytes
        - Number of averages - 2 bytes
        - PreEq On or Off - 1 byte
        - Subcarrier zero center frequency - 4 bytes
        - FirstActiveSubcarrierIndex - 2 bytes
        - Subcarrier Spacing in kHz - 1 byte
        - Length in bytes of RxMER data - 4 bytes
        - Subcarrier RxMER data - variable
    
    Note: Actual files include:
        - 2 version bytes after file type (standard PNM header)
        - Vendor-specific extra fields after CCAP ID (7 bytes)
    """

    # After standard 10-byte PNM header:
    # ifindex(I) + ccap_id(256s) + extra_ifindex(I) + extra_field(H) + reserved(B) +
    # mac(6s) + num_avg(H) + preeq(B) + zero_freq(I) + first_active(H) + spacing(B) + data_len(I)
    _HEADER_FMT = "!I256sIHB6sHBIHBI"
    _HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 287 bytes after PNM header

    def __init__(self, binary_data: bytes) -> None:
        super().__init__(binary_data)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._model: CmtsUsOfdmaRxMerModel

        self._logical_ch_ifindex: int = 0
        self._ccap_id: str = ""
        self._md_us_sg_ifindex: int = 0
        self._cm_mac_address: MacAddressStr = MacAddress.null()
        self._num_averages: int = 0
        self._preeq_enabled: bool = False
        self._first_active_subcarrier: int = 0
        self._subcarrier_zero_frequency: FrequencyHz = 0
        self._subcarrier_spacing: FrequencyHz = 0
        self._data_length: int = 0
        self._rxmer_data: bytes = b""
        self._rxmer_float_data: FloatSeries = []

        self._process()

    def _process(self) -> None:
        ft = self.get_pnm_file_type()
        if ft != PnmFileType.CMTS_US_OFDMA_RXMER:
            expected = PnmFileType.CMTS_US_OFDMA_RXMER.get_pnm_cann()
            actual = ft.get_pnm_cann() if isinstance(ft, PnmFileType) else str(ft)
            raise ValueError(
                f"PNM File Stream is not CMTS US OFDMA RxMER file type: {expected}, Error: {actual}"
            )

        try:
            if len(self.pnm_data) < self._HEADER_SIZE:
                raise ValueError(f"Binary data too short: {len(self.pnm_data)} < {self._HEADER_SIZE}")

            unpacked = struct.unpack(self._HEADER_FMT, self.pnm_data[:self._HEADER_SIZE])

            self._logical_ch_ifindex = unpacked[0]
            # CCAP ID is null-terminated string in 256 byte field
            ccap_bytes = unpacked[1]
            self._ccap_id = ccap_bytes.split(b'\x00')[0].decode('ascii', errors='ignore')
            self._md_us_sg_ifindex = unpacked[2]
            # unpacked[3] is extra vendor field
            # unpacked[4] is reserved byte
            mac_bytes = unpacked[5]
            self._cm_mac_address = MacAddress(mac_bytes).to_mac_format(MacAddressFormat.COLON)
            self._num_averages = unpacked[6]
            self._preeq_enabled = bool(unpacked[7])
            self._subcarrier_zero_frequency = unpacked[8]
            self._first_active_subcarrier = unpacked[9]
            # Spacing is 1 byte in kHz
            self._subcarrier_spacing = unpacked[10] * KHZ
            self._data_length = unpacked[11]

            # Read RxMER data
            data_start = self._HEADER_SIZE
            self._rxmer_data = self.pnm_data[data_start:data_start + self._data_length]

            if len(self._rxmer_data) < self._data_length:
                self.logger.warning(
                    f"RxMER data truncated: got {len(self._rxmer_data)}, expected {self._data_length}"
                )

            self._model = self._build_model()

        except struct.error as e:
            self.logger.error(f"Struct unpack error: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error processing CMTS US OFDMA RxMER data: {e}")
            raise

    def _build_model(self) -> CmtsUsOfdmaRxMerModel:
        values = self.get_rxmer_values()
        # Filter out excluded subcarriers (0xff = 63.75 dB)
        valid_values = [v for v in values if v < 63.5]
        
        return CmtsUsOfdmaRxMerModel(
            pnm_header=self.getPnmHeaderParameterModel(),
            logical_ch_ifindex=self._logical_ch_ifindex,
            ccap_id=self._ccap_id,
            md_us_sg_ifindex=self._md_us_sg_ifindex,
            cm_mac_address=self._cm_mac_address,
            num_averages=self._num_averages,
            preeq_enabled=self._preeq_enabled,
            num_active_subcarriers=len(valid_values),
            first_active_subcarrier_index=self._first_active_subcarrier,
            subcarrier_zero_frequency=self._subcarrier_zero_frequency,
            subcarrier_spacing=self._subcarrier_spacing,
            data_length=self._data_length,
            occupied_channel_bandwidth=FrequencyHz(len(valid_values) * self._subcarrier_spacing),
            values=values,
            signal_statistics=SignalStatistics(valid_values).compute() if valid_values else SignalStatistics([0.0]).compute(),
            modulation_statistics=ShannonSeries(valid_values).to_dict() if valid_values else {},
        )

    def get_rxmer_values(self) -> FloatSeries:
        """Convert raw RxMER bytes to dB values (quarter-dB units)."""
        if self._rxmer_float_data:
            return self._rxmer_float_data

        if not self._rxmer_data:
            return []

        # Quarter-dB units, clamp to [0.0, 63.75]
        self._rxmer_float_data = [min(max(byte / 4.0, 0.0), 63.75) for byte in self._rxmer_data]
        return self._rxmer_float_data

    def get_frequencies(self) -> FrequencySeriesHz:
        """Calculate frequency for each subcarrier."""
        spacing = int(self._subcarrier_spacing)
        f_zero = int(self._subcarrier_zero_frequency)
        first_idx = int(self._first_active_subcarrier)
        n = int(self._data_length)

        if spacing <= 0 or n <= 0:
            return []

        start = f_zero + spacing * first_idx
        return cast(FrequencySeriesHz, [start + i * spacing for i in range(n)])

    @property
    def ccap_id(self) -> str:
        """Return CCAP chassis identifier."""
        return self._ccap_id

    @property
    def num_averages(self) -> int:
        """Return number of averaging periods used."""
        return self._num_averages

    @property
    def preeq_enabled(self) -> bool:
        """Return whether pre-equalization was enabled during measurement."""
        return self._preeq_enabled

    def to_model(self) -> CmtsUsOfdmaRxMerModel:
        return self._model

    def to_dict(self) -> dict[str, object]:
        return self.to_model().model_dump()

    def to_json(self) -> str:
        return self.to_model().model_dump_json()

    def __repr__(self) -> str:
        return (
            f"<CmtsUsOfdmaRxMer(ifindex={self._logical_ch_ifindex}, "
            f"cm={self._cm_mac_address}, samples={self._data_length}, "
            f"spacing={self._subcarrier_spacing/1000}kHz)>"
        )
