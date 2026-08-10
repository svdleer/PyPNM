"""
Authoritative PNM capture source policy for the PyPNM API.

This module owns vendor-aware local/FTP/agent mode selection, CMTS upload
settings, FTP retrieval, PyPNM cache paths, safe deletion, and age-based
housekeeping. Callers outside PyPNM must use API contracts rather than sharing
filesystem paths or credentials.
"""
from __future__ import annotations

import fnmatch
import ftplib
import logging
import os
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def _env(key: str, default: str = '') -> str:
    return os.environ.get(key, default)


def _vendor_suffix(vendor: Optional[str]) -> str:
    vendor_lc = (vendor or '').strip().lower()
    if any(token in vendor_lc for token in ('commscope', 'arris', 'e6000')):
        return 'COMMSCOPE'
    if any(token in vendor_lc for token in ('cisco', 'cbr')):
        return 'CISCO'
    if any(token in vendor_lc for token in ('casa', 'evo', 'vccap')):
        return 'CASA'
    return 'ALT'


def resolve_file_mode(vendor: Optional[str] = None) -> str:
    """Return the authoritative local/ftp/agent mode for a CMTS vendor."""
    suffix = _vendor_suffix(vendor)
    for key in (
        f'{suffix}_TFTP',
        f'CMTS_TFTP_{suffix}',
        f'PNM_FILE_SOURCE_CMTS_{suffix}',
    ):
        mode = _env(key).strip().lower()
        if mode in ('local', 'ftp', 'agent'):
            return mode
    fallback = (
        _env('CMTS_TFTP')
        or _env('PNM_FILE_SOURCE_CMTS')
        or _env('PNM_FILE_SOURCE', 'local')
    ).strip().lower()
    return fallback if fallback in ('local', 'ftp', 'agent') else 'local'


def is_ftp_mode(vendor: Optional[str] = None) -> bool:
    return resolve_file_mode(vendor) == 'ftp'


def get_tftp_server(vendor: Optional[str] = None) -> str:
    """Return the configured CMTS-reachable TFTP destination."""
    suffix = _vendor_suffix(vendor)
    return (
        _env(f'TFTP_{suffix}')
        or (_env('TFTP_ARRIS') if suffix == 'COMMSCOPE' else '')
        or (_env('TFTP_IPV4_ALT') if suffix in ('CISCO', 'ALT') else '')
        or _env('TFTP_IPV4', '127.0.0.1')
    )


def get_tftp_dest_path(vendor: Optional[str] = None) -> str:
    suffix = _vendor_suffix(vendor)
    return _env(f'TFTP_ROOT_{suffix}') or _env('TFTP_DEST_PATH', './')


def get_ftp_config(vendor: Optional[str] = None) -> dict:
    suffix = _vendor_suffix(vendor)
    return {
        'host': _env(f'FTP_SERVER_IP_{suffix}') or _env('FTP_SERVER_IP') or _env('TFTP_IPV4', '127.0.0.1'),
        'port': int(_env(f'FTP_PORT_{suffix}') or _env('FTP_PORT', '21')),
        'user': _env(f'FTP_USER_{suffix}') or _env('FTP_USER', 'ftpaccess'),
        'password': _env(f'FTP_PASSWORD_{suffix}') or _env('FTP_PASSWORD', 'ftpaccessftp'),
        'ftp_dir': _env(f'FTP_TFTPBOOT_DIR_{suffix}') or _env('FTP_TFTPBOOT_DIR', '/var/lib/tftpboot'),
    }


def get_all_ftp_configs() -> list[dict]:
    configs: list[dict] = []
    seen: set[tuple] = set()
    for vendor in ('commscope', 'cisco', 'casa', 'alt'):
        config = get_ftp_config(vendor)
        key = (config['host'], config['port'], config['user'], config['ftp_dir'])
        if key not in seen:
            seen.add(key)
            configs.append(config)
    return configs


def get_cache_dir() -> str:
    d = _env('PNM_CACHE_DIR', '/app/data/pnm_cache')
    os.makedirs(d, exist_ok=True)
    return d


def local_pnm_dir(vendor: Optional[str] = None) -> Path:
    """
    Return the local filesystem Path PyPNM should search for capture files.

    - local mode: TFTPBOOT_DIR env (default /var/lib/tftpboot)
    - ftp mode:   local cache dir where files are pre-fetched
    """
    if is_ftp_mode(vendor):
        return Path(get_cache_dir())
    return Path(_env('TFTPBOOT_DIR', '/var/lib/tftpboot'))


def fetch_pnm_files(
    filename_prefix: str,
    *,
    ftp_cfg: dict | None = None,
    vendor: Optional[str] = None,
    allow_when_local: bool = False,
) -> List[str]:
    """
    Download every file on the FTP server whose basename starts with
    *filename_prefix* into the local cache directory.

    Returns the list of local file paths downloaded, or [] on error.

    By default downloads are attempted only in PNM_FILE_SOURCE=ftp mode.
    Set allow_when_local=True for hybrid deployments where API still needs to
    pull CMTS capture files from FTP while other flows use local/agent files.
    """
    if not is_ftp_mode(vendor) and not allow_when_local:
        return []

    configs = [ftp_cfg] if ftp_cfg is not None else (
        [get_ftp_config(vendor)] if vendor else get_all_ftp_configs()
    )
    prefix = Path(filename_prefix).name
    cache_dir = get_cache_dir()
    downloaded: List[str] = []

    for config in configs:
        downloaded.extend(_fetch_from_ftp(prefix, config, cache_dir))
    return downloaded


def _fetch_from_ftp(prefix: str, ftp_cfg: dict, cache_dir: str) -> List[str]:
    downloaded: List[str] = []
    ftp: ftplib.FTP | None = None
    try:
        ftp = ftplib.FTP()
        ftp.connect(ftp_cfg['host'], ftp_cfg['port'], timeout=15)
        ftp.login(ftp_cfg['user'], ftp_cfg['password'])
        ftp.cwd(ftp_cfg['ftp_dir'])
        try:
            all_files = ftp.nlst()
        except ftplib.error_perm:
            all_files = []

        matching = [f for f in all_files if Path(f).name.startswith(prefix)]
        for remote_file in matching:
            basename = Path(remote_file).name
            local_path = Path(cache_dir) / basename
            temp_path = local_path.with_suffix(local_path.suffix + '.part')
            try:
                with temp_path.open('wb') as fp:
                    ftp.retrbinary(f'RETR {basename}', fp.write)
                temp_path.replace(local_path)
                downloaded.append(str(local_path))
            except Exception as exc:
                temp_path.unlink(missing_ok=True)
                logger.warning("FTP: failed to download %s: %s", basename, exc)
    except Exception as exc:
        logger.warning("FTP fetch error (host=%s): %s", ftp_cfg.get('host'), exc)
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:
                pass
    return downloaded


def delete_pnm_files(
    filename_prefix: str,
    *,
    ftp_cfg: dict | None = None,
    vendor: Optional[str] = None,
    include_local_source: bool = False,
) -> int:
    """
    Delete files matching *filename_prefix* from FTP server and local cache.
    Returns number of deleted files.

    Cleans FTP when ``is_ftp_mode()`` **or** when ``FTP_SERVER_IP`` is set
    (hybrid mode: PNM_FILE_SOURCE=local but files fetched via FTP on demand).
    """
    prefix = Path(filename_prefix).name
    allowed_prefixes = ('utsc_', 'PNMCcapUsSpecAn_', 'rxmer_', 'usrxmer_', 'us_rxmer_')
    if not prefix.startswith(allowed_prefixes):
        raise ValueError("Refusing to delete an unrecognized PNM capture prefix")
    if ftp_cfg is None:
        ftp_cfg = get_ftp_config(vendor)

    deleted = 0

    ftp_host = ftp_cfg.get('host', '') or ''
    if is_ftp_mode(vendor) or ftp_host not in ('', '127.0.0.1'):
        try:
            ftp = ftplib.FTP()
            ftp.connect(ftp_cfg['host'], ftp_cfg['port'], timeout=15)
            ftp.login(ftp_cfg['user'], ftp_cfg['password'])
            try:
                ftp.cwd(ftp_cfg['ftp_dir'])
                all_files: List[str] = []
                try:
                    all_files = ftp.nlst()
                except ftplib.error_perm:
                    pass
                for fname in all_files:
                    bare = Path(fname).name
                    if bare.startswith(prefix):
                        try:
                            ftp.delete(bare)
                            deleted += 1
                            logger.debug(f"FTP housekeeping: deleted {bare}")
                        except Exception as e:
                            logger.warning(f"FTP housekeeping: could not delete {bare}: {e}")
            except ftplib.error_perm as e:
                logger.warning(f"FTP housekeeping: could not cd to {ftp_cfg['ftp_dir']}: {e}")
            finally:
                try:
                    ftp.quit()
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"FTP housekeeping error: {e}")

    # Clean PyPNM cache and, when explicitly requested by an API, local TFTP storage.
    roots = {Path(get_cache_dir())}
    if include_local_source and resolve_file_mode(vendor) == 'local':
        roots.add(local_pnm_dir(vendor))
    for root in roots:
        for p in root.glob(f"{prefix}*"):
            try:
                p.unlink()
                deleted += 1
                logger.debug(f"Local housekeeping: deleted {p.name}")
            except Exception as e:
                logger.warning(f"Local housekeeping {p.name}: {e}")

    if deleted:
        logger.info(f"Housekeeping: removed {deleted} file(s) for prefix '{prefix}'")
    return deleted


def list_pnm_files(
    pattern: str,
    *,
    vendor: Optional[str] = None,
    exclude: Optional[List[str]] = None,
) -> List[str]:
    """List capture basenames from the authoritative local or FTP source."""
    safe_pattern = Path(pattern).name
    excluded = {Path(name).name for name in (exclude or [])}
    mode = resolve_file_mode(vendor)
    names: set[str] = set()

    if mode == 'ftp':
        config = get_ftp_config(vendor)
        ftp: ftplib.FTP | None = None
        try:
            ftp = ftplib.FTP()
            ftp.connect(config['host'], config['port'], timeout=15)
            ftp.login(config['user'], config['password'])
            ftp.cwd(config['ftp_dir'])
            names.update(Path(name).name for name in ftp.nlst())
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except Exception:
                    pass
    elif mode == 'local':
        root = local_pnm_dir(vendor)
        if root.is_dir():
            names.update(path.name for path in root.rglob('*') if path.is_file())

    return sorted(
        name for name in names
        if name not in excluded and fnmatch.fnmatch(name, safe_pattern)
    )


def housekeeping_pnm_files(
    *,
    max_age_seconds: int,
    dry_run: bool = True,
    vendor: Optional[str] = None,
    prefixes: tuple[str, ...] = ('utsc_', 'PNMCcapUsSpecAn_'),
) -> dict:
    """Delete only aged PNM files with an explicitly allowed capture prefix."""
    cutoff = time.time() - max(1, int(max_age_seconds))
    records: list[dict] = []

    def _allowed(name: str) -> bool:
        return Path(name).name.startswith(prefixes)

    roots = {Path(get_cache_dir())}
    if resolve_file_mode(vendor) == 'local':
        roots.add(local_pnm_dir(vendor))
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob('*'):
            if not path.is_file() or not _allowed(path.name):
                continue
            stat = path.stat()
            if stat.st_mtime >= cutoff:
                continue
            records.append({'filename': path.name, 'size_bytes': stat.st_size, 'source': 'local'})
            if not dry_run:
                path.unlink(missing_ok=True)

    if resolve_file_mode(vendor) == 'ftp':
        config = get_ftp_config(vendor)
        ftp: ftplib.FTP | None = None
        try:
            ftp = ftplib.FTP()
            ftp.connect(config['host'], config['port'], timeout=15)
            ftp.login(config['user'], config['password'])
            ftp.cwd(config['ftp_dir'])
            for raw_name in ftp.nlst():
                name = Path(raw_name).name
                if not _allowed(name):
                    continue
                try:
                    modified = time.strptime(ftp.sendcmd(f'MDTM {name}').split()[-1], '%Y%m%d%H%M%S')
                    modified_at = time.mktime(modified)
                except Exception:
                    continue
                if modified_at >= cutoff:
                    continue
                try:
                    size = int(ftp.size(name) or 0)
                except Exception:
                    size = 0
                records.append({'filename': name, 'size_bytes': size, 'source': 'ftp'})
                if not dry_run:
                    ftp.delete(name)
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except Exception:
                    pass

    return {
        'success': True,
        'dry_run': dry_run,
        'candidate_count': len(records),
        'deleted_count': 0 if dry_run else len(records),
        'total_size_bytes': sum(item['size_bytes'] for item in records),
        'files': records[:50],
        'truncated': len(records) > 50,
    }
