# Phase 1: Base Contracts & Data Structures

**Goal**: Define the new enums, dataclasses, and abstract methods that the entire MTF system builds on. Zero runtime behavior change — this is pure contract definition.

**Risk**: Low — additive only, no existing code is modified destructively.

---

## Files Changed

| Action | File | What |
|--------|------|------|
| MODIFY | `backend/app/core/base_strategy.py` | Add enums, dataclasses, new abstract methods |
| MODIFY | `backend/app/models/db.py` | Add columns to `Strategy` and `BacktestRun` |

---

## Step 1.1 — Add `ExecutionMode` Enum

**File**: `backend/app/core/base_strategy.py` (top of file, after existing imports)

```python
from enum import Enum

class ExecutionMode(Enum):
    ON_CLOSE = "ON_CLOSE"    # Group A: fire only on LTF candle close
    ON_TOUCH = "ON_TOUCH"    # Group B: fire on price touch (intrabar)
    HYBRID = "HYBRID"        # Group C: HTF zone + LTF close confirmation
```

**Verify**: Import `ExecutionMode` in a Python shell — no errors.

---

## Step 1.2 — Add `ActiveZone` Dataclass

**File**: `backend/app/core/base_strategy.py`

```python
@dataclass
class ActiveZone:
    """Cached zone from HTF context analysis. Used by ZoneManager."""
    zone_type: str          # "order_block", "fvg", "fib_level", "sr", "liquidity_pool"
    direction: str          # "LONG", "SHORT", or "BOTH"
    top: float              # upper boundary
    bottom: float           # lower boundary
    midpoint: float = 0.0   # computed center; overwritten in __post_init__
    metadata: dict = field(default_factory=dict)  # strategy-specific data

    def __post_init__(self):
        if self.midpoint == 0.0:
            self.midpoint = (self.top + self.bottom) / 2

    def contains_price(self, price: float) -> bool:
        """Check if price is within this zone's boundaries."""
        return self.bottom <= price <= self.top

    def distance_to(self, price: float) -> float:
        """Absolute distance from price to nearest zone edge."""
        if price < self.bottom:
            return self.bottom - price
        elif price > self.top:
            return price - self.top
        return 0.0  # inside zone
```

---

## Step 1.3 — Add `ContextState` Dataclass

**File**: `backend/app/core/base_strategy.py`

```python
@dataclass
class ContextState:
    """HTF context computed by update_context(), cached between HTF candle closes."""
    regime: str = "NEUTRAL"                        # "BULLISH", "BEARISH", "NEUTRAL"
    active_zones: list = field(default_factory=list)  # list[ActiveZone]
    indicators_snapshot: dict = field(default_factory=dict)  # arbitrary HTF indicator values
    last_updated: Optional[datetime] = None
    htf_candle_count: int = 0

    def clear(self):
        """Reset state for fresh computation."""
        self.regime = "NEUTRAL"
        self.active_zones = []
        self.indicators_snapshot = {}
        self.last_updated = None
        self.htf_candle_count = 0
```

---

## Step 1.4 — Extend `BaseStrategy` Class

**File**: `backend/app/core/base_strategy.py`

Add new class attributes and methods to the existing `BaseStrategy`:

```python
class BaseStrategy(ABC):
    # --- EXISTING class attrs (unchanged) ---
    name: str = "Unnamed Strategy"
    description: str = ""
    timeframes: list = []
    version: str = "1.0"
    min_confidence: float = 0.5

    # --- NEW class attrs ---
    execution_mode: ExecutionMode = ExecutionMode.ON_CLOSE  # default: legacy
    context_tf: str = ""    # e.g. "4h" — HTF for context computation
    execution_tf: str = ""  # e.g. "15m" — LTF for trigger evaluation

    def __init__(self):
        self._context_state = ContextState()

    @property
    def context(self) -> ContextState:
        """Access the cached HTF context state."""
        return self._context_state

    # --- NEW methods (default no-ops for backward compat) ---

    def update_context(
        self,
        symbol: str,
        htf_candles: list,  # list[Candle]
        htf_indicators: 'Indicators',
        sr_zones: list[dict],
    ) -> None:
        """
        Called when a context_tf candle closes.
        Override to update self._context_state with regime, active zones, etc.
        Default: no-op (legacy strategies use scan() directly).
        """
        pass

    def evaluate_trigger(
        self,
        symbol: str,
        timeframe: str,
        ltf_candles: list,  # list[Candle]
        ltf_indicators: Optional['Indicators'],
        current_price: float,
    ) -> Optional['SetupSignal']:
        """
        Called on the execution stream (tick or LTF candle close).
        Override to check current price / LTF candle against cached context.
        Default: returns None (legacy strategies use scan()).
        """
        return None

    def has_mtf_support(self) -> bool:
        """True if this strategy has been migrated to the MTF system."""
        return bool(self.context_tf and self.execution_tf)

    # --- EXISTING abstract method (UNCHANGED) ---
    @abstractmethod
    def scan(self, symbol, timeframe, candles, indicators, sr_zones,
             htf_candles=None) -> Optional['SetupSignal']:
        ...

    # ... rest of existing methods unchanged ...
```

> [!IMPORTANT]
> The `__init__` is new. All 13 existing strategy subclasses do NOT define `__init__`, so they'll inherit this one cleanly. If any strategy has a custom `__init__`, it must call `super().__init__()`.

---

## Step 1.5 — Extend `SetupSignal` with MTF Metadata

**File**: `backend/app/core/base_strategy.py`

Add 4 new optional fields to the existing `SetupSignal` dataclass:

```python
@dataclass
class SetupSignal:
    # ... existing fields (unchanged) ...
    strategy_name: str
    symbol: str
    timeframe: str
    direction: str
    confidence: float
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    notes: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # --- NEW MTF metadata ---
    context_tf: str = ""            # which HTF provided the context
    execution_tf: str = ""          # which LTF triggered the entry
    htf_context_summary: str = ""   # human-readable HTF state for LLM
    ltf_trigger_summary: str = ""   # human-readable LTF trigger for LLM
```

Also add the new fields to `to_dict()`:

```python
def to_dict(self) -> dict:
    d = {
        # ... existing fields ...
    }
    # NEW
    if self.context_tf:
        d['context_tf'] = self.context_tf
    if self.execution_tf:
        d['execution_tf'] = self.execution_tf
    if self.htf_context_summary:
        d['htf_context_summary'] = self.htf_context_summary
    if self.ltf_trigger_summary:
        d['ltf_trigger_summary'] = self.ltf_trigger_summary
    return d
```

---

## Step 1.6 — DB Schema Changes

**File**: `backend/app/models/db.py`

**Strategy model** — add 2 columns:

```python
class Strategy(db.Model):
    # ... existing columns ...
    execution_mode = db.Column(db.String(20), default='ON_CLOSE')  # NEW
    context_tf = db.Column(db.String(10), nullable=True)           # NEW
```

Update `to_dict()` to include the new fields.

**BacktestRun model** — add 1 column:

```python
class BacktestRun(db.Model):
    # ... existing columns ...
    engine_version = db.Column(db.String(10), default='1.0')       # NEW
```

Update `to_dict()` to include `engine_version`.

---

## Verification Checklist

- [ ] `from app.core.base_strategy import ExecutionMode, ActiveZone, ContextState` works
- [ ] Existing strategies instantiate without errors (inherited `__init__` works)
- [ ] `strategy.has_mtf_support()` returns `False` for all existing strategies
- [ ] `strategy.context.regime` returns `"NEUTRAL"` for all existing strategies
- [ ] `strategy.scan(...)` still works exactly as before
- [ ] `SetupSignal.to_dict()` returns existing fields (no MTF fields when empty)
- [ ] DB migration runs: `flask db migrate -m "add MTF columns"` + `flask db upgrade`
- [ ] All existing tests pass unchanged
