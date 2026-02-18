#!/usr/bin/env python3
"""
Generate matplotlib visualization for CMTS US OFDMA RxMER data.
Produces a PNG file showing RxMER per subcarrier with statistics.
"""
import sys
import struct
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


def parse_usrxmer_file(filepath: str) -> dict:
    """Parse CMTS US OFDMA RxMER file and return parsed data."""
    data = open(filepath, "rb").read()
    
    offset = 0
    
    # File type + version: 6 bytes
    file_type = data[offset:offset+4]
    offset += 4
    version = data[offset:offset+2]
    offset += 2
    
    # Capture time: 4 bytes
    capture_time = struct.unpack("!I", data[offset:offset+4])[0]
    offset += 4
    
    # IfIndex: 4 bytes
    ifindex = struct.unpack("!I", data[offset:offset+4])[0]
    offset += 4
    
    # CCAP ID: 256 bytes
    ccap_id = data[offset:offset+256].split(b"\x00")[0].decode("ascii", errors="ignore")
    offset += 256
    
    # Extra fields: 7 bytes
    offset += 7
    
    # CM MAC: 6 bytes
    mac_bytes = data[offset:offset+6]
    mac_str = ":".join("%02x" % b for b in mac_bytes)
    offset += 6
    
    # Num averages: 2 bytes
    num_averages = struct.unpack("!H", data[offset:offset+2])[0]
    offset += 2
    
    # PreEq: 1 byte
    preeq = data[offset]
    offset += 1
    
    # Zero frequency: 4 bytes
    zero_freq = struct.unpack("!I", data[offset:offset+4])[0]
    offset += 4
    
    # FirstActiveSubcarrier: 2 bytes
    first_active = struct.unpack("!H", data[offset:offset+2])[0]
    offset += 2
    
    # Spacing: 1 byte (kHz)
    spacing_khz = data[offset]
    offset += 1
    
    # Data length: 4 bytes
    data_len = struct.unpack("!I", data[offset:offset+4])[0]
    offset += 4
    
    # RxMER data
    rxmer_bytes = data[offset:offset+data_len]
    rxmer_db = [b/4.0 for b in rxmer_bytes]
    
    # Calculate frequencies
    frequencies_mhz = []
    for i in range(len(rxmer_db)):
        freq_hz = zero_freq + (first_active + i) * spacing_khz * 1000
        frequencies_mhz.append(freq_hz / 1e6)
    
    return {
        "capture_time": capture_time,
        "ifindex": ifindex,
        "ccap_id": ccap_id,
        "cm_mac": mac_str,
        "num_averages": num_averages,
        "preeq": preeq,
        "zero_freq_mhz": zero_freq / 1e6,
        "first_active": first_active,
        "spacing_khz": spacing_khz,
        "data_length": data_len,
        "frequencies_mhz": frequencies_mhz,
        "rxmer_db": rxmer_db,
    }


def plot_usrxmer(parsed: dict, output_path: Optional[str] = None) -> str:
    """Generate RxMER plot and return path to PNG file."""
    
    freqs = np.array(parsed["frequencies_mhz"])
    rxmer = np.array(parsed["rxmer_db"])
    
    # Filter out excluded subcarriers (0xff = 63.75)
    valid_mask = rxmer < 63.5
    valid_rxmer = rxmer[valid_mask]
    valid_freqs = freqs[valid_mask]
    
    # Calculate statistics
    if len(valid_rxmer) > 0:
        mean_rxmer = np.mean(valid_rxmer)
        min_rxmer = np.min(valid_rxmer)
        max_rxmer = np.max(valid_rxmer)
        std_rxmer = np.std(valid_rxmer)
    else:
        mean_rxmer = min_rxmer = max_rxmer = std_rxmer = 0
    
    # Create figure
    fig, ax = plt.subplots(figsize=(14, 6))
    
    # Color coding based on RxMER thresholds (upstream)
    # Excellent: >= 40 dB (green)
    # Good: 35-40 dB (yellow)
    # Marginal: 30-35 dB (orange)
    # Poor: < 30 dB (red)
    colors = []
    for mer in rxmer:
        if mer >= 63.5:  # Excluded
            colors.append('#cccccc')
        elif mer >= 40:
            colors.append('#2ecc71')  # Green - Excellent
        elif mer >= 35:
            colors.append('#f1c40f')  # Yellow - Good
        elif mer >= 30:
            colors.append('#e67e22')  # Orange - Marginal
        else:
            colors.append('#e74c3c')  # Red - Poor
    
    # Plot bars
    bar_width = (freqs[-1] - freqs[0]) / len(freqs) * 0.8
    bars = ax.bar(freqs, rxmer, width=bar_width, color=colors, edgecolor='none', alpha=0.9)
    
    # Add mean line
    ax.axhline(y=mean_rxmer, color='blue', linestyle='--', linewidth=2, label=f'Mean: {mean_rxmer:.1f} dB')
    
    # Add threshold lines
    ax.axhline(y=40, color='#2ecc71', linestyle=':', linewidth=1, alpha=0.7)
    ax.axhline(y=35, color='#f1c40f', linestyle=':', linewidth=1, alpha=0.7)
    ax.axhline(y=30, color='#e74c3c', linestyle=':', linewidth=1, alpha=0.7)
    
    # Labels and title
    ax.set_xlabel('Frequency (MHz)', fontsize=12)
    ax.set_ylabel('RxMER (dB)', fontsize=12)
    ax.set_title(f'US OFDMA RxMER - CM: {parsed["cm_mac"].upper()}', fontsize=14, fontweight='bold')
    
    # Set axis limits
    ax.set_xlim(freqs[0] - 0.5, freqs[-1] + 0.5)
    ax.set_ylim(0, 55)
    
    # Add grid
    ax.grid(True, axis='y', alpha=0.3)
    ax.set_axisbelow(True)
    
    # Legend with color patches
    excellent_patch = mpatches.Patch(color='#2ecc71', label='Excellent (≥40 dB)')
    good_patch = mpatches.Patch(color='#f1c40f', label='Good (35-40 dB)')
    marginal_patch = mpatches.Patch(color='#e67e22', label='Marginal (30-35 dB)')
    poor_patch = mpatches.Patch(color='#e74c3c', label='Poor (<30 dB)')
    excluded_patch = mpatches.Patch(color='#cccccc', label='Excluded')
    
    ax.legend(handles=[excellent_patch, good_patch, marginal_patch, poor_patch, excluded_patch],
              loc='upper right', fontsize=9)
    
    # Stats text box
    stats_text = (
        f"CCAP: {parsed['ccap_id']}\n"
        f"ifIndex: {parsed['ifindex']}\n"
        f"Spacing: {parsed['spacing_khz']} kHz\n"
        f"Subcarriers: {len(valid_rxmer)}/{len(rxmer)}\n"
        f"BW: {len(valid_rxmer) * parsed['spacing_khz'] / 1000:.1f} MHz\n"
        f"─────────────\n"
        f"Min: {min_rxmer:.1f} dB\n"
        f"Mean: {mean_rxmer:.1f} dB\n"
        f"Max: {max_rxmer:.1f} dB\n"
        f"Std: {std_rxmer:.2f} dB"
    )
    
    props = dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor='gray')
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=9,
            verticalalignment='top', fontfamily='monospace', bbox=props)
    
    plt.tight_layout()
    
    # Save to file
    if output_path is None:
        output_path = f"/tmp/usrxmer_{parsed['cm_mac'].replace(':', '')}.png"
    
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    
    return output_path


def main():
    if len(sys.argv) < 2:
        filepath = "/var/lib/tftpboot/us_rxmer_2026-01-28_12.13.25.870"
    else:
        filepath = sys.argv[1]
    
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    print(f"Parsing: {filepath}")
    parsed = parse_usrxmer_file(filepath)
    
    print(f"CM MAC: {parsed['cm_mac']}")
    print(f"CCAP ID: {parsed['ccap_id']}")
    print(f"Subcarriers: {parsed['data_length']}")
    print(f"Spacing: {parsed['spacing_khz']} kHz")
    
    output = plot_usrxmer(parsed, output_path)
    print(f"Saved plot to: {output}")
    
    return output


if __name__ == "__main__":
    main()
