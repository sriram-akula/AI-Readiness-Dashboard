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

# Each field maps to a list of keywords (all must appear, case-insensitive) that identify
# its column, however the exact header text is spaced/punctuated in a given export.
COL_KEYWORDS = {
    'role': ["what is your role"],
    'industry': ["industry"],
    'size': ["employee", "strength"],       # deliberately NOT "organization size" -- that column is unused/blank on the live sheet
    'maturity': ["current ai maturity"],
    'skills_infra': ["resources and infrastructure"],
    'governance': ["governance structures"],
    'leadership_prep': ["leadership, learning"],
    'workforce_ready': ["workforce's readiness"],
    'perception': ["primarily perceive ai"],
    'barrier': ["biggest barrier"],
    'leaders_encourage': ["encourage experimentation"],
    'investment': ["greatest ai investment"],
    'prioritization': ["initiatives prioritized"],
    'skills_improve': ["skills need the most improvement"],
    'challenges': ["operational challenges"],
    'owner': ["owns ai adoption"],
    'impact_track': ["impact tracked"],
}

MAT_MAP = {'No implementation': 0, 'Early experimentation': 33, 'Functional deployment': 67, 'Enterprise transformation': 100}
ORD5 = {'Very Low': 0, 'Low': 25, 'Moderate': 50, 'High': 75, 'Very High': 100}
AGREE_MAP = {'Strongly Disagree': 0, 'Disagree': 25, 'Neutral': 50, 'Agree': 75, 'Strongly agree': 100, 'Strongly Agree': 100}


def find_column(columns, keywords):
    """Return the first column whose text contains every keyword, ignoring case/spacing."""
    for col in columns:
        norm = " ".join(str(col).lower().split())
        if all(kw.lower() in norm for kw in keywords):
            return col
    return None


def load_data(csv_url: str) -> pd.DataFrame:
    df = pd.read_csv(csv_url)
    rename_map = {}
    missing = []
    for field, keywords in COL_KEYWORDS.items():
        col = find_column(df.columns, keywords)
        if col:
            rename_map[col] = field
        else:
            missing.append(field)
    if missing:
        print("WARNING - fields not matched to any column (skipped):", missing, file=sys.stderr)
        print("Actual columns in sheet:", list(df.columns), file=sys.stderr)
    df = df.rename(columns=rename_map)
    # Strip stray whitespace from every text field -- avoids "Retail" and " Retail" being treated as different groups
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)
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
        # Google Forms exports multi-select answers comma-separated, e.g. "Skills gap, Mindset & trust"
        for item in [x.strip() for x in str(val).split(',')]:
            if item:
                counts[item] = counts.get(item, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def full_stats(sub: pd.DataFrame):
    """KPI scores PLUS every breakdown chart's data, scoped to just this cut (industry/role/size/overall)."""
    base = kpis(sub)
    if base is None:
        return None
    base['maturity_dist'] = sub['maturity'].value_counts().to_dict() if 'maturity' in sub.columns else {}
    base['barriers'] = multi_count(sub, 'barrier')
    base['skills_improve'] = multi_count(sub, 'skills_improve')
    base['challenges'] = multi_count(sub, 'challenges')
    base['perception'] = multi_count(sub, 'perception')
    base['investment'] = sub['investment'].value_counts().to_dict() if 'investment' in sub.columns else {}
    base['owner'] = sub['owner'].value_counts().to_dict() if 'owner' in sub.columns else {}
    base['impact_track'] = multi_count(sub, 'impact_track')
    base['prioritization'] = multi_count(sub, 'prioritization')
    return base


def group_size(v):
    v = str(v).strip()
    if v in ('<100', '100 - 500'):
        return 'Small (Under 500 employees)'
    if v in ('501 - 1000', '1001 - 5000'):
        return 'Medium (500 - 5,000 employees)'
    if v in ('5001 - 10000', '>10000'):
        return 'Large (5,000+ employees)'
    return None


def build_data_block(df: pd.DataFrame) -> str:
    df = score(df)
    overall = full_stats(df)

    industry = {"All Industries": overall}
    if 'industry' in df.columns:
        for ind, cnt in df['industry'].value_counts().items():
            industry[ind] = full_stats(df[df['industry'] == ind])

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
            role[rg] = full_stats(df[df['role_group'] == rg])

    size = {"All Sizes": overall}
    if 'size' in df.columns:
        df['size_group'] = df['size'].map(group_size)
        for sg in ['Small (Under 500 employees)', 'Medium (500 - 5,000 employees)', 'Large (5,000+ employees)']:
            sub = df[df['size_group'] == sg]
            if len(sub) > 0:
                size[sg] = full_stats(sub)

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
const SIZE = {js(size)};
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
