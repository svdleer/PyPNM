# Compiling MIBs For SNMP Operations

Reference For MIB Precompilation And Symbolic OID Usage.

| Guide                                                         | Description                                                                     |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| [PyPNM MIB Compiler](../../../tools/pypnm-mib-compiler.md)    | End-to-end workflow and rationale for generating `COMPILED_OIDS`.               |
| [MIB Compile Tool](https://github.com/svdleer/PyPNM/blob/main/tools/snmp/update-snmp-oid-dict.py) | Command-line script that runs `snmptranslate -Tz` and emits `compiled_oids.py`. |
| [Compiled MIBs](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/snmp/compiled_oids.py)  | Generated dictionary consumed at runtime.                                       |

> This Guide intentionally defers to the links above to keep MIB compilation docs in one place.
