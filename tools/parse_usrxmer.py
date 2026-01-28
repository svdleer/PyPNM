#!/usr/bin/env python3
"""
Parse CMTS US OFDMA RxMER file per Table 7-108 spec.

File Format (Table 7-108):
- File type (504E4D69) - 4 bytes
- Capture Time - 4 bytes
- IfIndex - 4 bytes
- Unique CCAP ID - 256 bytes
- CM MAC Address - 6 bytes
- Number of averages - 2 bytes
- PreEq On or Off - 1 byte
- Subcarrier zero center frequency - 4 bytes
- FirstActiveSubcarrierIndex - 2 bytes
- Subcarrier Spacing in kHz - 1 byte
- Length in bytes of RxMER data - 4 bytes
- Subcarrier RxMER data - variable

Note: Actual files have 2 version bytes after file type (standard PNM header)
      and vendor-specific extra fields after CCAP ID.
"""
import struct
import sys

def parse_file(filepath):
    data = open(filepath, "rb").read()
    print("File size:", len(data), "bytes")

    offset = 0

    # File type: 4 bytes (PNNi or PNMi)
    file_type = data[offset:offset+4]
    print("File type:", file_type)
    offset += 4

    # Version bytes (not in spec but present): 2 bytes
    version = data[offset:offset+2]
    print("Version:", version.hex())
    offset += 2

    # Capture time: 4 bytes
    capture_time = struct.unpack("!I", data[offset:offset+4])[0]
    print("Capture time:", capture_time)
    offset += 4

    # IfIndex: 4 bytes
    ifindex = struct.unpack("!I", data[offset:offset+4])[0]
    print("IfIndex:", ifindex)
    offset += 4

    # CCAP ID: 256 bytes
    ccap_id = data[offset:offset+256].split(b"\x00")[0].decode("ascii", errors="ignore")
    print("CCAP ID:", repr(ccap_id))
    offset += 256

    # --- Vendor-specific extra fields (not in simple spec) ---
    extra_ifindex = struct.unpack("!I", data[offset:offset+4])[0]
    print("Extra ifIndex (MD-US-SG?):", extra_ifindex)
    offset += 4

    extra_field = struct.unpack("!H", data[offset:offset+2])[0]
    print("Extra field:", extra_field)
    offset += 2

    reserved1 = data[offset]
    print("Reserved1:", reserved1)
    offset += 1

    # --- Standard spec fields ---
    # CM MAC: 6 bytes
    mac_bytes = data[offset:offset+6]
    mac_str = ":".join("%02x" % b for b in mac_bytes)
    print("CM MAC:", mac_str)
    offset += 6

    # Number of averages: 2 bytes
    num_averages = struct.unpack("!H", data[offset:offset+2])[0]
    print("Num averages:", num_averages)
    offset += 2

    # PreEq On/Off: 1 byte
    preeq = data[offset]
    print("PreEq:", "On" if preeq else "Off", "(", preeq, ")")
    offset += 1

    # Zero frequency: 4 bytes
    zero_freq = struct.unpack("!I", data[offset:offset+4])[0]
    print("Zero frequency:", zero_freq, "Hz (", zero_freq/1e6, "MHz)")
    offset += 4

    # FirstActiveSubcarrierIndex: 2 bytes
    first_active = struct.unpack("!H", data[offset:offset+2])[0]
    print("FirstActiveSubcarrierIndex:", first_active)
    offset += 2

    # Spacing: 1 byte (kHz)
    spacing = data[offset]
    print("Spacing:", spacing, "kHz")
    offset += 1

    # Data length: 4 bytes
    data_len = struct.unpack("!I", data[offset:offset+4])[0]
    print("Data length:", data_len, "bytes")
    offset += 4

    # RxMER data
    print("\n=== RxMER Data ===")
    print("Data starts at offset:", offset)
    print("Remaining bytes:", len(data) - offset)

    rxmer_data = data[offset:offset+data_len]
    rxmer_db = [b/4.0 for b in rxmer_data]

    # Filter out excluded subcarriers (0xff = 63.75)
    valid = [v for v in rxmer_db if v < 63.5]
    print("Total samples:", len(rxmer_db))
    print("Valid samples:", len(valid))

    if valid:
        print("Min:", round(min(valid), 2), "dB")
        print("Avg:", round(sum(valid)/len(valid), 2), "dB")
        print("Max:", round(max(valid), 2), "dB")

    print("First 30 values (dB):", [round(v, 2) for v in rxmer_db[:30]])

    # Calculate bandwidth
    bw_mhz = len(valid) * spacing / 1000
    print("Occupied bandwidth:", round(bw_mhz, 2), "MHz")

if __name__ == "__main__":
    filepath = sys.argv[1] if len(sys.argv) > 1 else "/var/lib/tftpboot/us_rxmer_2026-01-28_12.13.25.870"
    parse_file(filepath)
