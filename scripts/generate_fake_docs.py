"""Generate fake government documents as .txt files for demos and testing.

Each document type gets its own folder:

  <out>/policies/  <out>/sops/  <out>/circulars/
  <out>/guidelines/  <out>/reports/  <out>/meeting_minutes/

All agencies, people and figures are fictional. Output is reproducible for a given --seed.

Usage:
  python scripts/generate_fake_docs.py                     # 5 of each type into sample_data/
  python scripts/generate_fake_docs.py --count 20 --out data/fake --seed 7
"""

import argparse
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

AGENCIES = {
    "DDS": "Department of Digital Services",
    "MPW": "Ministry of Public Works",
    "DHW": "Department of Health and Wellbeing",
    "MEC": "Ministry of Education and Culture",
    "DFT": "Department of Finance and Treasury",
    "LAD": "Land Administration Department",
}

TOPICS = {
    "Remote Work": ["eligibility", "equipment", "working hours", "data security at home", "performance review"],
    "Procurement": ["quotation thresholds", "vendor registration", "tender evaluation", "conflict of interest", "payment terms"],
    "Data Protection": ["data classification", "personal data handling", "retention periods", "breach reporting", "access control"],
    "Travel and Claims": ["approval levels", "per diem rates", "accommodation limits", "claim submission", "receipts"],
    "Records Management": ["file naming", "archiving", "disposal schedules", "digitisation", "access logs"],
    "Workplace Safety": ["hazard reporting", "fire drills", "first aid", "incident investigation", "protective equipment"],
    "Public Complaints": ["intake channels", "response times", "escalation", "case closure", "satisfaction surveys"],
    "Cloud Adoption": ["approved providers", "workload classification", "cost monitoring", "backup", "exit planning"],
    "Leave Management": ["annual leave", "medical leave", "emergency leave", "carry-forward", "approval workflow"],
    "Asset Management": ["asset tagging", "annual stock take", "transfer of assets", "write-off", "loss reporting"],
}

FIRST_NAMES = ["Aisha", "Daniel", "Mei Ling", "Rajesh", "Nurul", "James", "Siti", "Kumar", "Grace", "Hafiz", "Lina", "Victor"]
LAST_NAMES = ["Rahman", "Tan", "Wong", "Abdullah", "Lim", "Nair", "Chong", "Ibrahim", "Lee", "Goh", "Osman", "Pillai"]
TITLES = ["Director", "Deputy Director", "Senior Manager", "Principal Assistant Secretary", "Head of Unit", "Senior Officer"]

TYPES = ["policies", "sops", "circulars", "guidelines", "reports", "meeting_minutes"]

# A "brown M&M's" canary (after Van Halen's tour rider): one fixed document with facts
# that appear nowhere else (Form LAD-0451, ext. 7731). It is written on every run so
# --clean never loses it. It belongs to the Land Administration Department, which the
# demo officer cannot search, so it checks two things:
#   - an admin asking about it gets Form LAD-0451 cited from LAD/CIR/2025/099 (retrieval works)
#   - the demo officer asking the same question gets no answer (collection access control works)
# See the canary-* questions in evals/golden_set.example.jsonl.
CANARY_NAME = "LAD-CIR-2025-099_meeting_room_confectionery"
CANARY_TEXT = """LAND ADMINISTRATION DEPARTMENT
============================================================
CIRCULAR
Title: Circular No. 99 of 2025: Confectionery in Meeting Rooms
Reference No.: LAD/CIR/2025/099
Date: 01 April 2025
To: All Heads of Department and Staff
Classification: Internal
============================================================

1. PURPOSE
This circular sets the standard for confectionery provided in meeting rooms for briefings attended by external contractors.

2. REQUIREMENTS
2.1 A bowl of chocolate-coated sweets must be provided at every briefing attended by external contractors.
2.2 All brown-coloured sweets must be removed from the bowl before the briefing starts.
2.3 The Unit Coordinator must confirm compliance on Form LAD-0451 (Confectionery Checklist) and file it within 2 working days.

3. RATIONALE
Compliance with this circular shows that the full briefing pack, including its safety and site access requirements, has been read in detail.

4. ENQUIRIES
Enquiries may be directed to the Facilities Unit at ext. 7731.

Issued by: Rina Halim, Principal Assistant Secretary"""


def person(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def official(rng: random.Random) -> str:
    return f"{person(rng)}, {rng.choice(TITLES)}"


def rand_date(rng: random.Random) -> date:
    return date(2022, 1, 1) + timedelta(days=rng.randint(0, 365 * 4))


def fmt(d: date) -> str:
    return d.strftime("%d %B %Y")


def header(kind: str, ref: str, agency: str, title: str, d: date, extra: list[str] | None = None) -> str:
    lines = [
        f"{AGENCIES[agency].upper()}",
        "=" * 60,
        f"{kind.upper()}",
        f"Title: {title}",
        f"Reference No.: {ref}",
        f"Date: {fmt(d)}",
        *(extra or []),
        "Classification: Internal",
        "=" * 60,
        "",
    ]
    return "\n".join(lines)


def policy(rng: random.Random, n: int) -> tuple[str, str]:
    agency = rng.choice(list(AGENCIES))
    topic, aspects = rng.choice(list(TOPICS.items()))
    d = rand_date(rng)
    ref = f"{agency}/POL/{d.year}/{n:03d}"
    title = f"{topic} Policy"
    body = [
        header("Policy", ref, agency, title, d, [f"Version: {rng.randint(1, 4)}.{rng.randint(0, 9)}", f"Effective: {fmt(d + timedelta(days=30))}"]),
        "1. PURPOSE",
        f"This policy sets out the principles and requirements governing {topic.lower()} across the "
        f"{AGENCIES[agency]}. It aims to ensure consistency, accountability and compliance with applicable regulations.",
        "",
        "2. SCOPE",
        "This policy applies to all permanent, contract and temporary staff, as well as consultants engaged by the department.",
        "",
        "3. POLICY STATEMENTS",
    ]
    for i, aspect in enumerate(rng.sample(aspects, k=rng.randint(3, len(aspects))), start=1):
        body.append(f"3.{i} {aspect.capitalize()}")
        body.append(
            f"    All staff shall comply with the requirements on {aspect} as described in this section. "
            f"Exceptions require written approval from the {rng.choice(TITLES)} and must be reviewed every "
            f"{rng.choice([6, 12, 24])} months."
        )
    body += [
        "",
        "4. ROLES AND RESPONSIBILITIES",
        "- Heads of Unit are responsible for enforcing this policy within their units.",
        f"- The Policy Owner ({official(rng)}) is responsible for reviewing this policy annually.",
        "- All staff are responsible for reading and complying with this policy.",
        "",
        "5. NON-COMPLIANCE",
        "Non-compliance may result in disciplinary action in accordance with the Public Service Conduct Regulations.",
        "",
        "6. REVIEW",
        f"This policy will be reviewed no later than {fmt(d + timedelta(days=365))}.",
        "",
        f"Approved by: {official(rng)}",
    ]
    return f"{ref.replace('/', '-')}_{slug(title)}", "\n".join(body)


def sop(rng: random.Random, n: int) -> tuple[str, str]:
    agency = rng.choice(list(AGENCIES))
    topic, aspects = rng.choice(list(TOPICS.items()))
    aspect = rng.choice(aspects)
    d = rand_date(rng)
    ref = f"{agency}/SOP/{d.year}/{n:03d}"
    title = f"Standard Operating Procedure for {aspect.title()} ({topic})"
    body = [
        header("Standard Operating Procedure", ref, agency, title, d, [f"Related Policy: {agency}/POL/{d.year - rng.randint(0, 2)}/{rng.randint(1, 20):03d}"]),
        "1. OBJECTIVE",
        f"To describe the step-by-step procedure for {aspect} under the {topic} framework.",
        "",
        "2. DEFINITIONS",
        "- Requester: the officer initiating the process.",
        "- Approver: the officer with delegated authority to approve the request.",
        "- Unit Coordinator: the officer who maintains records for the unit.",
        "",
        "3. PROCEDURE",
    ]
    steps = [
        "The Requester completes the relevant form in the internal portal.",
        "The Requester attaches supporting documents and submits the form.",
        f"The Unit Coordinator verifies completeness within {rng.randint(1, 3)} working days.",
        f"The Approver reviews and approves or rejects the request within {rng.randint(2, 7)} working days.",
        "If rejected, the Approver records the reason and returns the request to the Requester.",
        "Upon approval, the Unit Coordinator updates the register and notifies the Requester by email.",
        f"Records are retained for {rng.choice([3, 5, 7])} years in accordance with the Records Management Policy.",
    ]
    body += [f"Step {i}: {s}" for i, s in enumerate(steps, start=1)]
    body += [
        "",
        "4. TURNAROUND TIME",
        f"The end-to-end process shall not exceed {rng.randint(5, 15)} working days.",
        "",
        "5. FORMS AND TEMPLATES",
        f"- Form {agency}-{rng.randint(100, 999)}: Request Form",
        f"- Form {agency}-{rng.randint(100, 999)}: Approval Checklist",
        "",
        f"Prepared by: {official(rng)}",
        f"Approved by: {official(rng)}",
    ]
    return f"{ref.replace('/', '-')}_{slug(aspect)}", "\n".join(body)


def circular(rng: random.Random, n: int) -> tuple[str, str]:
    agency = rng.choice(list(AGENCIES))
    topic, aspects = rng.choice(list(TOPICS.items()))
    aspect = rng.choice(aspects)
    d = rand_date(rng)
    ref = f"{agency}/CIR/{d.year}/{n:03d}"
    title = f"Circular No. {n} of {d.year}: Updates to {aspect.title()}"
    old, new = sorted(rng.sample([3, 5, 7, 10, 14, 30], k=2), reverse=True)
    body = [
        header("Circular", ref, agency, title, d, ["To: All Heads of Department and Staff"]),
        "1. PURPOSE",
        f"This circular informs all staff of changes to requirements on {aspect} under the {topic} Policy.",
        "",
        "2. BACKGROUND",
        f"A review conducted in {d.year - 1} found inconsistencies in how units apply the current requirements, "
        f"resulting in delays and audit findings.",
        "",
        "3. CHANGES",
        f"3.1 Effective {fmt(d + timedelta(days=14))}, the processing period is reduced from {old} to {new} working days.",
        "3.2 All submissions must be made through the internal portal. Paper submissions will no longer be accepted.",
        f"3.3 Units must report monthly compliance figures to the {rng.choice(TITLES)} by the 5th of each month.",
        "",
        "4. SUPERSESSION",
        f"This circular supersedes Circular No. {rng.randint(1, 20)} of {d.year - rng.randint(1, 3)}.",
        "",
        "5. ENQUIRIES",
        f"Enquiries may be directed to {person(rng)} at ext. {rng.randint(2000, 2999)}.",
        "",
        f"Issued by: {official(rng)}",
    ]
    return f"{ref.replace('/', '-')}_{slug(aspect)}", "\n".join(body)


def guideline(rng: random.Random, n: int) -> tuple[str, str]:
    agency = rng.choice(list(AGENCIES))
    topic, aspects = rng.choice(list(TOPICS.items()))
    d = rand_date(rng)
    ref = f"{agency}/GL/{d.year}/{n:03d}"
    title = f"Guidelines on {topic}"
    body = [
        header("Guideline", ref, agency, title, d),
        "INTRODUCTION",
        f"These guidelines provide practical advice to help staff apply the {topic} Policy. "
        "They are advisory and should be read together with the relevant policy and SOPs.",
        "",
    ]
    for aspect in rng.sample(aspects, k=3):
        body += [
            aspect.upper(),
            f"- Do: document every decision related to {aspect} and keep evidence on file.",
            f"- Do: consult your Head of Unit when in doubt about {aspect}.",
            "- Don't: bypass the approval workflow, even for urgent cases.",
            f"- Tip: most issues with {aspect} raised in audits relate to missing records.",
            "",
        ]
    body += [
        "FREQUENTLY ASKED QUESTIONS",
        f"Q: Who approves exceptions?\nA: The {rng.choice(TITLES)} of the relevant division.",
        f"Q: How long does approval take?\nA: Typically {rng.randint(3, 10)} working days.",
        "",
        f"Contact: {person(rng)}, Policy and Planning Unit",
    ]
    return f"{ref.replace('/', '-')}_{slug(topic)}", "\n".join(body)


def report(rng: random.Random, n: int) -> tuple[str, str]:
    agency = rng.choice(list(AGENCIES))
    topic, aspects = rng.choice(list(TOPICS.items()))
    d = rand_date(rng)
    quarter = (d.month - 1) // 3 + 1
    ref = f"{agency}/RPT/{d.year}/{n:03d}"
    title = f"Q{quarter} {d.year} Performance Report: {topic}"
    cases = rng.randint(200, 5000)
    resolved = rng.randint(int(cases * 0.6), cases)
    budget = rng.randint(500, 20000) * 1000
    spent = int(budget * rng.uniform(0.5, 1.1))
    body = [
        header("Report", ref, agency, title, d, [f"Prepared by: {official(rng)}"]),
        "1. EXECUTIVE SUMMARY",
        f"In Q{quarter} {d.year}, the department handled {cases:,} cases related to {topic.lower()}, "
        f"of which {resolved:,} ({resolved / cases:.0%}) were resolved within the service standard.",
        "",
        "2. KEY PERFORMANCE INDICATORS",
        f"- Cases received: {cases:,}",
        f"- Cases resolved: {resolved:,}",
        f"- Average processing time: {rng.uniform(2, 15):.1f} working days",
        f"- Customer satisfaction: {rng.uniform(65, 95):.1f}%",
        "",
        "3. BUDGET",
        f"- Allocated: RM {budget:,}",
        f"- Spent: RM {spent:,} ({spent / budget:.0%} utilisation)",
        "",
        "4. ISSUES AND RISKS",
    ]
    body += [f"- Delays related to {a} due to staffing constraints." for a in rng.sample(aspects, k=2)]
    body += [
        "",
        "5. RECOMMENDATIONS",
        f"- Digitise remaining manual processes for {rng.choice(aspects)} by Q{min(quarter + 2, 4)} {d.year}.",
        f"- Recruit {rng.randint(2, 10)} additional officers to reduce backlog.",
        "- Conduct refresher training for all units.",
    ]
    return f"{ref.replace('/', '-')}_{slug(topic)}", "\n".join(body)


def minutes(rng: random.Random, n: int) -> tuple[str, str]:
    agency = rng.choice(list(AGENCIES))
    topics = rng.sample(list(TOPICS), k=3)
    d = rand_date(rng)
    ref = f"{agency}/MIN/{d.year}/{n:03d}"
    title = f"Minutes of the {rng.choice(['Management', 'Steering Committee', 'Operations', 'ICT Committee'])} Meeting No. {n}/{d.year}"
    start = rng.randint(9, 14)
    chair = official(rng)
    attendees = [official(rng) for _ in range(rng.randint(4, 7))]
    body = [
        header("Meeting Minutes", ref, agency, title, d, [f"Time: {start}:00", f"Venue: Meeting Room {rng.randint(1, 8)}, Level {rng.randint(2, 12)}"]),
        f"CHAIRPERSON: {chair}",
        "ATTENDEES:",
        *[f"  - {a}" for a in attendees],
        "",
        "1. CONFIRMATION OF PREVIOUS MINUTES",
        f"The minutes of Meeting No. {max(n - 1, 1)}/{d.year} were confirmed without amendment.",
        "",
    ]
    for i, t in enumerate(topics, start=2):
        owner = rng.choice(attendees).split(",")[0]
        body += [
            f"{i}. {t.upper()}",
            f"{i}.1 The meeting discussed the progress of {t.lower()} initiatives and noted {rng.choice(['good progress', 'delays', 'budget pressure', 'pending approvals'])}.",
            f"{i}.2 Decision: The meeting agreed to {rng.choice(['proceed with the proposal', 'defer the decision to the next meeting', 'form a working group', 'request a detailed cost estimate'])}.",
            f"{i}.3 Action: {owner} to report back by {fmt(d + timedelta(days=rng.randint(14, 45)))}.",
            "",
        ]
    body += [
        f"{len(topics) + 2}. ANY OTHER MATTERS",
        "No other matters were raised.",
        "",
        f"The meeting adjourned at {start + rng.randint(1, 3)}:{rng.choice(['00', '15', '30', '45'])}.",
        "",
        f"Recorded by: {person(rng)}, Secretariat",
        f"Confirmed by: {chair}",
    ]
    return f"{ref.replace('/', '-')}_{slug(title)}", "\n".join(body)


GENERATORS = {
    "policies": policy,
    "sops": sop,
    "circulars": circular,
    "guidelines": guideline,
    "reports": report,
    "meeting_minutes": minutes,
}


def slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")[:60]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=5, help="documents per type (default 5)")
    parser.add_argument("--out", type=Path, default=Path("sample_data"), help="output folder (default sample_data/)")
    parser.add_argument("--seed", type=int, default=42, help="random seed for reproducible output")
    parser.add_argument("--clean", action="store_true", help="delete the output folder first")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    if args.clean and args.out.exists():
        shutil.rmtree(args.out)

    for kind in TYPES:
        folder = args.out / kind
        folder.mkdir(parents=True, exist_ok=True)
        for n in range(1, args.count + 1):
            name, text = GENERATORS[kind](rng, n)
            (folder / f"{name}.txt").write_text(text + "\n", encoding="utf-8")
        print(f"{kind:16} {args.count} files -> {folder}")

    canary = args.out / "circulars" / f"{CANARY_NAME}.txt"
    canary.write_text(CANARY_TEXT + "\n", encoding="utf-8")
    print(f"{'canary':16} 1 file  -> {canary}")


if __name__ == "__main__":
    main()
