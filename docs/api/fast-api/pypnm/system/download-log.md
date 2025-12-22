# System Operations - PyPNM System Log

Centralized Access To The PyPNM System Log For Diagnostics And Support.

## Table Of Contents

[Overview](#overview)

[Endpoint](#endpoint)

[Request](#request)

- [Example Request (cURL)](#example-request-curl)

[Response](#response)

- [Successful Response](#successful-response)
- [Error Responses](#error-responses)
  - [Log File Not Found](#log-file-not-found)
  - [Other I/O Errors](#other-io-errors)

[Notes](#notes)

[Field Tables](#field-tables)

## Overview

The PyPNM System Log endpoint exposes the main backend log file as a downloadable text file. This is useful for:

- Capturing logs when reporting issues
- Automated log collection from CI or monitoring systems
- Ad-hoc troubleshooting when developing or integrating PyPNM

The endpoint simply streams the current log file that PyPNM writes to on disk (for example, `logs/pypnm.log`, as configured by `SystemConfigSettings`).

## Endpoint

`GET /pypnm/system/log/download`

## Request

No request body is required.

The endpoint does not accept query parameters. It respects any global FastAPI middleware you have configured (authentication, CORS, etc.).

### Example Request (cURL)

Download the log file to the current directory as `pypnm.log`:

```bash
curl -X GET "http://127.0.0.1:8000/pypnm/system/log/download" -o pypnm.log
```

If you are serving over HTTPS with a custom host/port, update the URL accordingly, for example:

```bash
curl -X GET "https://pypnm.example.net:443/pypnm/system/log/download" -o pypnm.log
```

## Response

On success, the endpoint returns the log file as `text/plain` with a `Content-Disposition` header that suggests the current log filename configured by `SystemConfigSettings.log_filename()` (typically `pypnm.log`).

### Successful Response

**Status:** `200 OK`  
**Body:** Raw text content of the PyPNM log file.

Example headers (abbreviated):

```http
HTTP/1.1 200 OK
content-type: text/plain; charset=utf-8
content-disposition: attachment; filename="pypnm.log"
```

Example snippet of response body:

```text
2025-12-06 13:52:08,050 [INFO] root: ==== PyPNM REST API Starting ====
2025-12-06 13:52:09,543 [INFO] CmDsOfdmRxMerService: MAC: aa:bb:cc:dd:ee:ff - INET: 192.168.100.20 - Index/ChannelID List: [(3, '194'), (48, '193')]
...
```

### Error Responses

If the log file does not exist or cannot be read, the endpoint returns an HTTP error with a JSON payload.

#### Log File Not Found

```http
HTTP/1.1 500 Internal Server Error
content-type: application/json
```

```json
{
  "detail": "Failed to retrieve log: Log file not found at: /path/to/logs/pypnm.log"
}
```

#### Other I/O Errors

```http
HTTP/1.1 500 Internal Server Error
content-type: application/json
```

```json
{
  "detail": "Failed to retrieve log: <reason from underlying exception>"
}
```

## Notes

- The location and name of the log file are governed by `SystemConfigSettings.log_dir()` and `SystemConfigSettings.log_filename()`.
- The endpoint does not paginate or truncate the log; it returns the file as-is. For very large logs, consider rotating or archiving them at the OS level.
- When filing a bug or support request, you can attach the downloaded `pypnm.log` alongside the PyPNM support bundle for more complete diagnostics.
- In demo mode, log content will reflect demo traffic and test captures rather than live CM/CMTS data.

## Field Tables

This endpoint returns a plain text file, not a structured JSON object. There is no `data.*` payload to document. The primary contract is:

| Element            | Type         | Description                                           |
| ------------------ | ------------ | ----------------------------------------------------- |
| HTTP method        | `GET`        | Read-only retrieval of the log file.                 |
| URL path           | string       | `/pypnm/system/log/download`                         |
| Response type      | `text/plain` | Entire contents of the configured PyPNM log file.    |
| Suggested filename | string       | Usually `pypnm.log` (via `Content-Disposition`).     |
