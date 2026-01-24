# DOCSIS Device Reset

Initiates A Remote Reset (Reboot) Of A DOCSIS Cable Modem Via SNMP.

## Endpoint

**POST** `/docs/dev/reset`

## Request

Use the SNMP-only format: [Common → Request](../../common/request.md)
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../common/response.md) (`mac_address`, `status`, `message`, `data`).

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": "Reset command sent to cable modem at 192.168.0.100 successfully.",
  "data": null
}
```

## Response Field Details

| Field         | Type   | Description                                        |
| ------------- | ------ | -------------------------------------------------- |
| `mac_address` | string | MAC address of the targeted cable modem.           |
| `status`      | int    | Operation status (`0` = success; non-zero = fail). |
| `message`     | string | Success or error message with IP/MAC detail.       |
| `data`        | null   | Reserved for future use or extended diagnostics.   |

## Notes

* Ensure SNMP credentials are valid and the modem is reachable.
* This operation reboots the modem and will briefly disrupt service.
* Useful for remote troubleshooting, recovery, or provisioning workflows.
