"""The one alert format every component produces and consumes.

Agree on this before anything else: the detectors write Alerts, the decision
maker reads them, and the dashboard and incident brief display them.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json

SOURCES = ("network", "physics", "threat_intel", "decision")
VERDICTS = ("normal", "attack_likely", "fault_likely", "uncertain")


@dataclass
class Alert:
    timestamp: datetime          # time of the reading that triggered it
    source: str                  # one of SOURCES
    score: float                 # 0.0 (normal) to 1.0 (certain problem)
    reason: str                  # one plain-English sentence
    verdict: str = "uncertain"   # one of VERDICTS, set by the decision maker
    details: dict = field(default_factory=dict)  # e.g. which sensors, expected vs actual

    def __post_init__(self):
        if self.source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}")
        if self.verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {VERDICTS}")
        self.score = float(min(max(self.score, 0.0), 1.0))

    def to_dict(self):
        d = asdict(self)
        d["timestamp"] = str(self.timestamp)
        return d

    def to_json(self):
        return json.dumps(self.to_dict(), default=str)
