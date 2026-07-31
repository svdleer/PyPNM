
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

from pydantic import BaseModel, Field

from pypnm.api.routes.common.classes.common_endpoint_classes.common_req_resp import (
    CommonSingleCaptureAnalysisType,
)
from pypnm.lib.types import FileName, MacAddressStr, TimeStamp, TransactionId


class FileQueryRequest(BaseModel):
    mac_address: MacAddressStr = Field(description="MAC address of the cable modem used when searching for registered PNM files")


class FileEntry(BaseModel):
    transaction_id: TransactionId           = Field(..., description="Unique identifier for this file transaction")
    filename: FileName                      = Field(..., description="Name of the file")
    pnm_test_type: str                      = Field(..., description="Type of PNM test performed")
    timestamp: TimeStamp                    = Field(..., description="Capture or transaction timestamp")
    system_description: dict | None      = Field(None, description="Optional system description metadata")


class FileQueryResponse(BaseModel):
    files: dict[str, list[FileEntry]]       = Field(..., description="Mapping of MAC address to list of PNM file entries")


class UploadFileRequest(BaseModel):
    filename: FileName                      = Field(..., description="Name of the file to upload")
    data: str | None                     = Field(None, description="Optional base64-encoded or raw file data")


class UploadFileResponse(BaseModel):
    mac_address: MacAddressStr      = Field(description="MAC address associated with the uploaded file (placeholder null MAC until header inspection is wired in)",)
    filename: FileName              = Field(..., description="Name of the file that was uploaded")
    transaction_id: TransactionId   = Field(..., description="Unique identifier for the created file transaction")

class FileSearchRequest(BaseModel):
    transaction_id: TransactionId = Field(description="Transaction ID returned from file search")

class FileAnalysisRequest(BaseModel):
    search: FileSearchRequest                   = Field(description="Transaction ID returned from file search")
    analysis: CommonSingleCaptureAnalysisType   = Field(description="Single capture analysis configuration")

class AnalysisJsonResponse(BaseModel):
    mac_address: MacAddressStr    = Field(description="MAC address associated with the analyzed file")
    pnm_file_type: str          = Field(..., description="PNM file type")
    status: str                   = Field(..., description="Status of the analysis operation")
    analysis: dict                = Field(..., description="Analysis result in JSON format")

class HexDumpResponse(BaseModel):
    transaction_id: TransactionId = Field(..., description="Transaction ID associated with the PNM file.")
    bytes_per_line: int           = Field(..., description="Number of bytes rendered per hexdump output line.")
    lines: list[str]              = Field(default_factory=list, description="Hexdump lines with offset, hex bytes, and ASCII text.")

class MacAddressSystemDescriptorEntry(BaseModel):
    mac_address         : MacAddressStr                                  = Field(..., description="Cable modem MAC address.")
    system_description  : dict[str, str | int | float | bool] | None      = Field(default=None, description="System descriptor (sysDescr fields) if available.")


class MacAddressSystemDescriptorResponse(BaseModel):
    mac_addresses       : list[MacAddressSystemDescriptorEntry] = Field(..., description="Unique MAC addresses that have registered PNM files.")


class RemotePnmFileEntry(BaseModel):
    """Sanitized metadata for a PNM file available through a file agent."""
    file_id: str = Field(..., description="Signed opaque identifier used for retrieval")
    filename: FileName = Field(..., description="Sanitized basename for display")
    pnm_file_type: str = Field(..., description="PNM type code (PNN2, PNN6, or PNN7)")
    direction: str = Field(..., description="Signal direction: downstream or upstream")
    mac_address: MacAddressStr = Field(..., description="MAC address parsed from the PNM payload")
    channel_id: int = Field(..., description="Channel identifier parsed from the PNM payload")
    capture_time: int = Field(default=0, description="Capture epoch from the PNM header")
    size: int = Field(..., ge=0, description="Binary file size in bytes")


class RemotePnmFileCatalogResponse(BaseModel):
    success: bool = Field(..., description="Whether the catalog operation completed")
    files: list[RemotePnmFileEntry] = Field(default_factory=list)
    count: int = Field(default=0, ge=0)
    error: str | None = Field(default=None)


class RemoteImpulseAnalysisRequest(BaseModel):
    mac_address: MacAddressStr = Field(..., description="Cable modem MAC address")
    direction: str = Field(default="both", pattern="^(downstream|upstream|both)$")
    file_id: str | None = Field(default=None, description="Optional file ID from the remote catalog; otherwise latest matching file(s) are used")


class RemoteImpulseAnalysisResult(BaseModel):
    file_id: str
    filename: FileName
    pnm_file_type: str
    direction: str
    analysis: dict


class RemoteImpulseAnalysisResponse(BaseModel):
    success: bool
    source: str = Field(default="existing_file")
    mac_address: MacAddressStr
    direction: str
    results: list[RemoteImpulseAnalysisResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None