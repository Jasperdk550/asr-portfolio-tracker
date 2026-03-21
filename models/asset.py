"""
Asset Model
-----------
Represents a single purchase lot (position) in the portfolio.
Each time an asset is bought it becomes its own Asset record,
enabling average-cost tracking and lot-level P&L.
"""

from dataclasses import dataclass, asdict, field
import uuid
from typing import Optional


VALID_ASSET_CLASSES = ["Equity", "ETF", "Bond", "Crypto", "Commodity", "Real Estate", "Other"]


@dataclass
class Asset:
    """
    A single purchase lot of an investment asset.

    Attributes
    ----------
    ticker       : Exchange ticker symbol (e.g. 'AAPL', 'BTC-USD').
    sector       : Business sector (e.g. 'Technology', 'Healthcare').
    asset_class  : Broad asset class (see VALID_ASSET_CLASSES).
    quantity     : Number of units purchased.
    purchase_price: Price per unit at time of purchase.
    purchase_date : Purchase date in ISO format 'YYYY-MM-DD'.
    name         : Human-readable instrument name (populated by yfinance).
    currency     : Currency the asset trades in (default 'USD').
    position_id  : Unique identifier for this specific lot.
    """

    ticker: str
    sector: str
    asset_class: str
    quantity: float
    purchase_price: float
    purchase_date: str          # ISO format YYYY-MM-DD
    name: str = ""
    currency: str = "USD"
    position_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def transaction_value(self) -> float:
        """Total cash outlay for this lot (quantity × purchase_price)."""
        return self.quantity * self.purchase_price

    def current_value(self, current_price: float) -> float:
        """Mark-to-market value of this lot."""
        return self.quantity * current_price

    def profit_loss(self, current_price: float) -> float:
        """Absolute profit / loss in the asset's currency."""
        return self.current_value(current_price) - self.transaction_value

    def profit_loss_pct(self, current_price: float) -> float:
        """Relative profit / loss as a percentage of cost basis."""
        if self.transaction_value == 0:
            return 0.0
        return (self.profit_loss(current_price) / self.transaction_value) * 100

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary (for JSON storage)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Asset":
        """Deserialise from a plain dictionary."""
        return cls(**data)

    def __repr__(self) -> str:
        return (
            f"Asset(id={self.position_id}, ticker={self.ticker}, "
            f"qty={self.quantity}, bought_at={self.purchase_price:.2f})"
        )
