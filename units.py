"""
Unit — a single traceable product moving through the production line.

Each Unit carries its own history: every machine that touched it, when,
and what that machine's readings looked like at the time. This is what
lets QC (once simulated) reason about *why* a specific unit passed or
failed, instead of just recording an isolated pass/fail event.
"""

import itertools
import time

_unit_counter = itertools.count(1)

# The counter lives in memory, so it restarts at 1 every time the
# simulator restarts. Without a per-run prefix, new units would reuse
# IDs already stored in the database and corrupt those units' histories.
_RUN_ID = time.strftime("%m%d%H%M%S")


class Unit:
    def __init__(self):
        self.unit_id = f"unit_{_RUN_ID}_{next(_unit_counter):06d}"
        self.created_at = time.time()
        self.status = "in_progress"  # in_progress / passed / failed / scrapped
        self.history: list[dict] = []

    def record_stage(self, *, sub_facility, machine_id, entered_at, exited_at,
                      readings, outcome, anomaly_score) -> None:
        """Called by a machine when it finishes working on this unit.
        `readings` is a snapshot of that machine's actual values at
        completion. `anomaly_score` is how far those readings deviated
        from setpoint (in combined std-deviations) — this is what lets
        QC later ask 'was anything unusual while this unit was here?'
        without needing to know what each field physically means."""
        self.history.append({
            "sub_facility": sub_facility,
            "machine_id": machine_id,
            "entered_at": entered_at,
            "exited_at": exited_at,
            "readings": readings,
            "outcome": outcome,  # "ok" or "flagged", this stage's own quick check
            "anomaly_score": anomaly_score,
        })

    def __repr__(self) -> str:
        return f"Unit({self.unit_id}, status={self.status}, stages_completed={len(self.history)})"