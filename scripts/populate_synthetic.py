"""Populate fabops_inventory, fabops_suppliers, fabops_incidents with synthetic data.

Run once on Day 2 after tables exist:
  PYTHONPATH=$(pwd) python scripts/populate_synthetic.py
"""
from fabops.config import TABLE_INVENTORY, TABLE_SUPPLIERS, TABLE_INCIDENTS
from fabops.data.carparts import load_carparts
from fabops.data.dynamo import batch_write
from fabops.data.synthetic import generate_inventory, generate_suppliers, generate_incidents


def main():
    print("Loading carparts for part_id list...")
    df = load_carparts()
    part_ids = df["part_id"].unique().tolist()
    part_ids = part_ids[:200]  # demo scope: first 200 parts
    print(f"Generating inventory for {len(part_ids)} parts...")
    inv = generate_inventory(part_ids, seed=42)
    print(f"  {len(inv)} inventory rows; writing to {TABLE_INVENTORY}...")
    batch_write(TABLE_INVENTORY, inv)

    print("Generating 20 suppliers...")
    suppliers = generate_suppliers(n_suppliers=20, seed=42)
    batch_write(TABLE_SUPPLIERS, suppliers)

    print("Generating 100 incidents...")
    incidents = generate_incidents(n_incidents=100, seed=42)
    batch_write(TABLE_INCIDENTS, incidents)

    print("Done.")


if __name__ == "__main__":
    main()
