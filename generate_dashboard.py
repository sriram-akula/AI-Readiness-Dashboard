"""
generate_dashboard.py
Pulls live responses from the published Google Sheet CSV, recomputes every
score exactly the way the original dashboard was built, and writes a fresh
dashboard.html ready to publish (e.g. via GitHub Pages).

Usage:
    python generate_dashboard.py <csv_url> [output_path]

The CSV URL is your Google Sheet's "Publish to web -> CSV" link, e.g.
https://docs.google.com/spreadsheets/d/e/XXXXX/pub?output=csv
"""

import sys
import json
import pandas as pd

DEFAULT_CSV_URL = "https://docs.google.com/spreadsheets/d/1GPqALG0AJ6F7yUUmFzSnIKhnWOOW7zowsKzhUou8NDs/export?format=csv&gid=0"
TEMPLATE_PATH = "dashboard_template.html"
DEFAULT_OUTPUT = "dashboard.html"

COLS = {
    'role': 'a) What is your role?',
    'industry': 'b) Industry',
    'size': 'c) Employee Strength',
    'maturity': "1. Which best describes your organization's current AI maturity?",
    'skills_infra': "2. How adequate are your organization's AI skills, resources and infrastructure?",
    'governance': "3. How established are your AI governance structures?",
    'leadership_prep': "4. How prepared is your organization to support AI adoption through leadership, learning and change management?",
    'workforce_ready': "5. How would you describe your workforce's readiness to adapt to AI-driven changes?",
    'perception': "6 . How do employees primarily perceive AI today? (you can select more than 1)",
    'barrier': "7. What is the biggest barrier to workforce AI readiness? (you can select more than 1)",
    'leaders_encourage': "8. Senior leaders actively encourage experimentation with AI.",
    'investment': "9. Which area receives the greatest AI investment?",
    'prioritization': "10 . How are AI initiatives prioritized? (you can select more than 1)",
    'skills_improve': "11. Which AI skills need the most improvement? (you can select more than 1)",
    'challenges': "12. Primary operational challenges? (you can select more than 1)",
    'owner': "13. Who owns AI adoption?",
    'impact_track': "14.How is AI impact tracked?(you can select more than 1)",
}

MAT_MAP = {'No implementation': 0, 'Early experimentation': 33, 'Functional deployment': 67, 'Enterprise transformation': 100}
ORD5 = {'Very Low': 0, 'Low': 25, 'Moderate': 50, 'High': 75, 'Very High': 100}
AGREE_MAP = {'Strongly Disagree': 0, 'Disagree': 25, 'Neutral': 50, 'Agree': 75, 'Strongly agree': 100, 'Strongly Agree': 100}


def load_data(csv_url: str) -> pd.DataFrame:
    df = pd.read_csv(csv_url)
    # Only rename columns that actually exist, so small header drift doesn't crash the run
    rename_map = {v: k for k, v in COLS.items() if v in df.columns}
    missing = [v for v in COLS.values() if v not in df.columns]
    if missing:
        print("WARNING - columns not found in sheet (skipped):", missing, file=sys.stderr)
    df = df.rename(columns=rename_map)
    # Google Sheets sometimes has blank spacer rows between responses -- drop them
    if 'maturity' in df.columns:
        df = df[df['maturity'].notna()].reset_index(drop=True)
    return df


def score(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['maturity_score'] = df.get('maturity', pd.Series(dtype=object)).map(MAT_MAP)
    df['skills_infra_score'] = df.get('skills_infra', pd.Series(dtype=object)).map(ORD5)
    df['governance_score'] = df.get('governance', pd.Series(dtype=object)).map(ORD5)
    df['leadership_score'] = df.get('leadership_prep', pd.Series(dtype=object)).map(ORD5)
    df['workforce_score'] = df.get('workforce_ready', pd.Series(dtype=object)).map(ORD5)
    df['leaders_encourage_score'] = df.get('leaders_encourage', pd.Series(dtype=object)).map(AGREE_MAP)
    df['org_readiness_score'] = df[['skills_infra_score', 'governance_score']].mean(axis=1)
    df['overall_score'] = df[['maturity_score', 'leadership_score', 'workforce_score', 'org_readiness_score']].mean(axis=1)
    return df


def kpis(sub: pd.DataFrame):
    n = len(sub)
    if n == 0:
        return None
    r = lambda s: round(float(s), 1) if pd.notna(s) else 0.0
    return {
        'n': n,
        'overall': r(sub['overall_score'].mean()),
        'maturity': r(sub['maturity_score'].mean()),
        'leadership': r(sub['leadership_score'].mean()),
        'workforce': r(sub['workforce_score'].mean()),
        'org_readiness': r(sub['org_readiness_score'].mean()),
        'governance': r(sub['governance_score'].mean()),
        'skills_infra': r(sub['skills_infra_score'].mean()),
        'leaders_encourage': r(sub['leaders_encourage_score'].mean()),
    }


def multi_count(df: pd.DataFrame, colname: str):
    counts = {}
    if colname not in df.columns:
        return counts
    for val in df[colname].dropna():
        for item in [x.strip() for x in str(val).split(';')]:
            if item:
                counts[item] = counts.get(item, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def build_data_block(df: pd.DataFrame) -> str:
    df = score(df)
    overall = kpis(df)

    industry = {"All Industries": overall}
    if 'industry' in df.columns:
        for ind, cnt in df['industry'].value_counts().items():
            industry[ind] = kpis(df[df['industry'] == ind])

    def group_role(r):
        r = str(r).strip()
        if r == 'CHRO/HR Head':
            return 'CHRO / HR Head'
        if r == 'HR COE':
            return 'HR COE'
        if r == 'Business Leader':
            return 'Business Leader'
        return 'Other Roles'

    role = {"All Roles": overall}
    if 'role' in df.columns:
        df['role_group'] = df['role'].map(group_role)
        for rg in df['role_group'].unique():
            role[rg] = kpis(df[df['role_group'] == rg])

    maturity_dist = df['maturity'].value_counts().to_dict() if 'maturity' in df.columns else {}
    barriers = multi_count(df, 'barrier')
    skills_improve = multi_count(df, 'skills_improve')
    challenges = multi_count(df, 'challenges')
    perception = multi_count(df, 'perception')
    investment = df['investment'].value_counts().to_dict() if 'investment' in df.columns else {}
    owner = df['owner'].value_counts().to_dict() if 'owner' in df.columns else {}
    impact_track = multi_count(df, 'impact_track')
    prioritization = multi_count(df, 'prioritization')

    # THEMES and MATRIX (secondary-research validation) stay fixed --
    # they compare against outside studies, not against live response counts.
    themes = ["Adaptability & learning mindset", "AI / data literacy", "Critical thinking",
              "Change management", "Ethical & responsible AI use", "Prompting & fact-checking skills",
              "Governance & risk clarity", "Cross-domain collaboration"]

    matrix = [
        {"sec": "Microsoft Work Trend Index: organizational factors (leadership, culture, incentives) drive ~67% of AI impact vs ~32% from individual capability.",
         "pri": "Leadership preparedness and organizational readiness are consistently among the lowest-scoring pillars.",
         "status": "confirmed", "label": "Confirmed"},
        {"sec": "Microsoft: only 26% of employees believe leadership is clearly aligned on AI strategy.",
         "pri": "Most respondents agree leaders encourage experimentation, but very few strongly agree.",
         "status": "partial", "label": "Partially confirmed"},
        {"sec": "Deloitte: technology-focused organizations are 1.6x more likely to miss expected AI ROI.",
         "pri": "The greatest share of AI investment consistently goes to Technology & Data over Workforce Upskilling.",
         "status": "confirmed", "label": "Confirmed"},
        {"sec": "Gartner / Stanford: governance, security and trust are lagging behind the pace of AI adoption.",
         "pri": "Governance readiness is consistently the lowest-scoring pillar, and governance & risk is a top-cited barrier.",
         "status": "confirmed", "label": "Confirmed"},
        {"sec": "PwC: AI-skilled workers earn a wage premium and required skills change quickly.",
         "pri": "Skills gap is consistently the most cited barrier, with prompting/workflow skills the top gaps.",
         "status": "confirmed", "label": "Confirmed"},
    ]

    def js(obj):
        return json.dumps(obj, ensure_ascii=False)

    block = f"""/* ==DATA_BLOCK_START== */
const OVERALL = {js(overall)};
const INDUSTRY = {js(industry)};
const ROLE = {js(role)};
const MATURITY_DIST = {js(maturity_dist)};
const BARRIERS = {js(barriers)};
const SKILLS_IMPROVE = {js(skills_improve)};
const CHALLENGES = {js(challenges)};
const PERCEPTION = {js(perception)};
const INVESTMENT = {js(investment)};
const OWNER = {js(owner)};
const IMPACT_TRACK = {js(impact_track)};
const PRIORITIZATION = {js(prioritization)};
const THEMES = {js(themes)};
const MATRIX = {js(matrix)};
/* ==DATA_BLOCK_END== */
"""
    return block


def main():
    csv_url = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else DEFAULT_CSV_URL
    output_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT

    df = load_data(csv_url)
    data_block = build_data_block(df)

    template = open(TEMPLATE_PATH, encoding="utf-8").read()
    start = template.index("/* ==DATA_BLOCK_START== */")
    end = template.index("/* ==DATA_BLOCK_END== */") + len("/* ==DATA_BLOCK_END== */")
    new_html = template[:start] + data_block.strip() + template[end:]

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"Dashboard regenerated from {len(df)} responses -> {output_path}")


if __name__ == "__main__":
    main()
