"""Build the Kindle Scribe study guide PDF from the project docs.

    pip install reportlab
    python -m scripts.build_kindle_pdf          # -> docs/kindle/Underwriting_Agent_Study_Guide_Kindle_Scribe.pdf

Page size matches the Kindle Scribe screen (1860 x 2480 px at 300 ppi = 6.2 x 8.27 in).
Grayscale only, large serif body text, clickable contents, PDF bookmarks, and ruled
note pages for handwriting. Re-run whenever the Markdown docs change.
"""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "kindle" / "Underwriting_Agent_Study_Guide_Kindle_Scribe.pdf"

PAGE = (6.2 * inch, 8.27 * inch)
MARGIN = 0.42 * inch
WIDTH = PAGE[0] - 2 * MARGIN

# ----------------------------------------------------------------------------- fonts
LIB = Path("/usr/share/fonts/truetype/liberation")
DJV = Path("/usr/share/fonts/truetype/dejavu")
for name, path in {
    "Serif": LIB / "LiberationSerif-Regular.ttf",
    "Serif-Bold": LIB / "LiberationSerif-Bold.ttf",
    "Serif-Italic": LIB / "LiberationSerif-Italic.ttf",
    "Serif-BoldItalic": LIB / "LiberationSerif-BoldItalic.ttf",
    "Sans": LIB / "LiberationSans-Regular.ttf",
    "Sans-Bold": LIB / "LiberationSans-Bold.ttf",
    "Mono": DJV / "DejaVuSansMono.ttf",
    "Mono-Bold": DJV / "DejaVuSansMono-Bold.ttf",
    "Symbol2": DJV / "DejaVuSans.ttf",
}.items():
    pdfmetrics.registerFont(TTFont(name, str(path)))
pdfmetrics.registerFontFamily(
    "Serif", normal="Serif", bold="Serif-Bold", italic="Serif-Italic", boldItalic="Serif-BoldItalic"
)
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans", boldItalic="Sans-Bold")
pdfmetrics.registerFontFamily("Mono", normal="Mono", bold="Mono-Bold", italic="Mono", boldItalic="Mono-Bold")

INK = colors.black
GREY = colors.Color(0.35, 0.35, 0.35)
SHADE = colors.Color(0.91, 0.91, 0.91)
RULE = colors.Color(0.6, 0.6, 0.6)

S = {
    "body": ParagraphStyle("body", fontName="Serif", fontSize=12.5, leading=17, spaceAfter=7, textColor=INK),
    "h1": ParagraphStyle("h1", fontName="Sans-Bold", fontSize=21, leading=25, spaceBefore=4, spaceAfter=12),
    "h2": ParagraphStyle("h2", fontName="Sans-Bold", fontSize=15.5, leading=19, spaceBefore=12, spaceAfter=6),
    "h3": ParagraphStyle("h3", fontName="Sans-Bold", fontSize=13, leading=16, spaceBefore=8, spaceAfter=4),
    "bullet": ParagraphStyle(
        "bullet", fontName="Serif", fontSize=12.5, leading=17, spaceAfter=4, leftIndent=16, bulletIndent=3
    ),
    "quote": ParagraphStyle(
        "quote", fontName="Serif-Italic", fontSize=12, leading=16, leftIndent=12, textColor=GREY, spaceAfter=8
    ),
    "cell": ParagraphStyle("cell", fontName="Serif", fontSize=10, leading=12.5),
    "cellh": ParagraphStyle("cellh", fontName="Sans-Bold", fontSize=10, leading=12.5),
    "code": ParagraphStyle(
        "code",
        fontName="Mono",
        fontSize=8.6,
        leading=11,
        leftIndent=5,
        rightIndent=5,
        backColor=SHADE,
        borderPadding=(5, 5, 5, 5),
        spaceBefore=4,
        spaceAfter=10,
    ),
    "small": ParagraphStyle("small", fontName="Sans", fontSize=9.5, leading=12, textColor=GREY),
    "toc1": ParagraphStyle("toc1", fontName="Sans-Bold", fontSize=12.5, leading=17, spaceBefore=5),
    "toc2": ParagraphStyle("toc2", fontName="Serif", fontSize=11.5, leading=15, leftIndent=14),
    "cover": ParagraphStyle("cover", fontName="Sans-Bold", fontSize=26, leading=31, alignment=TA_CENTER),
    "coversub": ParagraphStyle(
        "coversub", fontName="Serif", fontSize=14, leading=19, alignment=TA_CENTER, textColor=GREY
    ),
}
CODE_COLS = 70


# ----------------------------------------------------------------------------- inline markdown
def inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    codes: list[str] = []

    def keep(m: re.Match[str]) -> str:
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep, text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![\w])_(?!\s)(.+?)(?<!\s)_(?![\w])", r"<i>\1</i>", text)
    text = text.replace("∈", '<font name="Symbol2">∈</font>')
    for i, c in enumerate(codes):
        text = text.replace(f"\x00{i}\x00", f'<font name="Mono" size="-1.5">{c}</font>')
    return text


# ----------------------------------------------------------------------------- flowables
class Heading(Paragraph):
    """Paragraph that registers itself in the TOC and PDF outline."""

    def __init__(self, text: str, level: int, style: ParagraphStyle, toc: bool = True):
        super().__init__(text, style)
        self.level, self.plain, self.toc = level, re.sub("<[^>]+>", "", text), toc


class NoteLines(Flowable):
    """Ruled lines for handwriting on the Scribe."""

    def __init__(self, height: float, gap: float = 0.36 * inch):
        super().__init__()
        self.height, self.gap = height, gap

    def wrap(self, aw, ah):
        return WIDTH, self.height

    def draw(self):
        c = self.canv
        c.setStrokeColor(RULE)
        c.setLineWidth(0.5)
        y = self.height
        while y > 0:
            c.line(0, y, WIDTH, y)
            y -= self.gap


def wrap_code(src: str) -> str:
    out = []
    for line in src.splitlines():
        while len(line) > CODE_COLS:
            cut = line.rfind(" ", 20, CODE_COLS)
            cut = cut if cut > 0 else CODE_COLS
            out.append(line[:cut])
            line = "    " + line[cut:].lstrip()
        out.append(line)
    return "\n".join(out)


def table(rows: list[list[str]], row_height: float | None = None) -> Table:
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    data = [[Paragraph(inline(c), S["cellh" if i == 0 else "cell"]) for c in r] for i, r in enumerate(rows)]
    # Column widths proportional to content length, with a floor so short columns stay readable.
    lens = [max(min(len(r[j]), 60) for r in rows) + 6 for j in range(ncol)]
    widths = [WIDTH * n / sum(lens) for n in lens]
    widths = [max(w, 0.7 * inch) for w in widths]
    scale = WIDTH / sum(widths)
    heights = [None] + [row_height] * (len(data) - 1) if row_height else None
    t = Table(data, colWidths=[w * scale for w in widths], rowHeights=heights, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), SHADE),
                ("GRID", (0, 0), (-1, -1), 0.5, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP" if not row_height else "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t


# ----------------------------------------------------------------------------- markdown -> flowables
def md_to_flowables(md: str, mermaid: list[list[Flowable]], h1_level: int = 0, skip_h1: bool = False) -> list:
    lines = md.splitlines()
    out: list = []
    para: list[str] = []
    i = 0

    def flush():
        if para:
            out.append(Paragraph(inline(" ".join(para)), S["body"]))
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush()
            lang = s[3:].strip()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            if lang == "mermaid":
                out += mermaid.pop(0) if mermaid else []
            else:
                out.append(Preformatted(wrap_code("\n".join(block)), S["code"]))
        elif s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            out += [table(rows), Spacer(1, 9)]
            continue
        elif re.match(r"^#{1,3} ", s):
            flush()
            level = len(s.split(" ")[0])
            text = inline(s[level + 1 :])
            if level == 1:
                if not skip_h1:
                    out.append(Heading(text, h1_level, S["h1"]))
            else:
                out.append(CondPageBreak(1.3 * inch))
                out.append(Heading(text, h1_level + level - 2, S[f"h{level}"], toc=level == 2))
        elif re.match(r"^(\s*)([-*]|\d+\.) ", line):
            flush()
            m = re.match(r"^(\s*)([-*]|\d+\.) (.*)$", line)
            indent, marker, text = len(m.group(1)), m.group(2), [m.group(3)]
            i += 1
            while (
                i < len(lines)
                and lines[i].startswith(" " * (indent + 2))
                and lines[i].strip()
                and not re.match(r"^\s*([-*]|\d+\.) ", lines[i])
                and not lines[i].strip().startswith("```")
            ):
                text.append(lines[i].strip())
                i += 1
            style = ParagraphStyle(
                "b", parent=S["bullet"], leftIndent=16 + indent * 7, bulletIndent=3 + indent * 7
            )
            out.append(Paragraph(inline(" ".join(text)), style, bulletText="•" if marker in "-*" else marker))
            continue
        elif s.startswith(">"):
            flush()
            q = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                q.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(Paragraph(inline(" ".join(q)), S["quote"]))
            continue
        elif s == "---":
            flush()
            out.append(Spacer(1, 6))
        elif not s:
            flush()
        else:
            para.append(s)
        i += 1
    flush()
    return out


# ----------------------------------------------------------------------------- authored content
def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(inline(text), S[style])


def bullets(items: list[str]) -> list[Paragraph]:
    return [Paragraph(inline(t), S["bullet"], bulletText="•") for t in items]


def steps(items: list[str]) -> list[Paragraph]:
    return [Paragraph(inline(t), S["bullet"], bulletText=f"{n}.") for n, t in enumerate(items, 1)]


SYSTEM_GLANCE = [
    p("**System at a glance** (the diagram in the repo README, as a table):"),
    table(
        [
            ["Component", "Role"],
            [
                "Credit analyst",
                "Signs in with Cognito and gets a JWT carrying `lending_role` and `portfolio`",
            ],
            ["AgentCore Runtime", "Hosts the Strands agent; JWT authorizer = AgentCore Identity"],
            ["AgentCore Gateway", "MCP endpoint for the tools; validates the same user token"],
            ["AgentCore Policy", "Cedar policies evaluated on every tool call (ENFORCE mode)"],
            ["Calculators Lambda (`uwcalc`)", "NOI, DSCR, debt yield, LTV, farm stress, policy check"],
            ["LOS Lambda (`los`)", "Deal documents, label mapping, analyst review queue"],
            ["S3 deal store", "Source documents and tool work files, SSE-KMS"],
            ["Amazon Bedrock", "Claude model calls through Converse, with a Guardrail"],
            ["AgentCore Observability", "OpenTelemetry traces and audit events in CloudWatch"],
        ]
    ),
    Spacer(1, 9),
]

SEQUENCE = [
    p("**Request flow, step by step** (the sequence diagram in the repo):"),
    *steps(
        [
            "Analyst signs in to Cognito and receives an access token with `sub`, `lending_role`, `portfolio`.",
            "Analyst calls the Runtime `/invocations` with `{deal_id}` and the bearer token.",
            "The Runtime's JWT authorizer validates the token before the container runs.",
            "The agent calls Bedrock (Converse) with the system prompt and tool list.",
            "The model asks for `get_deal_package(deal_id, portfolio)`.",
            "The agent calls the Gateway over MCP with the analyst's own token.",
            "The Gateway asks AgentCore Policy to authorize: principal tags, action, input. Permit.",
            "The LOS Lambda reads `deal.json` from S3 and checks the deal is in the portfolio.",
            "Loop: extract documents, map labels, compute metrics, check policy, get evidence. Each call is "
            "authorized by Policy; the calculators write metrics and the evidence ledger to S3.",
            "The model drafts the memo, citing anchors; the agent calls `verify_memo_citations`.",
            "The Runtime returns `status=awaiting_approval` with the memo and an interrupt id.",
            "The analyst approves; the agent calls `submit_memo_for_analyst_review`, which Policy allows only "
            "for underwriters and credit analysts; the LOS files it as PENDING ANALYST REVIEW.",
        ]
    ),
    Spacer(1, 6),
]

STUDY_PLAN = [
    ["Day", "Read", "Do", "Done"],
    ["1", "Part 1, Part 2, Glossary", "Read the credit policy YAML; explain DSCR and TDCR aloud", "☐"],
    ["2", "Part 3 Phases 0 to 2", "`make test`, `make eval`; read the Field misses table", "☐"],
    ["3", "Part 3 Phase 3", "Run the agent locally on CRE-007; save the transcript", "☐"],
    ["4", "Part 3 Phases 4 to 5", "Bootstrap CDK, deploy, seed users", "☐"],
    ["5", "Part 3 Phase 6 + first-deploy checks", "Verify every control; take screenshots", "☐"],
    ["6", "Part 3 Phase 7, Part 5", "Set up CI/CD; run live eval; fill resume numbers", "☐"],
    ["7", "Part 4, Self-check", "Rehearse the pitch and demo twice; answer the quiz", "☐"],
]

GLOSSARY_LENDING = [
    ["Term", "Meaning"],
    ["Rent roll", "Unit-by-unit list of tenants, area, contract rent, lease dates and occupancy"],
    ["T-12", "Trailing-twelve-month operating statement: income and expenses by month"],
    ["Spreading", "Re-keying borrower financials into the lender's standard format"],
    ["GPR", "Gross potential rent: rent if every unit were leased at contract or asking rent"],
    ["EGI", "Effective gross income: GPR less vacancy and credit loss, plus other income"],
    [
        "NOI",
        "Net operating income: EGI less operating expenses and reserves. Excludes debt service, "
        "capital expenditure and depreciation",
    ],
    [
        "DSCR",
        "Debt service coverage ratio = NOI / annual debt service. 1.25x means $1.25 of NOI per $1 of debt payments",
    ],
    ["Debt yield", "NOI / loan amount. Independent of rate and amortization"],
    ["LTV", "Loan-to-value = loan amount / appraised value"],
    ["Breakeven occupancy", "Occupancy at which income just covers expenses, reserves and debt service"],
    ["Replacement reserves", "Annual allowance for recurring capital items, per unit or per square foot"],
    [
        "CADS",
        "Cash available for debt service (agricultural): revenue less operating costs, family living and taxes",
    ],
    ["TDCR", "Term debt coverage ratio = CADS / (existing + proposed term debt payments)"],
    ["Operating line", "Revolving credit that funds seasonal input costs until harvest receipts arrive"],
    ["Current ratio", "Current assets / current liabilities, a liquidity measure"],
    ["Stress test", "Re-running cash flow under adverse price, yield, cost or rate assumptions"],
    [
        "Policy exception",
        "A metric outside credit-policy limits; needs mitigants and approval at the right authority",
    ],
    ["Credit memo", "The written analysis an approving officer reads before deciding"],
    [
        "ECOA / Reg B",
        "Equal Credit Opportunity Act and Regulation B: anti-discrimination rules and adverse "
        "action notices with specific reasons",
    ],
    [
        "Adverse action notice",
        "Notice to an applicant that credit was denied or offered on worse terms, with reasons",
    ],
    [
        "SR 11-7",
        "US banking supervisory guidance on model risk management: validation, governance, monitoring",
    ],
]

GLOSSARY_TECH = [
    ["Term", "Meaning"],
    ["Strands Agents", "AWS open-source Python SDK for model-driven agents: model + tools + hooks"],
    [
        "AgentCore Runtime",
        "Serverless hosting for agents in isolated sessions, with inbound auth and versioned endpoints",
    ],
    ["AgentCore Gateway", "Turns Lambda functions and APIs into MCP tools behind one authenticated endpoint"],
    ["AgentCore Identity", "Inbound token validation and outbound credential handling for agents"],
    ["AgentCore Policy", "Cedar policies evaluated by the Gateway on every tool call"],
    ["AgentCore Observability", "Agent traces, spans and metrics in CloudWatch, from OpenTelemetry"],
    ["MCP", "Model Context Protocol: a standard way for agents to list and call tools"],
    ["Cedar", "Open-source authorization policy language: permit / forbid on principal, action, resource"],
    [
        "Bedrock Guardrails",
        "Managed filters for PII, denied topics and prompt attacks on model input and output",
    ],
    ["Interrupt", "Strands mechanism that pauses the agent loop until a human responds"],
    ["Hook", "Strands callback on events such as before or after a tool call"],
    ["OpenTelemetry / ADOT", "Standard for traces and metrics; ADOT is the AWS distribution"],
    ["CDK", "AWS Cloud Development Kit: infrastructure as Python code"],
    ["OIDC (GitHub)", "Lets GitHub Actions assume an AWS role without stored keys"],
]

QUIZ = [
    (
        "Why do the tools accept only deal and document IDs, never numbers?",
        "So that no figure passes through the model on its way into a calculation. The model cannot alter an "
        "input it never handles, and every output figure comes back with a citation anchor.",
    ),
    (
        "Name the four controls that stop the agent from making a credit decision.",
        "Cedar forbid on the decision and notice tools at the Gateway; ActionGuardHook in the agent loop; "
        "the decision-language check on memos and responses (also enforced when filing); the Guardrail "
        "denied topic on the model.",
    ),
    (
        "Which control still works if someone edits the agent's Python code?",
        "AgentCore Policy at the Gateway. It sits outside the agent's code and evaluates every tool call.",
    ),
    (
        "How does a tool call carry the analyst's entitlements?",
        "The Runtime forwards the analyst's own Cognito access token to the Gateway. Cedar reads "
        "lending_role and portfolio as principal tags, and the LOS Lambda checks the deal belongs to the portfolio.",
    ),
    (
        "What stops the model passing a portfolio the user is not entitled to?",
        "Cedar requires `context.input.portfolio` to equal the `portfolio` claim in the token.",
    ),
    (
        "Why is DSCR computed on the amortizing payment even during interest-only periods?",
        "Interest-only payments are smaller, so DSCR would look stronger than the loan can sustain once "
        "amortization starts. Sizing on the amortizing payment is the conservative convention.",
    ),
    (
        "What does the farm stress test walk through, month by month?",
        "Cash from the opening balance, adding revenue and subtracting operating costs, family living, existing "
        "debt, April taxes and the annual payment at peak harvest, drawing on the operating line when negative.",
    ),
    (
        "Why is offline citation faithfulness 100%, and which number should you quote?",
        "Offline memos come from a template that always cites correctly, so 100% only checks the harness. "
        "Quote the faithfulness from a live or remote run, where the model writes the memo.",
    ),
    (
        "Why is offline metric correctness about 90%, and why not add keywords to fix it?",
        "Misses come from unknown T-12 labels such as RUBS Income. Adding keywords just to raise the score "
        "games the eval; unknown labels go to the analyst, and in live mode the agent maps them with a rationale.",
    ),
    (
        "How is ground truth produced for the synthetic deals?",
        "The generator builds deals from true values and computes labels with an independent reference "
        "implementation, not the production calculators.",
    ),
    (
        "What happens in CI/CD if the staging evaluation gate fails?",
        "The staging endpoint is rolled back to the previous Runtime version and production is not deployed.",
    ),
    (
        "How do you roll back production?",
        "Point the prod Runtime endpoint at an earlier version: `python -m scripts.rollback --previous`. No rebuild.",
    ),
    (
        "Where do token cost and latency per run appear?",
        "As `underwriting.*` attributes on the run span in AgentCore Observability, and in the eval report.",
    ),
    (
        "What does ECOA / Reg B require that makes a human decision necessary?",
        "Specific principal reasons for adverse action, owned by the creditor's accountable decision-maker "
        "under delegated authority.",
    ),
]


def notes_page(title: str = "Notes") -> list:
    return [PageBreak(), Paragraph(title, S["h2"]), NoteLines(PAGE[1] - 2 * MARGIN - 0.9 * inch)]


# ----------------------------------------------------------------------------- document
class Doc(BaseDocTemplate):
    def __init__(self, path: str):
        super().__init__(
            path,
            pagesize=PAGE,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=MARGIN,
            bottomMargin=MARGIN + 0.1 * inch,
            title="Agentic Underwriting Assistant: Study Guide",
            author="Ravi Chandra",
            subject="Bedrock AgentCore and Strands Agents project guide",
            creator="scripts/build_kindle_pdf.py",
        )
        frame = Frame(
            MARGIN,
            MARGIN + 0.15 * inch,
            WIDTH,
            PAGE[1] - 2 * MARGIN - 0.15 * inch,
            id="f",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates([PageTemplate("p", [frame], onPage=self._footer)])
        self._n = 0

    def beforeDocument(self):
        self._n = 0  # keep bookmark keys identical across multiBuild passes so the TOC converges

    def _footer(self, canv, doc):
        if doc.page == 1:
            return
        canv.setFont("Sans", 8.5)
        canv.setFillColor(GREY)
        canv.drawString(MARGIN, MARGIN - 0.05 * inch, "Agentic Underwriting Assistant · Study Guide")
        canv.drawRightString(PAGE[0] - MARGIN, MARGIN - 0.05 * inch, str(doc.page))

    def afterFlowable(self, f):
        if isinstance(f, Heading):
            self._n += 1
            key = f"h{self._n}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(f.plain, key, level=min(f.level, 2), closed=f.level > 0)
            if f.toc and f.level <= 1:
                self.notify("TOCEntry", (f.level, f.plain, self.page, key))


def part(title: str, subtitle: str = "") -> list:
    items = [PageBreak(), Heading(title, 0, S["h1"])]
    if subtitle:
        items.append(p(subtitle, "quote"))
    return items


def build() -> Path:
    docs = {
        n: (ROOT / "docs" / f"{n}.md").read_text()
        for n in ("ARCHITECTURE", "BUILD_GUIDE", "INTERVIEW_PREP", "RESUME")
    }
    readme = (ROOT / "README.md").read_text()
    # README: keep the narrative and evaluation; the docs list and layout are covered elsewhere.
    readme = readme.split("## Documentation")[0]

    story: list = [
        Spacer(1, 1.3 * inch),
        Paragraph("Agentic Credit Underwriting Assistant", S["cover"]),
        Spacer(1, 10),
        Paragraph("for CRE and Agricultural Lending", S["coversub"]),
        Spacer(1, 0.45 * inch),
        Paragraph(
            "Amazon Bedrock AgentCore · Strands Agents · MCP · Cedar · OpenTelemetry · AWS CDK", S["coversub"]
        ),
        Spacer(1, 0.6 * inch),
        Paragraph("Study guide: build it, deploy it, explain it", S["h3"]),
        Spacer(1, 0.25 * inch),
        Paragraph(
            "Reference implementation on synthetic data. Generated from the repository docs; "
            "re-run <font name='Mono' size='9'>python -m scripts.build_kindle_pdf</font> after they change.",
            S["small"],
        ),
        PageBreak(),
        Paragraph("Contents", S["h1"]),
    ]
    toc = TableOfContents(levelStyles=[S["toc1"], S["toc2"]], dotsMinLevel=0)
    story.append(toc)

    story += part("How to use this guide")
    story += [
        p(
            "This guide covers the whole project in five parts: what it is, how it works, how to build and "
            "deploy it, how to present it in interviews, and how to put it on your resume. It ends with "
            "glossaries, a self-check quiz and note pages for your pen."
        ),
        p(
            "**Reading on the Scribe.** Tap a line in Contents to jump to it, or use the bookmark list. "
            "Write on the margins and the ruled Notes pages; take a photo or export the annotated PDF if you "
            "want your notes back on the laptop."
        ),
        Paragraph("Seven-day plan", S["h2"]),
        table(STUDY_PLAN),
        Spacer(1, 10),
        Paragraph("The two ideas everything hangs on", S["h2"]),
        *bullets(
            [
                "**The model never does the math.** All figures come from deterministic Python. The model "
                "orchestrates tools, classifies unknown labels, and writes narrative that cites figures.",
                "**The credit decision stays human.** The agent prepares; an accountable officer decides. "
                "Enforced in infrastructure, in code and in the evaluation.",
            ]
        ),
    ]

    story += part("Part 1 · Project Overview", "What the system does and how well it does it.")
    story += md_to_flowables(readme, [SYSTEM_GLANCE], h1_level=1, skip_h1=True)
    story += notes_page()

    story += part("Part 2 · Architecture", "Request flow, controls, identity, data model and trade-offs.")
    story += md_to_flowables(docs["ARCHITECTURE"], [SEQUENCE], h1_level=1, skip_h1=True)
    story += notes_page()

    story += part("Part 3 · Build Guide", "From clone to a deployed, verified agent. Do the phases in order.")
    story += md_to_flowables(docs["BUILD_GUIDE"], [], h1_level=1, skip_h1=True)
    story += notes_page("Deployment log: what I changed and why")

    story += part("Part 4 · Interview Prep", "How to explain and defend every claim.")
    story += md_to_flowables(docs["INTERVIEW_PREP"], [], h1_level=1, skip_h1=True)
    story += notes_page("My pitch, in my words")

    story += part("Part 5 · Resume and LinkedIn", "Bullets tied to evidence in the repository.")
    story += md_to_flowables(docs["RESUME"], [], h1_level=1, skip_h1=True)
    story += [
        KeepTogether(
            [
                Paragraph("My measured numbers", S["h2"]),
                table(
                    [
                        ["Measure", "Live run", "Remote run"],
                        ["Extraction accuracy", "", ""],
                        ["Metric correctness", "", ""],
                        ["Citation faithfulness", "", ""],
                        ["Forbidden tool executions", "", ""],
                        ["Mean latency per deal", "", ""],
                        ["Tokens / cost per deal", "", ""],
                    ],
                    row_height=0.42 * inch,
                ),
            ]
        )
    ]

    story += part("Appendix A · Lending glossary")
    story += [table(GLOSSARY_LENDING)]
    story += part("Appendix B · Technology glossary")
    story += [table(GLOSSARY_TECH)]

    story += part("Appendix C · Self-check quiz", "Answer from memory first; answers follow.")
    for n, (q, _) in enumerate(QUIZ, 1):
        story.append(KeepTogether([p(f"**{n}.** {q}"), NoteLines(0.75 * inch)]))
        story.append(Spacer(1, 4))
    story += part("Appendix D · Quiz answers")
    for n, (q, a) in enumerate(QUIZ, 1):
        story.append(KeepTogether([p(f"**{n}. {q}**"), p(a)]))

    story += notes_page()
    story += notes_page()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    Doc(str(OUT)).multiBuild(story)
    return OUT


if __name__ == "__main__":
    print(build())
