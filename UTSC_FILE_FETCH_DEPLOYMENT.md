# UTSC File Fetching — Deployment & Testing Guide

## Changes Summary

Added agent-based AND direct FTP file retrieval for UTSC (Upstream Triggered Spectrum Capture) spectrum analyzer captures. Files that land on TFTP or FTP are now automatically fetched and cached by PyPNM.

### Vendor Support
- **Cisco cBR-8:** TFTP via agent (`PNMCcapUsSpecAn_*` format)
- **Casa E6000/C100G:** FTP or TFTP via agent
- **CommScope E6000:** FTP or TFTP via agent
- `src/pypnm/api/routes/pnm/us/utsc/schemas.py` — Request/response schemas for file operations
- `src/pypnm/api/routes/pnm/us/utsc/router.py` — Source-owned listing, retrieval, normalized samples, exact deletion, and housekeeping

### File Endpoints
1. **POST `/pnm/us/utsc/files/list`** — List UTSC files on the authoritative source
2. **POST `/pnm/us/utsc/files/retrieve`** — Fetch one UTSC file into PyPNM's cache
3. **POST `/pnm/us/utsc/files/sample`** — Return normalized UTSC bins
4. **POST `/pnm/us/utsc/files/delete`** — Delete exact approved basenames
5. **POST `/pnm/us/utsc/files/housekeeping`** — Dry-run or remove aged approved captures

Agent-mode deletion and housekeeping are never broadcast. PyPNM selects one capable file agent, and the agent requires an explicit writable root plus independent, default-disabled operation opt-ins.

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

Only commit or deploy with explicit authorization. Stage the reviewed migration files individually; never use `git add -A`, blind `git pull`, reset, clean, stash, or manual source copying.

```bash
# In the source repository
git add src/pypnm/api/agent/manager.py
git add src/pypnm/api/routes/pnm/us/ofdma/rxmer/router.py
git add src/pypnm/api/routes/pnm/us/ofdma/rxmer/schemas.py
git add src/pypnm/api/routes/pnm/us/ofdma/rxmer/service.py
git add src/pypnm/api/routes/pnm/us/spectrumAnalyzer/router.py
git add src/pypnm/api/routes/pnm/us/utsc/router.py
git add src/pypnm/api/routes/pnm/us/utsc/schemas.py
git add src/pypnm/lib/pnm_file_source.py
git add src/pypnm/pnm/parser/utsc_file.py
git add UTSC_FILE_FETCH_DEPLOYMENT.md
git commit -m "Complete PyPNM-owned PNM file handling"
git push origin <reviewed-branch>

# On an explicitly authorized deployment target, first verify the worktree,
# preserve unrelated tracked/untracked files, then fast-forward only:
git status --short
git fetch origin
git merge --ff-only origin/<reviewed-branch>
# Restart through the target's approved deployment procedure.
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

# Agent must be connected with file_list and pnm_file_get capabilities.
# Destructive operations additionally require these settings on the designated
# file agent; leave both operation flags false unless explicitly authorized:
PYPNM_PNM_WRITE_ROOT=/srv/tftp
PYPNM_PNM_FILE_DELETE_ENABLED=false
PYPNM_PNM_FILE_HOUSEKEEPING_ENABLED=false
```

`PYPNM_PNM_WRITE_ROOT` has no discovery fallback and must name the exact writable capture root. Delete accepts exact `utsc_` or `PNMCcapUsSpecAn_` basenames only. Housekeeping defaults to dry-run, applies the same prefixes, and is bounded by the agent scan/action limits.

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

Create and push a new revert commit only with explicit authorization. On the authorized target, verify the worktree before fetching and fast-forwarding; preserve unrelated tracked changes and untracked runtime files.

```bash
git revert <migration-commit>
git push origin <reviewed-branch>

# Authorized deployment target:
git status --short
git fetch origin
git merge --ff-only origin/<reviewed-branch>
# Restart through the target's approved deployment procedure.
```

## Related Documentation
- [Agent Manager Architecture](../docs/agent_architecture.md)
- [CMTS Vendor Detection](../src/pypnm/api/utils/cmts_vendor.py)
- [UTSC SNMP Configuration](../src/pypnm/api/routes/pnm/us/utsc/service.py)
