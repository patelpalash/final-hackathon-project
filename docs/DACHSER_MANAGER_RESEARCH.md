# DACHSER traffic-manager presentation: research and implementation priorities

Research reviewed: 2 October 2026. These priorities are inferred from DACHSER's public material, not requirements validated through interviews or access to its internal systems.

## What the sources suggest

- DACHSER's [Short Distance Planning account](https://magazine.dachser.com/short-distance-planning-everything-at-a-glance/) describes dispatchers needing a clear overview, precise delivery windows and scheduling against available capacity. This is short-distance transport; applying the same decision priorities to our main-leg prototype is an inference.
- [Knowing where and how](https://www.dachser.com/en/mediaroom/Knowing-where-and-how-16747) describes telematics, arrival forecasts and visibility for long-distance groupage. Our animated vehicles are simulations and must not be described as integrated DACHSER telemetry.

## Implemented in this reporting improvement

1. Operational estimates use approved non-demo plans and matching baselines. Held and unapproved proposals do not contribute to totals.
2. Actual performance requires a recorded delivery matched to the approved quote. Below five usable observations, aggregate statistics stay unavailable. Individual records remain inspectable.
3. Demo scenarios have a separate view; synthetic filler rows and fabricated delivery statistics have been removed.
4. Planning value uses one baseline: transport estimate difference plus time valued at EUR 50/hour. Fuel valuation, a separate reroute comparison and protected cargo value are not added again.
5. Managers can inspect evidence and export the selected category to CSV. Recorded approval reasons are saved with the approved shipment. Older missing reasons are explicitly marked as unavailable.

## Recommended next: missed-connection and delivery-window warning

Show an attention queue ordered by operational consequence, with a short reason for each priority. For each affected journey show the planned hub arrival, next confirmed/user-entered departure, cutoff buffer and resulting delivery-window risk. Compare continuing, a verified reroute, and waiting for the next feasible departure.

Acceptance criteria:
- Use the same ETA/restriction engine for all compared choices.
- Include every overlapping weather zone and operational closure.
- Preserve the already-travelled road when a credible current vehicle position exists.
- State whether a timetable is user-entered or confirmed by a carrier system; do not imply booking capacity.
- Record the manager's selected action and reason, and require a fresh clear route before release from hold.
- Present extra kilometres, estimated cost and fuel, and arrival impact together. Missing evidence is unavailable, never zero.

## Later improvements

- Arrival windows calibrated from sufficient route-specific actuals; no invented confidence percentages.
- Real telemetry and dispatch-system integration, subject to DACHSER access and requirements.
- Capacity-aware hub alternatives once usable capacity data is supplied.
- Authenticated roles, database transactions and a durable decision audit for multi-user operation.

## Presentation sequence

Show Approved estimates, expand one evidence row, then open Actual outcomes and explain the sample count. Show Demo scenarios separately. Export the evidence for a manager to inspect. Explain that faster or cheaper estimates are hypotheses until actual outcomes are recorded; an arrival-time simulation is not proof of delivery.

## Checkpoints and rollback

Reporting calculations and the manager-facing evidence UI are committed separately with explanatory commit messages. Use a new git revert commit for a shared-history rollback rather than rewriting the branch. Local runtime shipment records and credentials are intentionally outside these code commits.
