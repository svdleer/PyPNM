# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

import csv
from enum import Enum
from pathlib import Path
from typing import Any
import pandas as pd


class CSVOrientation(Enum):
    """CSV data orientation"""
    VERTICAL = "vertical"      # Headers as columns, data as rows
    HORIZONTAL = "horizontal"  # Headers as rows, data as columns

class CSVValidationError(Exception):
    """Custom exception for CSV validation errors"""
    pass

class CSVManager:
    """
    A class to manage CSV creation and data insertion with validation.

    Supports both vertical (traditional) and horizontal orientations with
    strict validation to ensure data integrity.
    """

    def __init__(self, orientation: CSVOrientation = CSVOrientation.VERTICAL) -> None:
        """
        Initialize CSV manager.

        Args:
            orientation: Whether to create CSV in vertical or horizontal format
        """
        self.orientation = orientation
        self.headers: list[str] = []
        self.data: list[list[Any]] = []
        self._header_set = False
        self._file_path: Path

    def set_header(self, headers: list[str] | str) -> None:
        """
        Add headers to the CSV.

        Args:
            headers: List of header names or single header name

        Raises:
            CSVValidationError: If headers are already set or if headers are empty
        """
        if self._header_set:
            raise CSVValidationError("Headers have already been set. Use clear() to reset.")

        if isinstance(headers, str):
            headers = [headers]

        if not headers:
            raise CSVValidationError("Headers cannot be empty")

        # Validate header names
        for i, header in enumerate(headers):
            if not isinstance(header, str):
                raise CSVValidationError(f"Header at index {i} must be a string, got {type(header)}")
            if not header.strip():
                raise CSVValidationError(f"Header at index {i} cannot be empty or whitespace only")

        self.headers = [str(h).strip() for h in headers]
        self._header_set = True

    def insert_row(self, row_data: list[Any] | Any) -> None:
        """
        Insert a row of data.

        Args:
            row_data: List of values or single value (for single column CSV)

        Raises:
            CSVValidationError: If headers not set or row length doesn't match headers
        """
        if not self._header_set:
            raise CSVValidationError("Headers must be set before inserting data. Call add_header() first.")

        # Handle single value input
        if not isinstance(row_data, list):
            row_data = [row_data]

        # Validate row length matches header count
        if len(row_data) != len(self.headers):
            raise CSVValidationError(
                f"Row data length ({len(row_data)}) does not match header count ({len(self.headers)}). "
                f"Expected {len(self.headers)} elements, got {len(row_data)}"
                f"Header: {self.headers}"
                f"RowIdx: {row_data}"
            )

        # Convert all data to appropriate types and add row
        processed_row = []
        for _i, value in enumerate(row_data):
            if value is None:
                processed_row.append("")
            else:
                processed_row.append(str(value))

        self.data.append(processed_row)

    def insert_multiple_rows(self, rows: list[list[Any]]) -> None:
        """
        Insert multiple rows at once.

        Args:
            rows: List of row data lists
        """
        for i, row in enumerate(rows):
            try:
                self.insert_row(row)
            except CSVValidationError as e:
                raise CSVValidationError(f"Error in row {i}: {str(e)}") from e

    def get_row_count(self) -> int:
        """Get the number of data rows (excluding header)"""
        return len(self.data)

    def get_column_count(self) -> int:
        """Get the number of columns"""
        return len(self.headers)

    def get_headers(self) -> list[str]:
        """Get a copy of the headers"""
        return self.headers.copy()

    def get_data(self) -> list[list[str]]:
        """Get a copy of all data rows"""
        return [row.copy() for row in self.data]

    def clear(self) -> None:
        """Clear all headers and data"""
        self.headers = []
        self.data = []
        self._header_set = False

    def set_path_fname(self, file_path: str | Path) -> None:
        """
        Set the file path for saving the CSV.

        Args:
            file_path: Path where CSV will be saved
        """
        self._file_path = Path(file_path)

    def get_path_fname(self) -> Path:
        """Get the file path where the CSV will be saved.

        Returns:
            Path object of the file path
        """
        if not hasattr(self, '_file_path'):
            raise CSVValidationError("File path not set. Use set_path_fname() to specify a path.")

        return self._file_path

    def write(self, include_index: bool = False, delimiter: str = ',') -> bool:
        """
        Write CSV data to file based on orientation.

        Args:
            file_path: Path where CSV file will be created
            include_index: Whether to include row indices (only for vertical orientation)
            delimiter: CSV delimiter character

        Returns:
            Path object of the created file

        Raises:
            CSVValidationError: If no headers are set
        """
        if not self._header_set:
            raise CSVValidationError("Cannot create CSV: no headers have been set")

        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self._file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile, delimiter=delimiter)

            if self.orientation == CSVOrientation.VERTICAL:
                self._write_vertical_csv(writer, include_index)
            else:
                self._write_horizontal_csv(writer)

        return True

    def _write_vertical_csv(self, writer: csv.writer, include_index: bool = False) -> None:
        """Write CSV in vertical orientation (traditional format)"""
        # Write headers
        headers = self.headers.copy()
        if include_index:
            headers.insert(0, "Index")
        writer.writerow(headers)

        # Write data rows
        for i, row in enumerate(self.data):
            data_row = row.copy()
            if include_index:
                data_row.insert(0, str(i))
            writer.writerow(data_row)

    def _write_horizontal_csv(self, writer: csv.writer) -> None:
        """Write CSV in horizontal orientation (headers as first column)"""
        # Transpose the data: each header becomes a row with its corresponding data
        for i, header in enumerate(self.headers):
            row = [header]  # Start with header name
            # Add all values for this column across all data rows
            for data_row in self.data:
                if i < len(data_row):
                    row.append(data_row[i])
                else:
                    row.append("")  # Fill missing values with empty string
            writer.writerow(row)

    def to_dataframe(self) -> pd.DataFrame:
        """
        Convert CSV data to pandas DataFrame.

        Returns:
            DataFrame with headers as columns and data as rows

        Raises:
            CSVValidationError: If no headers are set
        """
        if not self._header_set:
            raise CSVValidationError("Cannot create DataFrame: no headers have been set")

        if not self.data:
            # Return empty DataFrame with just headers
            return pd.DataFrame(columns=self.headers)

        return pd.DataFrame(self.data, columns=self.headers)

    def from_dataframe(self, df: pd.DataFrame) -> None:
        """
        Load data from pandas DataFrame.

        Args:
            df: Source DataFrame
        """
        self.clear()

        # Set headers
        self.set_header(list(df.columns))

        # Add data rows
        for _, row in df.iterrows():
            self.insert_row(row.tolist())

    def preview(self, max_rows: int = 5) -> str:
        """
        Generate a preview string of the CSV data.

        Args:
            max_rows: Maximum number of data rows to show

        Returns:
            Formatted string preview of the CSV
        """
        if not self._header_set:
            return "No headers set"

        preview_lines = []

        # Add header info
        preview_lines.append(f"CSV Preview ({self.orientation.value} orientation)")
        preview_lines.append(f"Headers ({len(self.headers)}): {', '.join(self.headers)}")
        preview_lines.append(f"Data rows: {len(self.data)}")
        preview_lines.append("")

        if not self.data:
            preview_lines.append("No data rows")
            return "\n".join(preview_lines)

        # Show sample data
        preview_lines.append("Sample data:")
        preview_lines.append(" | ".join(f"{h:>10}" for h in self.headers))
        preview_lines.append("-" * (13 * len(self.headers)))

        rows_to_show = min(max_rows, len(self.data))
        for i in range(rows_to_show):
            row = self.data[i]
            formatted_row = " | ".join(f"{str(val):>10}" for val in row)
            preview_lines.append(formatted_row)

        if len(self.data) > max_rows:
            preview_lines.append(f"... and {len(self.data) - max_rows} more rows")

        return "\n".join(preview_lines)

    def validate_data_integrity(self) -> bool:
        """
        Validate that all rows have the correct number of elements.

        Returns:
            True if all data is valid

        Raises:
            CSVValidationError: If validation fails
        """
        if not self._header_set:
            raise CSVValidationError("No headers set for validation")

        expected_columns = len(self.headers)

        for i, row in enumerate(self.data):
            if len(row) != expected_columns:
                raise CSVValidationError(
                    f"Row {i} has {len(row)} elements, expected {expected_columns}"
                )

        return True

