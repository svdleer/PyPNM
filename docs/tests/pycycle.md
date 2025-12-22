# PyCycle Import-Cycle Checker - User Guide

Static Detection Of Circular Imports Across The PyPNM Codebase.

## 1. What PyCycle Does

PyCycle walks your Python source tree, builds an import graph, and reports **strongly connected components**
(SCCs) - i.e., circular import cycles. This is exactly the class of problems that tend to show up as:

- `ImportError: cannot import name ... from partially initialized module ...`
- brittle, order-dependent imports
- “mysterious” runtime behaviour when modules re-import each other

For PyPNM, PyCycle helps keep complex packages like:

- `pypnm.pnm.process.*`
- `pypnm.api.routes.*`
- `pypnm.lib.*`

free of cycles that would otherwise only show up when you run specific tools or endpoints.

## 2. Installation And Prerequisites

PyCycle is already included in the PyPNM development extras:

```bash
cd ~/Projects/PyPNM
pip install -e '.[dev]'
```

This will install `pycycle` into your current virtual environment (along with `ruff`, `pytest`, etc.).

If you ever want to install it directly:

```bash
pip install pycycle
```

## 3. How PyPNM Uses PyCycle

The **recommended** way to run PyCycle in this project is via the consolidated QA helper:
`pypnm-software-qa-checker`.

From the project root:

```bash
pypnm-software-qa-checker
```

The checker will execute (among other steps):

```bash
pycycle --here
```

`--here` tells PyCycle to scan the current directory recursively for Python packages and modules, building an
import graph for the entire project tree at once.

If you want to run PyCycle manually, simply do:

```bash
cd ~/Projects/PyPNM
pycycle --here
```

## 4. Basic CLI Usage

### 4.1 Scan The Whole Project

From the PyPNM root (where `pyproject.toml` lives):

```bash
pycycle --here
```

PyCycle will search for Python modules under the current directory, build an import graph, and print any
detected cycles. A simple example of the text output might look like:

```text
Import cycle detected:
  pypnm.pnm.process.CmDsOfdmChanEstimateCoef
  -> pypnm.pnm.process.pnm_parameter
  -> pypnm.pnm.process.CmDsOfdmChanEstimateCoef
```

Each block represents one cycle; the arrows show the chain of imports that leads back to the starting module.

### 4.2 Focus On A Sub-Package

If you want to limit analysis to a single subtree (for faster runs or targeted refactors), point PyCycle at a
specific directory:

```bash
pycycle src/pypnm/pnm/process
```

or a single file/module:

```bash
pycycle src/pypnm/pnm/parser/CmDsOfdmChanEstimateCoef.py
```

PyCycle will still compute import edges reachable from that entry point, but the surface area is smaller than
`--here` on the entire repo.

## 5. Interpreting Results

When PyCycle finds cycles, it prints each one as a path that eventually loops back to the origin. Typical
patterns you may see in PyPNM include:

- **Data/Model ↔ Service/Process** cycles  
  e.g. a process class imports a PNM parser, and that parser imports the process back.
- **Sibling process modules importing each other**  
  e.g. `CmDsOfdmChanEstimateCoef` ↔ `fetch_pnm_process`.
- **Shared utility modules that creep into everything**  
  e.g. a “god” module that is imported everywhere and begins importing domain modules back.

### 5.1 Exit Codes

PyCycle is CI-friendly:

- Exit code `0` - no import cycles detected.
- Non-zero exit code - at least one cycle was found, or there was an error.

The `pypnm-software-qa-checker` script treats a non-zero exit as a failure and surfaces that in its overall
exit code.

## 6. Recommended Workflow For PyPNM

### 6.1 Before Pushing A Branch

Use the QA helper to run everything at once:

```bash
pypnm-software-qa-checker
```

If a PyCycle failure appears, scroll to the `pycycle` section and inspect the printed cycles. Fix them (see
Section 7) and rerun the checker.

### 6.2 During Refactors Of “Process” And “Analysis” Layers

Whenever you make structural changes to:

- `src/pypnm/pnm/process`
- `src/pypnm/api/routes/*/analysis`
- shared model modules under `src/pypnm/pnm/lib`

run a targeted check from the root:

```bash
pycycle src/pypnm/pnm/process
```

This is much faster than scanning the entire repo, but still catches problematic module relationships in the
sensitive parts of the codebase.

## 7. Strategies For Breaking Cycles

PyCycle tells you **where** cycles exist; you still need to decide **how** to break them. Common refactors
that work well in PyPNM:

1. **Extract shared types into a neutral module**  
   If two modules both need a Pydantic model or enum and currently import each other, move the shared type
   into a new, lower-level module (e.g. `pypnm.pnm.process.model.shared_types`) and have both import that.

2. **Use local (function-level) imports for heavy dependencies**  
   For rarely used paths (e.g. analysis helpers that only run in one endpoint), move some imports inside the
   function or method that needs them. This breaks the top-level module dependency graph while keeping the
   behaviour unchanged.

3. **Invert dependencies via callbacks or interfaces**  
   Instead of A importing B and calling B.foo(), define an abstract interface or a simple callback used by A,
   and let B depend on that interface rather than A. This is especially helpful when routes depend on
   lower-level processing, but the processing should not depend on the routes.

4. **Split monolithic “god” modules**  
   If PyCycle repeatedly shows the same large module at the center of many cycles, try splitting it into
   feature-focused modules (e.g. separate parsing, models, and services) so that dependencies become a
   DAG instead of a mesh.

5. **Keep SNMP/IO layers below analysis and routing layers**  
   In PyPNM’s design, it helps to keep the data acquisition (SNMP, TFTP, parsing) in leaf modules and have
   the higher layers (analysis, routers, CLI tools) import them - not the other way around.

## 8. CI Integration

PyCycle is already wired into the `pypnm-software-qa-checker` console script and can therefore be used in
GitHub Actions or any other CI pipeline.

### 8.1 Full QA With Cycle Check

```yaml
- name: PyPNM software QA (with cycles)
  run: pypnm-software-qa-checker
```

### 8.2 Optional: Lint + Tests Only

If you want a faster pipeline that skips cycle detection:

```yaml
- name: PyPNM software QA (no cycle)
  run: pypnm-software-qa-checker --no-cycle
```

You can also call PyCycle directly in CI if you need a custom target:

```yaml
- name: PyCycle import cycle check (process layer only)
  run: pycycle src/pypnm/pnm/process
```

## 9. Summary

- PyCycle finds **circular import graphs** that otherwise cause subtle runtime bugs.
- It is installed as part of PyPNM’s `.[dev]` extras and integrated into the
  `pypnm-software-qa-checker` script.
- Use `pycycle --here` for a whole-repo sweep, or point it at specific subtrees for faster, focused runs.
- When cycles appear, rely on extraction, local imports, and dependency inversion to restore a clean,
  acyclic module graph.
