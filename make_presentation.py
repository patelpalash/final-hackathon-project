import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE

def create_deck():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    blank_layout = prs.slide_layouts[6]

    # DACHSER Brand Colors
    NAVY = RGBColor(0, 47, 108)        # #002F6C
    YELLOW = RGBColor(253, 195, 0)     # #FDC300
    DARK = RGBColor(20, 27, 38)        # #141B26
    WHITE = RGBColor(255, 255, 255)
    GRAY_BG = RGBColor(245, 247, 250)  # #F5F7FA
    GRAY_TEXT = RGBColor(100, 110, 125) # #646E7D
    BORDER_COLOR = RGBColor(220, 226, 235)
    GREEN = RGBColor(23, 118, 94)      # #17765E
    BLUE_ACCENT = RGBColor(26, 54, 130)
    RED_ACCENT = RGBColor(192, 57, 43)

    def add_bg(slide, color):
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
        bg.fill.solid()
        bg.fill.fore_color.rgb = color
        bg.line.fill.background()
        return bg

    def add_header(slide, title_text, category_text="DACHSER LIVE TRANSIT PLANNER"):
        cat_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.45), Inches(11.7), Inches(0.35))
        tf_c = cat_box.text_frame
        tf_c.word_wrap = True
        p_c = tf_c.paragraphs[0]
        p_c.text = category_text.upper()
        p_c.font.size = Pt(11)
        p_c.font.bold = True
        p_c.font.color.rgb = YELLOW
        p_c.font.name = "Arial"

        title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.8), Inches(11.7), Inches(0.8))
        tf_t = title_box.text_frame
        tf_t.word_wrap = True
        p_t = tf_t.paragraphs[0]
        p_t.text = title_text
        p_t.font.size = Pt(25)
        p_t.font.bold = True
        p_t.font.color.rgb = NAVY
        p_t.font.name = "Arial"

        # Yellow accent line
        line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.65), Inches(1.5), Inches(0.06))
        line.fill.solid()
        line.fill.fore_color.rgb = YELLOW
        line.line.fill.background()

    def add_card(slide, left, top, width, height, title, items, bg_color=WHITE, border_color=BORDER_COLOR, title_color=NAVY):
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
        card.fill.solid()
        card.fill.fore_color.rgb = bg_color
        card.line.color.rgb = border_color
        card.line.width = Pt(1.5)

        tb = slide.shapes.add_textbox(left + Inches(0.25), top + Inches(0.18), width - Inches(0.5), height - Inches(0.36))
        tf = tb.text_frame
        tf.word_wrap = True
        
        if title:
            p_title = tf.paragraphs[0]
            p_title.text = title
            p_title.font.size = Pt(17)
            p_title.font.bold = True
            p_title.font.color.rgb = title_color
            p_title.font.name = "Arial"
            p_title.space_after = Pt(10)

        for idx, itm in enumerate(items):
            p = tf.add_paragraph() if (title or idx > 0) else tf.paragraphs[0]
            p.text = "•  " + itm
            p.font.size = Pt(12.5)
            p.font.color.rgb = DARK
            p.font.name = "Arial"
            p.space_after = Pt(7)

    # -------------------------------------------------------------
    # SLIDE 1: TITLE SLIDE (Dark Navy Theme)
    # -------------------------------------------------------------
    s1 = prs.slides.add_slide(blank_layout)
    add_bg(s1, NAVY)

    top_bar = s1.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(0.18))
    top_bar.fill.solid()
    top_bar.fill.fore_color.rgb = YELLOW
    top_bar.line.fill.background()

    tb = s1.shapes.add_textbox(Inches(1.0), Inches(1.8), Inches(11.3), Inches(3.0))
    tf = tb.text_frame
    tf.word_wrap = True

    p = tf.paragraphs[0]
    p.text = "DACHSER Live Transit Planner"
    p.font.size = Pt(44)
    p.font.bold = True
    p.font.color.rgb = WHITE
    p.font.name = "Arial"
    p.space_after = Pt(12)

    p2 = tf.add_paragraph()
    p2.text = "Autonomous Road Logistics Orchestration & Route Optimization Platform"
    p2.font.size = Pt(21)
    p2.font.color.rgb = YELLOW
    p2.font.name = "Arial"
    p2.space_after = Pt(20)

    p3 = tf.add_paragraph()
    p3.text = "Multi-Route Comparison · Eliminating €800k+ Special Trips (2024-2025) · Cost Optimization · Dynamic Reroute · Quantified Time Save"
    p3.font.size = Pt(13.5)
    p3.font.color.rgb = RGBColor(200, 215, 235)
    p3.font.name = "Arial"

    badge = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1.0), Inches(5.6), Inches(4.8), Inches(0.9))
    badge.fill.solid()
    badge.fill.fore_color.rgb = RGBColor(12, 35, 75)
    badge.line.color.rgb = YELLOW
    badge.line.width = Pt(1)

    b_tb = s1.shapes.add_textbox(Inches(1.15), Inches(5.7), Inches(4.5), Inches(0.7))
    b_tf = b_tb.text_frame
    b_p = b_tf.paragraphs[0]
    b_p.text = "Built on Real DACHSER European Network Data"
    b_p.font.size = Pt(13)
    b_p.font.bold = True
    b_p.font.color.rgb = WHITE
    b_p.font.name = "Arial"
    b_p2 = b_tf.add_paragraph()
    b_p2.text = "Heilbronn Central Hub + 30 Branch Relations (19,980 Dispatches)"
    b_p2.font.size = Pt(11)
    b_p2.font.color.rgb = YELLOW
    b_p2.font.name = "Arial"

    # -------------------------------------------------------------
    # SLIDE 2: THE €800K SPECIAL TRIP PROBLEM (2024-2025)
    # -------------------------------------------------------------
    s2 = prs.slides.add_slide(blank_layout)
    add_bg(s2, GRAY_BG)
    add_header(s2, "The Core Problem: €800k+ in Special Trips (2024–2025)", "HISTORICAL LOGISTICS AUDIT")

    # High-impact alert banner
    alert_box = s2.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.95), Inches(11.7), Inches(1.2))
    alert_box.fill.solid()
    alert_box.fill.fore_color.rgb = RED_ACCENT
    alert_box.line.fill.background()
    a_tf = alert_box.text_frame
    a_p1 = a_tf.paragraphs[0]
    a_p1.text = "🚨 Over €800,000 Spent on Costly Special Trips (Sonderfahrten) Across 2024–2025"
    a_p1.font.size = Pt(18)
    a_p1.font.bold = True
    a_p1.font.color.rgb = WHITE
    a_p2 = a_tf.add_paragraph()
    a_p2.text = "DACHSER's 2-year operational records (disposition.csv) reveal that missed line trailers, cutoff delays, and unmanaged weekend hold-ups forced emergency premium dispatches costing up to 3x standard tariffs."
    a_p2.font.size = Pt(12)
    a_p2.font.color.rgb = RGBColor(255, 235, 235)

    add_card(s2, Inches(0.8), Inches(3.35), Inches(3.6), Inches(3.65), "1. Missed Line-Haul Cutoffs", [
        "Special trips are triggered when scheduled line-trailers depart without cargo.",
        "A 15-minute handling delay at a branch forces a dedicated €1,500+ emergency special trip.",
        "Lack of forward visibility creates last-minute scramble dispatches on Friday nights."
    ], bg_color=WHITE, title_color=RED_ACCENT)

    add_card(s2, Inches(4.85), Inches(3.35), Inches(3.6), Inches(3.65), "2. Regulatory Bottlenecks", [
        "Sonntagsfahrverbot: German Sunday truck ban (00:00–22:00) traps delayed trucks.",
        "Vehicles arriving Saturday evening sit idle for up to 26 hours, risking Monday delivery SLAs.",
        "Emergency special trips are deployed on Monday morning to compensate for lost transit time."
    ], bg_color=WHITE, title_color=RED_ACCENT)

    add_card(s2, Inches(8.9), Inches(3.35), Inches(3.6), Inches(3.65), "3. Fragmented Routing", [
        "Traditional TMS evaluates only static direct distance, ignoring intermediate hub bypasses.",
        "No continuous recalculation when corridor traffic jams (A8, A81, A6) or severe weather hit.",
        "Dispatchers lacked an automated tool to compare alternatives before booking special trips."
    ], bg_color=WHITE, title_color=RED_ACCENT)

    # -------------------------------------------------------------
    # SLIDE 3: COST OPTIMIZATION (Eliminating Special Trips)
    # -------------------------------------------------------------
    s3 = prs.slides.add_slide(blank_layout)
    add_bg(s3, GRAY_BG)
    add_header(s3, "Cost Optimization: Eliminating Emergency Freight Tariffs", "STRATEGIC COST OPTIMIZATION")

    add_card(s3, Inches(0.8), Inches(2.0), Inches(5.6), Inches(2.5), "Tariff Optimization vs. Special Trips", [
        "Standard line-trailer tariff vs. special trip penalty: Line-hauls cost €450–€850, whereas emergency special trips surge to €1,400–€2,800 on identical European lanes.",
        "Our engine plans shipments to guarantee connection to regular line-trailers, directly recovering the €800k+ historical loss.",
        "Load-normalized cost benchmarking from 19,980 real lane-day dispatches."
    ], title_color=NAVY)

    add_card(s3, Inches(6.9), Inches(2.0), Inches(5.6), Inches(2.5), "3 Pareto Optimization Modes", [
        "Lowest Cost Mode: Discovers the cheapest line-haul carrier combination that strictly respects the customer delivery deadline.",
        "Fastest Arrival Mode: Eliminates stationary wait times and selects rapid transit corridors.",
        "Balanced Mode: Ranks routes by Total Transport Cost (€) + (Transit Hours × €50/hr), quantifying driver labour value and operational trade-offs."
    ], title_color=NAVY)

    # Bottom summary card
    add_card(s3, Inches(0.8), Inches(4.75), Inches(11.7), Inches(2.2), "Quantified Cost Breakdown & Fuel Efficiency", [
        "Direct Transport Cost Savings: €3,565 saved on baseline operational test batches vs. direct standard runs.",
        "Fuel & Emission Abatement: 1,100 litres of diesel fuel saved, reducing carrier expenditure and operational CO₂ emissions.",
        "High-Value Exposure Avoidance: €3,000+ in cargo damage and theft exposure mitigated by preventing unmonitored weekend parking."
    ], bg_color=RGBColor(240, 248, 245), border_color=GREEN, title_color=GREEN)

    # -------------------------------------------------------------
    # SLIDE 4: MULTI-ROUTE COMPARISON ENGINE
    # -------------------------------------------------------------
    s4 = prs.slides.add_slide(blank_layout)
    add_bg(s4, GRAY_BG)
    add_header(s4, "Multi-Route Comparison & Benchmark Engine", "ROUTE INTELLIGENCE & COMPARISON")

    add_card(s4, Inches(0.8), Inches(2.0), Inches(3.6), Inches(4.8), "1. Side-by-Side Alternatives", [
        "Simultaneously calculates and displays up to 4 complete route options.",
        "Every alternative provides full breakdown: Road km, total transit minutes, transport cost (€), fuel (L), and risk score.",
        "Interactive route cards allow instant switching to inspect trade-offs.",
        "Transparently displays 'Advisory Estimate' or 'Confirmed Plan' based on data source."
    ])

    add_card(s4, Inches(4.85), Inches(2.0), Inches(3.6), Inches(4.8), "2. Direct vs. Transfer Hubs", [
        "Compares direct point-to-point against intermediate hub transfers (e.g. via Nürnberg, Chemnitz, Langenau, Heilbronn).",
        "Detour verification: Discards impractical detours and validates transfer hub capacity.",
        "Quantified difference metrics: Shows exact € variance and time delta compared to direct baseline.",
        "Identifies when a 40 km detour is 3 hours faster due to highway bottlenecks."
    ])

    add_card(s4, Inches(8.9), Inches(2.0), Inches(3.6), Inches(4.8), "3. Historical Benchmark", [
        "Direct integration with 19,980 historical lane records from disposition.csv.",
        "Compares planned cost against historical load-normalized actuals.",
        "Reliability proxy: Displays historical lane spillover rate and on-time consistency.",
        "Prevents dispatchers from committing to historically fragile corridors."
    ])

    # -------------------------------------------------------------
    # SLIDE 5: DYNAMIC REROUTING & DISRUPTION RESILIENCE
    # -------------------------------------------------------------
    s5 = prs.slides.add_slide(blank_layout)
    add_bg(s5, GRAY_BG)
    add_header(s5, "Dynamic Rerouting & Scenario Resilience", "ACTIVE DISRUPTION MANAGEMENT")

    add_card(s5, Inches(0.8), Inches(2.0), Inches(5.6), Inches(2.55), "Live Corridor Rerouting", [
        "Continuous corridor monitoring via TomTom Live Traffic and Open-Meteo weather forecasts.",
        "When severe congestion (+180 min) hits a direct motorway, the system immediately calculates transfer bypasses.",
        "Seamless transition: Preserves active leg and reroutes remaining journey without vehicle turnaround."
    ])

    add_card(s5, Inches(6.9), Inches(2.0), Inches(5.6), Inches(2.55), "Scenario Studio & Weather Lab", [
        "Scenario Studio: Operators can inject simulated highway closures or traffic jams to stress-test resilience.",
        "Weather Lab: Enter localized snow, ice, or wind alerts to preview ETA impact on the network.",
        "Pre-emptive dispatch: Recalculates before departure, avoiding en-route stranding."
    ])

    add_card(s5, Inches(0.8), Inches(4.8), Inches(11.7), Inches(2.2), "Control Room Audit Gate & Manager Approval", [
        "Pre-dispatch review gate: Proposed reroutes require an authorized review quote ID and an operator reason.",
        "Stale quote detection: Automatically invalidates proposals if weather or traffic conditions change during review.",
        "Immutable decision ledger: Every accepted, deferred, or rejected reroute is permanently logged with timestamp and author."
    ])

    # -------------------------------------------------------------
    # SLIDE 6: QUANTIFIED TIME SAVE & PERFORMANCE
    # -------------------------------------------------------------
    s6 = prs.slides.add_slide(blank_layout)
    add_bg(s6, GRAY_BG)
    add_header(s6, "Quantified Time Save & Delivery Performance", "TIME & RELIABILITY METRICS")

    time_metrics = [
        ("16.25 Hours", "Driver Labour Time Saved", "975 minutes eliminated by avoiding motorway jams & cutoff delays", BLUE_ACCENT),
        ("Up to 26 Hours", "Sunday Hold Traps Avoided", "Prevents shipments from being stranded under Sonntagsfahrverbot", GREEN),
        ("97.1%", "Audited On-Time Delivery", "Delivery reliability verified across 34 operational test shipments", GREEN),
        ("11.4 Min", "Mean Arrival Error (MAE)", "High-precision ETA forecasting compared against actual delivery times", NAVY),
        ("1,100 L", "Diesel Fuel Consumed Less", "Reduced idle engine time in traffic and optimized speed profiles", GREEN),
        ("€8,477.50", "Total Economic Benefit", "Combined financial value of time, fuel, tariffs, and risk avoidance", GREEN)
    ]

    for i, (val, title, desc, color) in enumerate(time_metrics):
        col = i % 3
        row = i // 3
        x = Inches(0.8 + col * 4.05)
        y = Inches(2.05 + row * 2.5)
        w = Inches(3.6)
        h = Inches(2.2)

        card = s6.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
        card.fill.solid()
        card.fill.fore_color.rgb = WHITE
        card.line.color.rgb = BORDER_COLOR
        card.line.width = Pt(1.5)

        tb = s6.shapes.add_textbox(x + Inches(0.2), y + Inches(0.15), w - Inches(0.4), h - Inches(0.3))
        tf = tb.text_frame
        tf.word_wrap = True

        p1 = tf.paragraphs[0]
        p1.text = val
        p1.font.size = Pt(28)
        p1.font.bold = True
        p1.font.color.rgb = color
        p1.font.name = "Arial"
        p1.space_after = Pt(4)

        p2 = tf.add_paragraph()
        p2.text = title
        p2.font.size = Pt(13)
        p2.font.bold = True
        p2.font.color.rgb = DARK
        p2.font.name = "Arial"
        p2.space_after = Pt(4)

        p3 = tf.add_paragraph()
        p3.text = desc
        p3.font.size = Pt(11)
        p3.font.color.rgb = GRAY_TEXT
        p3.font.name = "Arial"

    # -------------------------------------------------------------
    # SLIDE 7: 3-MINUTE JUDGE DEMO FLOW
    # -------------------------------------------------------------
    s7 = prs.slides.add_slide(blank_layout)
    add_bg(s7, GRAY_BG)
    add_header(s7, "3-Minute Live Demonstration Flow", "DEMONSTRATION SCRIPT")

    demo_steps = [
        ("Step 1: Plan & Compare", "Select Karlsruhe → Dresden. Compare Direct vs. via Chemnitz. Observe the road geometry, intermediate hub, ETA, fuel & cost trade-offs."),
        ("Step 2: Inject Disruption", "In Scenario Studio, apply 'Heavy Traffic (+180 min)' to the direct corridor. The engine recalculates in real-time — the transfer via Chemnitz becomes faster!"),
        ("Step 3: Control Room Review", "Open Control Room. Review the change notice showing time/cost variances. Enter a manager reason and approve the revised plan."),
        ("Step 4: Real-Time Simulation", "Open Journey Simulator. Watch vehicle progress, handling stages, and use 'Skip Hold' to jump past stationary rest periods.")
    ]

    for idx, (title, desc) in enumerate(demo_steps):
        y = Inches(2.05 + idx * 1.25)
        card = s7.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), y, Inches(11.7), Inches(1.1))
        card.fill.solid()
        card.fill.fore_color.rgb = WHITE
        card.line.color.rgb = BORDER_COLOR
        card.line.width = Pt(1.5)

        badge = s7.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1.0), y + Inches(0.18), Inches(2.6), Inches(0.74))
        badge.fill.solid()
        badge.fill.fore_color.rgb = NAVY if idx % 2 == 0 else BLUE_ACCENT
        badge.line.fill.background()
        b_tf = badge.text_frame
        b_p = b_tf.paragraphs[0]
        b_p.text = title
        b_p.font.size = Pt(13)
        b_p.font.bold = True
        b_p.font.color.rgb = YELLOW
        b_p.font.name = "Arial"
        b_p.alignment = PP_ALIGN.CENTER

        tb = s7.shapes.add_textbox(Inches(3.8), y + Inches(0.15), Inches(8.5), Inches(0.8))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = desc
        p.font.size = Pt(13)
        p.font.color.rgb = DARK
        p.font.name = "Arial"

    # -------------------------------------------------------------
    # SLIDE 8: TECH STACK & ARCHITECTURE
    # -------------------------------------------------------------
    s8 = prs.slides.add_slide(blank_layout)
    add_bg(s8, GRAY_BG)
    add_header(s8, "Modern & Robust Technology Stack", "SYSTEM ARCHITECTURE")

    add_card(s8, Inches(0.8), Inches(2.0), Inches(3.6), Inches(4.8), "Frontend (React 18)", [
        "React 18 & TypeScript 5.6 for rock-solid type safety and modular components.",
        "Vite 5.4 build system with instant hot-module replacement.",
        "MapLibre GL 4.7 with OpenStreetMap and CARTO raster basemaps.",
        "High-contrast black hub markers with interactive hover dialogs.",
        "Keep-Alive Tab System: Seamless navigation without page or simulation resets."
    ])

    add_card(s8, Inches(4.85), Inches(2.0), Inches(3.6), Inches(4.8), "Backend (FastAPI)", [
        "Python 3.11-3.13 asynchronous FastAPI REST gateway.",
        "Pydantic v2 data models for rigorous schema validation.",
        "tzdata for accurate Europe/Berlin timezone and daylight-savings rules.",
        "HTTPX async client for high-throughput provider queries.",
        "Atomic JSON store ledger ensuring zero data loss on restart."
    ])

    add_card(s8, Inches(8.9), Inches(2.0), Inches(3.6), Inches(4.8), "Data & Providers", [
        "Real DACHSER CSV Dataset: relationen, kalender, disposition, stoerungen.",
        "OSRM Road Geometry: Accurate European motorway polylines and distances.",
        "TomTom Live Traffic: Flow tiles, incident clusters, truck dimensions.",
        "Open-Meteo: Hourly weather forecasts along route corridors."
    ])

    # -------------------------------------------------------------
    # SLIDE 9: CONCLUSION & STRATEGIC VALUE (Dark Navy Theme)
    # -------------------------------------------------------------
    s9 = prs.slides.add_slide(blank_layout)
    add_bg(s9, NAVY)

    top_bar = s9.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(0.18))
    top_bar.fill.solid()
    top_bar.fill.fore_color.rgb = YELLOW
    top_bar.line.fill.background()

    tb = s9.shapes.add_textbox(Inches(1.0), Inches(1.5), Inches(11.3), Inches(4.8))
    tf = tb.text_frame
    tf.word_wrap = True

    p = tf.paragraphs[0]
    p.text = "Turning €800k in Special Trip Losses into Measurable Advantage"
    p.font.size = Pt(34)
    p.font.bold = True
    p.font.color.rgb = WHITE
    p.font.name = "Arial"
    p.space_after = Pt(14)

    p2 = tf.add_paragraph()
    p2.text = "DACHSER Live Transit Planner combines multi-objective route comparison, continuous dynamic rerouting, and regulatory compliance to protect customer deadlines while cutting transport expenditures."
    p2.font.size = Pt(17)
    p2.font.color.rgb = RGBColor(220, 230, 245)
    p2.font.name = "Arial"
    p2.space_after = Pt(24)

    bullets = [
        "✔  Recovers the €800k+ Special Trip Bleed: Plans shipments to secure regular line-trailers.",
        "✔  Comprehensive Comparison Engine: Evaluates direct vs. transfer hubs against 19,980 historical records.",
        "✔  Quantified Time Save: Eliminates 16.25 driver hours per batch and bypasses 26-hour Sunday driving bans.",
        "✔  Dynamic Rerouting & Control Room: Pre-emptive rerouting around corridor bottlenecks with manager sign-off.",
        "✔  Zero Fabricated Live Data: Transparent, audited, and production-ready for European road logistics."
    ]
    for b in bullets:
        pb = tf.add_paragraph()
        pb.text = b
        pb.font.size = Pt(14)
        pb.font.bold = True
        pb.font.color.rgb = YELLOW
        pb.font.name = "Arial"
        pb.space_after = Pt(8)

    out_path = os.path.join(os.path.dirname(__file__), "DACHSER_Live_Transit_Planner_Presentation.pptx")
    try:
        prs.save(out_path)
        print(f"Presentation saved successfully to: {out_path}")
    except PermissionError:
        out_path_v2 = os.path.join(os.path.dirname(__file__), "DACHSER_Live_Transit_Planner_Presentation_v2.pptx")
        prs.save(out_path_v2)
        print(f"Original file was open in PowerPoint. Saved updated presentation to: {out_path_v2}")

if __name__ == "__main__":
    create_deck()
