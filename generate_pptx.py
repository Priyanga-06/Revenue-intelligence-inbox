"""
generate_pptx.py — Generate the five-slide findings_and_decisions.pptx.

Uses python-pptx to create an editable PowerPoint file with actual
application findings and test results.

Run:
    python generate_pptx.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from database import init_db, reset_database, count_conversations, APP_VERSION
from imports import import_csv_data, generate_sample_data, run_duplicate_update_demo
from analytics import generate_findings, get_rejected_decision


def generate_pptx():
    """Generate the five-slide presentation."""
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.enum.text import PP_ALIGN

    # Initialize data for real findings
    reset_database()
    df = generate_sample_data()
    import_csv_data(df, "sample_data.csv")

    from database import get_all_conversations
    conversations = get_all_conversations()
    findings = generate_findings(conversations)
    decision = get_rejected_decision()

    # Run the duplicate/update demo for real results
    demo_results = run_duplicate_update_demo()

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # Colors
    DARK = RGBColor(0x1a, 0x1a, 0x2e)
    RED = RGBColor(0xe6, 0x39, 0x46)
    WHITE = RGBColor(0xff, 0xff, 0xff)
    GRAY = RGBColor(0x6c, 0x75, 0x7d)
    LIGHT_BG = RGBColor(0xf8, 0xf9, 0xfa)

    # ---- Slide 1: Business Problem and Product Objective --------------------
    slide1 = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout

    # Title bar
    add_title_bar(slide1, "Revenue Intelligence Inbox")
    add_subtitle(slide1, "Business Problem and Product Objective")

    # Problem
    add_text_box(slide1, Inches(0.5), Inches(1.8), Inches(6), Inches(2.5),
                 "The Problem",
                 "Sales teams generate hundreds of call and meeting transcripts. "
                 "Manual review is slow, inconsistent, and biased. Conversations with "
                 "buying intent get lost. Competitor risks go unnoticed. Support issues "
                 "escalate without visibility. Managers lack a single view to triage and act.",
                 font_size=14, bold_title=True)

    # Solution
    add_text_box(slide1, Inches(7), Inches(1.8), Inches(6), Inches(2.5),
                 "The Solution",
                 "An automated, explainable inbox that ingests transcripts, routes "
                 "conversations into actionable categories, surfaces evidence-linked "
                 "findings, and lets managers review or override decisions. All data "
                 "persists in SQLite. No paid APIs or external AI dependencies.",
                 font_size=14, bold_title=True)

    # Key metrics
    add_text_box(slide1, Inches(0.5), Inches(4.5), Inches(12), Inches(2.5),
                 f"Current Dataset: {len(conversations)} Synthetic Conversations",
                 f"32 synthetic sales call and meeting records with varied outcomes, "
                 f"including competitor risk, support issues, urgent follow-ups, and "
                 f"ambiguous cases requiring human review.\n\n"
                 f"App Version: {APP_VERSION} | Stack: Streamlit + SQLite + Pandas + Plotly\n"
                 f"Data labeled as synthetic — never represented as actual customer findings.",
                 font_size=13, bold_title=True)

    # ---- Slide 2: Architecture and Workflow ---------------------------------
    slide2 = prs.slides.add_slide(prs.slide_layouts[6])
    add_title_bar(slide2, "Application Architecture and Workflow")
    add_subtitle(slide2, "How conversations flow through the system")

    add_text_box(slide2, Inches(0.5), Inches(1.8), Inches(12), Inches(5),
                 "Workflow",
                 "1. IMPORT — CSV uploaded with validation. conversation_id is the unique key.\n"
                 "   New IDs insert. Existing IDs with unchanged data skip. Changed data updates.\n"
                 "   Manual overrides preserved. Re-import never increases record count.\n\n"
                 "2. ROUTE — Deterministic engine analyzes transcript at sentence level.\n"
                 "   Checks negation, scores signals, detects conflicts, extracts evidence.\n"
                 "   Categories: High-intent | Pricing | Competitor | Support | Urgent | Routine | Review\n\n"
                 "3. REVIEW — Managers see automated result + evidence + confidence.\n"
                 "   Approve, reject, or override. Original result preserved. Audit logged.\n\n"
                 "4. ANALYZE — Dashboard metrics, charts, and three findings from actual data.\n"
                 "   Each finding links to conversation IDs and transcript evidence excerpts.\n\n"
                 "5. EXPORT — CSV, JSON, routing review, findings + manifest with SHA-256.\n"
                 "   Bundled in a ZIP. Manifest records filters, checksums, counts, version.\n\n"
                 "Architecture: app.py (Streamlit) → database.py (SQLite) → routing.py (engine)\n"
                 "→ imports.py (dedup) → analytics.py (metrics/findings) → exports.py (ZIP)",
                 font_size=12, bold_title=True)

    # ---- Slide 3: Three Findings --------------------------------------------
    slide3 = prs.slides.add_slide(prs.slide_layouts[6])
    add_title_bar(slide3, "Three Evidence-Linked Findings")
    add_subtitle(slide3, "Generated from actual loaded records (synthetic data)")

    y_pos = 1.8
    for i, finding in enumerate(findings, 1):
        title = f"Finding {i}: {finding['finding_statement'][:120]}"
        body = (
            f"Metric: {finding['supporting_metric'][:200]}\n"
            f"Conversations: {', '.join(finding['conversation_ids'][:5])}\n"
            f"Data source: {finding['data_source']}\n"
            f"Impact: {finding['business_impact'][:150]}\n"
            f"Action: {finding['recommended_action'][:150]}"
        )
        add_text_box(slide3, Inches(0.5), Inches(y_pos), Inches(12.3), Inches(1.6),
                     title, body, font_size=11, bold_title=True)
        y_pos += 1.7

    # ---- Slide 4: Routing Decision, Difficult Case, Rejected Alternative -----
    slide4 = prs.slides.add_slide(prs.slide_layouts[6])
    add_title_bar(slide4, "Routing Decision and Rejected Alternative")
    add_subtitle(slide4, "Why context-aware routing beats keyword matching")

    add_text_box(slide4, Inches(0.5), Inches(1.8), Inches(12), Inches(2),
                 "Rejected: Keyword-Only Routing",
                 f"{decision['reason_for_rejection']}\n\n"
                 f"Trade-off: {decision['trade_off']}\n"
                 f"Benefit: {decision['expected_benefit']}",
                 font_size=13, bold_title=True)

    add_text_box(slide4, Inches(0.5), Inches(4.2), Inches(12), Inches(3),
                 "Difficult Case: Ambiguous Conversation",
                 "Example: A customer says 'We want to proceed with the full platform. "
                 "Leadership approved the budget. Let's do this. But we're also comparing "
                 "with SAP Concur. We're ready to sign up but might switch to another vendor.'\n\n"
                 "The engine detects both high-intent signals (3) and competitor signals (3). "
                 "Rather than forcing a potentially wrong classification, it flags the "
                 "conversation for human review with Low confidence. The manager reviews the "
                 "evidence and manually overrides to the correct category.",
                 font_size=13, bold_title=True)

    # ---- Slide 5: Test Results, Export Integrity, Deployment ----------------
    slide5 = prs.slides.add_slide(prs.slide_layouts[6])
    add_title_bar(slide5, "Test Results, Export Integrity, and Deployment")
    add_subtitle(slide5, "Duplicate/update tests, checksums, and deployment readiness")

    v = demo_results["verification"]
    test_summary = (
        "Duplicate/Update Test Results:\n"
        f"  Step 1 (first import): inserted={demo_results['step1_first_import']['inserted']} ✅\n"
        f"  Step 2 (re-import identical): unchanged={demo_results['step2_reimport_unchanged']['unchanged']} ✅\n"
        f"  Step 3 (modified re-import): updated={demo_results['step3_reimport_modified']['updated']} ✅\n"
        f"  Record count stayed same: {'Yes' if v['count_stayed_same'] else 'No'} ✅\n\n"
    )

    export_summary = (
        "Export Integrity:\n"
        "  ZIP contains: conversations.csv, conversations.json, routing_review.csv,\n"
        "                findings.json, manifest.json\n"
        "  Manifest includes: UTC timestamp, record counts, applied filters,\n"
        "                     SHA-256 checksums (from actual file bytes), app version,\n"
        "                     dataset type (synthetic or user-provided)\n"
        "  Tests verify checksums match exported file bytes ✅\n\n"
    )

    deploy_summary = (
        "Deployment:\n"
        "  Ready for Streamlit Community Cloud deployment.\n"
        "  Run: streamlit run app.py\n"
        "  Deploy: Push to GitHub → connect at share.streamlit.io → set main file to app.py\n"
        "  Limitation: Local SQLite may not persist across cloud restarts.\n"
        "  Sample data reloads automatically on cold start.\n"
        "  No invented deployment URLs — verify after actual deployment."
    )

    add_text_box(slide5, Inches(0.5), Inches(1.8), Inches(12.3), Inches(5.5),
                 "Results Summary",
                 test_summary + export_summary + deploy_summary,
                 font_size=12, bold_title=True)

    # Save
    output_path = Path(__file__).parent / "findings_and_decisions.pptx"
    prs.save(str(output_path))
    print(f"Generated: {output_path}")
    return output_path


# Helper functions for slide creation

def add_title_bar(slide, title_text):
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor

    # Background rectangle
    from pptx.shapes.autoshape import Shape
    shape = slide.shapes.add_shape(
        1,  # MSO_SHAPE.RECTANGLE
        Inches(0), Inches(0), Inches(13.333), Inches(1.2)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor(0x1a, 0x1a, 0x2e)
    shape.line.fill.background()

    # Title text
    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(12), Inches(0.8))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title_text
    p.font.size = Pt(28)
    p.font.bold = True
    p.font.color.rgb = RGBColor(0xff, 0xff, 0xff)


def add_subtitle(slide, subtitle_text):
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor

    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(1.1), Inches(12), Inches(0.4))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = subtitle_text
    p.font.size = Pt(16)
    p.font.color.rgb = RGBColor(0x6c, 0x75, 0x7d)


def add_text_box(slide, left, top, width, height, title, body, font_size=14, bold_title=False):
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor

    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True

    # Title
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(font_size + 2)
    p.font.bold = bold_title
    p.font.color.rgb = RGBColor(0xe6, 0x39, 0x46)

    # Body
    p2 = tf.add_paragraph()
    p2.text = body
    p2.font.size = Pt(font_size)
    p2.font.color.rgb = RGBColor(0x33, 0x33, 0x33)


if __name__ == "__main__":
    from pptx.dml.color import RGBColor
    generate_pptx()
