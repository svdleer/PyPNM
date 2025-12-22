# PyPNM Acronyms And Common Terms

This page collects acronyms and short-hand terms used throughout the PyPNM project,
documentation, and codebase.

## Table Of Contents

- [DOCSIS & Access Network](#docsis--access-network)
- [PNM & Analysis](#pnm--analysis)
- [Protocols & Transport](#protocols--transport)
- [FastAPI, CLI & Tooling](#fastapi-cli--tooling)
- [Configuration & Files](#configuration--files)
- [Miscellaneous](#miscellaneous)

## DOCSIS & Access Network {#docsis--access-network}

| Acronym | Expansion                                      | Notes |
| :------ | :--------------------------------------------- | :---- |
| CM      | Cable Modem                                   | DOCSIS customer premise device. |
| CMTS    | Cable Modem Termination System                | Headend/CCAP platform terminating DOCSIS CMs. |
| DOCSIS  | Data Over Cable Service Interface Specification | CableLabs specification family for broadband over HFC. |
| HFC     | Hybrid Fiber-Coax                              | Physical access network used by DOCSIS. |
| OFDM    | Orthogonal Frequency Division Multiplexing     | DOCSIS 3.1+ downstream multi-carrier modulation. |
| OFDMA   | Orthogonal Frequency Division Multiple Access  | DOCSIS 3.1+ upstream multi-user OFDM. |
| PLC     | Physical Link Channel                         | Robust OFDM channel used for downstream signaling. |
| SC-QAM  | Single-Carrier QAM                            | Legacy DOCSIS downstream channels. |
| RxMER   | Received Modulation Error Ratio               | Per-subcarrier or per-channel metric of downstream quality. |
| FEC     | Forward Error Correction                      | Coding layer providing error detection/correction. |
| NCP     | Next Codeword Pointer                         | DOCSIS PHY metadata related to FEC codeword boundaries. |

## PNM & Analysis {#pnm--analysis}

| Acronym | Expansion                                      | Notes |
| :------ | :--------------------------------------------- | :---- |
| PNM     | Proactive Network Maintenance                  | Overall toolkit focus: predictive plant maintenance. |
| DPD     | Downstream Pre-Distortion                      | Related to linearization and echo cancellation. |
| MTE     | Main Tap Energy                               | Metric derived from pre-equalization taps. |
| TTE     | Total Tap Energy                              | Sum of all tap energies in pre-equalization. |
| NMTER   | Normalized Main Tap To Error Ratio            | Quality metric from upstream pre-EQ coefficients. |
| QAM     | Quadrature Amplitude Modulation               | Constellation format for DOCSIS payloads. |
| SNR     | Signal-to-Noise Ratio                         | Often derived or related to RxMER. |
| CSV     | Comma-Separated Values                        | Plain-text export format for analysis results. |

## Protocols & Transport {#protocols--transport}

| Acronym | Expansion                                      | Notes |
| :------ | :--------------------------------------------- | :---- |
| SNMP    | Simple Network Management Protocol            | Used for DOCSIS MIB access and PNM test control. |
| MIB     | Management Information Base                   | SNMP schema defining objects and tables. |
| TFTP    | Trivial File Transfer Protocol                | Primary method for CM bulk PNM file upload. |
| FTP     | File Transfer Protocol                        | Optional PNM file retrieval method. |
| SCP     | Secure Copy Protocol                          | SSH-based PNM file retrieval method. |
| SFTP    | SSH File Transfer Protocol                    | SSH-based PNM file retrieval method (preferred over SCP in many setups). |
| SSH     | Secure Shell                                  | Underlying protocol for SCP/SFTP and remote login. |
| IPv4    | Internet Protocol version 4                   | 32-bit address family. |
| IPv6    | Internet Protocol version 6                   | 128-bit address family. |

## FastAPI, CLI & Tooling {#fastapi-cli--tooling}

| Term    | Expansion                                      | Notes |
| :------ | :--------------------------------------------- | :---- |
| FastAPI | FastAPI Web Framework                         | Python ASGI framework used for the PyPNM REST API. |
| REST    | Representational State Transfer               | API style / pattern used by PyPNM endpoints. |
| CLI     | Command-Line Interface                        | Python helper scripts and shell commands. |
| JSON    | JavaScript Object Notation                    | Wire-format for API requests and responses. |
| CI      | Continuous Integration                        | GitHub Actions workflows (daily-build, CodeQL, etc.). |
| VENV    | Virtual Environment                           | Local Python environment (for example `.env`). |

## Configuration & Files {#configuration--files}

| Term          | Expansion                                | Notes |
| :------------ | :--------------------------------------- | :---- |
| system.json   | PyPNM System Configuration File         | Global configuration for SNMP, paths, PNM file retrieval, logging. |
| PNM file      | Proactive Network Maintenance Capture   | Binary file generated by the cable modem for a specific measurement. |
| demo/         | Demo Data And Settings Tree             | Pre-captured PNM files and demo system configuration. |
| .data/        | Default Data Directory                  | Location where PNM files and analysis outputs are stored. |
| pnm_dir       | PNM Save Directory                      | Root directory where PyPNM expects PNM input files. |

## Miscellaneous {#miscellaneous}

| Term      | Expansion                                   | Notes |
| :-------- | :------------------------------------------ | :---- |
| MAC       | Media Access Control Address                | Example in docs: `aa:bb:cc:dd:ee:ff`. |
| IP        | Internet Protocol Address                   | Example in docs: `192.168.0.100`. |
| HW_REV    | Hardware Revision                          | Part of example `system_description` JSON. |
| SW_REV    | Software Revision                          | Part of example `system_description` JSON. |
| MODEL     | Device Model Identifier                    | Example: `LCPET-3` in system description. |
