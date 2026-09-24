# Transit — combined hackathon prototype

This version combines the Codex-style planner, Scenario Studio and manager workflow with the latest ZIP's shipment dashboard, historical analytics, cost/fuel estimates and MapLibre/OSRM road routes. The original Codex project remains separate.

## Open the running version

- Frontend: http://127.0.0.1:5176/
- Backend API docs: http://127.0.0.1:8004/docs
- Run `powershell -File .\start.ps1` from this folder to start locally. Requires Node/npm and Python 3.11–3.13. Dependencies install on first launch. Logs go in `.runtime`.

## Judge demo (3 minutes)

1. Open Route planner. Choose Karlsruhe → Dresden. Set a weekday departure and a deadline two days later. Calculate routes.
2. Select an alternative: its real road polyline, intermediate hub, destination distance, detour, ETA, fuel and cost appear together. Every option is a planning estimate, not a booked carrier departure.
3. Apply Heavy traffic in Scenario Studio. It adds 180 minutes to that direct corridor and automatically recalculates. A transfer alternative may become faster. Events are labelled simulations. Resolve the event to remove its effect.
4. Save a selected plan for review. Open Control room, select that shipment and review recalculated options. Enter a reason; accept, keep or defer. Accept writes the selected plan to the shipment. Deadline misses require an explicit acknowledgement. Changed conditions invalidate old approvals.
5. In Weather lab enter Heavy Snow, visibility 500 m, wind 35 km/h, HIGH severity at a route facility. Choose an observation window covering the planned journey. Save or edit the record. The common weather engine generates the alert and route delay; dashboard and hubs show matching alerts. LOW/clear records can resolve the alert without a live API key.
6. Use Load Saturday demo. Select Via Chemnitz (when OSRM supplies this corridor). Show Saturday arrival, Weekend Hold through Sunday, and Monday onward movement.
7. Show Network intelligence and Assumptions to explain exactly which inputs are measured, derived or simulated.

For the interactive weather demo, calculate a live route, choose **Heavy snow**, **Heavy rain**, or **Tornado** in **Weather simulation**, then drag it onto the map or use **Place on route**. The circle and animated effect mark a manually simulated area. The planner recalculates the affected ETA, checks provider road geometry against every active zone with a 2 km margin, and ranks the shortest verified candidate detour. Drag a zone pin to move it, select a zone to change its radius, or remove it. If no provider route clears the zones, the UI says so and keeps the affected option visible. These are what-if conditions, not detected storms.

## Fixes and implementation

- `backend/app/hub_selection.py`: road corridor screening, operational/capacity eligibility, road detour verification, nearest-destination priority. No forced Heilbronn intermediary. Up to three suitable alternatives; no invented hub when road routing is unavailable.
- `backend/app/weekend.py` and `restrictions.py`: Saturday intermediate arrival → Monday eligibility; Sunday full-day business restriction; holiday chaining and Europe/Berlin daylight-saving handling.
- `backend/app/weather_rules.py`: provider-neutral thresholds, explicit observation windows, one worst-case observation per leg. Estimated delays 120/45 minutes.
- `backend/app/eta.py`: single journey calculation shared by route search, shipments and manager replanning; road geometry/distance, weather, event and weekend timeline components.
- `backend/app/operations.py`: atomic local persistence for observations, events and decisions; planning revisions; single-process synchronization.
- `backend/app/shipments.py`: selected-option persistence, forced scheduling correction, stale option rejection, previous plan preserved during review.
- `backend/app/assumptions.json`: edit this one file to update the in-app Assumptions section.
- `frontend/src/combined.css`: Codex-inspired responsive visual system; original data views remain available.
- `frontend/src/components/LiveMap.tsx`: road geometry preserved even when the basemap/WebGL is unavailable.

## Honest boundaries

The dataset does not provide timed departure schedules or measured hub processing times. City coordinates, the original Heilbronn central-hub mapping, and branch transfer eligibility are assumptions. Stuttgart is a clearly documented supplementary demonstration hub. OSRM uses standard road routing, not truck-certified routing. Historical reliability is derived from spillover, not actual arrival-time accuracy. The holiday simplification is not a jurisdiction-complete legal engine. Full Sunday hold is a requested BUSINESS rule.

TomTom traffic integration requires a backend TOMTOM_API_KEY. Without a key, the map uses labelled simulated traffic and routing falls back to OSRM. Open-Meteo forecast weather works without a key. Scenario traffic/political closures and manually entered weather are explicitly manual/simulated. Political closures affect a facility, not an unmodelled entire road corridor. External routing needs internet; offline routes are clearly labelled approximate and return no unverified intermediate hub. No shipment is actually dispatched. Manager authorization here is a demo role, without login.

Storage is local JSON for a single backend process. Saved plans/events/weather/decisions survive restart. The ordinary activity feed is in-memory. Existing older saved shipments can be recalculated from Control room. Replanning is intentionally limited to pre-dispatch shipments. Estimates may have positive and negative trade-offs; savings are not guaranteed.

## Live map, optimization and historical comparison

- Map layers: weather, traffic flow, incidents and facilities. Click markers for source, conditions and timestamps; click alternatives to compare. Fit route, fullscreen and manual refresh are available.
- OpenStreetMap tiles are served on demand through the local backend and cached for seven days, so the browser can render the basemap even when direct tile requests fail. OpenFreeMap Liberty and Positron are key-free alternatives in the map selector. Map style changes restore the road and weather overlays.
- When a simulated weather zone causes a verified detour, the map highlights the affected road and a decision card compares distance, ETA, fuel and transport cost against driving through the zone. The weather delay remains a labelled manual assumption; public OSRM geometry is not truck-certified.
- Forecast preview: planned passage, now, +3/+6/+12 hours. Preview changes only the overlay; current traffic layers are hidden for future previews.
- Planner ETAs refresh every 2 minutes while the page is active and inputs are unchanged. The selected alternative is preserved if still available. Saved plans are not silently dispatched or replaced.
- Weather samples use Open-Meteo hourly forecasts, cached for 15 minutes. Severity-to-delay rules remain prototype assumptions. Unavailable/out-of-range forecasts are labelled.
- TomTom routing uses truck dimensions, gross weight and traffic. Provider delay is included exactly once. Current incidents are sampled near the route; this is not complete corridor coverage. Predictions are not vehicle GPS tracking.
- Choose Fastest arrival, Lowest cost within deadline, or Balanced. Balanced ranks transport euros + transit hours × €50; this is a value-of-time assumption, not a billed charge. If every option misses the deadline, the UI says so.
- Save recommended saves the first-ranked route for manager review. Save plan saves the selected alternative. Saved comparison snapshots supply signed cost/time/fuel estimates against the same direct-route baseline.
- Historical costs from disposition.csv are normalized by historical loading metres, then allocated to the shipment. Unmatched routes show clearly labelled reference lanes. There are no historical arrival timestamps, so historical time savings are unavailable.

### Enable traffic

Set TOMTOM_API_KEY in the environment of the backend before starting it; for example, in your own PowerShell terminal:

```powershell
$env:TOMTOM_API_KEY = 'your-key'
powershell -File .\start.ps1
```

If the backend is already running, restart that backend process with the variable set. Keys remain on the backend; do not put them in frontend VITE variables or commit them. The key must have routing and traffic access. Account limits and external availability apply. Provider failures fall back to labelled estimates.

## Focused verification

Frontend production build passed. Four targeted backend checks passed for cost optimization/saved history comparison, counting provider traffic delay once, forecast conversion, and scenario recalculation/stale decision handling. The running browser also displayed real Open-Meteo forecast markers, real OSRM road geometry, signed route trade-offs and historical cost comparisons. Live TomTom responses could not be verified without a configured key. No broad test suite was run for this update.


## Reliability upgrade

- Approval now requires the reviewed quote ID and a manager reason, including the shipment drawer and legacy scheduling endpoint. The backend recalculates before approval; materially changed proposals are rejected and the saved snapshot stays intact. Data providers use cached observations within their stated TTLs, so this is not a guaranteed last-second traffic check.
- Change notices compare the selected proposal with the saved ETA, cost and route. Operational inputs, restrictions, provider coverage and deadline changes are material; so are ETA changes of at least 15 minutes or cost changes of at least 5%.
- Departure schedules are an expandable planner control. Add a service for the selected origin and destination, weekdays, departure time and cutoff buffer. Timetable waiting appears as a separate journey step. Departures roll forward after missed cutoffs, Sunday restrictions, holidays or closure. Timetables remain user-entered assumptions; carrier capacity is not booked.
- Shipment details allow marking an approved shipment delivered and recording actual departure, arrival and cost. These compare against the approved snapshot. Corrections retain an outcome history. Savings shows actual aggregate performance only after five non-demo outcomes; on-time percentage needs five deadlines. New seeded examples and judge demo shipments are labelled demo and excluded from these metrics and estimated savings totals. Legacy unlabelled shipments remain user data; no historical actual values are invented.
- The isolated Judge walkthrough uses three captured OSRM road geometries. Basemap tiles may still require internet; the existing fallback preserves captured geometry. It never disguises simulated delays as live traffic.
- TomTom failure cooldown: 30 seconds. Routing/incident cache: two minutes; forecast cache: 15 minutes. API keys stay on the backend. No TomTom key was configured for this update, so live traffic could not be verified.

### Three-minute judge script

1. Expand **Judge walkthrough** in Route planner. Create baseline plan; note its DEMO shipment ID and saved direct route.
2. Add the 180-minute direct-connection delay. Compare the faster transfer alternative, added transport cost, ETA and historical benchmark.
3. Open Control room, select that DEMO shipment and review the saved-versus-proposed notice. Enter a reason, then accept the recommended option. Show the persisted decision history.
4. Optionally open the shipment in Shipments, mark it delivered and enter illustrative outcomes. Show that its DEMO results are excluded from real performance metrics.
5. Use **Start another demo** for another run. Existing scenarios and shipments are preserved.

### Verification of this upgrade

Frontend production build passed. Seven focused checks covered timetable cutoffs/holidays, provider changes without manual revisions, quote replacement, saved snapshot preservation, isolated demo approval and actual-outcome exclusion, signed savings, traffic counted once, and explicit deadline override persistence. External TomTom validation remains pending a key.

The browser walkthrough created an isolated demo baseline, applied the disruption, reviewed the Nürnberg alternative and saved a manager decision. A map loading race found during hot reload was fixed with a per-map readiness guard.
