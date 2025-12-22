## Agent Review Bundle Summary
- Goal: Resolve remaining ruff issues and unblock pytest collection by fixing parser typing and circular imports.
- Changes: Import PnmParsers and sort imports; adjust legacy retrieval assignment; break SpecAnCapturePara circular import; update SPDX years.
- Files: src/pypnm/api/routes/docs/pnm/files/service.py; src/pypnm/lib/secret/crypto_manager.py; src/pypnm/api/routes/common/extended/types.py
- Tests: python3 -m compileall src; ruff check src; ruff format --check . (fails: many files would reformat); pytest -q (passed, 510 passed, 3 skipped: PNM_CM_IT)
- Notes: Ruff format check shows widespread formatting drift in repo; pytest skips hardware integration tests.

# FILE: src/pypnm/api/routes/docs/pnm/files/service.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import cast

from fastapi import HTTPException
from fastapi.responses import FileResponse

from pypnm.api.routes.basic.abstract.analysis_report import AnalysisRptMatplotConfig
from pypnm.api.routes.basic.channel_estimation_analysis_rpt import ChanEstimationReport
from pypnm.api.routes.basic.constellation_display_analysis_rpt import (
    ConstDisplayAnalysisRptMatplotConfig,
    ConstellationDisplayReport,
)
from pypnm.api.routes.basic.fec_summary_analysis_rpt import FecSummaryAnalysisReport
from pypnm.api.routes.basic.modulation_profile_analysis_rpt import (
    ModulationProfileReport,
)
from pypnm.api.routes.basic.rxmer_analysis_rpt import RxMerAnalysisReport
from pypnm.api.routes.basic.us_ofdma_pre_eq_analysis_rpt import CmUsOfdmaPreEqReport
from pypnm.api.routes.common.classes.analysis.model.schema import (
    ParserAnalysisModelReturn,
)
from pypnm.api.routes.common.classes.file_capture.file_type import FileType
from pypnm.api.routes.common.classes.file_capture.pnm_file_opearation import (
    OperationCaptureGroupResolver,
)
from pypnm.api.routes.common.classes.file_capture.pnm_file_transaction import (
    PnmFileTransaction,
)
from pypnm.api.routes.docs.pnm.files.schemas import (
    FileAnalysisRequest,
    FileEntry,
    FileQueryRequest,
    FileQueryResponse,
    HexDumpResponse,
    MacAddressSystemDescriptorEntry,
    MacAddressSystemDescriptorResponse,
    UploadFileResponse,
)
from pypnm.config.system_config_settings import SystemConfigSettings
from pypnm.lib.archive.manager import ArchiveManager
from pypnm.lib.constants import MediaType
from pypnm.lib.file_processor import FileProcessor
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import (
    FileName,
    MacAddressStr,
    OperationId,
    PathLike,
    TransactionId,
)
from pypnm.lib.utils import Generate
from pypnm.pnm.parser.model.parser_rtn_models import (
    CmDsConstDispMeasModel,
    CmDsHistModel,
    CmDsOfdmChanEstimateCoefModel,
    CmDsOfdmFecSummaryModel,
    CmDsOfdmModulationProfileModel,
    CmDsOfdmRxMerModel,
    CmUsOfdmaPreEqModel,
)
from pypnm.pnm.parser.pnm_file_type import PnmFileType
from pypnm.pnm.parser.pnm_parameter import (
    GetPnmParserAndParameters,
    PnmParserParametersModel,
    PnmParsers,
)
from pypnm.pnm.parser.pnm_type_header_mapper import PnmFileTypeMapper


class PnmFileService:
    """
    Handles file storage, metadata registration, and high-level analysis
    for PNM-related binary data pushed into the PyPNM system.

    Methods:
        - search_files: List available files by MAC.
        - get_file_by_transaction_id: Download raw PNM file by transaction ID.
        - get_file_by_operation_id: Download all files for an operation as a ZIP.
        - get_file_by_mac_address: Download all files for a MAC as a ZIP.
        - upload_file: Accepts uploaded files, saves, and registers.
        - get_analysis: Produces analysis for a stored file.
        - get_file: Serve generated CSV/JSON/ARCHIVE files.
    """

    def __init__(self) -> None:
        self.pnm_dir: PathLike = SystemConfigSettings.pnm_dir()
        self.logger = logging.getLogger(self.__class__.__name__)

    def search_files(self, req: FileQueryRequest) -> FileQueryResponse:
        """
        Searches for all registered PNM files tied to a specific MAC address.
        """
        try:
            mac = MacAddress(req.mac_address)
            txn = PnmFileTransaction()
            results = txn.get_file_info_via_macaddress(mac)

            if not results:
                self.logger.warning(f"No files found for MAC: {mac}")
                return FileQueryResponse(files={str(mac): []})

            file_entries: list[FileEntry] = []

            for entry in results:
                device_details = getattr(entry, "device_details", None)

                if hasattr(device_details, "model_dump"):
                    system_description = device_details.model_dump()
                elif isinstance(device_details, dict):
                    system_description = device_details
                else:
                    system_description = None

                file_entries.append(
                    FileEntry(
                        transaction_id      = entry.transaction_id,
                        filename            = entry.filename,
                        pnm_test_type       = entry.pnm_test_type,
                        timestamp           = entry.timestamp,
                        system_description  = system_description,
                    )
                )

            return FileQueryResponse(files={str(mac): file_entries})

        except Exception as e:
            self.logger.error(f"Failed to search files for MAC {req.mac_address}: {e}")
            return FileQueryResponse(files={req.mac_address: []})

    def get_file_by_transaction_id(self, transaction_id: TransactionId) -> FileResponse:
        """
        Retrieves and serves the binary file associated with the given transaction ID.
        """
        txn_data = PnmFileTransaction().get_record(transaction_id)

        if not txn_data:
            raise HTTPException(status_code=404, detail="Transaction ID not found.")

        filename = txn_data.get("filename")
        full_path = Path(self.pnm_dir) / str(filename)

        self.logger.info(f"Retrieving file for transaction {transaction_id}: {full_path}")

        if not full_path.exists():
            raise HTTPException(status_code=404, detail="File not found on disk.")

        return FileResponse(
            path        =   full_path,
            filename    =   filename,
            media_type  =   MediaType.APPLICATION_OCTET_STREAM,
        )

    def get_file_by_operation_id(self, operation_id: OperationId) -> FileResponse:
        """
        Retrieve All PNM Files For An Operation ID As A ZIP Archive.

        Resolves the capture group associated with the supplied operation ID,
        then collects all transaction records in that group, locates their
        corresponding PNM files on disk, and packages them into a single ZIP
        archive for download.
        """
        resolver    = OperationCaptureGroupResolver()
        txn_models  = resolver.get_transaction_models_for_operation(operation_id)

        if not txn_models:
            raise HTTPException(status_code=404, detail="No transactions found for Operation ID.")

        files_to_archive: list[Path] = []
        for rec in txn_models:
            src_path = Path(self.pnm_dir) / Path(rec.filename)
            if not src_path.is_file():
                self.logger.warning(
                    "Skipping missing file for transaction %s at %s",
                    rec.transaction_id,
                    src_path,
                )
                continue
            files_to_archive.append(src_path)

        if not files_to_archive:
            raise HTTPException(status_code=404, detail="No files on disk for Operation ID.")

        archive_dir = Path(SystemConfigSettings.archive_dir())
        archive_dir.mkdir(parents=True, exist_ok=True)

        archive_name = f"pnm_operation_{operation_id}_{Generate.time_stamp()}.zip"
        archive_path = archive_dir / archive_name

        ArchiveManager.zip_files(
            files         = files_to_archive,
            archive_path  = archive_path,
            mode          = "w",
            compression   = "zipdeflated",
            preserve_tree = False,
        )

        if not archive_path.is_file():
            self.logger.error("Archive creation failed for Operation ID %s at %s", operation_id, archive_path)
            raise HTTPException(status_code=500, detail="Failed to create archive for Operation ID.")

        self.logger.info("Returning ZIP archive for Operation ID %s: %s", operation_id, archive_path)

        return FileResponse(
            path        = str(archive_path),
            filename    = archive_name,
            media_type  = MediaType.APPLICATION_ZIP,
        )

    def get_file_by_mac_address(self, mac_address: MacAddressStr) -> FileResponse:
        """
        Retrieve All PNM Files For A MAC Address As A ZIP Archive.

        Looks up all transaction records bound to the provided cable modem
        MAC address, collects their associated PNM files from the PNM
        directory, and packages them into a single ZIP archive for download.

        If no records are found, or none of the files exist on disk, a 404 is raised.
        """
        records = PnmFileTransaction().get_file_info_via_macaddress(MacAddress(mac_address))

        if not records:
            raise HTTPException(status_code=404, detail="No transactions found for MAC address.")

        files_to_archive: list[Path] = []
        for rec in records:
            src_path = Path(self.pnm_dir) / Path(rec.filename)
            if not src_path.is_file():
                self.logger.warning(
                    "Skipping missing file for transaction %s: %s",
                    rec.transaction_id,
                    src_path,
                )
                continue
            files_to_archive.append(src_path)

        if not files_to_archive:
            raise HTTPException(status_code=404, detail="No files on disk for MAC address.")

        archive_dir = Path(SystemConfigSettings.archive_dir())
        archive_dir.mkdir(parents=True, exist_ok=True)

        safe_mac = str(MacAddress(mac_address).to_mac_format())
        archive_name = f"pnm_files_{safe_mac}_{Generate.time_stamp()}.zip"
        archive_path = archive_dir / archive_name

        ArchiveManager.zip_files(
            files           = files_to_archive,
            archive_path    = archive_path,
            mode            = "w",
            compression     = "zipdeflated",
            preserve_tree   = False,
        )

        if not archive_path.is_file():
            self.logger.error("Archive creation failed for MAC %s at %s", mac_address, archive_path)
            raise HTTPException(status_code=500, detail="Failed to create archive for MAC address.")

        self.logger.info("Returning ZIP archive for MAC %s: %s", mac_address, archive_path)

        return FileResponse(
            path        =   str(archive_path),
            filename    =   archive_name,
            media_type  =   MediaType.APPLICATION_ZIP,
        )

    def upload_file(self, filename: FileName, data: bytes) -> UploadFileResponse:
        """
        Handle A User-Initiated Upload Of A Raw PNM Binary File.

        1. Saves the file locally to the configured directory.
        2. Inspects its header to identify the PNM file type and MAC.
        3. Maps it to a known DOCSIS test type.
        4. Registers the transaction and returns the transaction ID.
        """
        os.makedirs(self.pnm_dir, exist_ok=True)
        filepath = os.path.join(self.pnm_dir, filename)

        processor = FileProcessor(filepath)
        success = processor.write_file(data)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to write file")

        params = GetPnmParserAndParameters(processor.read_file()).to_model()
        mac_address = params.mac_address or MacAddress.null()
        pnm_file_type: PnmFileType = params.file_type

        transaction_id = PnmFileTransaction().set_file_by_user(
            mac_address   = MacAddress(mac_address),
            pnm_test_type = PnmFileTypeMapper.get_test_type(pnm_file_type),
            filename      = filename,
        )

        return UploadFileResponse(
            mac_address     = MacAddress(mac_address).mac_address,
            filename        = filename,
            transaction_id  = transaction_id,
        )

    def get_file(self, file_type: FileType, filename: PathLike) -> FileResponse:
        """
        Serve a generated file from its configured directory.

        Supported types:
        - CSV: returns text/csv from SystemConfigSettings.csv_dir
        - JSON: returns application/json from SystemConfigSettings.json_dir
        - ARCHIVE: returns application/zip from SystemConfigSettings.archive_dir
        """
        safe_name = Path(filename).name

        valid_extensions = [".csv", ".json", ".zip"]
        if not any(safe_name.endswith(ext) for ext in valid_extensions):
            raise HTTPException(status_code=400, detail=f"Invalid file extension, file: {safe_name}")

        if file_type == FileType.CSV:
            base_dir = SystemConfigSettings.csv_dir()
            media_type = MediaType.TEXT_CSV

        elif file_type == FileType.JSON:
            base_dir = SystemConfigSettings.json_dir()
            media_type = MediaType.APPLICATION_JSON

        elif file_type == FileType.ARCHIVE:
            base_dir = SystemConfigSettings.archive_dir()
            media_type = MediaType.APPLICATION_ZIP

        else:
            self.logger.error(f"Unsupported file type requested: {file_type.name}")
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_type.name}")

        file_path = Path(base_dir) / safe_name
        if not file_path.is_file():
            self.logger.warning(f"File not found: {file_path}")
            raise HTTPException(status_code=404, detail="File not found on disk.")

        return FileResponse(
            path        =   str(file_path),
            filename    =   safe_name,
            media_type  =   media_type,
        )

    def get_analysis(self, req: FileAnalysisRequest) -> tuple[ParserAnalysisModelReturn, PnmFileType]:
        """
        Returns basic analysis result for a stored PNM file identified by transaction ID.
        The analysis performed depends on the PNM file type.

        Return:
        Tuple[ParserAnalysisModelReturn, PnmFileType]
            A tuple containing the analysis model and the PNM file type.
        """
        txn_rec = PnmFileTransaction().get_record(req.search.transaction_id)
        if not txn_rec:
            raise HTTPException(status_code=404, detail="Transaction ID not found for analysis.")

        filename = txn_rec.get("filename")
        if not filename:
            raise HTTPException(status_code=404, detail="Filename not found in transaction record.")

        self.logger.info(f"Starting analysis for transaction ID {req.search.transaction_id} on file: {self.pnm_dir}/{filename}")

        # Get binary file
        file_path = f'{self.pnm_dir}/{filename}'

        if not Path(file_path).is_file():
            raise HTTPException(status_code=404, detail="PNM file not found on disk for analysis.")
        fp = FileProcessor(file_path).read_file()

        # Get PnmHeader to Determine PnmFileType
        from pypnm.pnm.parser.pnm_parameter import GetPnmParserAndParameters
        parser, model  = GetPnmParserAndParameters(fp).get_parser()

        self.logger.info(f"Performing {model.file_type.name} analysis for transaction {req.search.transaction_id} on file {filename}")

        return self.__get_analysis(parser, model)

    def get_pnm_path_for_transaction(self, transaction_id: TransactionId) -> Path:
        """
        Resolve The Filesystem Path For A PNM File From A Transaction ID.

        Parameters
        ----------
        transaction_id:
            Transaction identifier associated with the PNM capture file.

        Returns
        -------
        Path
            Fully-resolved path to the PNM file on disk.

        Raises
        ------
        HTTPException
            If the transaction record does not exist, the filename is missing,
            or the file is not present on disk.
        """
        txn_data = PnmFileTransaction().get_record(transaction_id)
        if not txn_data:
            raise HTTPException(status_code=404, detail="Transaction ID not found.")

        filename = txn_data.get("filename")
        if not filename:
            raise HTTPException(status_code=404, detail="Filename not found in transaction record.")

        full_path = Path(self.pnm_dir) / str(filename)

        self.logger.info(
            "Resolving PNM file for transaction %s at %s",
            transaction_id,
            full_path,
        )

        if not full_path.exists() or not full_path.is_file():
            self.logger.warning(
                "PNM file not found on disk for transaction %s at %s",
                transaction_id,
                full_path,
            )
            raise HTTPException(status_code=404, detail="PNM file not found on disk.")

        return full_path

    def get_hexdump_by_transaction_id(self, transaction_id: TransactionId, bytes_per_line: int) -> HexDumpResponse:
        """
        Generate A Structured Hexdump For A PNM File Identified By Transaction ID.

        Parameters
        ----------
        transaction_id:
            Transaction identifier associated with the PNM capture file.
        bytes_per_line:
            Number of bytes per output line in the hexdump view. Typical values
            are 8, 16, or 32. Non-positive values are coerced to the default
            configured via DEFAULT_HEXDUMP_BYTES_PER_LINE.

        Returns
        -------
        HexDumpResponse
            Structured hexdump payload including the transaction ID, the
            effective bytes-per-line setting, and formatted hexdump lines
            containing offset, hex bytes, and ASCII representation.
        """
        DEFAULT_HEXDUMP_BYTES_PER_LINE = 16

        if bytes_per_line <= 0:
            bytes_per_line = DEFAULT_HEXDUMP_BYTES_PER_LINE

        file_path  = self.get_pnm_path_for_transaction(transaction_id)
        processor  = FileProcessor(file_path)
        lines      = processor.hexdump(bytes_per_line=bytes_per_line)

        if not lines:
            self.logger.error(
                "Hexdump generation failed or produced no data for transaction %s at %s",
                transaction_id,
                file_path,
            )
            raise HTTPException(status_code=500, detail="Failed to generate hexdump for PNM file.")

        return HexDumpResponse(
            transaction_id = transaction_id,
            bytes_per_line = bytes_per_line,
            lines          = lines,
        )

    def __get_analysis(self, parser: PnmParsers, model:PnmParserParametersModel) -> tuple[ParserAnalysisModelReturn, PnmFileType]:
        """
        Internal method to instantiate the Analysis class with the given parser and model.
        """
        from pypnm.api.routes.common.classes.analysis.analysis import Analysis
        if model.file_type == PnmFileType.RECEIVE_MODULATION_ERROR_RATIO:
            return Analysis.basic_analysis_rxmer_from_model(cast(CmDsOfdmRxMerModel, parser.to_model())), model.file_type

        elif model.file_type == PnmFileType.OFDM_CHANNEL_ESTIMATE_COEFFICIENT:
            return Analysis.basic_analysis_ds_chan_est_from_model(cast(CmDsOfdmChanEstimateCoefModel, parser.to_model())), model.file_type

        elif model.file_type == PnmFileType.OFDM_MODULATION_PROFILE:
            return Analysis.basic_analysis_ds_modulation_profile_from_model(cast(CmDsOfdmModulationProfileModel, parser.to_model())), model.file_type

        elif model.file_type == PnmFileType.DOWNSTREAM_CONSTELLATION_DISPLAY:
            return Analysis.basic_analysis_ds_constellation_display_from_model(cast(CmDsConstDispMeasModel, parser.to_model())), model.file_type

        elif model.file_type == PnmFileType.DOWNSTREAM_HISTOGRAM:
            return Analysis.basic_analysis_ds_histogram_from_model(cast(CmDsHistModel, parser.to_model())), model.file_type

        elif model.file_type == PnmFileType.OFDM_FEC_SUMMARY:
            return Analysis.basic_analysis_ds_ofdm_fec_summary_from_model(cast(CmDsOfdmFecSummaryModel, parser.to_model())), model.file_type

        elif model.file_type == PnmFileType.UPSTREAM_PRE_EQUALIZER_COEFFICIENTS or model.file_type == PnmFileType.UPSTREAM_PRE_EQUALIZER_COEFFICIENTS_LAST_UPDATE:
            return Analysis.basic_analysis_us_ofdma_pre_equalization_from_model(cast(CmUsOfdmaPreEqModel, parser.to_model())), model.file_type

        raise HTTPException(
            status_code=400,
            detail=f"Analysis not implemented for file type: {model.file_type.name}"
        )

    def get_archive(self, request: FileAnalysisRequest) -> FileResponse:
        rpt: Path = Path()

        theme = request.analysis.plot.ui.theme
        plot_config = AnalysisRptMatplotConfig(theme = theme)
        analysis_model, pnm_ftype = self.get_analysis(request)

        # TODO: Need to clean up circlar import at next major release
        from pypnm.api.routes.common.classes.analysis.analysis import Analysis
        analysis = Analysis.get_analysis_from_model(analysis_model)

        if pnm_ftype == PnmFileType.RECEIVE_MODULATION_ERROR_RATIO:
            analysis_rpt = RxMerAnalysisReport(analysis, plot_config)
            rpt: Path = cast(Path, analysis_rpt.build_report())

        elif pnm_ftype == PnmFileType.OFDM_CHANNEL_ESTIMATE_COEFFICIENT:
            analysis_rpt = ChanEstimationReport(analysis, plot_config)
            rpt: Path = cast(Path, analysis_rpt.build_report())

        elif pnm_ftype == PnmFileType.OFDM_MODULATION_PROFILE:
            analysis_rpt = ModulationProfileReport(analysis, plot_config)
            rpt: Path = cast(Path, analysis_rpt.build_report())

        elif pnm_ftype == PnmFileType.DOWNSTREAM_CONSTELLATION_DISPLAY:
            plot_config = ConstDisplayAnalysisRptMatplotConfig(theme = theme)
            analysis_rpt = ConstellationDisplayReport(analysis, plot_config)
            rpt: Path = cast(Path, analysis_rpt.build_report())

        elif pnm_ftype == PnmFileType.UPSTREAM_PRE_EQUALIZER_COEFFICIENTS or pnm_ftype == PnmFileType.UPSTREAM_PRE_EQUALIZER_COEFFICIENTS_LAST_UPDATE:
            plot_config = ConstDisplayAnalysisRptMatplotConfig(theme = theme)
            analysis_rpt = CmUsOfdmaPreEqReport(analysis)
            rpt: Path = cast(Path, analysis_rpt.build_report())

        elif pnm_ftype == PnmFileType.OFDM_FEC_SUMMARY:
            plot_config = ConstDisplayAnalysisRptMatplotConfig(theme = theme)
            analysis_rpt = FecSummaryAnalysisReport(analysis, plot_config)
            rpt: Path = cast(Path, analysis_rpt.build_report())

        return PnmFileService().get_file(FileType.ARCHIVE, rpt.name)

    def get_mac_addresses(self) -> MacAddressSystemDescriptorResponse:
        """
        Retrieve Unique MAC Addresses With Registered PNM Files.

        This scans all transaction records and returns a de-duplicated set of
        MAC addresses. When multiple records exist for the same MAC, the most
        recent record (by timestamp) is used as the source for the system
        descriptor when available.

        Parameters
        ----------
        req:
            Placeholder request model for endpoint compatibility. Currently not
            used for filtering.

        Returns
        -------
        MacAddressSystemDescriptorResponse
            Unique MAC address list with optional system descriptor per MAC.
        """
        records = PnmFileTransaction().get_all_record_models()
        if not records:
            return MacAddressSystemDescriptorResponse(mac_addresses=[])

        latest_by_mac: dict[str, tuple[int, dict[str, str] | None]] = {}

        for rec in records:
            mac_value = getattr(rec, "mac_address", "")
            mac_str   = str(mac_value).lower().strip()
            if not mac_str:
                continue

            ts_value = getattr(rec, "timestamp", 0)
            try:
                ts_int = int(ts_value)
            except Exception:
                ts_int = 0

            system_description: dict[str, str] | None = None

            device_details = getattr(rec, "device_details", None)
            if device_details is not None:
                if hasattr(device_details, "system_description"):
                    sd_value = getattr(device_details, "system_description", None)
                    if sd_value is not None:
                        if hasattr(sd_value, "model_dump"):
                            system_description = sd_value.model_dump()
                        elif isinstance(sd_value, dict):
                            system_description = sd_value

                elif hasattr(device_details, "model_dump"):
                    dd_dump = device_details.model_dump()
                    if isinstance(dd_dump, dict):
                        sd_value = dd_dump.get("system_description")
                        if isinstance(sd_value, dict):
                            system_description = sd_value

                elif isinstance(device_details, dict):
                    sd_value = device_details.get("system_description")
                    if isinstance(sd_value, dict):
                        system_description = sd_value

            existing = latest_by_mac.get(mac_str)
            if existing is None:
                latest_by_mac[mac_str] = (ts_int, system_description)
                continue

            existing_ts, _existing_sd = existing
            if ts_int >= existing_ts:
                latest_by_mac[mac_str] = (ts_int, system_description)

        entries: list[MacAddressSystemDescriptorEntry] = []
        for mac_str, (_ts, sd) in sorted(latest_by_mac.items(), key=lambda x: x[0]):
            entries.append(
                MacAddressSystemDescriptorEntry(
                    mac_address         = mac_str,
                    system_description  = sd,
                )
            )

        return MacAddressSystemDescriptorResponse(mac_addresses=entries)

# FILE: src/pypnm/lib/secret/crypto_manager.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import base64
import contextlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class SecretCryptoError(Exception):
    """
    Secret Encryption/Decryption Failure.

    Raised when a secret cannot be encrypted or decrypted due to missing keys,
    invalid token formats, permission problems, or cryptographic validation
    failures.
    """


@dataclass(frozen=True, slots=True)
class SecretToken:
    """
    Versioned Encrypted Secret Token.

    Attributes
    ----------
    version:
        Token version string (example: "v1").
    payload:
        The encrypted payload (Fernet token string).
    """

    version: str
    payload: str


class SecretCryptoManager:
    """
    Secret Encryption Manager For Config-Stored Passwords.

    This class supports storing encrypted passwords inside JSON configuration
    (example: system.json) while keeping the decryption key outside the repo,
    typically in the user's ~/.ssh directory.

    Security Model
    --------------
    - The encrypted password may safely live in the config file.
    - The decrypt key MUST NOT live in the config file or repo.
    - The decrypt key is loaded from one of:
      1) A key file (default: ~/.ssh/pypnm_secrets.key)
      2) An environment variable (default: PYPNM_SECRET_KEY)

    Token Format
    ------------
    Tokens are stored as:

        ENC[v1]:<fernet-token>

    Where <fernet-token> is a URL-safe base64 encoded token produced by Fernet.

    Notes
    -----
    Fernet provides authenticated encryption (confidentiality + integrity). If a
    token is altered, decryption will fail with an integrity error.
    """

    DEFAULT_ENV_VAR_NAME            = "PYPNM_SECRET_KEY"
    DEFAULT_KEY_FILE_NAME           = "pypnm_secrets.key"
    DEFAULT_TOKEN_VERSION           = "v1"
    DEFAULT_TOKEN_PREFIX            = "ENC"
    SSH_DIR_NAME                    = ".ssh"

    FERNET_KEY_SIZE_BYTES           = 32

    KEY_FILE_PERMISSIONS            = 0o600
    SSH_DIR_PERMISSIONS             = 0o700

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"{self.__class__.__name__}")

    @staticmethod
    def default_key_path() -> Path:
        """
        Return The Default Key File Path Under ~/.ssh.

        Returns
        -------
        Path
            The default key file path: ~/.ssh/pypnm_secrets.key
        """
        home_dir = Path.home()
        return home_dir / SecretCryptoManager.SSH_DIR_NAME / SecretCryptoManager.DEFAULT_KEY_FILE_NAME

    @staticmethod
    def build_token(payload: str, version: str = DEFAULT_TOKEN_VERSION) -> str:
        """
        Build A Versioned Token String.

        Parameters
        ----------
        payload:
            Fernet token string (URL-safe base64).
        version:
            Token version (default: "v1").

        Returns
        -------
        str
            Versioned token string in format: ENC[vX]:<payload>
        """
        return f"{SecretCryptoManager.DEFAULT_TOKEN_PREFIX}[{version}]:{payload}"

    @staticmethod
    def parse_token(token: str) -> SecretToken:
        """
        Parse A Versioned Token String.

        Parameters
        ----------
        token:
            Token string in format: ENC[vX]:<payload>

        Returns
        -------
        SecretToken
            Parsed token components.

        Raises
        ------
        SecretCryptoError
            If the token is malformed or missing required parts.
        """
        prefix = f"{SecretCryptoManager.DEFAULT_TOKEN_PREFIX}["
        if not token.startswith(prefix):
            raise SecretCryptoError("Encrypted token missing expected 'ENC[...]:...' prefix.")

        end_bracket_index = token.find("]:")
        if end_bracket_index < 0:
            raise SecretCryptoError("Encrypted token missing closing ']:' delimiter.")

        version = token[len(prefix):end_bracket_index].strip()
        if version == "":
            raise SecretCryptoError("Encrypted token version is empty.")

        payload = token[end_bracket_index + 2:].strip()
        if payload == "":
            raise SecretCryptoError("Encrypted token payload is empty.")

        return SecretToken(version=version, payload=payload)

    @staticmethod
    def generate_key_b64() -> str:
        """
        Generate A New Fernet Key As A Base64 String.

        Returns
        -------
        str
            URL-safe base64 encoded key string.
        """
        key_bytes = Fernet.generate_key()
        return key_bytes.decode("utf-8")

    @staticmethod
    def write_key_file(key_path: Path, key_b64: str) -> Path:
        """
        Write A Fernet Key To Disk With Tight Permissions.

        Parameters
        ----------
        key_path:
            Path to write the key file (example: ~/.ssh/pypnm_secrets.key).
        key_b64:
            Fernet key (URL-safe base64 string).

        Returns
        -------
        Path
            The key_path written.

        Raises
        ------
        SecretCryptoError
            If the key is invalid or cannot be written securely.
        """
        SecretCryptoManager.validate_key_b64(key_b64)
        ssh_dir = key_path.parent
        ssh_dir.mkdir(parents=True, exist_ok=True)

        with contextlib.suppress(OSError):
            os.chmod(ssh_dir, SecretCryptoManager.SSH_DIR_PERMISSIONS)

        key_path.write_text(key_b64.strip() + "\n", encoding="utf-8")

        with contextlib.suppress(OSError):
            os.chmod(key_path, SecretCryptoManager.KEY_FILE_PERMISSIONS)

        return key_path

    @staticmethod
    def validate_key_b64(key_b64: str) -> None:
        """
        Validate A Fernet Key String.

        Parameters
        ----------
        key_b64:
            Fernet key as a URL-safe base64 string.

        Raises
        ------
        SecretCryptoError
            If the key is invalid.
        """
        key_str = key_b64.strip()
        if key_str == "":
            raise SecretCryptoError("Secret key is empty.")

        try:
            raw = base64.urlsafe_b64decode(key_str.encode("utf-8"))
        except Exception as exc:
            raise SecretCryptoError(f"Secret key is not valid base64: {exc}") from exc

        if len(raw) != SecretCryptoManager.FERNET_KEY_SIZE_BYTES:
            raise SecretCryptoError(
                f"Secret key decoded size is invalid: {len(raw)} bytes (expected {SecretCryptoManager.FERNET_KEY_SIZE_BYTES})."
            )

        try:
            Fernet(key_str.encode("utf-8"))
        except Exception as exc:
            raise SecretCryptoError(f"Secret key is not a valid Fernet key: {exc}") from exc

    @staticmethod
    def load_key_bytes(key_path: Path, env_var_name: str = DEFAULT_ENV_VAR_NAME) -> bytes:
        """
        Load Secret Key Bytes From Key File Or Environment Variable.

        Resolution Order
        ----------------
        1) key_path file
        2) env var env_var_name

        Parameters
        ----------
        key_path:
            Path to the key file (example: ~/.ssh/pypnm_secrets.key).
        env_var_name:
            Environment variable name to use as fallback (default: PYPNM_SECRET_KEY).

        Returns
        -------
        bytes
            Fernet key bytes.

        Raises
        ------
        SecretCryptoError
            If no key source is available or if the key is invalid.
        """
        if key_path.exists() and key_path.is_file():
            key_b64 = key_path.read_text(encoding="utf-8").strip()
            SecretCryptoManager.validate_key_b64(key_b64)
            return key_b64.encode("utf-8")

        env_value = os.environ.get(env_var_name, "").strip()
        if env_value != "":
            SecretCryptoManager.validate_key_b64(env_value)
            return env_value.encode("utf-8")

        raise SecretCryptoError(
            f"Missing secret key. Provide key file '{key_path}' or set environment variable '{env_var_name}'."
        )

    @staticmethod
    def encrypt_password(
        password: str,
        key_path: Path | None = None,
        env_var_name: str = DEFAULT_ENV_VAR_NAME,
        version: str = DEFAULT_TOKEN_VERSION,
    ) -> str:
        """
        Encrypt A Password For Storage In system.json.

        Parameters
        ----------
        password:
            Plaintext password to encrypt.
        key_path:
            Key file path. If empty, defaults to ~/.ssh/pypnm_secrets.key
        env_var_name:
            Environment variable for key fallback (default: PYPNM_SECRET_KEY).
        version:
            Token version label (default: "v1").

        Returns
        -------
        str
            Versioned token string in format: ENC[vX]:<payload>

        Raises
        ------
        SecretCryptoError
            If encryption fails due to missing/invalid key or invalid input.
        """
        password_str = password.strip()
        if password_str == "":
            raise SecretCryptoError("Password is empty; refusing to encrypt empty value.")

        actual_key_path = key_path if key_path is not None else SecretCryptoManager.default_key_path()
        key_bytes       = SecretCryptoManager.load_key_bytes(actual_key_path, env_var_name=env_var_name)
        fernet          = Fernet(key_bytes)

        token_bytes = fernet.encrypt(password_str.encode("utf-8"))
        token_str   = token_bytes.decode("utf-8")

        return SecretCryptoManager.build_token(payload=token_str, version=version)

    @staticmethod
    def decrypt_password(
        token: str,
        key_path: Path | None = None,
        env_var_name: str = DEFAULT_ENV_VAR_NAME,
        accepted_versions: tuple[str, ...] = (DEFAULT_TOKEN_VERSION,),
    ) -> str:
        """
        Decrypt A Password Token From system.json.

        Parameters
        ----------
        token:
            Versioned token string in format: ENC[vX]:<payload>
        key_path:
            Key file path. If empty, defaults to ~/.ssh/pypnm_secrets.key
        env_var_name:
            Environment variable for key fallback (default: PYPNM_SECRET_KEY).
        accepted_versions:
            Allowed token versions (default: ("v1",)).

        Returns
        -------
        str
            Decrypted plaintext password.

        Raises
        ------
        SecretCryptoError
            If decryption fails due to invalid token, missing key, wrong key,
            unsupported token version, or integrity/authentication failure.
        """
        token_str         = token.strip()
        parsed            = SecretCryptoManager.parse_token(token_str)
        version_supported = parsed.version in accepted_versions

        if not version_supported:
            raise SecretCryptoError(
                f"Unsupported encrypted token version '{parsed.version}'. Allowed: {', '.join(accepted_versions)}"
            )

        actual_key_path = key_path if key_path is not None else SecretCryptoManager.default_key_path()
        key_bytes       = SecretCryptoManager.load_key_bytes(actual_key_path, env_var_name=env_var_name)
        fernet          = Fernet(key_bytes)

        try:
            clear_bytes = fernet.decrypt(parsed.payload.encode("utf-8"))
        except InvalidToken as exc:
            raise SecretCryptoError("Failed to decrypt password: invalid token or wrong secret key.") from exc

        clear_str = clear_bytes.decode("utf-8").strip()
        if clear_str == "":
            raise SecretCryptoError("Decrypted password is empty; token or key may be invalid.")

        return clear_str

    @staticmethod
    def encrypt_system_config_secrets(config: dict[str, Any]) -> dict[str, Any]:
        """
        Encrypt System Config Secrets In-Place Semantics (Returns Updated Copy).

        Contract
        --------
        - Never persist a 'password' key.
        - If a password exists (from 'password' or 'password_enc'), store it as
          encrypted token in 'password_enc' (ENC[...]).
        - If password is empty, keep 'password_enc' as "" and still remove 'password'.
        - SCP is not handled here (removed as an option); this function only enforces
          secret storage semantics for configured methods.
        """
        pnm = config.get("PnmFileRetrieval", {})
        retrieval = pnm.get("retrieval_method")
        if not isinstance(retrieval, dict):
            legacy = pnm.get("retrival_method")
            retrieval = legacy if isinstance(legacy, dict) else {}
        methods = retrieval.get("methods", {})

        if not isinstance(methods, dict):
            return config

        for method_cfg in methods.values():
            if not isinstance(method_cfg, dict):
                continue

            password_enc = str(method_cfg.get("password_enc", "") or "").strip()
            password     = str(method_cfg.get("password", "") or "").strip()

            token_source = password_enc if password_enc != "" else password

            if token_source == "":
                method_cfg.pop("password", None)
                method_cfg["password_enc"] = ""
                continue

            if token_source.startswith("ENC["):
                method_cfg["password_enc"] = token_source
            else:
                method_cfg["password_enc"] = SecretCryptoManager.encrypt_password(token_source)

            method_cfg.pop("password", None)

        return config

# FILE: src/pypnm/api/routes/common/extended/types.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

from pydantic import BaseModel

from pypnm.api.routes.docs.pnm.spectrumAnalyzer.schemas import SpecAnCapturePara
from pypnm.lib.types import StringEnum


class CommonMessagingServiceExtension(StringEnum):
    SPECTRUM_ANALYSIS_SNMP_CAPTURE_PARAMETER = "spectrum_analysis_snmp_capture_parameters"

class CommonMsgServiceExtParams(BaseModel):
    spectrum_analysis_snmp_capture_parameters: SpecAnCapturePara

class CommonMessagingServiceExtensionModel(BaseModel):
    extension: CommonMsgServiceExtParams
