"""The made-up job ads the demo's fake job boards return, with the score each one gets.

Every company here is a stock fictional name (Globex, Initech, Contoso, Hooli, Vandelay) or
"Example …", so none can be mistaken for a real employer. `score` is what the fake scorer hands back (None: the
filters drop the ad before scoring — an excluded keyword, a language not in the profile).
"""

_LEAD_FC = (
    "We are looking for a {title} to lead a team of four controllers and accountants. "
    "You will own the monthly close and the group reporting, work closely with sales and "
    "operations, and mentor the team. Requirements: several years as a controller, strong "
    "IFRS, experience with SAP or another large ERP, advanced Excel and Power BI, and "
    "experience leading people. A CMA or similar qualification is a plus. Hybrid work from "
    "our Copenhagen office."
)

_HEAD_FIN = (
    "As {title} you will build and run the finance function: hire, set the reporting and "
    "planning calendar and give the business numbers it can steer by. You report to the CEO "
    "and work with sales, operations and the board. We expect a track record of leading "
    "finance teams, hands-on budgeting and forecasting, IFRS, and the ability to explain the "
    "numbers to non-financial stakeholders. Our systems are Dynamics 365 and Power BI. "
    "Office in Copenhagen, two days a week from home."
)

_GROUP = (
    "We are hiring a {title} to own the consolidation of our twelve subsidiaries. "
    "You will run the group close, the intercompany reconciliations and the external audit, "
    "set reporting standards and coach the local controllers. You have deep experience with "
    "IFRS, group consolidation and internal controls, and you enjoy making a close faster and "
    "cleaner. Based in Copenhagen."
)

_FPA = (
    "Our {title} leads the planning team behind our budgets, forecasts and board reporting. "
    "You will own the planning platform (Anaplan), set up the SaaS metrics the board follows "
    "and grow a team of four. Strong financial modelling and experience with subscription "
    "revenue required; a background in a software company is a plus. Hybrid, Copenhagen."
)

_ACC_MANAGER = (
    "As {title} you manage a team of accountants in our banking operations. You will "
    "prioritise the work, run the monthly reconciliations and make sure the books close on "
    "time. Experience with Danish GAAP and banking regulation, plus fluent Danish for the "
    "work with the authorities, is required. Copenhagen, on-site."
)

_DANISH = (
    "Vi søger en {title} til vores økonomiafdeling. Du skal udarbejde budgetter og "
    "regnskaber for kommunens forvaltninger og formidle resultaterne til ledelsen. Vi "
    "forventer erfaring med offentlig økonomi og Excel, og du taler og skriver flydende dansk. "
    "Arbejdssted er rådhuset."
)

_OFF_TARGET = (
    "We are looking for a {title} to join our team in Copenhagen. You will take part in "
    "the daily running of the department, coordinate with colleagues and suppliers, and "
    "help us improve our processes. We offer a good working environment and a competitive "
    "salary. Send your application as soon as possible."
)


POSTINGS = {
    "jobindex": [
        {"title": "Head of Finance", "company": "Globex Energy", "text": _HEAD_FIN,
         "score": 0.91, "reason": "Builds a finance function from scratch, as you did at Acme Corp; budgeting and stakeholder work match.",
         "matching": ["leading finance teams", "budgeting and forecasting", "IFRS", "Power BI"], "missing": ["energy sector"]},
        {"title": "Senior Financial Controller", "company": "Initech Insurance", "text": _LEAD_FC,
         "score": 0.86, "reason": "Lead role with mentoring and the monthly close; your five-day close at Acme Corp is direct evidence.",
         "matching": ["IFRS", "SAP", "month-end close", "mentoring"], "missing": ["insurance domain"]},
        {"title": "Accounting Manager", "company": "Example Bank", "text": _ACC_MANAGER,
         "score": 0.58, "reason": "Management fits, but Danish GAAP for banks is not in the CV and fluent Danish is required.",
         "matching": ["team leadership", "reconciliations"], "missing": ["banking regulation", "fluent Danish"]},
        {"title": "Warehouse Coordinator", "company": "Example Logistics", "text": _OFF_TARGET,
         "score": 0.08, "reason": "Operations role with no finance content."},
        {"title": "Junior Accountant", "company": "Example Media", "text": _LEAD_FC, "score": None},
        {"title": "Økonomicontroller", "company": "Eksempel Kommune", "text": _DANISH, "score": None},
    ],
    "thehub": [
        {"title": "Group Controller", "company": "Contoso Pay", "text": _GROUP,
         "score": 0.88, "reason": "Group consolidation and IFRS reporting across subsidiaries match your Big Bank work and CMA.",
         "matching": ["group consolidation", "IFRS", "external audit", "internal controls"], "missing": ["payments domain"]},
        {"title": "FP&A Lead", "company": "Hooli Labs", "text": _FPA,
         "score": 0.67, "reason": "Leadership fits; the role leans on Anaplan and SaaS metrics, which the CV only touches.",
         "matching": ["team leadership", "budgeting", "forecasting"], "missing": ["Anaplan", "SaaS metrics", "subscription revenue"]},
        {"title": "Office Manager", "company": "Contoso Pay", "text": _OFF_TARGET,
         "score": 0.05, "reason": "Administrative role; nothing in the CV is relevant."},
    ],
    "workable": [
        {"title": "Financial Controller, Planning", "company": "Vandelay Forecasting", "text": _LEAD_FC,
         "score": 0.82, "reason": "Rolling forecasts and budgeting are a strong fit; the controller scope matches.",
         "matching": ["rolling forecast", "budgeting", "Power BI", "IFRS"], "missing": ["energy markets"]},
        {"title": "Financial Controller", "company": "Example Health", "text": _GROUP,
         "score": 0.61, "reason": "Solid overlap but a single-entity role below your target seniority.",
         "matching": ["IFRS", "month-end close", "internal controls"], "missing": ["healthcare reimbursement"]},
        {"title": "Customer Success Manager", "company": "Vandelay Forecasting", "text": _OFF_TARGET,
         "score": 0.12, "reason": "Customer-facing role outside finance."},
    ],
}

# How many results each fake board reports per search keyword, for the live progress lines.
KEYWORD_HITS = {
    "jobindex": [("financial controller", 41), ("head of finance", 6), ("accounting manager", 9)],
    "thehub": [("financial controller", 17), ("finance manager", 4)],
    "workable": [("financial controller", 23), ("group controller", 3)],
}

# What `follow` finds for each employer the boards turned up (the rest: no feed found), and
# what `collect` then reads from each followed feed. A feed repeats the board's ad (dedup keeps
# one copy) and adds the ones the boards never showed.
FEEDS = {
    "Globex Energy": ("greenhouse", "globex", [
        {"title": "Head of Finance", "text": _HEAD_FIN},
        {"title": "Finance Business Partner, Energy Trading", "text": _LEAD_FC,
         "score": 0.79, "reason": "Partners with the business on budgets and forecasts; your Big Bank forecasting work fits.",
         "matching": ["business partnering", "forecasting", "Power BI"], "missing": ["energy trading"]},
    ]),
    "Initech Insurance": ("greenhouse", "initech", [
        {"title": "Senior Financial Controller", "text": _LEAD_FC},
        {"title": "Head of Group Reporting", "text": _HEAD_FIN,
         "score": 0.84, "reason": "Builds and runs group reporting; the reporting calendar and close you built at Acme Corp match.",
         "matching": ["group reporting", "IFRS", "stakeholder communication"], "missing": ["insurance domain"]},
    ]),
    "Vandelay Forecasting": ("greenhouse", "vandelay", [
        {"title": "Financial Controller, Planning", "text": _LEAD_FC},
    ]),
}
