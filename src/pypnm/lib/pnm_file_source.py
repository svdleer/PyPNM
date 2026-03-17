"""
PNM file source abstraction for PyPNM API.

Mirrors the PyPNMGui pnm_file_source but runs inside the API container.

Environment variables (same as GUI):
    PNM_FILE_SOURCE     "local" (default) or "ftp"
    FTP_SERVER_IP       FTP server hostname/IP  (falls back to TFTP_IPV4)
    FTP_PORT            FTP port (default: 21)
    FTP_USER            FTP username             (default: ftpaccess)
    FTP_PASSWORD        FTP password             (default: ftpaccessftp)
    FTP_TFTPBOOT_DIR    Remote directory on FTP server where CMTS files land
                        (default: /var/lib/tftpboot)
    TFTPBOOT_DIR        Local path used in 'local' mode
                        (default: /var/lib/tftpboot)
    PNM_CACHE_DIR       Local cache dir used in 'ftp' mode
                        (default: /app/data/pnm_cache)
"""
from __future__ import annotations

import ftplib
import logging
import os
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def _env(key: str, default: str = '') -> str:
    return os.environ.get(key, default)


def is_ftp_mode() -> bool:
    return _env('PNM_FILE_SOURCE', 'local').lower() == 'ftp'


def get_ftp_config() -> dict:
    return {
        'host':     _env('FTP_SERVER_IP') or _env('TFTP_IPV4', '127.0.0.1'),
        'port':     int(_env('FTP_PORT', '21')),
        'user':     _env('FTP_USER', 'ftpaccess'),
        'password': _env('FTP_PASSWORD', 'ftpaccessftp'),
        'ftp_dir':  _env('FTP_TFTPBOOT_DIR', '/var/lib/tftpboot'),
    }


def get_cache_dir() -> str:
    d = _env('PNM_CACHE_DIR', '/app/data/pnm_cache')
    os.makedirs(d, exist_ok=True)
    return d


def local_pnm_dir() -> Path:
    """
    Return the local filesystem Path PyPNM should search for capture files.

    - local mode: TFTPBOOT_DIR env (default /var/lib/tftpboot)
    - ftp mode:   local cache dir where files are pre-fetched
    """
    if is_ftp_mode():
        return Path(get_cache_dir())
    return Path(_env('TFTPBOOT_DIR', '/var/lib/tftpboot'))


def fetch_pnm_files(filename_prefix: str, *, ftp_cfg: dict | None = None) -> List[str]:
    """
    Download every file on the FTP server whose basename starts with
    *filename_prefix* into the local cache directory.

    Returns the list of local file paths downloaded, or [] on error / not ftp mode.
    """
    if not is_ftp_mode():
        return []

    if ftp_cfg is None:
        ftp_cfg = get_ftp_config()

    prefix = Path(filename_prefix).name
    cache_dir = get_cache_dir()
    downloaded: List[str] = []

    try:
        ftp = ftplib.FTP()
        ftp.connect(ftp_cfg['host'], ftp_cfg['port'], timeout=15)
        ftp.login(ftp_cfg['user'], ftp_cfg['password'])

        ftp_dir = ftp_cfg['ftp_dir']
        try:
            ftp.cwd(ftp_dir)
        except ftplib.error_perm as e:
            logger.warning(f"FTP: could not cd to {ftp_dir}: {e}")
            ftp.quit()
            return []

        try:
            all_files = ftp.nlst()
        except ftplib.error_perm:
            all_files = []

        matching = [f for f in all_files if Path(f).name.startswith(prefix)]

        if not matching:
            logger.debug(f"FTP: no files matching '{prefix}*' in {ftp_dir}")

        for remote_file in matching:
            basename = Path(remote_file).name
            local_path = os.path.join(cache_dir, basename)
            try:
                with open(local_path, 'wb') as fp:
                    ftp.retrbinary(f'RETR {basename}', fp.write)
                downloaded.append(local_path)
                logger.debug(f"FTP: fetched {basename} -> {local_path}")
            except Exception as e:
                logger.warning(f"FTP: failed to download {basename}: {e}")

        ftp.quit()
        logger.info(f"FTP fetch: {len(downloaded)} file(s) for prefix '{prefix}'")

    except Exception as e:
        logger.warning(f"FTP fetch error (host={ftp_cfg.get('host')}): {e}")

    return downloaded


def delete_pnm_files(filename_prefix: str, *, ftp_cfg: dict | None = None) -> int:
    """
    Delete files matching *filename_prefix* from FTP server and local cache.
    Returns number of deleted files.
    """
    if ftp_cfg is None:
        ftp_cfg = get_ftp_config()

    prefix = Path(filename_prefix).name
    deleted = 0

    if is_ftp_mode():
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

    # Clean local cache
    for p in Path(get_cache_dir()).glob(f"{prefix}*"):
        try:
            p.unlink()
            deleted += 1
            logger.debug(f"Cache housekeeping: deleted {p.name}")
        except Exception as e:
            logger.warning(f"Cache housekeeping {p.name}: {e}")

    if deleted:
        logger.info(f"Housekeeping: removed {deleted} file(s) for prefix '{prefix}'")
    return deleted
