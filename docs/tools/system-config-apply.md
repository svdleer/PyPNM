# System config apply (non-interactive)

Use this helper to apply JSON updates to `system.json` without interactive prompts.

## Examples

```bash
./tools/system_config/apply_config.py --input /path/to/patch.json
```

```bash
cat patch.json | ./tools/system_config/apply_config.py --stdin
```

Replace the config entirely:

```bash
./tools/system_config/apply_config.py --input /path/to/system.json --replace
```
