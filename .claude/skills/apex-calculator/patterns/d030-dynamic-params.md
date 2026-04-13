# D030 Dynamic Configurable Parameters Pattern

Every constructor parameter must propagate dynamically. Never hardcode downstream.

## Wrong (OFI PR #113 original landmine)

```python
def __init__(self, windows: tuple[int, ...] = (10, 50, 100)) -> None:
    self._windows = windows

def output_columns(self) -> list[str]:
    return ["ofi_10", "ofi_50", "ofi_100", "ofi_signal"]  # ← hardcoded!
```

If user passes `windows=(5, 20, 60)`, output columns are mislabeled silently.

## Right (PR #113 hotfix)

```python
def __init__(self, windows: tuple[int, ...] = (10, 50, 100), ...) -> None:
    # Validate first
    if len(windows) == 0:
        raise ValueError("windows must contain at least one value")
    if any(w < 1 for w in windows):
        raise ValueError("all window sizes must be >= 1")
    self._windows = windows

def output_columns(self) -> list[str]:
    return [f"ofi_{w}" for w in self._windows] + ["ofi_signal"]
```

## Constructor validation rules (D030)

Validate all invariants in `__init__` with explicit ValueError. Common patterns:

- `param >= min_value` — raise with message including actual value
- `len(list_a) == len(list_b)` — raise with both lengths
- `sum(weights) == 1.0` — allow `abs(sum - 1.0) < 1e-9` tolerance, raise with actual sum
- `threshold_low < threshold_high` — raise with both
- `param > 0` or `param != 0` — raise for non-positive or zero values

## Test template (one per validated invariant)

```python
def test_<param>_<violation>_raises(self) -> None:
    with pytest.raises(ValueError, match="<param>"):
        <Calc>(
            <param>=<invalid_value>,
            # other params valid
        )
```
