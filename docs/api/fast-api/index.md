# FastAPI overview

PyPNM exposes a FastAPI service that you can run locally ([localhost API](http://127.0.0.1:8000) by default) or deploy to your own infrastructure. Use this section whenever you call the service over HTTP.

> **Before you start**
>
> - Default base URL: [FastAPI host](http://<host>:8000) unless overridden via CLI flags (see [pypnm CLI](../../system/pypnm-cli.md)).
> - Authentication: none by default; secure deployments should front the API with network ACLs or a proxy.
> - Response envelope: every endpoint returns the standard [response schema](common/response.md). Familiarize yourself with it before consuming the API.
> - Errors and retries: see [FastAPI status codes](status/fast-api-status-codes.md) for retry guidance and validation failures.

## Pick a guide

| Section | When to use it | Common actions |
|---------|----------------|----------------|
| [PyPNM](pypnm/index.md) | Service/system endpoints (health, status, operations). | Check health; list operations; fetch service status. |
| [Single capture](single/index.md) | One-shot capture/queries (downstream, upstream, system). | Pull RxMER/FEC once; read event log; spectrum/histogram. |
| [Multi capture](multi/index.md) | Scheduled or multi-snapshot workflows and analysis. | Start capture; poll status; download ZIP; stop early. |
| [File management](file-manager/file-manager-api.md) | Upload/download files to/from the system. | Upload config; download logs; list stored files. |
| [Common schemas](common/index.md) | Request/response conventions and shared schemas. | Review request schema; response wrapper; error model. |
| [Status codes](status/fast-api-status-codes.md) | API status and error codes. | Map errors to fixes; see retry/validation guidance. |
