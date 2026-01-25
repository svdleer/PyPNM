# Spectrum Analyzer Request Schema Plan

## Goal
Remove the unused channel field from the `get_capture` request schema without changing shared BaseModels.

## Scope
Target endpoint:
- `async def get_capture(request: SingleCaptureSpectrumAnalyzer) -> SnmpResponse | PnmAnalysisResponse | FileResponse`

## Proposed Approach
1) Add a new endpoint-specific request model in
   `src/pypnm/api/routes/docs/pnm/spectrumAnalyzer/schemas.py` that mirrors the
   current fields of `SingleCaptureSpectrumAnalyzer` but intentionally omits the
   channel field.
2) Update the `get_capture` endpoint signature in
   `src/pypnm/api/routes/docs/pnm/spectrumAnalyzer/router.py` to use the new
   request model.
3) Leave all shared/common BaseModels unchanged to avoid impacting other routes.
4) Update FastAPI docs/examples to remove the channel field from the request
   payload for this endpoint.

### Proposed Model Shape (Example)

```python
class SingleCaptureSpectrumAnalyzerRequest(BaseModel):
    cable_modem: CableModemPnmConfig = Field(description="Cable modem configuration")
    analysis: ExtendCommonSingleCaptureAnalysisType = Field(description="Analysis type")
    capture_parameters: SpecAnCapturePara = Field(description="Spectrum capture parameters")
```

### Router Signature Update (Example)

```python
async def get_capture(
    request: SingleCaptureSpectrumAnalyzerRequest,
) -> SnmpResponse | PnmAnalysisResponse | FileResponse:
    ...
```

## Why This Avoids Side Effects
- The new model is endpoint-specific, so other endpoints continue to use the
  existing BaseModels unchanged.
- The router change only affects the OpenAPI schema and validation for this
  endpoint; other routes are untouched.

## Files To Change (If Approved)
- `src/pypnm/api/routes/docs/pnm/spectrumAnalyzer/schemas.py`
- `src/pypnm/api/routes/docs/pnm/spectrumAnalyzer/router.py`
- `docs/api/fast-api/single/spectrum-analyzer/spectrum-analyzer.md`

## Questions
- Confirm the exact channel field name to omit in `SingleCaptureSpectrumAnalyzer`.
- Confirm whether the change should also adjust any client examples or tests
  beyond the FastAPI docs.
