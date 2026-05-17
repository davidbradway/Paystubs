"""
Parse Duke University paystub PDFs into a pandas DataFrame.

Format: DUKE UNIVERSITY/HEALTH SYSTEM MONTHLY PAYROLL STATEMENT
Key field: 403B PST (post-tax employee 403b contribution, appears in RETIREMENT box)
"""

import re
import pdfplumber
import pandas as pd
from pathlib import Path


def parse_amount(s: str) -> float:
    """Convert '1,234.56' or '1,234.56-' to float. Returns 0.0 for empty/None."""
    if not s:
        return 0.0
    s = s.strip().replace(',', '')
    negative = s.endswith('-')
    s = s.rstrip('-')
    try:
        return -float(s) if negative else float(s)
    except ValueError:
        return 0.0


def parse_paystub(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        text = '\n'.join(p.extract_text() or '' for p in pdf.pages)

    result = {'file': path.name}

    # Period end date and check date from header line:
    m = re.search(r'\|(\d{2}/\d{2}/\d{4})\|\s*(\d{2}/\d{2}/\d{4})', text)
    if m:
        result['period_end'] = pd.to_datetime(m.group(1), format='%m/%d/%Y')
        result['check_date'] = pd.to_datetime(m.group(2), format='%m/%d/%Y')
    else:
        result['period_end'] = pd.NaT
        result['check_date'] = pd.NaT

    # Monthly rate and position
    m = re.search(r'RATE:\s*([\d,]+\.\d{2})', text)
    result['monthly_rate'] = parse_amount(m.group(1)) if m else 0.0

    m = re.search(r'POSITION:\s*(.+)', text)
    result['position'] = m.group(1).strip() if m else ''

    # Summary line (current period totals):
    #   GROSS PAY  PRETAX  TAX DEF  TAXABLE GROSS  TAXES  DEDUCTIONS  NET PAY
    m = re.search(
        r'GROSS PAY\s+PRETAX\s+TAX DEF\s+TAXABLE GROSS\s+TAXES\s+DEDUCTIONS\s+NET PAY\s*\n'
        r'([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+'
        r'([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})',
        text,
    )
    if m:
        result['gross_pay']     = parse_amount(m.group(1))
        result['pretax_ded']    = parse_amount(m.group(2))
        result['tax_deferred']  = parse_amount(m.group(3))
        result['taxable_gross'] = parse_amount(m.group(4))
        result['taxes']         = parse_amount(m.group(5))
        result['deductions']    = parse_amount(m.group(6))
        result['net_pay']       = parse_amount(m.group(7))
    else:
        for k in ('gross_pay', 'pretax_ded', 'tax_deferred', 'taxable_gross',
                  'taxes', 'deductions', 'net_pay'):
            result[k] = 0.0

    # --- 403B post-tax employee contribution (current period) ---
    # Appears in RETIREMENT box as "403B PST ..."; absent in early years (= 0)
    m = re.search(r'403B PST\s+([\d,]+\.\d{2})', text)
    result['403b_employee_current'] = parse_amount(m.group(1)) if m else 0.0

    # --- HSA/RETIREMENT SAVINGS CONTRIBUTIONS table (bottom of stub) ---
    # Columns: PLAN | CURRENT EMPLOYER CONTRIBUTION | YTD EMPLOYEE | YTD EMPLOYER
    # The 403B line appears mid-line: "TAX GROSS ..."
    # Use negative lookahead to skip the "403B PST" line in the RETIREMENT box.
    m = re.search(
        r'\b403B(?!\s+PST)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})',
        text,
    )
    if m:
        result['403b_employer_current'] = parse_amount(m.group(1))
        result['403b_employee_ytd']     = parse_amount(m.group(2))
        result['403b_employer_ytd']     = parse_amount(m.group(3))
    else:
        result['403b_employer_current'] = 0.0
        result['403b_employee_ytd']     = 0.0
        result['403b_employer_ytd']     = 0.0

    # --- Year-to-date totals (left column of bottom section) ---
    ytd_fields = {
        'GROSS':    'ytd_gross',
        'PRETAX':   'ytd_pretax',
        'TAX DEF':  'ytd_tax_def',
        'TAX GROSS':'ytd_tax_gross',
        'FED TAX':  'ytd_fed_tax',
        'NC TAX':   'ytd_nc_tax',
        'MEDICARE': 'ytd_medicare',
        'OASDI':    'ytd_oasdi',
    }
    for label, col in ytd_fields.items():
        m = re.search(rf'^{re.escape(label)}\s+([\d,]+\.\d{2})', text, re.MULTILINE)
        result[col] = parse_amount(m.group(1)) if m else 0.0

    # --- Current-period taxes (parsed from TAXES column) ---
    tax_fields = {
        r'FED\s':       'tax_fed',
        r'OASDI\s':     'tax_oasdi',
        r'MEDICARE\s':  'tax_medicare',
        r'NC WITHH\s':  'tax_nc',
    }
    for pattern, col in tax_fields.items():
        m = re.search(rf'\|{pattern}([\d,]+\.\d{{2}})', text)
        result[col] = parse_amount(m.group(1)) if m else 0.0

    return result


def load_all_paystubs(directory: str = r'D:\Paystubs') -> pd.DataFrame:
    paystub_dir = Path(directory)
    records = []
    errors = []
    for pdf_path in sorted(paystub_dir.glob('Paystub_*.pdf')):
        try:
            records.append(parse_paystub(pdf_path))
        except Exception as e:
            errors.append((pdf_path.name, str(e)))

    if errors:
        print(f"Errors parsing {len(errors)} file(s):")
        for name, err in errors:
            print(f"  {name}: {err}")

    df = pd.DataFrame(records)
    df = df.sort_values('period_end').reset_index(drop=True)
    df['year'] = df['period_end'].dt.year
    df['month'] = df['period_end'].dt.month
    return df


if __name__ == '__main__':
    import matplotlib.pyplot as plt

    df = load_all_paystubs()

    # Save dataframe to Parquet file for later reloading
    df.to_parquet(r'paystubs.parquet')
    print("Saved dataframe to paystubs.parquet")

    print(f"\nLoaded {len(df)} paystubs from "
          f"{df['period_end'].min().date()} to {df['period_end'].max().date()}\n")

    # --- 403B summary ---
    contrib = df[df['403b_employee_current'] > 0]
    print("=== 403B Post-Tax Employee Contributions ===")
    print(f"  Months with contributions: {len(contrib)}")
    print(f"  First contribution: {contrib['period_end'].min().date()}")
    print(f"  Total contributed:  ${contrib['403b_employee_current'].sum():,.2f}")
    print(f"  Monthly avg:        ${contrib['403b_employee_current'].mean():,.2f}")
    print()

    annual = df.groupby('year').agg(
        gross=('gross_pay', 'sum'),
        net=('net_pay', 'sum'),
        taxes=('taxes', 'sum'),
        emp_403b=('403b_employee_current', 'sum'),
        er_403b=('403b_employer_current', 'sum'),
    ).round(2)
    print("=== Annual Summary ===")
    print(annual.to_string())

    # --- Plot: 403B contributions over time ---
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))

    ax = axes[0]
    ax.bar(df['period_end'], df['403b_employee_current'], width=25,
           label='Employee (post-tax)', color='steelblue')
    ax.bar(df['period_end'], df['403b_employer_current'], width=25,
           bottom=df['403b_employee_current'],
           label='Employer match', color='orange', alpha=0.8)
    ax.set_title('Monthly 403(b) Contributions')
    ax.set_ylabel('Amount ($)')
    ax.legend()
    ax.grid(axis='y', alpha=0.3)

    ax = axes[1]
    ax.plot(df['period_end'], df['gross_pay'], label='Gross Pay', color='green')
    ax.plot(df['period_end'], df['net_pay'], label='Net Pay', color='steelblue')
    ax.plot(df['period_end'], df['taxes'], label='Taxes', color='red', alpha=0.7)
    ax.set_title('Monthly Pay Summary')
    ax.set_ylabel('Amount ($)')
    ax.legend()
    ax.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(r'paystub_summary.png', dpi=150)
    plt.show()
    print("\nPlot saved to paystub_summary.png\n")

    # --- Find totals for each column ---
    columns_to_sum = [
        'gross_pay', 'pretax_ded', 'tax_deferred', 'taxable_gross', 'taxes',
        'deductions', 'net_pay', '403b_employee_current',
        '403b_employer_current','tax_fed',
        'tax_oasdi', 'tax_medicare', 'tax_nc'
    ]

    for column in columns_to_sum:
        total = df[column].sum()
        print(f"Total {column}: ${total:,.2f}")
