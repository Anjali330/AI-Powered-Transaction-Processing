import pandas as pd
df = pd.read_csv("test_dirty.csv", dtype=str, keep_default_na=False)
df.columns = [c.strip().lower() for c in df.columns]
print(repr(list(df.columns)))
for i, row in df.iterrows():
    print(f"Row {i}: amount={row.get('amount')!r}  currency={row.get('currency')!r}  merchant={row.get('merchant')!r}")
