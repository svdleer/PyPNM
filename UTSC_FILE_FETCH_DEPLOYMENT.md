# UTSC File Fetching — Deployment & Testing Guide

## Changes Summary

Added agent-based AND direct FTP file retrieval for UTSC (Upstream Triggered Spectrum Capture) spectrum analyzer captures. Files that land on TFTP or FTP are now automatically fetched and cached by PyPNM.

### Vendor Support
- **Cisco cBR-8:** TFTP via agent (`PNMCcapUsSpecAn_*` format)
- **Casa E6000/C100G:** FTP or TFTP via agent
- **CommScope E6000:** FTP or TFTP via agent
- `src/pypnm/api/routes/pnm/us/utsc/schemas.py` — Added request/response schemas for file operations
- `src/pypnm/api/routes/pnm/us/utsc/router.py` — Added 2 new FastAPI endpoints + agent prefetch helper

### New Endpoints
1. **POST `/pnm/us/utsc/files/list`** — List UTSC files on TFTP server
2. **POST `/pnm/us/utsc/files/retrieve`** — Fetch a UTSC file from agent to local cache

## Deployment Steps

### 1. Review Changes

```bash
cd /Users/silvester/PythonDev/Git/PyPNM

# Review schema changes
git diff src/pypnm/api/routes/pnm/us/utsc/schemas.py | head -100

# Review router changes  
git diff src/pypnm/api/routes/pnm/us/utsc/router.py | head -100
```

### 2. Verify Syntax

```bash
cd /Users/silvester/PythonDev/Git/PyPNM
python3 -m py_compile \
  src/pypnm/api/routes/pnm/us/utsc/schemas.py \
  src/pypnm/api/routes/pnm/us/utsc/router.py

# Expected: No output (success)
```

### 3. Commit & Deploy

```bash
cd /Users/silvester/PythonDev/Git/PyPNM

# Commit changes
git add -A
git commit -m "feat: Add agent-based UTSC file fetching endpoints

- Add /pnm/us/utsc/files/list endpoint to list UTSC files on TFTP
- Add /pnm/us/utsc/files/retrieve endpoint to fetch files from agent
- Implement vendor-aware filename pattern matching (Cisco/CommScope)
- Parallel agent lookup with fallback; first-success strategy

Fixes spectrum analyzer data retrieval for UTSC captures."

# Push to origin
git push origin main

# SSH to server and deploy
ssh mndlab 'cd /Users/silvester/PythonDev/Git/PyPNM && git pull && docker-compose restart pypnm'
```

## Configuration

### Environment Variables

#### Agent/Local Mode (TFTP)
```bash
# In .env for PyPNM — use agent-based file retrieval
PNM_FILE_SOURCE=agent        # Enable agent-based file access
CMTS_TFTP_UTSC=agent         # UTSC-specific setting (optional)

# Or use global setting
CMTS_TFTP=agent              # Applies to both RxMER and UTSC

# Agent must be connected with file_list and pnm_file_get capabilities
```

#### Direct FTP Mode
```bash
# In .env for PyPNM — use direct FTP (Casa, CommScope vendors)
PNM_FILE_SOURCE=ftp          # Enable direct FTP retrieval
FTP_SERVER_IP=10.0.0.3       # FTP server IP
FTP_PORT=21                  # FTP port (default 21)
FTP_USER=ftpaccess           # FTP username
FTP_PASSWORD=ftpaccessftp    # FTP password
FTP_TFTPBOOT_DIR=/var/lib/tftpboot  # Remote directory on FTP server

# Files will be downloaded and cached locally
PNM_CACHE_DIR=/app/data/pnm_cache   # Where files are cached
```

## Testing

### Prerequisites
- PyPNM running with agent connection active
- CMTS configured to generate UTSC files
- Files landing on TFTP server (e.g., `/var/lib/tftpboot`)

### Test 1: List UTSC Files

```bash
# Request
curl -X POST http://localhost:8000/pnm/us/utsc/files/list \
  -H "Content-Type: application/json" \
  -d '{
    "rf_port_ifindex": 100
  }'

# Expected response (200 OK):
{
  "success": true,
  "files": [
    "PNMCcapUsSpecAn_HFD-LC0011-CCAP201_2026-06-03_06:59:03:890_493230"
  ],
  "count": 1,
  "prefix_used": "PNMCcapUsSpecAn_*_100"
}
```

### Test 2: Retrieve UTSC File

```bash
# Request
curl -X POST http://localhost:8000/pnm/us/utsc/files/retrieve \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "PNMCcapUsSpecAn_*_100",
    "glob": true
  }'

# Expected response (200 OK):
{
  "success": true,
  "filename": "PNMCcapUsSpecAn_HFD-LC0011-CCAP201_2026-06-03_06:59:03:890_493230",
  "cache_path": "~/.cache/pypnm_docsis/PNMCcapUsSpecAn_HFD-LC0011-CCAP201_2026-06-03_06:59:03:890_493230",
  "file_size": 27600,
  "agent_id": "cmts-agent@10.0.0.5"
}
```

### Test 3: Full UTSC Flow

```bash
#!/bin/bash

# 1. Configure UTSC test
curl -X POST http://localhost:8000/pnm/us/utsc/configure \
  -H "Content-Type: application/json" \
  -d '{
    "cmts": {
      "cmts_ip": "10.0.0.1",
      "community": "public"
    },
    "rf_port_ifindex": 100,
    "trigger_mode": 2,
    "tftp_server": "10.0.0.2",
    "filename": "utsc_test_capture"
  }'

# 2. Start test
curl -X POST http://localhost:8000/pnm/us/utsc/start \
  -H "Content-Type: application/json" \
  -d '{
    "cmts": {"cmts_ip": "10.0.0.1", "community": "public"},
    "rf_port_ifindex": 100
  }'

# 3. Poll status until SAMPLE_READY (4)
for i in {1..60}; do
  curl -s -X GET \
    'http://localhost:8000/pnm/us/utsc/status?cmts_ip=10.0.0.1&rf_port_ifindex=100' \
    -H "Content-Type: application/json" | jq '.meas_status_name'
  sleep 1
done

# 4. List files
curl -X POST http://localhost:8000/pnm/us/utsc/files/list \
  -H "Content-Type: application/json" \
  -d '{"rf_port_ifindex": 100}' | jq '.files'

# 5. Retrieve newest file
FILENAME=$(curl -s -X POST http://localhost:8000/pnm/us/utsc/files/list \
  -H "Content-Type: application/json" \
  -d '{"rf_port_ifindex": 100}' | jq -r '.files[0]')

curl -X POST http://localhost:8000/pnm/us/utsc/files/retrieve \
  -H "Content-Type: application/json" \
  -d "{\"filename\": \"$FILENAME\", \"glob\": false}" | jq '.'
```

## Troubleshooting

### Issue: Determining Which Mode to Use

**How to check what mode is active:**
```bash
# Check PyPNM env
docker exec pypnm env | grep PNM_FILE_SOURCE
# Result: PNM_FILE_SOURCE=ftp or PNM_FILE_SOURCE=agent or not set (defaults to local)
```

### FTP Mode Issues

#### Issue: "FTP listing failed" or "FTP download failed"

**Diagnosis:**
```bash
# Test FTP connectivity from PyPNM container
docker exec pypnm python3 -c "
import ftplib
ftp = ftplib.FTP('10.0.0.3', 21, timeout=15)
ftp.login('ftpaccess', 'ftpaccessftp')
ftp.cwd('/var/lib/tftpboot')
files = ftp.nlst()
print(f'FTP connected: found {len(files)} files')
ftp.quit()
"
```

**Resolution:**
- Verify FTP_SERVER_IP is correct and reachable from PyPNM container
- Check FTP credentials (FTP_USER, FTP_PASSWORD)
- Verify FTP_TFTPBOOT_DIR path on FTP server: `ssh ftp.example.com 'ls -l /var/lib/tftpboot/'`
- Check firewall rules between PyPNM and FTP server (port 21)

### Agent Mode Issues

**Diagnosis:**
```bash
# Check if agents are connected
curl http://localhost:8000/api/agents | jq '.agents[] | {id, capabilities}'
```

**Resolution:**
- Verify agent is running on remote equipment
- Check agent connection status in PyPNM logs: `docker logs pypnm | grep agent`
- Ensure agent websocket URL is correct in PyPNM config

### Issue: "No agent returned file_list results"

**Diagnosis:**
- Agent capability exists but command failed
- Check agent logs for errors

**Resolution:**
- Verify `TFTP_ROOT` or `PYPNM_TFTP_PATH` is correct on agent
- Ensure files actually exist on agent TFTP: `ls -l /var/lib/tftpboot/PNMCcapUsSpecAn_*`

### Issue: Files not being generated at all

**Diagnosis:**
- Configure/start endpoints succeeded, but CMTS isn't generating files

**Resolution:**
1. Check CMTS UTSC status:
   ```bash
   # Get status from CMTS
   curl -X GET 'http://localhost:8000/pnm/us/utsc/status?cmts_ip=10.0.0.1&rf_port_ifindex=100'
   # Look for meas_status: should be 4 (SAMPLE_READY) after test completes
   ```

2. Verify bulk destination is configured:
   ```bash
   curl -X GET 'http://localhost:8000/pnm/us/utsc/bulk-destinations?cmts_ip=10.0.0.1'
   # Should show tftp_server IP in response
   ```

3. Check CMTS SNMP directly:
   ```bash
   # SSH to CMTS and query OID
   snmpwalk -v2c -c public 10.0.0.1 1.3.6.1.4.1.4491.2.1.27.1.3.8
   # Should show UTSC configuration rows
   ```

## Architecture Notes

### Why This Matters
- **Before:** UTSC files generated on CMTS, uploaded to TFTP/FTP, but PyPNM couldn't fetch them → no Spectrum Analyzer data
- **After:** UTSC files automatically fetched via agent (TFTP) or direct FTP → Spectrum Analyzer populated

### Design Decisions
1. **Dual-mode support:** 
   - **Agent-based (TFTP):** Agents in remote cable plant, PyPNM in data center. Agents have TFTP access.
   - **Direct FTP:** For vendors that require/prefer FTP (Casa, CommScope)
2. **Parallel agent lookup (agent mode only):** First agent to successfully return file wins (fault-tolerant)
3. **Cached locally:** Files written to `~/.cache/pypnm_docsis/` or `PNM_CACHE_DIR` for parsing and analysis
4. **Vendor-aware:** Auto-detects filename patterns for Cisco vs CommScope CMTS

### Mode Selection: Environment Variables
```bash
# Agent/TFTP mode (default if agent is connected)
PNM_FILE_SOURCE=agent

# Direct FTP mode (for Casa, CommScope vendors)
PNM_FILE_SOURCE=ftp
```

### Flow Diagram - Agent/TFTP Mode
```
CMTS (RF port)
  │
  └─→ Generates UTSC spectrum file
       │
       └─→ Uploads to TFTP (via agent in cable plant)
            │
            ├─→ /var/lib/tftpboot/PNMCcapUsSpecAn_...
            │
            └─→ PyPNM POST /pnm/us/utsc/files/list
                 │
                 └─→ Agent sends file_list command
                      │
                      └─→ Returns matching filenames
                           │
                           └─→ PyPNM POST /pnm/us/utsc/files/retrieve
                                │
                                └─→ Agent sends pnm_file_get command
                                     │
                                     └─→ Returns file content (base64)
                                          │
                                          └─→ Cached locally
                                               │
                                               └─→ Parsed for Spectrum Analyzer view
```

### Flow Diagram - Direct FTP Mode
```
CMTS (RF port)
  │
  └─→ Generates UTSC spectrum file
       │
       └─→ Uploads to FTP server
            │
            ├─→ ftp.example.com:/var/lib/tftpboot/...
            │
            └─→ PyPNM POST /pnm/us/utsc/files/list
                 │
                 └─→ Direct FTP nlst() command
                      │
                      └─→ Returns matching filenames
                           │
                           └─→ PyPNM POST /pnm/us/utsc/files/retrieve
                                │
                                └─→ Direct FTP RETR command
                                     │
                                     └─→ Returns file content
                                          │
                                          └─→ Cached locally
                                               │
                                               └─→ Parsed for Spectrum Analyzer view
```

## Rollback

If issues occur:

```bash
git revert HEAD --no-edit
git push origin main
ssh mndlab 'cd /Users/silvester/PythonDev/Git/PyPNM && git pull && docker-compose restart pypnm'
```

## Related Documentation
- [Agent Manager Architecture](../docs/agent_architecture.md)
- [CMTS Vendor Detection](../src/pypnm/api/utils/cmts_vendor.py)
- [UTSC SNMP Configuration](../src/pypnm/api/routes/pnm/us/utsc/service.py)
