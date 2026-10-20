import csv
from collections import Counter
from pathlib import Path

CSV_PATH = Path(__file__).with_name("stations.csv")
TOP_N = 5
X = 10 # Numero de estações que queremos encontrar
EXAMPLES_N = 10

with CSV_PATH.open(encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))

counts = Counter(row["city_id"] for row in rows)

print(f"Total de estações: {len(rows)}")
print(f"Total de cidades (city_id distintos): {len(counts)}")

print(f"\nTop {TOP_N} cidades com mais estações:")
for city_id, n in counts.most_common(TOP_N):
    print(f"  city_id {city_id:>6}: {n}")

print(f"\nTop {TOP_N} cidades com menos estações:")
for city_id, n in sorted(counts.items(), key=lambda item: item[1])[:TOP_N]:
    print(f"  city_id {city_id:>6}: {n}")

matching = [city_id for city_id, n in counts.items() if n == X]

print(f"\nCidades com exatamente {X} estações: {len(matching)}")
for city_id in matching[:EXAMPLES_N]:
    print(f"  city_id {city_id:>6}")