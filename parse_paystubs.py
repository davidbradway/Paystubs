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

    # --- Get the totals ---
    # Find the last occurrence of "TOTAL" in the original text
    last_total_start_index = text.rfind("TOTAL")

    if last_total_start_index != -1:
        # Get the substring starting from the found "TOTAL"
        # and extend it to the next newline character, or to the end of the text
        segment_start_index = last_total_start_index
        newline_index = text.find('\n', segment_start_index)

        if newline_index != -1:
            # Extract the line segment containing "TOTAL" and the numbers after it
            line_segment = text[segment_start_index:newline_index]
        else:
            # If no newline, take till the end of the string
            line_segment = text[segment_start_index:]

        # Now, use a forward-looking regex on this extracted line segment
        # to capture the three numbers immediately following "TOTAL".
        # The regex must now match numbers in their natural, non-reversed format.
        pattern_forward = r"TOTAL\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})"
        m_forward = re.search(pattern_forward, line_segment)

        if m_forward:
            # Captured values are in the correct order for parse_amount
            result['total_cur_employer_cont'] = parse_amount(m_forward.group(1))
            result['total_ytd_employee_cont'] = parse_amount(m_forward.group(2))
            result['total_ytd_employer_cont'] = parse_amount(m_forward.group(3))
        else:
            print("Could not extract the three numbers after the last 'TOTAL' using forward regex.")
    else:
        print("Could not find the substring 'TOTAL' in the text.")

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

    load = True  # Set to False to re-parse PDFs instead of loading from Parquet
    if load and Path('paystubs.parquet').exists():
        print("Loading dataframe from paystubs.parquet...")
        df = pd.read_parquet('paystubs.parquet')
    else:
        print("Parquet file not found. Parsing PDFs...")
        df = load_all_paystubs()

    # Save dataframe to Parquet file for later reloading
    df.to_parquet(r'paystubs.parquet')
    print("Saved dataframe to paystubs.parquet")

    print(f"\nLoaded {len(df)} paystubs from "
          f"{df['period_end'].min().date()} to {df['period_end'].max().date()}\n")

    # --- 403B summary ---
    # Warning! This assumes that Total Year to Date Employee Contributions are
    # purely from 403B contributions, which is true for mypaystubs but may not
    # be universally true. For example HSA contributions could also be 
    # included in that total in other cases (and will be for me in 2026+)
    contrib = df[(df['total_ytd_employee_cont'] > 0) & (df['month'] == 12)]
    print("=== Total Employee Contributions ===")
    print(f"  Total contributed:  ${contrib['total_ytd_employee_cont'].sum():,.2f}")
    print()

# --- Plot ---
fig, axes = plt.subplots(1, 2, figsize=(12, 8))
# add a panel to the plot to show total_ytd_employee_cont by year
ax = axes[0]
yearly_contrib = df[df['month'] == 12]
ax.plot(yearly_contrib['period_end'], yearly_contrib['total_ytd_employee_cont'], color='steelblue')
ax.set_title('Yearly Employee Contributions')
ax.set_xlabel('Year')
ax.set_ylabel('Amount ($)')
ax.grid(alpha=0.3)

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
